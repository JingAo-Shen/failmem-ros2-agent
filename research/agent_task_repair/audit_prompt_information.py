"""
Prompt Information Content Audit for 2x2 Attribution Runs.
Audits actual prompts across ALL 32 runs and EVERY individual llm_call_record.
Outputs full per-call records and condition-level aggregations.
"""
import json
import re
from pathlib import Path

RESULTS_FILE = Path("/code/failmem-ros2-agent/research/agent_task_repair/results/attribution_2x2_results.json")
AUDIT_OUTPUT = Path("/code/failmem-ros2-agent/research/agent_task_repair/results/prompt_information_audit.json")

def analyze_single_prompt(prompt_text: str, call_type: str, record: dict):
    """Audit the 8 specific information fields for a single prompt."""
    
    # 1. 目标流程步骤名称或顺序
    has_recipe_in_tools = "requires isolate 'engage' first" in prompt_text or "isolate 'release'" in prompt_text
    has_domain_interlock = "Domain Interlock Protocols:" in prompt_text
    explicit_power_chain = "isolate('power_unit', 'engage') -> clear_fault('power_unit')" in prompt_text
    explicit_pneu_chain = "isolate('pneumatic_line', 'engage') -> clear_fault('pneumatic_line')" in prompt_text
    has_step_names_or_order = (has_recipe_in_tools or has_domain_interlock or explicit_power_chain or explicit_pneu_chain)

    # 2. 前置检查要求
    has_precond_reqs = ("Verified Action Preconditions:" in prompt_text or 
                        "requires isolate" in prompt_text or 
                        "Precondition check:" in prompt_text or
                        "preconditions" in prompt_text.lower() and "unmet" in prompt_text.lower())

    # 3. 错误特征与原因的直接对应表
    has_error_reason_mapping = ("Observed Negative Preconditions & Failures:" in prompt_text or
                                "Unmet Predicates / Interlock:" in prompt_text or
                                "Failure Reason:" in prompt_text or
                                "Execution issue:" in prompt_text)

    # 4. 工具参数示例或约束条件
    has_param_examples = ("Available Tools:" in prompt_text and "(" in prompt_text and ")" in prompt_text)
    
    # 5. 失败时应调用的下一个建议动作
    has_suggested_next_action = ("Domain Interlock Protocols:" in prompt_text or
                                 "isolate('power_unit', 'engage')" in prompt_text or
                                 "Please formulate a 1 to 4 step corrective action plan" in prompt_text)

    # 6. 历史执行状态或环境事实摘要
    has_history_facts = ("=== Current Known Workstation State" in prompt_text or
                         "Verified State Transitions:" in prompt_text or
                         "=== Current Episode Execution History ===" in prompt_text)

    # 7. 提示字符数与 token 规模
    char_len = len(prompt_text)
    token_len = record.get("prompt_tokens", len(prompt_text) // 4)

    # 8. 提示信息来源：公共工具说明 vs 单次重规划注入 vs 基础提示
    sources = []
    if "Available Tools:" in prompt_text:
        sources.append("system_tool_description")
    if "=== CRITICAL CONSTRAINT REPAIR TRIGGERED ===" in prompt_text:
        sources.append("critical_replan_injection")
    elif "=== Execution Interception & Replanning ===" in prompt_text:
        sources.append("standard_replan_injection")
    if not sources:
        sources.append("base_prompt")

    return {
        "1_target_step_names_or_order": {
            "present": has_step_names_or_order,
            "in_tool_description": has_recipe_in_tools,
            "in_replan_interlock": has_domain_interlock,
            "explicit_power_chain": explicit_power_chain,
            "explicit_pneu_chain": explicit_pneu_chain,
        },
        "2_precondition_check_requirements": {
            "present": has_precond_reqs,
            "has_action_preconditions": "Verified Action Preconditions:" in prompt_text,
            "has_unmet_predicates": "Unmet Predicates" in prompt_text,
        },
        "3_error_reason_mapping_table": {
            "present": has_error_reason_mapping,
            "has_negative_preconditions": "Observed Negative Preconditions" in prompt_text,
            "has_failure_reason_field": "Failure Reason:" in prompt_text or "Execution issue:" in prompt_text,
        },
        "4_tool_params_examples_or_constraints": {
            "present": has_param_examples,
        },
        "5_suggested_next_repair_action": {
            "present": has_suggested_next_action,
            "suggests_explicit_unblocking_chain": has_domain_interlock or explicit_power_chain,
        },
        "6_history_state_or_fact_summary": {
            "present": has_history_facts,
            "has_known_state": "=== Current Known Workstation State" in prompt_text,
            "has_verified_transitions": "Verified State Transitions:" in prompt_text,
            "has_trajectory_history": "=== Current Episode Execution History ===" in prompt_text,
        },
        "7_prompt_size": {
            "character_length": char_len,
            "prompt_tokens": token_len,
        },
        "8_information_source": sources,
    }

def main():
    with open(RESULTS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    audit_summary = {
        "audit_metadata": {
            "source_results_file": str(RESULTS_FILE),
            "total_runs": len(data["results"]),
            "investigation_focus": "Exhaustive per-call audit of all 32 runs and all llm_call_records",
        },
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
        "conditions_audit": {},
    }

    all_detailed_records = []

    for cond_info in data["conditions"]:
        cname = cond_info["condition_name"]
        runs = [r for r in data["results"] if r["condition"] == cname]
        
        condition_calls = []
        call_types_seen = set()
        
        for run_idx, r in enumerate(runs):
            run_id = f"{cname}_run_{run_idx+1}"
            task_id = r.get("task_id", "")
            records = r.get("llm_call_records", [])
            
            for call_idx, rec in enumerate(records):
                ctype = rec.get("call_type", "unknown")
                call_types_seen.add(ctype)
                prompt_text = rec.get("prompt", "")
                
                analysis = analyze_single_prompt(prompt_text, ctype, rec)
                call_entry = {
                    "run_id": run_id,
                    "task_id": task_id,
                    "condition": cname,
                    "call_index": call_idx,
                    "call_type": ctype,
                    "analysis": analysis,
                }
                condition_calls.append(call_entry)
                all_detailed_records.append(call_entry)
                
        # Aggregate metrics for this condition
        total_calls = len(condition_calls)
        calls_with_step_names = sum(1 for c in condition_calls if c["analysis"]["1_target_step_names_or_order"]["present"])
        calls_with_precond = sum(1 for c in condition_calls if c["analysis"]["2_precondition_check_requirements"]["present"])
        calls_with_error_map = sum(1 for c in condition_calls if c["analysis"]["3_error_reason_mapping_table"]["present"])
        calls_with_params = sum(1 for c in condition_calls if c["analysis"]["4_tool_params_examples_or_constraints"]["present"])
        calls_with_suggested_next = sum(1 for c in condition_calls if c["analysis"]["5_suggested_next_repair_action"]["present"])
        calls_with_history = sum(1 for c in condition_calls if c["analysis"]["6_history_state_or_fact_summary"]["present"])
        
        tokens = [c["analysis"]["7_prompt_size"]["prompt_tokens"] for c in condition_calls]
        chars = [c["analysis"]["7_prompt_size"]["character_length"] for c in condition_calls]
        
        replan_calls = [c for c in condition_calls if "replan" in c["call_type"]]
        replan_with_interlock = sum(1 for c in replan_calls if c["analysis"]["1_target_step_names_or_order"]["in_replan_interlock"])
        replan_with_transitions = sum(1 for c in replan_calls if c["analysis"]["6_history_state_or_fact_summary"]["has_verified_transitions"])

        audit_summary["conditions_audit"][cname] = {
            "recipe_mode": cond_info["recipe_mode"],
            "replan_mode": cond_info["replan_mode"],
            "description": cond_info["desc"],
            "total_runs": len(runs),
            "total_llm_calls_audited": total_calls,
            "call_types_observed": sorted(list(call_types_seen)),
            "aggregates": {
                "calls_with_step_names_count": calls_with_step_names,
                "calls_with_step_names_pct": round(calls_with_step_names / max(1, total_calls) * 100, 1),
                "calls_with_preconditions_count": calls_with_precond,
                "calls_with_preconditions_pct": round(calls_with_precond / max(1, total_calls) * 100, 1),
                "calls_with_error_mapping_count": calls_with_error_map,
                "calls_with_error_mapping_pct": round(calls_with_error_map / max(1, total_calls) * 100, 1),
                "calls_with_params_count": calls_with_params,
                "calls_with_params_pct": round(calls_with_params / max(1, total_calls) * 100, 1),
                "calls_with_suggested_action_count": calls_with_suggested_next,
                "calls_with_suggested_action_pct": round(calls_with_suggested_next / max(1, total_calls) * 100, 1),
                "calls_with_history_count": calls_with_history,
                "calls_with_history_pct": round(calls_with_history / max(1, total_calls) * 100, 1),
                "replan_calls_total": len(replan_calls),
                "replan_calls_with_domain_interlock": replan_with_interlock,
                "replan_calls_with_verified_transitions": replan_with_transitions,
                "mean_prompt_tokens": round(sum(tokens) / max(1, total_calls), 1),
                "min_prompt_tokens": min(tokens) if tokens else 0,
                "max_prompt_tokens": max(tokens) if tokens else 0,
                "mean_prompt_chars": round(sum(chars) / max(1, total_calls), 1),
            },
            "per_call_records_sample_first_and_replan": [
                c for c in condition_calls if c["call_index"] == 0 or "replan" in c["call_type"]
            ][:8],
        }

    audit_summary["all_calls_index"] = [
        {
            "run_id": c["run_id"],
            "task_id": c["task_id"],
            "condition": c["condition"],
            "call_index": c["call_index"],
            "call_type": c["call_type"],
            "tokens": c["analysis"]["7_prompt_size"]["prompt_tokens"],
            "chars": c["analysis"]["7_prompt_size"]["character_length"],
            "sources": c["analysis"]["8_information_source"],
            "has_step_names": c["analysis"]["1_target_step_names_or_order"]["present"],
            "has_replan_interlock": c["analysis"]["1_target_step_names_or_order"]["in_replan_interlock"],
            "has_verified_transitions": c["analysis"]["6_history_state_or_fact_summary"]["has_verified_transitions"],
        }
        for c in all_detailed_records
    ]

    with open(AUDIT_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(audit_summary, f, indent=2, ensure_ascii=False)

    print(f"Exhaustive audit completed! Total calls indexed: {len(all_detailed_records)}. Saved to {AUDIT_OUTPUT}")

if __name__ == "__main__":
    main()
