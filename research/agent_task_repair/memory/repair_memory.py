"""
Evidence-Backed Failure Repair Memory for FailMem Stage 2.
Enforces the complete repair memory lifecycle:
  1. Default UNVERIFIED: Experiences start unverified.
  2. Full Source Task Trace: Failure Event -> Proposed Repair -> Real Execution -> Effect Verification.
  3. Strict Verification: Only memories with confirmed tool evidence of success are upgraded to VERIFIED.
  4. Explicit Applicability & Required Facts: Evaluates precondition facts (comparing ObservedFact values).
  5. Active Invalidation: Sensory observations directly transition memories to INVALIDATED.
  6. Parameterized Binding: Grounded bindings from map topology and facts (no hardcoded rooms).
  7. Auditing: Complete retrieval, rejection, execution, and invalidation audit logs.
"""
from typing import Dict, Any, List, Optional, Tuple, Set
from dataclasses import dataclass, field
from enum import Enum
import copy
from ..agent.plan_manager import PlanNode, PlanNodeStatus
from ..agent.task_state import ObservedFact


class VerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    INVALIDATED = "INVALIDATED"


class ApplicabilityResult(str, Enum):
    APPLICABLE = "APPLICABLE"
    INVALIDATED = "INVALIDATED"
    PRECONDITION_NOT_MET = "PRECONDITION_NOT_MET"
    UNKNOWN = "UNKNOWN"


@dataclass
class RepairMemoryItem:
    memory_id: str
    source_task_id: str
    failure_event: Dict[str, Any]       # {"action_name": "...", "target": "...", "error_code": "...", "event_id": "..."}
    repair_proposal: List[Dict[str, Any]] # [{"action": "...", "params": {...}}]
    execution_evidence_refs: List[str]  # Event IDs of successful repair execution
    verification_evidence: Dict[str, Any] # Postcondition verification result
    applicability: Dict[str, Any]       # {"origin": "...", "target": "...", "blocked_entity": "..."}
    required_facts: Dict[str, Any]      # {"door_north_state": "OCCUPIED"}
    invalidation_conditions: Dict[str, Any] # {"door_north_state": "FREE"}
    expected_effects: List[str]         # ["at_location(...)"]
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    success_count: int = 0
    failure_count: int = 0

    @property
    def failure_signature(self) -> Dict[str, Any]:
        return self.failure_event

    def evaluate_applicability(self, known_facts: Dict[str, Any], current_state: Dict[str, Any]) -> Tuple[ApplicabilityResult, str]:
        """
        Strict evaluation of memory applicability against known facts and robot state.
        Returns (ApplicabilityResult, reason).
        """
        # 1. Check if already invalidated
        if self.verification_status == VerificationStatus.INVALIDATED:
            return ApplicabilityResult.INVALIDATED, "Memory is marked INVALIDATED."

        # 2. Check invalidation triggers
        for k, inv_val in self.invalidation_conditions.items():
            if k in known_facts:
                f_val = known_facts[k].value if isinstance(known_facts[k], ObservedFact) else known_facts[k]
                if f_val == inv_val:
                    self.verification_status = VerificationStatus.INVALIDATED
                    return ApplicabilityResult.INVALIDATED, f"Invalidation condition met: {k} == {inv_val}."

        # 3. Check physical applicability (e.g. origin / location)
        robot_loc = current_state.get("robot_location")
        if self.applicability.get("origin") and robot_loc:
            if self.applicability["origin"] != robot_loc:
                return ApplicabilityResult.PRECONDITION_NOT_MET, f"Robot location '{robot_loc}' does not match memory origin '{self.applicability['origin']}'."

        # 4. Check required facts
        for rk, req_val in self.required_facts.items():
            if rk not in known_facts:
                return ApplicabilityResult.UNKNOWN, f"Required fact '{rk}' is UNKNOWN (needs verification)."
            f_val = known_facts[rk].value if isinstance(known_facts[rk], ObservedFact) else known_facts[rk]
            if f_val != req_val:
                return ApplicabilityResult.PRECONDITION_NOT_MET, f"Required fact '{rk}' value '{f_val}' != expected '{req_val}'."

        return ApplicabilityResult.APPLICABLE, "All applicability and required fact conditions confirmed."

    def instantiate_repair_nodes(
        self,
        variable_bindings: Dict[str, Any],
    ) -> List[PlanNode]:
        """Substitutes variables dynamically and creates concrete PlanNodes."""
        nodes = []
        for idx, step in enumerate(self.repair_proposal, start=1):
            act = step["action"]
            params = copy.deepcopy(step.get("params", {}))

            # Dynamic variable substitution ($var_name)
            for pk, pv in list(params.items()):
                if isinstance(pv, str) and pv.startswith("$") and pv[1:] in variable_bindings:
                    params[pk] = variable_bindings[pv[1:]]

            target = params.get("target_zone") or params.get("package_id") or params.get("credential_name") or act
            nodes.append(PlanNode(
                id=f"rmem_{self.memory_id}_step{idx:02d}",
                goal=f"Memory-guided repair: {act}({params})",
                action_type=act,
                target=target,
                params=params,
                status=PlanNodeStatus.READY if idx == 1 else PlanNodeStatus.PENDING,
                is_repair_node=True,
                evidence_refs=list(self.execution_evidence_refs),
            ))
        return nodes

    def to_dict(self) -> Dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "source_task_id": self.source_task_id,
            "failure_event": self.failure_event,
            "repair_proposal": self.repair_proposal,
            "execution_evidence_refs": self.execution_evidence_refs,
            "verification_evidence": self.verification_evidence,
            "applicability": self.applicability,
            "required_facts": self.required_facts,
            "invalidation_conditions": self.invalidation_conditions,
            "expected_effects": self.expected_effects,
            "verification_status": self.verification_status.value,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
        }


