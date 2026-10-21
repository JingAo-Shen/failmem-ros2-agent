"""
Qwen3-14B-AWQ LLM Client
Provides AWQ-quantized inference with float16 non-quantized weights,
enable_thinking=False chat template formatting, explicit sampling parameters,
and token/VRAM tracking.
"""

import os
import re
import json
import time
import random
from typing import Dict, Any, Optional, Tuple, List, Set
import numpy as np
import torch
from transformers import AutoTokenizer
from awq import AutoAWQForCausalLM


def set_deterministic_seed(seed: int = 3407):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


class Qwen3AWQClient:
    def __init__(self, model_path: str = "/models/Qwen3-14B-AWQ", device: str = "cuda:0"):
        self.model_path = model_path
        self.device = device
        self.total_calls = 0
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_latency_seconds = 0.0

        print(f"[Qwen3AWQClient] Loading tokenizer from {model_path}...")
        self.tokenizer = AutoTokenizer.from_pretrained(model_path)

        print(f"[Qwen3AWQClient] Loading AWQ model from {model_path} with torch_dtype=torch.float16, device_map='auto'...")
        self.model = AutoAWQForCausalLM.from_quantized(
            model_path,
            fuse_layers=False,
            batch_size=1,
            safetensors=True,
            torch_dtype=torch.float16,
            device_map="auto"
        )
        self.model.model.eval()

        self.fixed_gen_params = {
            "do_sample": True,
            "temperature": 0.7,
            "top_p": 0.8,
            "top_k": 20,
            "max_new_tokens": 256,
            "pad_token_id": self.tokenizer.eos_token_id
        }
        peak_vram = round(torch.cuda.max_memory_allocated() / (1024**3), 3)
        print(f"[Qwen3AWQClient] Model loaded successfully. Peak VRAM: {peak_vram} GB")

    def generate(self, user_prompt: str, system_prompt: str = "", max_new_tokens: int = 256) -> Tuple[str, Dict[str, Any]]:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        prompt_text = self.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False
        )
        inputs = self.tokenizer([prompt_text], return_tensors="pt").to(self.device)
        in_len = inputs.input_ids.shape[1]

        actual_gen_params = dict(self.fixed_gen_params)
        actual_gen_params["max_new_tokens"] = max_new_tokens

        t0 = time.time()
        with torch.no_grad():
            outputs = self.model.model.generate(
                **inputs,
                **actual_gen_params
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
            "total_calls": self.total_calls,
            "actual_generation_params": actual_gen_params,
            "peak_vram_gib": round(torch.cuda.max_memory_allocated() / (1024**3), 3)
        }
        return response_text, stats

    def generate_json(self, user_prompt: str, system_prompt: str = "", max_new_tokens: int = 256) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        raw_text, stats = self.generate(user_prompt, system_prompt, max_new_tokens=max_new_tokens)
        stats["raw_text"] = raw_text
        stats["attempts"] = 1
        parsed = self._extract_json(raw_text)
        if parsed is not None:
            return parsed, stats

        # Retry once if JSON was invalid
        retry_prompt = f"{user_prompt}\n\nPREVIOUS OUTPUT WAS INVALID JSON:\n{raw_text}\nPlease output ONLY valid JSON."
        raw_text2, stats2 = self.generate(retry_prompt, system_prompt, max_new_tokens=max_new_tokens)
        stats2["raw_text"] = raw_text2
        stats2["raw_text_first_attempt"] = raw_text
        stats2["attempts"] = 2
        # Cumulative tokens for the JSON request
        stats2["input_tokens"] += stats["input_tokens"]
        stats2["output_tokens"] += stats["output_tokens"]
        stats2["latency_s"] = round(stats["latency_s"] + stats2["latency_s"], 3)

        parsed2 = self._extract_json(raw_text2)
        if parsed2 is not None:
            return parsed2, stats2

        return {"raw_text": raw_text2, "parse_error": True}, stats2

    def _extract_json(self, text: str) -> Optional[Dict[str, Any]]:
        code_block = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
        if code_block:
            try:
                return json.loads(code_block.group(1).strip())
            except Exception:
                pass
        brace_match = re.search(r'\{[\s\S]*\}', text)
        if brace_match:
            try:
                return json.loads(brace_match.group(0).strip())
            except Exception:
                pass
        return None

    def get_model_metadata(self) -> Dict[str, Any]:
        quant_layers: Set[str] = set()
        device_dist: Dict[str, int] = {}
        for name, module in self.model.model.named_modules():
            mod_type = module.__class__.__name__
            if "quant" in mod_type.lower() or "wq" in mod_type.lower() or "awq" in mod_type.lower():
                quant_layers.add(f"{module.__class__.__module__}.{mod_type}")
            if hasattr(module, "weight") and module.weight is not None and hasattr(module.weight, "device"):
                dev_str = str(module.weight.device)
                device_dist[dev_str] = device_dist.get(dev_str, 0) + 1

        first_param = next(self.model.model.parameters(), None)

        return {
            "model_wrapper_class": f"{self.model.__class__.__module__}.{self.model.__class__.__name__}",
            "underlying_model_class": f"{self.model.model.__class__.__module__}.{self.model.model.__class__.__name__}",
            "model_config_name_or_path": getattr(self.model.model.config, "_name_or_path", str(self.model_path)),
            "tokenizer_class": f"{self.tokenizer.__class__.__module__}.{self.tokenizer.__class__.__name__}",
            "tokenizer_name_or_path": getattr(self.tokenizer, "name_or_path", str(self.model_path)),
            "quantization_config": getattr(self.model.model.config, "quantization_config", None),
            "quantized_layer_types": sorted(list(quant_layers)),
            "device_distribution": device_dist,
            "non_quantized_parameter_dtype": str(first_param.dtype) if first_param is not None else "float16",
            "chat_template_enable_thinking": False,
            "generation_parameters": self.fixed_gen_params,
            "peak_vram_gib": round(torch.cuda.max_memory_allocated() / (1024**3), 3)
        }
