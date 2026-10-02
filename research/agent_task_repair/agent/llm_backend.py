"""
Unified LLM Backend for FailMem Stage 2 Planning Agent.
Enforces:
  - Mandatory real neural model loading for evaluation runs (fails fast if missing).
  - Fallback engine strictly isolated to unit testing mode with explicit flag.
  - Comprehensive token, call count, and latency tracking.
"""
from typing import Dict, Any, List, Optional
import time
import json
import re


class LLMBackend:
    def __init__(
        self,
        model_path: Optional[str] = None,
        device: str = "cuda",
        torch_dtype: str = "float16",
        max_new_tokens: int = 128,
        temperature: float = 0.0,
        allow_fallback: bool = False,
    ):
        self.model_path = model_path
        self.device = device
        self.torch_dtype = torch_dtype
        self.max_new_tokens = max_new_tokens
        self.temperature = temperature
        self.allow_fallback = allow_fallback

        self.model = None
        self.tokenizer = None
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
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        print(f"[LLMBackend] Loading neural model from {self.model_path} onto {self.device}...")
        t0 = time.time()
        dtype = torch.float16 if self.torch_dtype == "float16" else torch.bfloat16
        self.tokenizer = AutoTokenizer.from_pretrained(self.model_path, trust_remote_code=True)
        self.model = AutoModelForCausalLM.from_pretrained(
            self.model_path,
            torch_dtype=dtype,
            device_map="auto" if self.device == "cuda" else None,
            trust_remote_code=True,
        )
        t1 = time.time()
        print(f"[LLMBackend] Model successfully loaded in {t1 - t0:.2f}s.")

    def generate(self, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        """
        Executes chat completion given conversation messages.
        Returns: {"content": str, "prompt_tokens": int, "generated_tokens": int, "latency_s": float}
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

        import torch
        prompt_text = self.tokenizer.apply_chat_template(messages, add_generation_prompt=True, tokenize=False)
        inputs = self.tokenizer(prompt_text, return_tensors="pt").to(self.model.device)
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
        output_text = self.tokenizer.decode(gen_tokens, skip_special_tokens=True).strip()
        t1 = time.time()
        latency = t1 - t0

        gen_len = len(gen_tokens)
        self.total_prompt_tokens += prompt_len
        self.total_generated_tokens += gen_len
        self.total_latency_s += latency

        return {
            "content": output_text,
            "prompt_tokens": prompt_len,
            "generated_tokens": gen_len,
            "latency_s": latency,
        }

    def _fallback_generate(self, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        """
        Deterministic rule-based solver restricted strictly to unit tests.
        """
        user_msg = messages[-1]["content"] if messages else ""
        decision: Dict[str, Any]

        if "Lobby" in user_msg and "holding" not in user_msg and "inventory: []" in user_msg:
            # Pickup package
            if "pkg_docs" in user_msg:
                decision = {
                    "decision_summary": "Picking up pkg_docs at Lobby.",
                    "action": "pickup",
                    "params": {"package_id": "pkg_docs", "from_location": "Lobby"}
                }
            elif "pkg_hardware" in user_msg:
                decision = {
                    "decision_summary": "Picking up pkg_hardware at Lobby.",
                    "action": "pickup",
                    "params": {"package_id": "pkg_hardware", "from_location": "Lobby"}
                }
            else:
                decision = {
                    "decision_summary": "Navigating to Corridor_North.",
                    "action": "navigate",
                    "params": {"target_zone": "Corridor_North"}
                }
        elif "pkg_docs" in user_msg and "Office_A" in user_msg:
            decision = {
                "decision_summary": "Delivering pkg_docs to Alice at Office_A.",
                "action": "deliver",
                "params": {"package_id": "pkg_docs", "recipient": "Alice"}
            }
        else:
            decision = {
                "decision_summary": "Navigating towards goal.",
                "action": "navigate",
                "params": {"target_zone": "Corridor_North"}
            }

        content_str = f"```json\n{json.dumps(decision, indent=2)}\n```"
        return {
            "content": content_str,
            "prompt_tokens": len(user_msg.split()),
            "generated_tokens": len(content_str.split()),
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
            "total_tokens": self.total_prompt_tokens + self.total_generated_tokens,
            "total_latency_s": round(self.total_latency_s, 3),
            "avg_latency_s": round(self.total_latency_s / max(1, self.total_calls), 3),
        }
