"""FailMem Milestone P2a Deterministic Failure Memory Module.

Provides deterministic, rule-based failure memory policies:
- M0: No Memory (Blind repeat dispatches until budget exhaustion)
- M1: Persistent Memory (Permanent suppression of failed targets/regions)
- M2: Conditional Memory (Invalidated only by verified physical perception evidence)

Zero LLM reliance, zero privileged oracle sensors, strict auditability.
"""
from __future__ import annotations

import copy
import math
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union


class MemoryState(str, Enum):
    """Lifecycle states of a failure memory entry."""
    ACTIVE = "ACTIVE"                       # Suppression active
    INVALIDATED = "INVALIDATED"             # Precondition met (e.g. doorway FREE), retry permitted
    RECOVERY_VERIFIED = "RECOVERY_VERIFIED" # Physical arrival confirmed after recovery dispatch
    EXPIRED = "EXPIRED"                     # Budget or horizon exhausted


@dataclass
class FailureMemoryEntry:
    """Structured record of an observed execution failure and its invalidation criteria."""
    memory_id: str
    created_sim_time: float
    target_goal: List[float]
    target_region: str
    failure_reason: str
    invalidation_criteria: Dict[str, Any]
    state: MemoryState = MemoryState.ACTIVE
    invalidation_sim_time: Optional[float] = None
    invalidation_evidence: Optional[Dict[str, Any]] = None
    verification_sim_time: Optional[float] = None
    verification_evidence: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["state"] = self.state.value
        return d


