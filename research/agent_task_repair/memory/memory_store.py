"""
Condition-Aware Failure Memory Store for FailMem Stage 2.
Implements structured failure items, epistemic tagging (FACT vs CONJECTURE),
evidence-driven dynamic invalidation, and verified repair action tracking.
"""
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Set
from enum import Enum
import time


class EpistemicLevel(str, Enum):
    FACT = "FACT"              # Directly confirmed by environment tool response
    CONJECTURE = "CONJECTURE"  # Inferred or speculated by LLM without direct tool evidence


class MemoryStatus(str, Enum):
    ACTIVE = "ACTIVE"              # Failure condition is believed to still hold
    INVALIDATED = "INVALIDATED"    # Contradicted by newer sensor/tool evidence
    EXPIRED = "EXPIRED"            # Staled by time/decay heuristic
    INAPPLICABLE = "INAPPLICABLE"  # Preconditions do not match current context


@dataclass
class FailureMemoryItem:
    mem_id: str
    task_id: str
    action_name: str
    target: str
    error_code: str
    observable_conditions: Dict[str, Any]
    raw_message: str
    epistemic_level: EpistemicLevel = EpistemicLevel.FACT
    status: MemoryStatus = MemoryStatus.ACTIVE
    created_at_sim_time: float = 0.0
    last_verified_sim_time: float = 0.0
    suggested_repair: Optional[Dict[str, Any]] = None
    repair_verified: bool = False
    evidence_ref: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mem_id": self.mem_id,
            "task_id": self.task_id,
            "action_name": self.action_name,
            "target": self.target,
            "error_code": self.error_code,
            "observable_conditions": self.observable_conditions,
            "raw_message": self.raw_message,
            "epistemic_level": self.epistemic_level.value,
            "status": self.status.value,
            "created_at_sim_time": self.created_at_sim_time,
            "last_verified_sim_time": self.last_verified_sim_time,
            "suggested_repair": self.suggested_repair,
            "repair_verified": self.repair_verified,
            "evidence_ref": self.evidence_ref,
        }

    def format_for_prompt(self) -> str:
        """Format item for LLM planner context."""
        repair_str = ""
        if self.suggested_repair:
            status_tag = "VERIFIED" if self.repair_verified else "UNVERIFIED"
            repair_str = f" | Suggested Repair ({status_tag}): {self.suggested_repair}"
        return (
            f"[{self.status.value}] {self.action_name}({self.target}) failed ({self.error_code}). "
            f"Conditions: {self.observable_conditions} (Level: {self.epistemic_level.value}){repair_str}"
        )


class ConditionAwareMemoryStore:
    def __init__(self):
        self.memories: Dict[str, FailureMemoryItem] = {}
        self._next_id: int = 1

    def record_failure(
        self,
        task_id: str,
        action_name: str,
        target: str,
        error_code: str,
        observable_conditions: Dict[str, Any],
        raw_message: str,
        epistemic_level: EpistemicLevel = EpistemicLevel.FACT,
        sim_time: float = 0.0,
        suggested_repair: Optional[Dict[str, Any]] = None,
        evidence_ref: str = "",
    ) -> FailureMemoryItem:
        mem_id = f"mem_{self._next_id:04d}"
        self._next_id += 1

        item = FailureMemoryItem(
            mem_id=mem_id,
            task_id=task_id,
            action_name=action_name,
            target=target,
            error_code=error_code,
            observable_conditions=observable_conditions,
            raw_message=raw_message,
            epistemic_level=epistemic_level,
            status=MemoryStatus.ACTIVE,
            created_at_sim_time=sim_time,
            last_verified_sim_time=sim_time,
            suggested_repair=suggested_repair,
            repair_verified=False,
            evidence_ref=evidence_ref,
        )
        self.memories[mem_id] = item
        return item

    def update_with_observation(self, observation: Dict[str, Any], current_sim_time: float) -> List[str]:
        """
        Actively inspects new tool observations to dynamically invalidate contradicted memories.
        Returns list of invalidated memory IDs.
        """
        invalidated_ids = []
        for mem_id, item in self.memories.items():
            if item.status != MemoryStatus.ACTIVE:
                continue

            # Case 1: Doorway was blocked, now observed FREE
            if "door" in observation and "passage_state" in observation:
                door_name = observation["door"]
                passage_state = observation["passage_state"]
                if item.observable_conditions.get(f"{door_name}_state") == "OCCUPIED" and passage_state == "FREE":
                    item.status = MemoryStatus.INVALIDATED
                    item.last_verified_sim_time = current_sim_time
                    invalidated_ids.append(mem_id)

            # Case 2: Missing credential acquired
            if "credentials" in observation:
                held_creds = set(observation["credentials"])
                req_cred = item.observable_conditions.get("required_credential")
                if req_cred and req_cred in held_creds:
                    item.status = MemoryStatus.INVALIDATED
                    item.last_verified_sim_time = current_sim_time
                    invalidated_ids.append(mem_id)

            # Case 3: Recipient was busy/in_meeting, now available
            if "recipient" in observation and "status" in observation:
                rec_name = observation["recipient"]
                rec_status = observation["status"]
                if item.observable_conditions.get(f"{rec_name}_status") == "in_meeting" and rec_status == "available":
                    item.status = MemoryStatus.INVALIDATED
                    item.last_verified_sim_time = current_sim_time
                    invalidated_ids.append(mem_id)

        return invalidated_ids

    def mark_repair_success(self, failed_action_name: str, target: str, repair_action: Dict[str, Any]):
        """Mark a suggested repair as verified when executed successfully."""
        for item in self.memories.values():
            if item.action_name == failed_action_name and item.target == target:
                item.suggested_repair = repair_action
                item.repair_verified = True

    def get_active_memories(self, current_context: Optional[Dict[str, Any]] = None) -> List[FailureMemoryItem]:
        """Returns all ACTIVE memories that match current context predicates."""
        active = [m for m in self.memories.values() if m.status == MemoryStatus.ACTIVE]
        if not current_context:
            return active

        applicable = []
        for m in active:
            # Check if any condition is explicitly contradicted by known context
            is_valid = True
            for k, expected_v in m.observable_conditions.items():
                if k in current_context and current_context[k] != expected_v:
                    is_valid = False
                    break
            if is_valid:
                applicable.append(m)
        return applicable

    def get_all_memories(self) -> List[FailureMemoryItem]:
        return list(self.memories.values())

    def clear(self):
        self.memories.clear()
        self._next_id = 1
