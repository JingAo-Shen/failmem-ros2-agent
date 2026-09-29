"""FailMem Milestone P2a Deterministic Failure Memory Module (v2.0).

Provides deterministic, rule-based failure memory policies:
- M0: No Memory (Blind repeat dispatches until budget exhaustion)
- M1: Persistent Memory (Permanent suppression of failed targets/regions without invalidation)
- M2: Conditional Memory (Invalidated only by verified physical perception evidence, verified on arrival)

Strict Architecture Rules:
1. Zero LLM reliance, zero privileged oracle sensors, strict auditability.
2. Identical memory recording eligibility for M1 and M2 (requires action failure + fresh OCCUPIED evidence).
3. Invalidation requires valid FREE evidence strictly newer than failure timestamp matching map & region.
4. Policy feedback strictly isolated from ground-truth evaluation records.
"""
from __future__ import annotations

import copy
import math
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union


class MemoryState(str, Enum):
    """Lifecycle states of a failure memory entry."""
    ACTIVE = "ACTIVE"                       # Obstruction active -> action dispatch suppressed
    INVALIDATED = "INVALIDATED"             # Precondition met (doorway FREE) -> retry action permitted
    RECOVERY_VERIFIED = "RECOVERY_VERIFIED" # Recovery navigation action succeeded & verified online
    EXPIRED = "EXPIRED"                     # Lifetime or episode horizon exhausted


def is_finite_number(val: Any) -> bool:
    if val is None or not isinstance(val, (int, float)):
        return False
    return not (math.isnan(val) or math.isinf(val))


def is_failure_eligible_for_doorway_memory(
    failure_reason: str,
    perception_evidence: Optional[Dict[str, Any]],
) -> bool:
    """Validate if a navigation failure qualifies for doorway blockage memory creation.
    
    Strict Rules:
    - Must have fresh physical perception evidence.
    - doorway_state MUST be 'OCCUPIED'.
    - If doorway_state is 'UNKNOWN', 'FREE', or missing -> NOT eligible (cannot attribute to doorway obstacle).
    """
    if not perception_evidence or not isinstance(perception_evidence, dict):
        return False
    doorway_state = perception_evidence.get("doorway_state")
    if doorway_state != "OCCUPIED":
        return False
    return True


@dataclass
class FailureMemoryEntry:
    """Structured record of an observed execution failure and its invalidation criteria."""
    memory_id: str
    map_version: str
    region_id: str
    goal: List[float]
    failed_action_id: str
    failure_time: float
    failure_evidence_id: str
    failure_evidence: Dict[str, Any]
    invalidation_criteria: Dict[str, Any]
    state: MemoryState = MemoryState.ACTIVE
    invalidation_time: Optional[float] = None
    invalidation_evidence_id: Optional[str] = None
    invalidation_evidence: Optional[Dict[str, Any]] = None
    recovery_action_id: Optional[str] = None
    recovery_time: Optional[float] = None
    recovery_evidence: Optional[Dict[str, Any]] = None
    history: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def created_sim_time(self) -> float:
        return self.failure_time

    @property
    def invalidation_sim_time(self) -> Optional[float]:
        return self.invalidation_time

    @property
    def verification_sim_time(self) -> Optional[float]:
        return self.recovery_time

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["state"] = self.state.value
        d["created_sim_time"] = self.failure_time
        d["invalidation_sim_time"] = self.invalidation_time
        d["verification_sim_time"] = self.recovery_time
        return d