class FailureMemoryStore:
    """Deterministic memory store tracking failure entries, condition checks, and lifecycle."""

    def __init__(self, region_matching_tolerance_m: float = 0.50):
        self.region_matching_tolerance_m = region_matching_tolerance_m
        self.entries: List[FailureMemoryEntry] = []
        self._next_id = 1

    def record_failure(
        self,
        target_goal: List[float],
        target_region: str,
        failure_reason: str,
        sim_time: float,
        invalidation_criteria: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> FailureMemoryEntry:
        """Register a new active failure memory entry."""
        if invalidation_criteria is None:
            invalidation_criteria = {
                "type": "DOORWAY_CLEARANCE",
                "region": target_region,
                "required_doorway_state": "FREE",
            }
        entry = FailureMemoryEntry(
            memory_id=f"mem_entry_{self._next_id:04d}",
            created_sim_time=round(float(sim_time), 4),
            target_goal=[round(float(x), 4) for x in target_goal[:3]],
            target_region=str(target_region),
            failure_reason=str(failure_reason),
            invalidation_criteria=invalidation_criteria,
            state=MemoryState.ACTIVE,
            metadata=metadata or {},
        )
        self._next_id += 1
        self.entries.append(entry)
        return entry

    def is_dispatch_blocked(
        self,
        target_goal: List[float],
        target_region: Optional[str] = None,
    ) -> Tuple[bool, Optional[FailureMemoryEntry], str]:
        """Check if dispatch to target_goal or target_region is blocked by an ACTIVE memory entry."""
        for entry in self.entries:
            if entry.state == MemoryState.ACTIVE:
                # Check region match
                if target_region and entry.target_region == target_region:
                    return True, entry, f"BLOCKED_BY_ACTIVE_MEMORY_REGION ({entry.memory_id})"
                # Check coordinate match
                dist = math.hypot(target_goal[0] - entry.target_goal[0], target_goal[1] - entry.target_goal[1])
                if dist <= self.region_matching_tolerance_m:
                    return True, entry, f"BLOCKED_BY_ACTIVE_MEMORY_GOAL ({entry.memory_id}, dist={dist:.2f}m)"
        return False, None, "DISPATCH_ALLOWED"

    def evaluate_perception_for_invalidation(
        self,
        perception_evidence: Dict[str, Any],
        sim_time: float,
    ) -> List[FailureMemoryEntry]:
        """Evaluate physical perception evidence against invalidation criteria of ACTIVE entries."""
        invalidated_entries = []
        doorway_state = perception_evidence.get("doorway_state")

        for entry in self.entries:
            if entry.state == MemoryState.ACTIVE:
                criteria = entry.invalidation_criteria
                if criteria.get("type") == "DOORWAY_CLEARANCE":
                    req_state = criteria.get("required_doorway_state", "FREE")
                    if doorway_state == req_state:
                        entry.state = MemoryState.INVALIDATED
                        entry.invalidation_sim_time = round(float(sim_time), 4)
                        entry.invalidation_evidence = copy.deepcopy(perception_evidence)
                        invalidated_entries.append(entry)

        return invalidated_entries

    def verify_recovery(
        self,
        target_goal: List[float],
        physical_evaluation: Dict[str, Any],
        sim_time: float,
    ) -> bool:
        """Mark invalidated entries as RECOVERY_VERIFIED upon confirmed physical arrival."""
        arrival = physical_evaluation.get("strict_physical_arrival_and_stable", False)
        if not arrival:
            return False

        verified_any = False
        for entry in self.entries:
            if entry.state == MemoryState.INVALIDATED:
                dist = math.hypot(target_goal[0] - entry.target_goal[0], target_goal[1] - entry.target_goal[1])
                if dist <= self.region_matching_tolerance_m:
                    entry.state = MemoryState.RECOVERY_VERIFIED
                    entry.verification_sim_time = round(float(sim_time), 4)
                    entry.verification_evidence = copy.deepcopy(physical_evaluation)
                    verified_any = True

        return verified_any

    def get_summary(self) -> Dict[str, Any]:
        """Export full snapshot of memory entries and counts."""
        active = [e.to_dict() for e in self.entries if e.state == MemoryState.ACTIVE]
        invalidated = [e.to_dict() for e in self.entries if e.state == MemoryState.INVALIDATED]
        verified = [e.to_dict() for e in self.entries if e.state == MemoryState.RECOVERY_VERIFIED]
        return {
            "total_entries": len(self.entries),
            "active_count": len(active),
            "invalidated_count": len(invalidated),
            "recovery_verified_count": len(verified),
            "entries": [e.to_dict() for e in self.entries],
        }


class FailureMemoryPolicy:
    """Base interface for policy decision making."""
    policy_name: str = "BASE"

    def on_navigation_failure(
        self,
        target_goal: List[float],
        target_region: str,
        failure_reason: str,
        sim_time: float,
        perception_evidence: Optional[Dict[str, Any]] = None,
    ):
        pass

    def check_dispatch_allowed(
        self,
        target_goal: List[float],
        target_region: str,
        sim_time: float,
    ) -> Tuple[bool, str]:
        raise NotImplementedError

    def on_observation_update(
        self,
        perception_evidence: Dict[str, Any],
        sim_time: float,
    ):
        pass

    def on_navigation_success(
        self,
        target_goal: List[float],
        target_region: str,
        physical_eval: Dict[str, Any],
        sim_time: float,
    ):
        pass

    def export_state(self) -> Dict[str, Any]:
        return {"policy_name": self.policy_name}


class M0NoMemoryPolicy(FailureMemoryPolicy):
    """M0: No Memory Baseline.
    
    Always permits navigation dispatches regardless of prior failures.
    """
    policy_name = "M0_NO_MEMORY"

    def __init__(self):
        self.dispatches_attempted = 0
        self.failures_recorded = 0

    def on_navigation_failure(self, target_goal, target_region, failure_reason, sim_time, perception_evidence=None):
        self.failures_recorded += 1

    def check_dispatch_allowed(self, target_goal, target_region, sim_time) -> Tuple[bool, str]:
        self.dispatches_attempted += 1
        return True, "M0_ALWAYS_ALLOWED"

    def export_state(self) -> Dict[str, Any]:
        return {
            "policy_name": self.policy_name,
            "dispatches_attempted": self.dispatches_attempted,
            "failures_recorded": self.failures_recorded,
            "memory_entries": [],
        }


class M1PersistentMemoryPolicy(FailureMemoryPolicy):
    """M1: Persistent Memory Baseline.
    
    Permanently suppresses failed targets/regions without invalidation mechanism.
    """
    policy_name = "M1_PERSISTENT_MEMORY"

    def __init__(self, tolerance_m: float = 0.50):
        self.tolerance_m = tolerance_m
        self.blocked_goals: List[Dict[str, Any]] = []
        self.blocked_regions: set = set()
        self.dispatches_attempted = 0
        self.dispatches_blocked = 0

    def on_navigation_failure(self, target_goal, target_region, failure_reason, sim_time, perception_evidence=None):
        self.blocked_goals.append({
            "goal": list(target_goal[:3]),
            "sim_time": round(float(sim_time), 4),
            "reason": str(failure_reason),
        })
        self.blocked_regions.add(str(target_region))

    def check_dispatch_allowed(self, target_goal, target_region, sim_time) -> Tuple[bool, str]:
        self.dispatches_attempted += 1
        if str(target_region) in self.blocked_regions:
            self.dispatches_blocked += 1
            return False, f"M1_PERSISTENT_BLOCK_REGION ({target_region})"

        for bg in self.blocked_goals:
            dist = math.hypot(target_goal[0] - bg["goal"][0], target_goal[1] - bg["goal"][1])
            if dist <= self.tolerance_m:
                self.dispatches_blocked += 1
                return False, f"M1_PERSISTENT_BLOCK_GOAL ({dist:.2f}m <= {self.tolerance_m}m)"

        return True, "M1_DISPATCH_ALLOWED"

    def export_state(self) -> Dict[str, Any]:
        return {
            "policy_name": self.policy_name,
            "dispatches_attempted": self.dispatches_attempted,
            "dispatches_blocked": self.dispatches_blocked,
            "blocked_goals": self.blocked_goals,
            "blocked_regions": list(self.blocked_regions),
        }


class M2ConditionalMemoryPolicy(FailureMemoryPolicy):
    """M2: Conditional Failure Memory (FailMem Core Mechanism).
    
    Suppresses repeats while precondition (doorway FREE) is unmet.
    Invalidates memory upon physical perception evidence.
    Verifies recovery upon confirmed arrival.
    """
    policy_name = "M2_CONDITIONAL_MEMORY"

    def __init__(self, tolerance_m: float = 0.50):
        self.store = FailureMemoryStore(region_matching_tolerance_m=tolerance_m)
        self.dispatches_attempted = 0
        self.dispatches_blocked = 0
        self.dispatches_permitted = 0

    def on_navigation_failure(self, target_goal, target_region, failure_reason, sim_time, perception_evidence=None):
        self.store.record_failure(
            target_goal=target_goal,
            target_region=target_region,
            failure_reason=failure_reason,
            sim_time=sim_time,
            metadata={"initial_evidence": perception_evidence},
        )

    def on_observation_update(self, perception_evidence: Dict[str, Any], sim_time: float):
        self.store.evaluate_perception_for_invalidation(perception_evidence=perception_evidence, sim_time=sim_time)

    def check_dispatch_allowed(self, target_goal, target_region, sim_time) -> Tuple[bool, str]:
        self.dispatches_attempted += 1
        blocked, entry, reason = self.store.is_dispatch_blocked(target_goal=target_goal, target_region=target_region)
        if blocked:
            self.dispatches_blocked += 1
            return False, reason
        self.dispatches_permitted += 1
        return True, reason

    def on_navigation_success(self, target_goal, target_region, physical_eval, sim_time):
        self.store.verify_recovery(target_goal=target_goal, physical_evaluation=physical_eval, sim_time=sim_time)

    def export_state(self) -> Dict[str, Any]:
        res = self.store.get_summary()
        res.update({
            "policy_name": self.policy_name,
            "dispatches_attempted": self.dispatches_attempted,
            "dispatches_blocked": self.dispatches_blocked,
            "dispatches_permitted": self.dispatches_permitted,
        })
        return res
