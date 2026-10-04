"""
Unified LLM Backend for FailMem Stage 2 Planning Agent.
Supports:
  - FP16 models (e.g. Qwen2.5-Coder-7B-Instruct)
  - AWQ 4-bit models (e.g. Qwen3-14B-AWQ) with AutoAWQ / Transformers backend
  - Native Thinking Mode (`enable_thinking=True` / `enable_thinking=False`)
  - Accurate telemetry: prompt/generated tokens, latency, peak VRAM, tokens/sec.
"""
from typing import Dict, Any, List, Optional, Tuple
import time
import json
import re
import torch


class LLMBackend:
    def __init__(
        self,
        model_path: Optional[str] = None,
        device: str = "cuda",
        torch_dtype: str = "float16",
        max_new_tokens: int = 256,
        temperature: float = 0.0,
        enable_thinking: Optional[bool] = None,
        quantization_format: Optional[str] = None,
        allow_fallback: bool = False,
    ):
        self.model_path = model_path
        self.device = device
        self.torch_dtype = torch_dtype
        self.max_new_tokens = max_new_tokens
        self.temperature = temperature
        self.enable_thinking = enable_thinking
        self.quantization_format = quantization_format
        self.allow_fallback = allow_fallback

        self.model = None
        self.tokenizer = None
        self.model_metadata: Dict[str, Any] = {}
        self.total_prompt_tokens = 0
        self.total_generated_tokens = 0
        self.total_calls = 0
        self.total_latency_s = 0.0

        if model_path:
            self._load_model()
        elif not allow_fallback:
            raise RuntimeError(
                "[LLMBackend] No model_path provided and allow_fallback=False. "
                "Evaluation runs must explicitly load a real local model."
            )

    def _load_model(self):
        from transformers import AutoModelForCausalLM, AutoTokenizer

        print(f"[LLMBackend] Loading model from '{self.model_path}' onto {self.device}...")
        t0 = time.time()
        dtype = torch.float16 if self.torch_dtype == "float16" else torch.bfloat16

        self.tokenizer = AutoTokenizer.from_pretrained(self.model_path, trust_remote_code=True)

        load_kwargs: Dict[str, Any] = {
            "trust_remote_code": True,
            "device_map": "auto" if self.device == "cuda" else None,
        }

        # Check for AWQ quantization in config or parameter
        is_awq = False
        if self.quantization_format == "awq" or "AWQ" in (self.model_path or ""):
            is_awq = True

        if not is_awq:
            load_kwargs["torch_dtype"] = dtype

        try:
            self.model = AutoModelForCausalLM.from_pretrained(self.model_path, **load_kwargs)
        except Exception as e:
            print(f"[LLMBackend] AutoModelForCausalLM load error: {e}. Attempting AutoAWQForCausalLM...")
            if is_awq:
                from awq import AutoAWQForCausalLM
                awq_wrapper = AutoAWQForCausalLM.from_quantized(
                    self.model_path,
                    fuse_layers=False,
                    trust_remote_code=True,
                    device_map="auto" if self.device == "cuda" else None,
                )
                self.model = awq_wrapper.model if hasattr(awq_wrapper, "model") else awq_wrapper
            else:
                raise

        t1 = time.time()
        peak_vram_mb = round(torch.cuda.max_memory_allocated() / (1024 * 1024), 2) if torch.cuda.is_available() else 0.0
        print(f"[LLMBackend] Model loaded successfully in {t1 - t0:.2f}s (Peak VRAM: {peak_vram_mb} MB).")

        self.model_metadata = {
            "model_path": self.model_path,
            "device": self.device,
            "quantization": "awq_4bit" if is_awq else "fp16",
            "enable_thinking": self.enable_thinking,
            "peak_vram_mb": peak_vram_mb,
            "load_time_s": round(t1 - t0, 2),
        }

    def generate(self, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        """
        Executes chat completion with native thinking mode support.
        Returns: {"content": str, "reasoning_content": str, "prompt_tokens": int, "generated_tokens": int, "latency_s": float, "tok_per_sec": float}
        """
        t0 = time.time()
        self.total_calls += 1

        if self.model is None or self.tokenizer is None:
            if not self.allow_fallback:
                raise RuntimeError("[LLMBackend] Neural model is not loaded and fallback is disabled.")
            res = self._fallback_generate(messages)
            t1 = time.time()
            res["latency_s"] = t1 - t0
            self.total_latency_s += res["latency_s"]
            self.total_prompt_tokens += res["prompt_tokens"]
            self.total_generated_tokens += res["generated_tokens"]
            return res

        template_kwargs: Dict[str, Any] = {"add_generation_prompt": True, "tokenize": False}
        if self.enable_thinking is not None:
            template_kwargs["enable_thinking"] = self.enable_thinking

        try:
            prompt_text = self.tokenizer.apply_chat_template(messages, **template_kwargs)
        except TypeError:
            # Fallback if tokenizer does not take enable_thinking arg
            prompt_text = self.tokenizer.apply_chat_template(messages, add_generation_prompt=True, tokenize=False)

        # Robust device determination
        if hasattr(self.model, "device"):
            model_dev = self.model.device
        else:
            model_dev = next(self.model.parameters()).device

        inputs = self.tokenizer(prompt_text, return_tensors="pt").to(model_dev)
        prompt_len = inputs.input_ids.shape[1]

        do_sample = self.temperature > 0.0
        with torch.no_grad():
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=self.max_new_tokens,
                do_sample=do_sample,
                temperature=self.temperature if do_sample else None,
                pad_token_id=self.tokenizer.eos_token_id,
            )

        gen_tokens = outputs[0][prompt_len:]
        full_output = self.tokenizer.decode(gen_tokens, skip_special_tokens=False).strip()
        t1 = time.time()
        latency = t1 - t0

        # Separate thinking reasoning content and final JSON content
        reasoning_content = ""
        final_content = full_output
        if "<think>" in full_output and "</think>" in full_output:
            parts = full_output.split("</think>")
            reasoning_content = parts[0].replace("<think>", "").strip()
            final_content = parts[1].strip()
        elif "<think>" in full_output:
            reasoning_content = full_output.replace("<think>", "").strip()

        # Clean special tokens from final content
        final_content = final_content.replace("<|im_end|>", "").replace("<|endoftext|>", "").strip()

        gen_len = len(gen_tokens)
        tok_per_sec = round(gen_len / max(0.001, latency), 2)

        self.total_prompt_tokens += prompt_len
        self.total_generated_tokens += gen_len
        self.total_latency_s += latency

        return {
            "content": final_content,
            "reasoning_content": reasoning_content,
            "raw_output": full_output,
            "prompt_tokens": prompt_len,
            "generated_tokens": gen_len,
            "latency_s": latency,
            "tok_per_sec": tok_per_sec,
        }

    def _fallback_generate(self, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        """Deterministic rule solver for unit tests only."""
        user_msg = messages[-1]["content"] if messages else ""
        if "Lobby" in user_msg and "inventory: []" in user_msg:
            decision = {"action": "pickup", "params": {"package_id": "pkg_docs", "from_location": "Lobby"}}
        elif "Office_A" in user_msg and "pkg_docs" in user_msg:
            decision = {"action": "deliver", "params": {"package_id": "pkg_docs", "recipient": "Alice"}}
        else:
            decision = {"action": "navigate", "params": {"target_zone": "Corridor_North"}}

        content_str = f"```json\n{json.dumps(decision, indent=2)}\n```"
        return {
            "content": content_str,
            "reasoning_content": "",
            "raw_output": content_str,
            "prompt_tokens": len(user_msg.split()),
            "generated_tokens": len(content_str.split()),
            "latency_s": 0.001,
            "tok_per_sec": 1000.0,
        }

    def get_aggregate_stats(self) -> Dict[str, Any]:
        return {
            "model_path": self.model_path,
            "device": self.device,
            "temperature": self.temperature,
            "max_new_tokens": self.max_new_tokens,
            "total_calls": self.total_calls,
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_generated_tokens": self.total_generated_tokens,
            "total_latency_s": round(self.total_latency_s, 3),
            "avg_latency_s": round(self.total_latency_s / max(1, self.total_calls), 3),
            "avg_tokens_per_sec": round(self.total_generated_tokens / max(0.001, self.total_latency_s), 2),
        }
