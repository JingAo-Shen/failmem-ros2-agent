"""
Regression Verifier Module:
Executes candidate condition predicates across historical support cases and counterexamples.
Replaces flawed LLM self-reporting with deterministic program evaluation.
"""

from typing import Dict, Any, List, Tuple
from condition_evaluator import ConditionEvaluator, ConditionResult


class RegressionVerifier:
    def __init__(self):
        self.evaluator = ConditionEvaluator()

    def verify_candidate_condition(
        self,
        candidate_condition: str,
        support_cases: List[Dict[str, Any]],
        counterexample_case: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Independently checks if candidate_condition:
        1. Evaluates to TRUE on all historical support cases (No regression).
        2. Evaluates to FALSE on the counterexample case (Excludes counterexample).
        """
        report = {
            "candidate_condition": candidate_condition,
            "support_checks": [],
            "counterexample_check": None,
            "passed_regression": False,
            "passed_exclusion": False,
            "decision": "REJECT",
            "reason": ""
        }

        # 1. Check Historical Support Cases
        all_support_passed = True
        for case in support_cases:
            target = case.get("target", "unknown_target")
            task_desc = case.get("task_desc", "")
            key_obs = case.get("key_obs", "")
            
            res, explanation = self.evaluator.evaluate_condition_string(
                condition_str=candidate_condition,
                target=target,
                task_desc=task_desc,
                current_obs=key_obs
            )
            
            check_item = {
                "task_id": case.get("task_id"),
                "target": target,
                "result": res.value,
                "explanation": explanation
            }
            report["support_checks"].append(check_item)
            
            if res != ConditionResult.TRUE:
                all_support_passed = False

        report["passed_regression"] = all_support_passed and len(support_cases) > 0

        # 2. Check Counterexample Case
        cnt_target = counterexample_case.get("target", "unknown_target")
        cnt_desc = counterexample_case.get("task_desc", "")
        cnt_obs = counterexample_case.get("key_obs", "")
        
        cnt_res, cnt_expl = self.evaluator.evaluate_condition_string(
            condition_str=candidate_condition,
            target=cnt_target,
            task_desc=cnt_desc,
            current_obs=cnt_obs
        )
        report["counterexample_check"] = {
            "task_id": counterexample_case.get("task_id"),
            "target": cnt_target,
            "result": cnt_res.value,
            "explanation": cnt_expl
        }

        # Exclusion passes ONLY if condition evaluates to FALSE on counterexample
        report["passed_exclusion"] = (cnt_res == ConditionResult.FALSE)

        # 3. Overall Decision
        if report["passed_regression"] and report["passed_exclusion"]:
            report["decision"] = "ACCEPT"
            report["reason"] = "Condition preserves all historical support cases (TRUE) and cleanly excludes counterexample (FALSE)."
        elif not report["passed_regression"]:
            report["decision"] = "REJECT_REGRESSION"
            report["reason"] = f"Candidate condition failed regression check on historical support cases."
        elif not report["passed_exclusion"]:
            report["decision"] = "REJECT_INSUFFICIENT_EXCLUSION"
            report["reason"] = f"Candidate condition does not evaluate to FALSE on the counterexample (result={cnt_res.value})."

        return report
