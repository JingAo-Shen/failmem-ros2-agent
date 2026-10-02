"""
Traceable Condition-Aware Failure Memory Store for FailMem Stage 2.
Implements:
  - Structured failure items with 3-valued condition matching (MATCH, MISMATCH, UNKNOWN).
  - Epistemic classification (FACT vs CONJECTURE).
  - Globally unique event tracing and verifiable repair tracking.
  - Observation-driven dynamic invalidation.
"""
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple, Set
from enum import Enum
import time


class EpistemicLevel(str, Enum):
    FACT = "FACT"              # Directly confirmed by environment tool return
    CONJECTURE = "CONJECTURE"  # Inferred or speculated without direct tool observation


class MemoryStatus(str, Enum):
    ACTIVE = "ACTIVE"              # Condition is believed to currently hold
    INVALIDATED = "INVALIDATED"    # Contradicted by newer direct tool observation
    EXPIRED = "EXPIRED"            # Expired by TTL / time-decay policy
    INAPPLICABLE = "INAPPLICABLE"  # Known preconditions contradict current state


class ConditionMatchResult(str, Enum):
    MATCH = "MATCH"                # All required preconditions are confirmed in current known state
    MISMATCH = "MISMATCH"          # At least one precondition contradicts current known state
    UNKNOWN = "UNKNOWN"            # Some preconditions cannot be verified from current known state


@dataclass
class FailureMemoryItem:
    mem_id: str
    event_id: str                  # Globally unique event ID (e.g., 'evt_t0_s03_fail')
    task_id: str
    action_name: str
    target: str
    error_code: str
    observable_conditions: Dict[str, Any]
    raw_message: str
    epistemic_level: EpistemicLevel = EpistemicLevel.FACT
    status: MemoryStatus = MemoryStatus.ACTIVE
    created_at_sim_time: float = 0.0
    created_task_index: int = 0
    last_verified_sim_time: float = 0.0
    suggested_repair: Optional[Dict[str, Any]] = None
    repair_verified: bool = False
    repair_event_id: Optional[str] = None
    evidence_ref: str = ""

    def evaluate_applicability(self, known_state: Dict[str, Any]) -> ConditionMatchResult:
        """
        Evaluates 3-valued condition matching against current known/observed state.
        Returns MATCH, MISMATCH, or UNKNOWN.
        """
        if not self.observable_conditions:
            return ConditionMatchResult.MATCH

        has_unknown = False
        for k, expected_v in self.observable_conditions.items():
            if k not in known_state:
                has_unknown = True
            elif known_state[k] != expected_v:
                return ConditionMatchResult.MISMATCH

        return ConditionMatchResult.UNKNOWN if has_unknown else ConditionMatchResult.MATCH

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mem_id": self.mem_id,
            "event_id": self.event_id,
            "task_id": self.task_id,
            "action_name": self.action_name,
            "target": self.target,
            "error_code": self.error_code,
            "observable_conditions": self.observable_conditions,
            "raw_message": self.raw_message,
            "epistemic_level": self.epistemic_level.value,
            "status": self.status.value,
            "created_at_sim_time": self.created_at_sim_time,
            "created_task_index": self.created_task_index,
            "last_verified_sim_time": self.last_verified_sim_time,
            "suggested_repair": self.suggested_repair,
            "repair_verified": self.repair_verified,
            "repair_event_id": self.repair_event_id,
            "evidence_ref": self.evidence_ref,
        }

    def format_for_prompt(self, match_result: ConditionMatchResult = ConditionMatchResult.MATCH) -> str:
        """Format item for LLM planner context with clear condition match status."""
        repair_str = ""
        if self.suggested_repair:
            status_tag = "VERIFIED" if self.repair_verified else "UNVERIFIED"
            repair_str = f" | Suggested Repair ({status_tag}): {self.suggested_repair}"

        match_tag = f"[{match_result.value}]" if match_result != ConditionMatchResult.MATCH else ""
        return (
            f"[{self.status.value}{match_tag}] {self.action_name}({self.target}) failed ({self.error_code}). "
            f"Conditions: {self.observable_conditions} (Level: {self.epistemic_level.value}){repair_str}"
        )


