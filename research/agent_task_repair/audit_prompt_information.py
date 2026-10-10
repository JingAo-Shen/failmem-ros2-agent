"""
Prompt Information Content Audit for 2x2 Attribution Runs.
Audits actual prompts from llm_call_records across all 4 conditions.
"""
import json
import re
from pathlib import Path

RESULTS_FILE = Path("/code/failmem-ros2-agent/research/agent_task_repair/results/attribution_2x2_results.json")
AUDIT_OUTPUT = Path("/code/failmem-ros2-agent/research/agent_task_repair/results/prompt_information_audit.json")

def analyze_prompt_content(prompt_text: str):
    """Extract information categories from prompt text."""
    # 1. Tool descriptions
    tool_desc_present = "Available Tools:" in prompt_text
    
    # 2. Human action chains (Recipe)
    has_recipe_in_tools = "requires isolate 'engage' first" in prompt_text or "isolate 'release'" in prompt_text
    has_domain_interlock = "Domain Interlock Protocols:" in prompt_text
    human_action_chains = {
        "in_tool_description": has_recipe_in_tools,
        "in_repair_prompt_domain_interlock": has_domain_interlock,
        "explicit_power_chain": "isolate('power_unit', 'engage') -> clear_fault('power_unit')" in prompt_text,
        "explicit_pneu_chain": "isolate('pneumatic_line', 'engage') -> clear_fault('pneumatic_line')" in prompt_text,
    }
    
    # 3. Source state transitions
    has_verified_transitions = "Verified State Transitions:" in prompt_text
    # Count transitions if present
    tr_matches = len(re.findall(r"-\s*Action\s+[^:]+:\s*yielded effects", prompt_text))
    source_state_transitions = {
        "present": has_verified_transitions,
        "count_extracted": tr_matches,
    }
    
    # 4. Source failure facts
    has_negative_preconditions = "Observed Negative Preconditions & Failures:" in prompt_text
    neg_matches = len(re.findall(r"-\s*Failed Action\s+[^:]+:\s*yielded", prompt_text))
    has_action_preconditions = "Verified Action Preconditions:" in prompt_text
    source_failure_facts = {
        "present": has_negative_preconditions or has_action_preconditions,
        "has_negative_preconditions": has_negative_preconditions,
        "negative_preconditions_count": neg_matches,
        "has_action_preconditions": has_action_preconditions,
    }
    
    # 5. Current observations
    has_known_state = "=== Current Known Workstation State" in prompt_text
    current_observations = {
        "present": has_known_state,
        "is_empty_or_unknown": "Workstation state unknown" in prompt_text or "{}" in prompt_text,
    }
    
    # 6. Current unmet conditions
    has_unmet_preds = "Unmet Predicates / Interlock:" in prompt_text or "Unmet conditions:" in prompt_text
    has_issue_reason = "Execution issue:" in prompt_text or "Failure Reason:" in prompt_text
    current_unmet_conditions = {
        "present": has_unmet_preds or has_issue_reason,
        "has_unmet_predicates": has_unmet_preds,
        "has_failure_reason": has_issue_reason,
    }
    
    # 7. Trajectory history
    has_traj_history = "=== Current Episode Execution History ===" in prompt_text
    trajectory_history = {
        "present": has_traj_history,
        "has_actions_recorded": has_traj_history and "No actions executed yet." not in prompt_text,
    }
    
    # 8. Repair instructions
    is_critical_repair = "=== CRITICAL CONSTRAINT REPAIR TRIGGERED ===" in prompt_text
    is_execution_interception = "=== Execution Interception & Replanning ===" in prompt_text
    repair_instructions = {
        "mode": "critical_constraint_repair" if is_critical_repair else ("execution_interception_replanning" if is_execution_interception else "standard_planning"),
        "prompts_unblocking": "Please formulate a 1 to 4 step corrective action plan to satisfy the unmet preconditions" in prompt_text,
        "prompts_goal_progress": "Please formulate a new 1 to 4 step plan to resolve active issues and progress towards the goal" in prompt_text,
    }
    
    return {
        "tool_descriptions": tool_desc_present,
        "human_action_chains": human_action_chains,
        "source_state_transitions": source_state_transitions,
        "source_failure_facts": source_failure_facts,
        "current_observations": current_observations,
        "current_unmet_conditions": current_unmet_conditions,
        "trajectory_history": trajectory_history,
        "repair_instructions": repair_instructions,
    }

def main():
    with open(RESULTS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    audit_summary = {
        "audit_metadata": {
            "source_results_file": str(RESULTS_FILE),
            "total_runs": len(data["results"]),
            "investigation_focus": "Nominal 2x2 configuration vs actual prompt information content audit",
        },
        "conditions_audit": {},
        "confounding_findings": {
            "finding_1_structured_facts_asymmetry": (
                "_plan_standard_replan actively appends verified_transitions and negative_preconditions from structured_facts, "
                "whereas _plan_constraint_repair receives structured_facts as an argument but completely omits it from the prompt string."
            ),
            "finding_2_domain_interlock_injection": (
                "ExpertRecipe_FocusedRepair injects Domain Interlock Protocols directly into the repair prompt, "
                "giving the agent an explicit step-by-step unblocking recipe (isolate -> clear_fault -> release) that no other condition receives at replan time."
            ),
            "finding_3_reclassification": (
                "The 4 conditions represent a 'Nominal 2x2 prompt configuration comparison with confounded information content' "
                "(名义 2×2 提示配置比较，存在信息内容混杂), and CANNOT be treated as a 'strictly decoupled causal attribution' (严格解耦的因果归因)."
            ),
        },
    }

    for cond_info in data["conditions"]:
        cname = cond_info["condition_name"]
        runs = [r for r in data["results"] if r["condition"] == cname]
        
        # Analyze call records by type
        by_call_type = {}
        for r in runs:
            for rec in r.get("llm_call_records", []):
                ctype = rec.get("call_type", "unknown")
                if ctype not in by_call_type:
                    by_call_type[ctype] = analyze_prompt_content(rec["prompt"])
        
        audit_summary["conditions_audit"][cname] = {
            "recipe_mode": cond_info["recipe_mode"],
            "replan_mode": cond_info["replan_mode"],
            "description": cond_info["desc"],
            "total_runs": len(runs),
            "observed_call_types": list(by_call_type.keys()),
            "call_type_information_content": by_call_type,
        }

    with open(AUDIT_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(audit_summary, f, indent=2, ensure_ascii=False)

    print(f"Audit completed successfully! Saved to {AUDIT_OUTPUT}")

if __name__ == "__main__":
    main()
