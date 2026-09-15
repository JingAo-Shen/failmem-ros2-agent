import argparse
import sys
import json
import os
from src.evaluate import run_evaluation

def main():
    parser = argparse.ArgumentParser(description="FailMem Runner CLI")
    parser.add_argument("--config", required=True)
    args = parser.parse_args()

    with open(args.config, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    data_file = cfg.get("data_file", "data/task-specs.jsonl")
    with open(data_file, "r", encoding="utf-8") as f:
        tasks = [json.loads(line) for line in f if line.strip()]

    run_id = cfg.get("run_id", "smoke_run")
    metrics = run_evaluation(
        tasks,
        use_memory=cfg.get("use_memory", True),
        use_verifier=cfg.get("use_verifier", True),
        output_dir=os.path.join("runs", run_id)
    )
    print(f"Run completed: {run_id}, Recovery Success Rate: {metrics['recovery_success_rate']*100:.1f}%, Repeat Failure Rate: {metrics['repeat_failure_rate']*100:.2f}%")

if __name__ == "__main__":
    main()