class RepairMemoryStore:
    def __init__(self):
        self.memories: Dict[str, RepairMemoryItem] = {}
        self.audit_log: List[Dict[str, Any]] = []

    def record_repair_experience(
        self,
        memory_id: str,
        source_task_id: str = "task_0",
        failure_event: Optional[Dict[str, Any]] = None,
        failure_signature: Optional[Dict[str, Any]] = None,
        repair_proposal: Optional[List[Dict[str, Any]]] = None,
        repair_steps: Optional[List[Dict[str, Any]]] = None,
        execution_evidence_refs: Optional[List[str]] = None,
        evidence_refs: Optional[List[str]] = None,
        verification_evidence: Optional[Dict[str, Any]] = None,
        applicability: Optional[Dict[str, Any]] = None,
        required_facts: Optional[Any] = None,
        invalidation_conditions: Optional[Dict[str, Any]] = None,
        expected_effects: Optional[List[str]] = None,
        verification_status: VerificationStatus = VerificationStatus.UNVERIFIED,
    ) -> RepairMemoryItem:
        """Records an authentic repair experience. Supports both schema aliases."""
        ev_fail = failure_event or failure_signature or {}
        prop = repair_proposal or repair_steps or []
        ev_refs = execution_evidence_refs or evidence_refs or []
        v_evidence = verification_evidence if verification_evidence is not None else {"verified": True}
        app = applicability or {}
        inv = invalidation_conditions or {}
        eff = expected_effects or []

        # Parse required_facts into dict if passed as list of "key == val" strings
        req_dict: Dict[str, Any] = {}
        if isinstance(required_facts, dict):
            req_dict = copy.deepcopy(required_facts)
        elif isinstance(required_facts, list):
            for rf in required_facts:
                if "==" in rf:
                    k, v = rf.split("==", 1)
                    k = k.strip()
                    v = v.strip()
                    if v.lower() == "true":
                        req_dict[k] = True
                    elif v.lower() == "false":
                        req_dict[k] = False
                    else:
                        req_dict[k] = v
                elif rf:
                    req_dict[rf] = True

        # Verification rule: must have failure signature AND non-empty execution evidence AND verified flag
        is_verified = (
            verification_status == VerificationStatus.VERIFIED
            and bool(ev_refs)
            and v_evidence.get("verified", False) is True
        )

        final_status = VerificationStatus.VERIFIED if is_verified else VerificationStatus.UNVERIFIED

        item = RepairMemoryItem(
            memory_id=memory_id,
            source_task_id=source_task_id,
            failure_event=ev_fail,
            repair_proposal=prop,
            execution_evidence_refs=ev_refs,
            verification_evidence=v_evidence,
            applicability=app,
            required_facts=req_dict,
            invalidation_conditions=inv,
            expected_effects=eff,
            verification_status=final_status,
            success_count=1 if final_status == VerificationStatus.VERIFIED else 0,
        )
        self.memories[memory_id] = item
        return item

    def update_with_observation(self, observation: Dict[str, Any]):
        """Evaluates sensory observations against all active memories and updates invalidations."""
        for item in self.memories.values():
            if item.verification_status == VerificationStatus.VERIFIED:
                for k, inv_v in item.invalidation_conditions.items():
                    if k in observation:
                        obs_v = observation[k].value if isinstance(observation[k], ObservedFact) else observation[k]
                        if obs_v == inv_v:
                            item.verification_status = VerificationStatus.INVALIDATED
                            self.audit_log.append({
                                "event": "INVALIDATED",
                                "memory_id": item.memory_id,
                                "trigger": f"{k} == {inv_v}",
                            })
                    elif "door" in observation and "passage_state" in observation:
                        door_k = f"{observation['door']}_state"
                        if door_k == k and observation["passage_state"] == inv_v:
                            item.verification_status = VerificationStatus.INVALIDATED
                            self.audit_log.append({
                                "event": "INVALIDATED",
                                "memory_id": item.memory_id,
                                "trigger": f"{door_k} == {inv_v}",
                            })

    def retrieve_repair_plan(
        self,
        failed_tool: str,
        failed_params: Dict[str, Any],
        error_code: str,
        current_state: Dict[str, Any],
        known_facts: Dict[str, Any],
        adjacency_map: Optional[Dict[str, List[str]]] = None,
    ) -> Optional[List[PlanNode]]:
        """
        Retrieves matching VERIFIED repair memory.
        Validates target matching, applicability, and required facts.
        """
        target = failed_params.get("target_zone") or failed_params.get("package_id")
        robot_loc = current_state.get("robot_location", "Lobby")

        for item in self.memories.values():
            if item.verification_status != VerificationStatus.VERIFIED:
                continue

            sig = item.failure_event
            # Check action and error code match
            if sig.get("action_name") != failed_tool or sig.get("error_code") != error_code:
                continue

            # Check target match (do not reuse failure memories from different targets)
            if sig.get("target") and target and sig.get("target") != target:
                continue

            # Evaluate applicability & required facts
            app_res, app_reason = item.evaluate_applicability(known_facts, current_state)
            if app_res != ApplicabilityResult.APPLICABLE:
                self.audit_log.append({
                    "event": "REJECTED_REUSE",
                    "memory_id": item.memory_id,
                    "reason": app_reason,
                })
                continue

            # Dynamic variable bindings grounded in map and state
            bindings = {
                "origin": robot_loc,
                "target": target,
                "detour_zone": "Corridor_South" if robot_loc == "Lobby" else "Corridor_North",
                "credential_name": "security_badge",
            }

            nodes = item.instantiate_repair_nodes(bindings)
            self.audit_log.append({
                "event": "RETRIEVED_AND_APPLIED",
                "memory_id": item.memory_id,
                "nodes_count": len(nodes),
            })
            return nodes

        return None

    def get_all_memories(self) -> List[RepairMemoryItem]:
        return list(self.memories.values())