class FailureMemoryStore:
    """Deterministic memory store tracking failure entries, condition checks, and lifecycle."""

    def __init__(self, region_matching_tolerance_m: float = 0.50):
        self.region_matching_tolerance_m = region_matching_tolerance_m
        self.entries: List[FailureMemoryEntry] = []
        self._next_id = 1

    def record_failure(
        self,
        goal: List[float],
        region_id: str,
        failure_reason: str,
        sim_time: float,
        failed_action_id: str,
        failure_evidence_id: str,
        failure_evidence: Dict[str, Any],
        map_version: str = "chokepoint_world_v1",
        invalidation_criteria: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[FailureMemoryEntry]:
        """Register a new active failure memory entry IF eligible."""
        if not is_failure_eligible_for_doorway_memory(failure_reason, failure_evidence):
            return None

        if invalidation_criteria is None:
            invalidation_criteria = {
                "type": "DOORWAY_CLEARANCE",
                "map_version": map_version,
                "region_id": region_id,
                "required_doorway_state": "FREE",
            }

        mem_id = f"mem_entry_{self._next_id:04d}"
        history_item = {
            "from_state": None,
            "to_state": MemoryState.ACTIVE.value,
            "sim_time": round(float(sim_time), 4),
            "reason": f"FAILURE_RECORDED ({failure_reason})",
            "evidence_id": str(failure_evidence_id),
        }

        entry = FailureMemoryEntry(
            memory_id=mem_id,
            map_version=str(map_version),
            region_id=str(region_id),
            goal=[round(float(x), 4) for x in goal[:3]],
            failed_action_id=str(failed_action_id),
            failure_time=round(float(sim_time), 4),
            failure_evidence_id=str(failure_evidence_id),
            failure_evidence=copy.deepcopy(failure_evidence),
            invalidation_criteria=invalidation_criteria,
            state=MemoryState.ACTIVE,
            history=[history_item],
            metadata=metadata or {},
        )
        self._next_id += 1
        self.entries.append(entry)
        return entry

    def is_dispatch_blocked(
        self,
        target_goal: List[float],
        target_region: Optional[str] = None,
        map_version: str = "chokepoint_world_v1",
    ) -> Tuple[bool, Optional[FailureMemoryEntry], str]:
        """Check if dispatch to target_goal or target_region is blocked by an ACTIVE memory entry."""
        for entry in self.entries:
            if entry.state == MemoryState.ACTIVE:
                if entry.map_version != map_version:
                    continue
                if target_region and entry.region_id == target_region:
                    return True, entry, f"BLOCKED_BY_ACTIVE_MEMORY_REGION ({entry.memory_id})"
                dist = math.hypot(target_goal[0] - entry.goal[0], target_goal[1] - entry.goal[1])
                if dist <= self.region_matching_tolerance_m:
                    return True, entry, f"BLOCKED_BY_ACTIVE_MEMORY_GOAL ({entry.memory_id}, dist={dist:.2f}m)"
        return False, None, "DISPATCH_ALLOWED"

    def evaluate_perception_for_invalidation(
        self,
        perception_evidence: Dict[str, Any],
        sim_time: float,
        evidence_id: str = "obs_invalidation",
        map_version: str = "chokepoint_world_v1",
        region_id: Optional[str] = None,
    ) -> List[FailureMemoryEntry]:
        """Evaluate physical perception evidence against invalidation criteria of ACTIVE entries."""
        invalidated_entries = []
        doorway_state = perception_evidence.get("doorway_state")

        if doorway_state != "FREE":
            return []

        for entry in self.entries:
            if entry.state == MemoryState.ACTIVE:
                # 1. Map version check
                if entry.map_version != map_version:
                    continue
                # 2. Region check (if specified)
                if region_id and entry.region_id != region_id:
                    continue
                # 3. Temporal causality check: invalidation evidence must be strictly after failure time
                if sim_time <= entry.failure_time:
                    continue

                criteria = entry.invalidation_criteria
                if criteria.get("type") == "DOORWAY_CLEARANCE":
                    req_state = criteria.get("required_doorway_state", "FREE")
                    if doorway_state == req_state:
                        entry.state = MemoryState.INVALIDATED
                        entry.invalidation_time = round(float(sim_time), 4)
                        entry.invalidation_evidence_id = str(evidence_id)
                        entry.invalidation_evidence = copy.deepcopy(perception_evidence)
                        entry.history.append({
                            "from_state": MemoryState.ACTIVE.value,
                            "to_state": MemoryState.INVALIDATED.value,
                            "sim_time": round(float(sim_time), 4),
                            "reason": "DOORWAY_CLEARANCE_OBSERVED_FREE",
                            "evidence_id": str(evidence_id),
                        })
                        invalidated_entries.append(entry)

        return invalidated_entries

    def verify_recovery(
        self,
        target_goal: List[float],
        recovery_action_id: str,
        online_feedback: Dict[str, Any],
        sim_time: float,
        target_region: Optional[str] = None,
        map_version: str = "chokepoint_world_v1",
        memory_id: Optional[str] = None,
        goal_tolerance_m: float = 0.30,
    ) -> bool:
        """Verify recovery online using non-GT public feedback (Nav2 success + AMCL pose)."""
        nav2_status = online_feedback.get("nav2_status", online_feedback.get("ros_terminal_status"))
        if nav2_status != "SUCCEEDED":
            return False

        # Online AMCL check if present
        amcl_pose = online_feedback.get("amcl_pose")
        if amcl_pose and is_finite_number(amcl_pose.get("x")) and is_finite_number(amcl_pose.get("y")):
            d_amcl = math.hypot(amcl_pose["x"] - target_goal[0], amcl_pose["y"] - target_goal[1])
            if d_amcl > (goal_tolerance_m + 0.15):  # allow mild AMCL uncertainty
                return False

        verified_any = False
        for entry in self.entries:
            if entry.state == MemoryState.INVALIDATED:
                if memory_id and entry.memory_id != memory_id:
                    continue
                if entry.map_version != map_version:
                    continue
                if target_region and entry.region_id != target_region:
                    continue
                dist = math.hypot(target_goal[0] - entry.goal[0], target_goal[1] - entry.goal[1])
                if dist <= self.region_matching_tolerance_m:
                    entry.state = MemoryState.RECOVERY_VERIFIED
                    entry.recovery_action_id = str(recovery_action_id)
                    entry.recovery_time = round(float(sim_time), 4)
                    entry.recovery_evidence = copy.deepcopy(online_feedback)
                    entry.history.append({
                        "from_state": MemoryState.INVALIDATED.value,
                        "to_state": MemoryState.RECOVERY_VERIFIED.value,
                        "sim_time": round(float(sim_time), 4),
                        "reason": f"RECOVERY_ACTION_SUCCEEDED ({recovery_action_id})",
                        "evidence_id": str(recovery_action_id),
                    })
                    verified_any = True

        return verified_any

    def get_summary(self) -> Dict[str, Any]:
        """Export full snapshot of memory entries and counts."""
        active = [e.to_dict() for e in self.entries if e.state == MemoryState.ACTIVE]
        invalidated = [e.to_dict() for e in self.entries if e.state == MemoryState.INVALIDATED]
        verified = [e.to_dict() for e in self.entries if e.state == MemoryState.RECOVERY_VERIFIED]
        ever_invalidated = [e.to_dict() for e in self.entries if e.invalidation_time is not None or e.state in (MemoryState.INVALIDATED, MemoryState.RECOVERY_VERIFIED)]
        return {
            "total_entries": len(self.entries),
            "active_count": len(active),
            "invalidated_count": len(invalidated),
            "ever_invalidated_count": len(ever_invalidated),
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
        failed_action_id: str,
        failure_evidence_id: str,
        perception_evidence: Optional[Dict[str, Any]] = None,
        map_version: str = "chokepoint_world_v1",
    ):
        pass

    def check_dispatch_allowed(
        self,
        target_goal: List[float],
        target_region: str,
        sim_time: float,
        map_version: str = "chokepoint_world_v1",
    ) -> Tuple[bool, str, Optional[str]]:
        """Returns (allowed: bool, reason: str, blocked_by_memory_id: Optional[str])."""
        raise NotImplementedError

    def on_observation_update(
        self,
        perception_evidence: Dict[str, Any],
        sim_time: float,
        evidence_id: str = "obs_update",
        map_version: str = "chokepoint_world_v1",
        region_id: Optional[str] = None,
    ):
        pass

    def on_navigation_success(
        self,
        target_goal: List[float],
        target_region: str,
        action_id: str,
        online_feedback: Dict[str, Any],
        sim_time: float,
        map_version: str = "chokepoint_world_v1",
        memory_id: Optional[str] = None,
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
        self.successes_recorded = 0

    def on_navigation_failure(
        self,
        target_goal: List[float],
        target_region: str,
        failure_reason: str,
        sim_time: float,
        failed_action_id: str,
        failure_evidence_id: str,
        perception_evidence: Optional[Dict[str, Any]] = None,
        map_version: str = "chokepoint_world_v1",
    ):
        self.failures_recorded += 1

    def check_dispatch_allowed(
        self,
        target_goal: List[float],
        target_region: str,
        sim_time: float,
        map_version: str = "chokepoint_world_v1",
    ) -> Tuple[bool, str, Optional[str]]:
        self.dispatches_attempted += 1
        return True, "M0_ALWAYS_ALLOWED", None

    def on_navigation_success(
        self,
        target_goal: List[float],
        target_region: str,
        action_id: str,
        online_feedback: Dict[str, Any],
        sim_time: float,
        map_version: str = "chokepoint_world_v1",
        memory_id: Optional[str] = None,
    ):
        self.successes_recorded += 1

    def export_state(self) -> Dict[str, Any]:
        return {
            "policy_name": self.policy_name,
            "dispatches_attempted": self.dispatches_attempted,
            "failures_recorded": self.failures_recorded,
            "successes_recorded": self.successes_recorded,
            "memory_entries": [],
        }


class M1PersistentMemoryPolicy(FailureMemoryPolicy):
    """M1: Persistent Memory Baseline.
    
    Permanently suppresses failed targets/regions without invalidation mechanism.
    Enforces identical memory eligibility as M2 (requires OCCUPIED evidence).
    """
    policy_name = "M1_PERSISTENT_MEMORY"

    def __init__(self, tolerance_m: float = 0.50):
        self.tolerance_m = tolerance_m
        self.blocked_goals: List[Dict[str, Any]] = []
        self.blocked_regions: Dict[str, Dict[str, Any]] = {}
        self.dispatches_attempted = 0
        self.dispatches_blocked = 0
        self.dispatches_permitted = 0
        self.failures_recorded = 0

    def on_navigation_failure(
        self,
        target_goal: List[float],
        target_region: str,
        failure_reason: str,
        sim_time: float,
        failed_action_id: str,
        failure_evidence_id: str,
        perception_evidence: Optional[Dict[str, Any]] = None,
        map_version: str = "chokepoint_world_v1",
    ):
        # Strict eligibility check: only write doorway blockage if OCCUPIED
        if not is_failure_eligible_for_doorway_memory(failure_reason, perception_evidence):
            return

        self.failures_recorded += 1
        block_info = {
            "memory_id": f"mem_entry_m1_{self.failures_recorded:04d}",
            "goal": [round(float(x), 4) for x in target_goal[:3]],
            "region_id": str(target_region),
            "sim_time": round(float(sim_time), 4),
            "failed_action_id": str(failed_action_id),
            "failure_evidence_id": str(failure_evidence_id),
            "reason": str(failure_reason),
            "map_version": str(map_version),
        }
        self.blocked_goals.append(block_info)
        self.blocked_regions[str(target_region)] = block_info

    def check_dispatch_allowed(
        self,
        target_goal: List[float],
        target_region: str,
        sim_time: float,
        map_version: str = "chokepoint_world_v1",
    ) -> Tuple[bool, str, Optional[str]]:
        self.dispatches_attempted += 1
        if str(target_region) in self.blocked_regions:
            info = self.blocked_regions[str(target_region)]
            if info["map_version"] == map_version:
                self.dispatches_blocked += 1
                return False, f"M1_PERSISTENT_BLOCK_REGION ({target_region})", info["memory_id"]

        for bg in self.blocked_goals:
            if bg["map_version"] != map_version:
                continue
            dist = math.hypot(target_goal[0] - bg["goal"][0], target_goal[1] - bg["goal"][1])
            if dist <= self.tolerance_m:
                self.dispatches_blocked += 1
                return False, f"M1_PERSISTENT_BLOCK_GOAL ({dist:.2f}m <= {self.tolerance_m}m)", bg["memory_id"]

        self.dispatches_permitted += 1
        return True, "M1_DISPATCH_ALLOWED", None

    def export_state(self) -> Dict[str, Any]:
        return {
            "policy_name": self.policy_name,
            "dispatches_attempted": self.dispatches_attempted,
            "dispatches_blocked": self.dispatches_blocked,
            "dispatches_permitted": self.dispatches_permitted,
            "failures_recorded": self.failures_recorded,
            "blocked_goals": self.blocked_goals,
            "blocked_regions": list(self.blocked_regions.keys()),
        }


class M2ConditionalMemoryPolicy(FailureMemoryPolicy):
    """M2: Conditional Failure Memory (FailMem Core Mechanism).
    
    Suppresses repeats while precondition (doorway FREE) is unmet.
    Invalidates memory upon physical perception evidence.
    Verifies recovery upon confirmed online arrival.
    """
    policy_name = "M2_CONDITIONAL_MEMORY"

    def __init__(self, tolerance_m: float = 0.50):
        self.store = FailureMemoryStore(region_matching_tolerance_m=tolerance_m)
        self.dispatches_attempted = 0
        self.dispatches_blocked = 0
        self.dispatches_permitted = 0

    def on_navigation_failure(
        self,
        target_goal: List[float],
        target_region: str,
        failure_reason: str,
        sim_time: float,
        failed_action_id: str,
        failure_evidence_id: str,
        perception_evidence: Optional[Dict[str, Any]] = None,
        map_version: str = "chokepoint_world_v1",
    ):
        self.store.record_failure(
            goal=target_goal,
            region_id=target_region,
            failure_reason=failure_reason,
            sim_time=sim_time,
            failed_action_id=failed_action_id,
            failure_evidence_id=failure_evidence_id,
            failure_evidence=perception_evidence or {},
            map_version=map_version,
        )

    def on_observation_update(
        self,
        perception_evidence: Dict[str, Any],
        sim_time: float,
        evidence_id: str = "obs_update",
        map_version: str = "chokepoint_world_v1",
        region_id: Optional[str] = None,
    ):
        self.store.evaluate_perception_for_invalidation(
            perception_evidence=perception_evidence,
            sim_time=sim_time,
            evidence_id=evidence_id,
            map_version=map_version,
            region_id=region_id,
        )

    def check_dispatch_allowed(
        self,
        target_goal: List[float],
        target_region: str,
        sim_time: float,
        map_version: str = "chokepoint_world_v1",
    ) -> Tuple[bool, str, Optional[str]]:
        self.dispatches_attempted += 1
        blocked, entry, reason = self.store.is_dispatch_blocked(
            target_goal=target_goal,
            target_region=target_region,
            map_version=map_version,
        )
        if blocked:
            self.dispatches_blocked += 1
            return False, reason, entry.memory_id if entry else None
        self.dispatches_permitted += 1
        return True, reason, None

    def on_navigation_success(
        self,
        target_goal: List[float],
        target_region: str,
        action_id: str,
        online_feedback: Dict[str, Any],
        sim_time: float,
        map_version: str = "chokepoint_world_v1",
        memory_id: Optional[str] = None,
    ):
        self.store.verify_recovery(
            target_goal=target_goal,
            recovery_action_id=action_id,
            online_feedback=online_feedback,
            sim_time=sim_time,
            target_region=target_region,
            map_version=map_version,
            memory_id=memory_id,
        )

    def export_state(self) -> Dict[str, Any]:
        res = self.store.get_summary()
        res.update({
            "policy_name": self.policy_name,
            "dispatches_attempted": self.dispatches_attempted,
            "dispatches_blocked": self.dispatches_blocked,
            "dispatches_permitted": self.dispatches_permitted,
        })
        return res
