"""
Run Manager Module for Experiment Execution and Output Isolation.
Creates independent run directories and logs:
- metadata.json (environment, model, commit, config)
- episodes.jsonl (episode summaries)
- steps.jsonl (step-level telemetry: proposed action, executed action, adapter modification, condition eval, memory exposure)
- revision_events.jsonl (deterministic condition verification traces and decisions)
- metrics.json (computed objective metrics)
"""

import os
import json
import time
import subprocess
from typing import Dict, Any, List, Optional


class RunManager:
    def __init__(self, base_dir: str = "/code/failmem-ros2-agent/research/condition_revision/runs", phase: str = "P0", tag: str = "validity_check"):
        self.phase = phase
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        self.run_id = f"run_{timestamp}_{phase}_{tag}"
        self.run_dir = os.path.join(base_dir, self.run_id)
        os.makedirs(self.run_dir, exist_ok=True)

        self.episodes_path = os.path.join(self.run_dir, "episodes.jsonl")
        self.steps_path = os.path.join(self.run_dir, "steps.jsonl")
        self.revision_events_path = os.path.join(self.run_dir, "revision_events.jsonl")
        self.metadata_path = os.path.join(self.run_dir, "metadata.json")
        self.metrics_path = os.path.join(self.run_dir, "metrics.json")

        self._init_metadata()

    def _get_git_commit(self) -> str:
        try:
            return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd="/code/failmem-ros2-agent").decode().strip()
        except Exception:
            return "unknown"

    def _init_metadata(self):
        metadata = {
            "run_id": self.run_id,
            "phase": self.phase,
            "git_commit": self._get_git_commit(),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "environment": "ScienceWorld v1.2.3 (OpenJDK 11)",
            "simplification": "teleportAction,openDoors",
            "model": "Qwen2.5-Coder-7B-Instruct (bfloat16, RTX 2080 Ti)",
            "temperature": 0.0,
            "sampling": False
        }
        with open(self.metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)

    def log_step(
        self,
        episode_id: str,
        step: int,
        thought: str,
        model_action: str,
        executed_action: str,
        adapter_modified: bool,
        adapter_reason: str,
        observation: str,
        reward: float,
        done: bool,
        injected_rule: Optional[Dict[str, Any]] = None,
        condition_eval_results: Optional[List[Dict[str, Any]]] = None,
        termination_reason: Optional[str] = None,
        memory_exposure: Optional[Dict[str, Any]] = None
    ):
        record = {
            "episode_id": episode_id,
            "step": step,
            "thought": thought,
            "action": executed_action,
            "executed_action": executed_action,
            "model_action": model_action,
            "proposed_action": model_action,
            "adapter_modified": adapter_modified,
            "adapter_reason": adapter_reason,
            "observation": observation,
            "reward": reward,
            "done": done,
            "injected_rule_id": injected_rule.get("rule_id") if injected_rule else None,
            "injected_rule_version": injected_rule.get("version") if injected_rule else None,
            "condition_eval_results": condition_eval_results or [],
            "memory_exposure": memory_exposure,
            "termination_reason": termination_reason
        }
        with open(self.steps_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    def log_episode(
        self,
        episode_id: str,
        stage: str,
        round_num: int,
        agent_name: str,
        task_name: str,
        variation: int,
        task_desc: str,
        target_entity: str,
        success: bool,
        score: float,
        num_steps: int,
        termination_reason: str,
        memory_injected: bool,
        memory_exposure: Optional[Dict[str, Any]] = None
    ):
        record = {
            "episode_id": episode_id,
            "stage": stage,
            "round": round_num,
            "agent": agent_name,
            "task_name": task_name,
            "variation": variation,
            "task_desc": task_desc,
            "task_description": task_desc,
            "target_entity": target_entity,
            "success": success,
            "score": score,
            "num_steps": num_steps,
            "termination_reason": termination_reason,
            "memory_injected": memory_injected,
            "memory_exposure": memory_exposure
        }
        with open(self.episodes_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    def log_revision_event(self, event_data: Dict[str, Any]):
        event_data["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with open(self.revision_events_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event_data) + "\n")

    def save_metrics(self, metrics: Dict[str, Any]):
        with open(self.metrics_path, "w", encoding="utf-8") as f:
            json.dump(metrics, f, indent=2)