class ConditionAwareMemoryStore:
    def __init__(self):
        self.memories: Dict[str, FailureMemoryItem] = {}
        self._next_id: int = 1

    def record_failure(
        self,
        event_id: str,
        task_id: str,
        action_name: str,
        target: str,
        error_code: str,
        observable_conditions: Dict[str, Any],
        raw_message: str,
        epistemic_level: EpistemicLevel = EpistemicLevel.FACT,
        sim_time: float = 0.0,
        task_index: int = 0,
        suggested_repair: Optional[Dict[str, Any]] = None,
        evidence_ref: str = "",
    ) -> FailureMemoryItem:
        mem_id = f"mem_{self._next_id:04d}"
        self._next_id += 1

        item = FailureMemoryItem(
            mem_id=mem_id,
            event_id=event_id,
            task_id=task_id,
            action_name=action_name,
            target=target,
            error_code=error_code,
            observable_conditions=observable_conditions,
            raw_message=raw_message,
            epistemic_level=epistemic_level,
            status=MemoryStatus.ACTIVE,
            created_at_sim_time=sim_time,
            created_task_index=task_index,
            last_verified_sim_time=sim_time,
            suggested_repair=suggested_repair,
            repair_verified=False,
            evidence_ref=evidence_ref,
        )
        self.memories[mem_id] = item
        return item

    def update_with_observation(
        self,
        observation: Dict[str, Any],
        current_sim_time: float,
        obs_event_id: str = "",
    ) -> List[str]:
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
                    item.evidence_ref = obs_event_id
                    invalidated_ids.append(mem_id)

            # Case 2: Missing credential acquired
            if "credentials" in observation:
                held_creds = set(observation["credentials"])
                req_cred = item.observable_conditions.get("required_credential")
                if req_cred and req_cred in held_creds:
                    item.status = MemoryStatus.INVALIDATED
                    item.last_verified_sim_time = current_sim_time
                    item.evidence_ref = obs_event_id
                    invalidated_ids.append(mem_id)

            # Case 3: Recipient was busy/in_meeting, now available
            if "recipient" in observation and "status" in observation:
                rec_name = observation["recipient"]
                rec_status = observation["status"]
                if item.observable_conditions.get(f"{rec_name}_status") == "in_meeting" and rec_status == "available":
                    item.status = MemoryStatus.INVALIDATED
                    item.last_verified_sim_time = current_sim_time
                    item.evidence_ref = obs_event_id
                    invalidated_ids.append(mem_id)

        return invalidated_ids

    def mark_repair_success(
        self,
        failed_event_id: str,
        repair_event_id: str,
        repair_action: Dict[str, Any],
    ):
        """Mark a suggested repair as verified when execution logs confirm the full chain."""
        for item in self.memories.values():
            if item.event_id == failed_event_id:
                item.suggested_repair = repair_action
                item.repair_verified = True
                item.repair_event_id = repair_event_id

    def retrieve_memories(
        self,
        known_state: Dict[str, Any],
        query_target: Optional[str] = None,
    ) -> List[Tuple[FailureMemoryItem, ConditionMatchResult]]:
        """
        Retrieves active memories evaluated under 3-valued condition matching.
        Returns list of (item, match_result). Filters out explicit MISMATCH items.
        """
        results = []
        for item in self.memories.values():
            if item.status != MemoryStatus.ACTIVE:
                continue

            match_res = item.evaluate_applicability(known_state)
            if match_res == ConditionMatchResult.MISMATCH:
                continue  # Inapplicable condition

            # Filter by target or relevant entity if provided
            if query_target:
                target_match = (
                    item.target.lower() in query_target.lower()
                    or query_target.lower() in item.target.lower()
                    or any(query_target.lower() in k.lower() for k in item.observable_conditions)
                )
                if not target_match:
                    continue

            results.append((item, match_res))

        return results

    def get_all_memories(self) -> List[FailureMemoryItem]:
        return list(self.memories.values())

    def clear(self):
        self.memories.clear()
        self._next_id = 1
