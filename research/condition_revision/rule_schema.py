"""
Rule Schema & Data Representation for Counterexample-Driven Condition Revision.
Defines explicit provenance tracking, versioning, support case links, and condition structures.
"""

from typing import Dict, Any, List, Optional
import time


class Rule:
    def __init__(
        self,
        rule_id: str,
        goal: str,
        applicability_conditions: List[str],
        recovery_procedure: str,
        avoidance_rules: List[str] = None,
        support_cases: List[Dict[str, Any]] = None,
        counterexample_cases: List[Dict[str, Any]] = None,
        version: int = 1,
        status: str = "active"
    ):
        self.rule_id = rule_id
        self.version = version
        self.goal = goal
        self.applicability_conditions = list(applicability_conditions)
        self.recovery_procedure = recovery_procedure
        self.avoidance_rules = list(avoidance_rules or [])
        self.support_cases = list(support_cases or [])
        self.counterexample_cases = list(counterexample_cases or [])
        self.status = status
        self.revision_history = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "version": self.version,
            "goal": self.goal,
            "applicability_conditions": list(self.applicability_conditions),
            "recovery_procedure": self.recovery_procedure,
            "avoidance_rules": list(self.avoidance_rules),
            "support_cases": list(self.support_cases),
            "counterexample_cases": list(self.counterexample_cases),
            "status": self.status,
            "revision_history": list(self.revision_history)
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Rule":
        rule = cls(
            rule_id=data.get("rule_id", "rule_0"),
            goal=data.get("goal", ""),
            applicability_conditions=data.get("applicability_conditions", []),
            recovery_procedure=data.get("recovery_procedure", ""),
            avoidance_rules=data.get("avoidance_rules", []),
            support_cases=data.get("support_cases", []),
            counterexample_cases=data.get("counterexample_cases", []),
            version=data.get("version", 1),
            status=data.get("status", "active")
        )
        rule.revision_history = data.get("revision_history", [])
        return rule

    def add_support_case(self, task_id: str, task_desc: str, target: str, key_obs: str, score: float):
        case = {
            "task_id": task_id,
            "task_desc": task_desc,
            "target": target,
            "key_obs": key_obs,
            "score": score,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        }
        self.support_cases.append(case)

    def add_counterexample_case(self, task_id: str, task_desc: str, target: str, key_obs: str, score: float):
        case = {
            "task_id": task_id,
            "task_desc": task_desc,
            "target": target,
            "key_obs": key_obs,
            "score": score,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        }
        self.counterexample_cases.append(case)

    def record_revision(self, old_conditions: List[str], new_condition: str, reason: str, verification_summary: Dict[str, Any]):
        self.version += 1
        self.revision_history.append({
            "from_version": self.version - 1,
            "to_version": self.version,
            "old_conditions": old_conditions,
            "added_condition": new_condition,
            "reason": reason,
            "verification_summary": verification_summary,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        })
