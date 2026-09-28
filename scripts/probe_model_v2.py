#!/usr/bin/env python3
"""FailMem Model Interface Feasibility Probe v2 (Problem Lock v0.2 Compliant).

Evaluates whether the local LLM can parse and output structured action schemas
using tokenizer.apply_chat_template, measures actual synchronized latency, peak VRAM,
and checks parameters via src/schema_validator.py.

DOES NOT evaluate recovery capability or claim planner reliability.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.schema_validator import parse_and_validate_action

SYSTEM_PROMPT = """You are the high-level decision module for an indoor mobile robot.
Your role is to output structured actions to achieve task goals and recover from obstacles.
Available actions (Problem Lock v0.2):
1. navigate: {"action": "navigate", "action_id": "<str>", "params": {"goal": [x, y, yaw], "frame_id": "map", "timeout_sec": 60.0}}
2. observe: {"action": "observe", "action_id": "<str>", "params": {"target_id": "<str>"}}
3. inspect_status: {"action": "inspect_status", "action_id": "<str>", "params": {}}
4. clear_costmap: {"action": "clear_costmap", "action_id": "<str>", "params": {}}
5. retry: {"action": "retry", "action_id": "<str>", "params": {"original_action_id": "<str>", "replayed_params": {...}}}

Respond ONLY with a valid JSON object matching the action schema above."""

TEST_PROMPTS = [
    {
        "prompt_id": "probe_01_navigate",
        "description": "Initial navigation toward observation stance",
        "user_message": "Task: Navigate to the safe observation stance at coordinates x=4.0, y=3.0, yaw=0.0 to inspect target_box_01.",
        "expected_action": "navigate",
    },
    {
        "prompt_id": "probe_02_observe",
        "description": "Target observation upon arrival at stance",
        "user_message": "Robot has arrived and stabilized at observation stance (4.0, 3.0, 0.0). Execute observation on target_box_01.",
        "expected_action": "observe",
    },
    {
        "prompt_id": "probe_03_costmap_clear",
        "description": "Transient lidar artifact clearance",
        "user_message": "Navigation halted: lidar reports transient ghost noise in local costmap. Clear the local sensor layer.",
        "expected_action": "clear_costmap",
    },
    {
        "prompt_id": "probe_04_inspect_status",
        "description": "Inspection of robot odometry and sensors",
        "user_message": "Inspect current robot odometry pose and scan status before replanning.",
        "expected_action": "inspect_status",
    },
    {
        "prompt_id": "probe_05_retry",
        "description": "Replay original action after clearing transient artifact",
        "user_message": "Transient costmap layer cleared. Replay previous navigation action act_nav_01 with goal [4.0, 3.0, 0.0].",
        "expected_action": "retry",
    },
]


def parse_args():
    parser = argparse.ArgumentParser(description="FailMem Model Interface Feasibility Probe v2")
    parser.add_argument(
        "--model-path",
        type=str,
        default="/root/.cache/modelscope/models/Qwen--Qwen2.5-Coder-7B-Instruct/snapshots/master",
        help="Path to local HuggingFace / ModelScope model directory",
    )
    parser.add_argument(
        "--dtype",
        type=str,
        choices=["bfloat16", "float16", "float32"],
        default="bfloat16",
        help="Torch dtype for model weights",
    )
    parser.add_argument(
        "--device",
        type=str,
        default="cuda:0",
        help="Device to load model on (e.g. cuda:0 or cpu)",
    )
    parser.add_argument(
        "--output-file",
        type=str,
        default=str(REPO_ROOT / "reports/evidence/p0/model_probe_v2.json"),
        help="Path to save probe results JSON",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for torch generation",
    )
    parser.add_argument(
        "--max-new-tokens",
        type=int,
        default=128,
        help="Max tokens generated",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.1,
        help="Sampling temperature",
    )
    parser.add_argument(
        "--top-p",
        type=float,
        default=0.9,
        help="Top-p nucleus sampling",
    )
    parser.add_argument(
        "--do-sample",
        action="store_true",
        default=True,
        help="Whether to sample or greedy decode",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Force overwrite existing output file",
    )
    return parser.parse_args()


def record_failure_and_exit(error_stage: str, error_msg: str, output_path: Path, run_id: str):
    result = {
        "status": "FAILED",
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "error_stage": error_stage,
        "error_message": error_msg,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"[FATAL] Model probe failed at stage '{error_stage}': {error_msg}", file=sys.stderr)
    sys.exit(1)


def main():
    args = parse_args()
    output_path = Path(args.output_file)
    run_id = f"probe_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"

    # Prevent silent overwrite
    if output_path.exists() and not args.force:
        print(f"[ERROR] Output file '{output_path}' already exists. Pass --force to overwrite.", file=sys.stderr)
        sys.exit(1)

    # 1. Environment & CUDA checks
    try:
        import torch
        import transformers
    except ImportError as e:
        record_failure_and_exit("IMPORT_DEPENDENCIES", str(e), output_path, run_id)

    # Set seed
    torch.manual_seed(args.seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(args.seed)

    cuda_available = torch.cuda.is_available()
    if not cuda_available and args.device.startswith("cuda"):
        record_failure_and_exit("CUDA_UNAVAILABLE", "CUDA is not available but cuda device was requested.", output_path, run_id)

    model_dir = Path(args.model_path)
    if not model_dir.exists():
        record_failure_and_exit("MODEL_PATH_NOT_FOUND", f"Directory {model_dir} does not exist", output_path, run_id)

    # File manifest
    model_files = sorted([f.name for f in model_dir.iterdir() if f.is_file()])
    total_weights_size_bytes = sum(f.stat().st_size for f in model_dir.iterdir() if f.is_file())

    # Hardware & Capability Detection (queried dynamically)
    if cuda_available and args.device.startswith("cuda"):
        dev_idx = 0
        if ":" in args.device:
            try:
                dev_idx = int(args.device.split(":")[1])
            except ValueError:
                dev_idx = 0
        device_name = torch.cuda.get_device_name(dev_idx)
        device_cap = list(torch.cuda.get_device_capability(dev_idx))
        torch_bf16_supported = bool(torch.cuda.is_bf16_supported()) if hasattr(torch.cuda, "is_bf16_supported") else False
        native_hardware_bf16 = (device_cap[0] >= 8) if device_cap else False
        cuda_runtime_version = torch.version.cuda if hasattr(torch.version, "cuda") else None
        cuda_status_note = None
    else:
        device_name = "CPU"
        device_cap = None
        torch_bf16_supported = False
        native_hardware_bf16 = False
        cuda_runtime_version = None
        cuda_status_note = "CUDA not available or CPU requested"

    dtype_map = {
        "bfloat16": torch.bfloat16,
        "float16": torch.float16,
        "float32": torch.float32,
    }
    target_dtype = dtype_map[args.dtype]

    print(f"=== FailMem Model Probe v2 (Run ID: {run_id}) ===")
    print(f"Model Path: {model_dir}")
    print(f"Device: {args.device} ({device_name}, Compute Cap: {device_cap})")
    print(f"Seed: {args.seed}")
    print(f"Requested Dtype: {args.dtype} | PyTorch bf16 support: {torch_bf16_supported} | Native Hardware BF16: {native_hardware_bf16}")

    # 2. Model Loading
    t_load_start = time.perf_counter()
    try:
        from transformers import AutoModelForCausalLM, AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(str(model_dir), trust_remote_code=True)
        if cuda_available:
            torch.cuda.reset_peak_memory_stats(0)
            torch.cuda.empty_cache()

        model = AutoModelForCausalLM.from_pretrained(
            str(model_dir),
            torch_dtype=target_dtype,
            device_map=args.device,
            trust_remote_code=True,
        )
        if cuda_available:
            torch.cuda.synchronize(0)
    except Exception as e:
        record_failure_and_exit("MODEL_LOAD_ERROR", str(e), output_path, run_id)

    load_time_sec = time.perf_counter() - t_load_start
    actual_param_dtype = str(next(model.parameters()).dtype)

    generation_config = {
        "max_new_tokens": args.max_new_tokens,
        "temperature": args.temperature,
        "top_p": args.top_p,
        "do_sample": args.do_sample,
        "seed": args.seed,
    }

    # 3. Prompt Execution using apply_chat_template
    trials = []
    total_input_tokens = 0
    total_output_tokens = 0
    latencies = []

    for item in TEST_PROMPTS:
        pid = item["prompt_id"]
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": item["user_message"]},
        ]

        # Apply chat template
        prompt_text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        prompt_hash = hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()

        inputs = tokenizer(prompt_text, return_tensors="pt").to(args.device)
        in_tokens = inputs["input_ids"].shape[1]
        total_input_tokens += in_tokens

        if cuda_available:
            torch.cuda.synchronize(0)
        t_gen_start = time.perf_counter()

        try:
            with torch.no_grad():
                output_ids = model.generate(
                    **inputs,
                    max_new_tokens=generation_config["max_new_tokens"],
                    temperature=generation_config["temperature"],
                    top_p=generation_config["top_p"],
                    do_sample=generation_config["do_sample"],
                    pad_token_id=tokenizer.eos_token_id,
                )
            if cuda_available:
                torch.cuda.synchronize(0)
        except Exception as e:
            record_failure_and_exit(f"GENERATION_ERROR_{pid}", str(e), output_path, run_id)

        t_gen_end = time.perf_counter()
        gen_latency = t_gen_end - t_gen_start
        latencies.append(gen_latency)

        out_tokens = output_ids.shape[1] - in_tokens
        total_output_tokens += out_tokens

        raw_generated = tokenizer.decode(output_ids[0][in_tokens:], skip_special_tokens=True).strip()

        # Validate with strict schema validator
        val_result = parse_and_validate_action(raw_generated)

        trials.append({
            "prompt_id": pid,
            "description": item["description"],
            "expected_action": item["expected_action"],
            "prompt_text": prompt_text,
            "prompt_hash_sha256": prompt_hash,
            "generation_config": generation_config,
            "input_tokens": int(in_tokens),
            "output_tokens": int(out_tokens),
            "latency_sec": round(gen_latency, 4),
            "raw_output": raw_generated,
            "json_parseable": bool(val_result["json_parseable"]),
            "schema_valid": bool(val_result["schema_valid"]),
            "runtime_precondition_status": val_result["runtime_precondition_status"],
            "action_executable_deprecated": False,
            "action_executable_note": "Deprecated static check; static validator only verifies syntax. Preconditions checked at runtime.",
            "parsed_action": val_result["action_name"],
            "error_stage": val_result["error_stage"],
            "error_type": val_result["error_type"],
            "error_message": val_result["error_message"],
        })
        print(f"[{pid}] latency={gen_latency:.3f}s | parseable={val_result['json_parseable']} | schema={val_result['schema_valid']} | action={val_result['action_name']}")

    # 4. Summary calculation with decimal and binary units
    peak_vram_bytes = torch.cuda.max_memory_allocated(0) if cuda_available else 0
    peak_vram_gb = peak_vram_bytes / (1000 ** 3)
    peak_vram_gib = peak_vram_bytes / (1024 ** 3)

    num_trials = len(trials)
    parseable_count = sum(1 for t in trials if t["json_parseable"])
    schema_valid_count = sum(1 for t in trials if t["schema_valid"])

    summary = {
        "status": "COMPLETED",
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "purpose": "Model interface feasibility probe under Problem Lock v0.2. Static probe only - DOES NOT evaluate recovery capability or runtime preconditions.",
        "system_prompt_sha256": hashlib.sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest(),
        "generation_config": generation_config,
        "environment": {
            "device": args.device,
            "device_name": device_name,
            "device_compute_capability": device_cap,
            "torch_version": torch.__version__,
            "transformers_version": transformers.__version__,
            "cuda_runtime_version": cuda_runtime_version,
            "cuda_status_note": cuda_status_note,
            "torch_cuda_is_bf16_supported": torch_bf16_supported,
            "hardware_native_bf16_tensor_cores": native_hardware_bf16,
            "hardware_native_bf16_note": (
                "Native hardware BF16 Tensor Cores require SM >= 8.0 (Ampere+). "
                "On SM 7.5 (Turing), PyTorch executes BF16 operations via software emulation / conversion."
            ),
        },
        "model_metadata": {
            "model_path": str(model_dir),
            "requested_dtype": args.dtype,
            "actual_param_dtype": actual_param_dtype,
            "weights_size_gb": round(total_weights_size_bytes / (1000 ** 3), 2),
            "weights_size_gib": round(total_weights_size_bytes / (1024 ** 3), 2),
            "manifest_file_count": len(model_files),
            "model_files": model_files,
        },
        "performance": {
            "model_load_time_sec": round(load_time_sec, 2),
            "peak_vram_bytes": peak_vram_bytes,
            "peak_vram_gb": round(peak_vram_gb, 3),
            "peak_vram_gib": round(peak_vram_gib, 3),
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "mean_latency_sec": round(sum(latencies) / num_trials, 4) if num_trials > 0 else 0,
            "min_latency_sec": round(min(latencies), 4) if num_trials > 0 else 0,
            "max_latency_sec": round(max(latencies), 4) if num_trials > 0 else 0,
        },
        "validation_metrics": {
            "total_trials": num_trials,
            "json_parseable_count": parseable_count,
            "json_parseable_rate": round(parseable_count / num_trials, 4) if num_trials > 0 else 0,
            "schema_valid_count": schema_valid_count,
            "schema_valid_rate": round(schema_valid_count / num_trials, 4) if num_trials > 0 else 0,
            "runtime_preconditions_checked": False,
            "action_executable_status": "DEPRECATED_STATIC_CHECK",
            "action_executable_note": "Static validator does not judge execution readiness. Runtime preconditions must be checked in EpisodeExecutionContext.",
        },
        "trials": trials,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print("\n=== Probe Execution Completed ===")
    print(f"Results written to: {output_path}")
    print(f"Parseable: {parseable_count}/{num_trials} | Schema Valid: {schema_valid_count}/{num_trials}")
    print(f"Peak VRAM: {peak_vram_gb:.2f} GB ({peak_vram_gib:.2f} GiB) | Mean Latency: {summary['performance']['mean_latency_sec']:.3f} s")


if __name__ == "__main__":
    main()
