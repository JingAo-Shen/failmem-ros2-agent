"""
LLM Client for Qwen2.5-Coder-7B-Instruct:
Provides structured JSON generation, token and latency tracking, and deterministic inference.
"""

import os
import re
import json
import time
from typing import Dict, Any, Optional, Tuple, List
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer


class LLMClient:
    _instance = None

    def __init__(self, model_path: str = "/models/Qwen2.5-Coder-7B-Instruct", device: str = "cuda:0"):
        self.model_path = model_path
        self.device = device
        self.total_calls = 0
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_latency_seconds = 0.0

        print(f"[LLMClient] Loading tokenizer from {model_path}...")
        self.tokenizer = AutoTokenizer.from_pretrained(model_path)
        print(f"[LLMClient] Loading model onto {device} in bfloat16...")
        self.model = AutoModelForCausalLM.from_pretrained(
            model_path,
            torch_dtype=torch.bfloat16,
            device_map=device
        )
        self.model.eval()
        print(f"[LLMClient] Model loaded successfully. VRAM: {torch.cuda.memory_allocated()/1e9:.2f} GB")

    @classmethod
    def get_instance(cls, model_path: str = "/models/Qwen2.5-Coder-7B-Instruct"):
        if cls._instance is None:
            cls._instance = cls(model_path=model_path)
        return cls._instance

    def generate(self, user_prompt: str, system_prompt: str = "", max_new_tokens: int = 128) -> Tuple[str, Dict[str, Any]]:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        prompt_text = self.tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = self.tokenizer([prompt_text], return_tensors="pt").to(self.device)
        in_len = inputs.input_ids.shape[1]

        t0 = time.time()
        with torch.no_grad():
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=False,
                pad_token_id=self.tokenizer.eos_token_id
            )
        dt = time.time() - t0
        out_ids = outputs[0][in_len:]
        out_len = len(out_ids)
        response_text = self.tokenizer.decode(out_ids, skip_special_tokens=True).strip()

        # Update stats
        self.total_calls += 1
        self.total_input_tokens += in_len
        self.total_output_tokens += out_len
        self.total_latency_seconds += dt

        stats = {
            "input_tokens": in_len,
            "output_tokens": out_len,
            "latency_s": round(dt, 3),
            "total_calls": self.total_calls
        }
        return response_text, stats

    def generate_json(self, user_prompt: str, system_prompt: str = "", max_new_tokens: int = 256) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        raw_text, stats = self.generate(user_prompt, system_prompt, max_new_tokens=max_new_tokens)
        stats["raw_text"] = raw_text
        parsed = self._extract_json(raw_text)
        if parsed is not None:
            return parsed, stats

        # Retry once if JSON was invalid
        retry_prompt = f"{user_prompt}\n\nPREVIOUS OUTPUT WAS INVALID JSON:\n{raw_text}\nPlease output ONLY valid JSON."
        raw_text2, stats2 = self.generate(retry_prompt, system_prompt, max_new_tokens=max_new_tokens)
        stats2["raw_text"] = raw_text2
        parsed2 = self._extract_json(raw_text2)
        if parsed2 is not None:
            return parsed2, stats2

        # Fallback dictionary if parsing completely failed
        return {"raw_text": raw_text2, "parse_error": True}, stats2

    def _extract_json(self, text: str) -> Optional[Dict[str, Any]]:
        # Try finding markdown code block
        code_block = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
        if code_block:
            try:
                return json.loads(code_block.group(1).strip())
            except Exception:
                pass
        # Try finding outermost braces { ... }
        brace_match = re.search(r'\{[\s\S]*\}', text)
        if brace_match:
            try:
                return json.loads(brace_match.group(0).strip())
            except Exception:
                pass
        return None

    def get_aggregate_stats(self) -> Dict[str, Any]:
        return {
            "total_calls": self.total_calls,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_tokens": self.total_input_tokens + self.total_output_tokens,
            "total_latency_seconds": round(self.total_latency_seconds, 2),
            "avg_latency_per_call": round(self.total_latency_seconds / max(1, self.total_calls), 3)
        }
