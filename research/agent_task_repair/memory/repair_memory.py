"""
Evidence-Backed Failure Repair Memory for FailMem Stage 2.
Enforces the complete repair memory lifecycle:
  1. Default UNVERIFIED: Experiences start strictly unverified.
  2. Two-Phase API: propose_repair (UNVERIFIED) -> verify_and_promote (VERIFIED).
  3. Grounded Trajectory Verifier: Checks source failure existence, actual execution, tool success,
     expected effects satisfaction, and same-trajectory integrity.
  4. Explicit Lifecycle Tracking:
     RETRIEVED -> INSTANTIATED -> EXECUTED -> VERIFIED_EFFECT / REJECTED / INVALIDATED.
  5. Active Invalidation: Sensory observations directly transition memories to INVALIDATED.
  6. Parameterized Dynamic Binding: Bindings from actual trajectory, public state, and topology (no hardcoding).
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
    REJECTED = "REJECTED"


class MemoryLifecycleState(str, Enum):
    PROPOSED = "PROPOSED"
    RETRIEVED = "RETRIEVED"
    INSTANTIATED = "INSTANTIATED"
    EXECUTED = "EXECUTED"
    VERIFIED_EFFECT = "VERIFIED_EFFECT"
    REJECTED = "REJECTED"
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
    failure_event: Dict[str, Any]         # {"action_name": "...", "target": "...", "error_code": "...", "event_id": "..."}
    repair_proposal: List[Dict[str, Any]] # [{"action": "...", "params": {...}}]
    execution_evidence_refs: List[str]    # Event IDs of successful repair execution
    verification_evidence: Dict[str, Any] # Postcondition verification result (empty if unverified)
    applicability: Dict[str, Any]         # {"origin": "...", "target": "...", "blocked_entity": "..."}
    required_facts: Dict[str, Any]        # {"door_north_state": "OCCUPIED"}
    invalidation_conditions: Dict[str, Any] # {"door_north_state": "FREE"}
    expected_effects: List[str]           # ["at_location(...)"]
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    lifecycle_state: MemoryLifecycleState = MemoryLifecycleState.PROPOSED
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
        if self.verification_status == VerificationStatus.INVALIDATED or self.lifecycle_state == MemoryLifecycleState.INVALIDATED:
            return ApplicabilityResult.INVALIDATED, "Memory is marked INVALIDATED."

        # 2. Check invalidation triggers
        for k, inv_val in self.invalidation_conditions.items():
            if k in known_facts:
                f_val = known_facts[k].value if isinstance(known_facts[k], ObservedFact) else known_facts[k]
                if f_val == inv_val:
                    self.verification_status = VerificationStatus.INVALIDATED
                    self.lifecycle_state = MemoryLifecycleState.INVALIDATED
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

            target = params.get("target_zone") or params.get("package_id") or params.get("credential_name") or params.get("target") or act
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
        self.lifecycle_state = MemoryLifecycleState.INSTANTIATED
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
            "lifecycle_state": self.lifecycle_state.value,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
        }


class RepairMemoryStore:
    def __init__(self):
        self.memories: Dict[str, RepairMemoryItem] = {}
        self.audit_log: List[Dict[str, Any]] = []

    def propose_repair(
        self,
        memory_id: str,
        source_task_id: str = "task_0",
        failure_event: Optional[Dict[str, Any]] = None,
        repair_proposal: Optional[List[Dict[str, Any]]] = None,
        applicability: Optional[Dict[str, Any]] = None,
        required_facts: Optional[Any] = None,
        invalidation_conditions: Optional[Dict[str, Any]] = None,
        expected_effects: Optional[List[str]] = None,
    ) -> RepairMemoryItem:
        """
        Phase 1: Registers a proposed repair memory item in UNVERIFIED status.
        Never defaults to verified without rigorous trajectory evidence.
        """
        ev_fail = failure_event or {}
        prop = repair_proposal or []
        app = applicability or {}
        inv = invalidation_conditions or {}
        eff = expected_effects or []

        req_dict: Dict[str, Any] = {}
        if isinstance(required_facts, dict):
            req_dict = copy.deepcopy(required_facts)
        elif isinstance(required_facts, list):
            for rf in required_facts:
                if "==" in rf:
                    k, v = rf.split("==", 1)
                    k, v = k.strip(), v.strip()
                    if v.lower() == "true":
                        req_dict[k] = True
                    elif v.lower() == "false":
                        req_dict[k] = False
                    else:
                        req_dict[k] = v
                elif rf:
                    req_dict[rf] = True

        item = RepairMemoryItem(
            memory_id=memory_id,
            source_task_id=source_task_id,
            failure_event=ev_fail,
            repair_proposal=prop,
            execution_evidence_refs=[],
            verification_evidence={},
            applicability=app,
            required_facts=req_dict,
            invalidation_conditions=inv,
            expected_effects=eff,
            verification_status=VerificationStatus.UNVERIFIED,
            lifecycle_state=MemoryLifecycleState.PROPOSED,
            success_count=0,
            failure_count=0,
        )
        self.memories[memory_id] = item
        self.audit_log.append({
            "event": "PROPOSED",
            "memory_id": memory_id,
            "source_task_id": source_task_id,
            "status": "UNVERIFIED",
        })
        return item

    def verify_and_promote(
        self,
        memory_id: str,
        source_trajectory: List[Dict[str, Any]],
        expected_effects: Optional[List[str]] = None,
    ) -> Tuple[bool, str]:
        """
        Phase 2: ONLY valid entry point to promote a proposed repair to VERIFIED status.
        Strict verification rules:
          1. Memory item must exist in store.
          2. Trajectory must contain the source failure event (matching action, error_code, target, event_id).
          3. All trajectory events must belong to the same source_task_id / run_id (no cross-task splicing).
          4. Subsequent trajectory must sequentially execute all proposed repair steps matching BOTH action AND parameters.
          5. Every executed repair step must have succeeded (result.success == True).
          6. Expected effects must be strictly checked against grounded post-repair state. Unknown effects are rejected.
          7. Evidence references must resolve to real event_ids from the executed trajectory.
        """
        if memory_id not in self.memories:
            return False, f"Memory '{memory_id}' not found in store."

        item = self.memories[memory_id]
        if not source_trajectory:
            item.verification_status = VerificationStatus.UNVERIFIED
            item.lifecycle_state = MemoryLifecycleState.REJECTED
            return False, "Empty trajectory provided for verification."

        # 1. Single Task / Run Integrity Check (Reject cross-task spliced evidence)
        task_ids_in_traj = set()
        run_ids_in_traj = set()
        for s in source_trajectory:
            tid = s.get("task_id")
            rid = s.get("run_id")
            if tid:
                task_ids_in_traj.add(tid)
            if rid:
                run_ids_in_traj.add(rid)

        if len(task_ids_in_traj) > 1 or len(run_ids_in_traj) > 1:
            item.verification_status = VerificationStatus.UNVERIFIED
            item.lifecycle_state = MemoryLifecycleState.REJECTED
            reason = f"Cross-task spliced trajectory detected: task_ids={task_ids_in_traj}, run_ids={run_ids_in_traj}."
            self.audit_log.append({"event": "VERIFICATION_FAILED", "memory_id": memory_id, "reason": reason})
            return False, reason

        fail_sig = item.failure_event
        failed_tool = fail_sig.get("action_name") or fail_sig.get("tool")
        failed_err = fail_sig.get("error_code")
        failed_target = fail_sig.get("target")
        req_event_id = fail_sig.get("event_id")

        # 2. Locate failure event in trajectory
        fail_step_idx = -1
        for idx, step in enumerate(source_trajectory):
            tool = step.get("tool")
            res = step.get("result", {})
            err = res.get("error_code") or step.get("error_code")
            params = step.get("params", {})
            target = params.get("target_zone") or params.get("package_id") or params.get("credential_name") or params.get("target")
            ev_id = step.get("event_id")

            if (not failed_tool or tool == failed_tool) and (not failed_err or err == failed_err):
                if not failed_target or target == failed_target:
                    if not req_event_id or ev_id == req_event_id:
                        # Verify this step actually failed
                        step_succ = res.get("success", True) if isinstance(res, dict) else False
                        if not step_succ:
                            fail_step_idx = idx
                            break

        if fail_step_idx == -1:
            item.verification_status = VerificationStatus.UNVERIFIED
            item.lifecycle_state = MemoryLifecycleState.REJECTED
            reason = f"Failure event '{fail_sig}' not found or did not fail in source trajectory."
            self.audit_log.append({"event": "VERIFICATION_FAILED", "memory_id": memory_id, "reason": reason})
            return False, reason

        # 3. Check subsequent execution of repair steps
        executed_repair_steps = source_trajectory[fail_step_idx + 1:]
        if not executed_repair_steps:
            item.verification_status = VerificationStatus.UNVERIFIED
            item.lifecycle_state = MemoryLifecycleState.REJECTED
            reason = "No subsequent actions executed after failure event in trajectory (only failure evidence)."
            self.audit_log.append({"event": "VERIFICATION_FAILED", "memory_id": memory_id, "reason": reason})
            return False, reason

        evidence_refs: List[str] = []
        prop_steps = item.repair_proposal
        if not prop_steps:
            item.verification_status = VerificationStatus.UNVERIFIED
            item.lifecycle_state = MemoryLifecycleState.REJECTED
            reason = "Empty repair proposal steps in memory item."
            self.audit_log.append({"event": "VERIFICATION_FAILED", "memory_id": memory_id, "reason": reason})
            return False, reason

        # Check sequential execution matching BOTH action AND parameters
        matched_prop_idx = 0
        for step in executed_repair_steps:
            if matched_prop_idx >= len(prop_steps):
                break
            req_step = prop_steps[matched_prop_idx]
            req_act = req_step["action"]
            req_params = req_step.get("params", {})
            actual_tool = step.get("tool")
            actual_params = step.get("params", {})
            step_res = step.get("result", {})
            step_success = step_res.get("success", False) if isinstance(step_res, dict) else False
            step_ev_id = step.get("event_id")

            if actual_tool == req_act:
                # Strict parameter check
                params_match = True
                for pk, pv in req_params.items():
                    if not isinstance(pv, str) or not pv.startswith("$"):
                        if actual_params.get(pk) != pv:
                            params_match = False
                            break

                if not params_match:
                    item.verification_status = VerificationStatus.UNVERIFIED
                    item.lifecycle_state = MemoryLifecycleState.REJECTED
                    reason = f"Repair step {matched_prop_idx+1} parameter mismatch: expected {req_params}, got {actual_params}."
                    self.audit_log.append({"event": "VERIFICATION_FAILED", "memory_id": memory_id, "reason": reason})
                    return False, reason

                if not step_success:
                    item.verification_status = VerificationStatus.UNVERIFIED
                    item.lifecycle_state = MemoryLifecycleState.REJECTED
                    reason = f"Repair step {matched_prop_idx+1} '{req_act}({actual_params})' failed during execution."
                    self.audit_log.append({"event": "VERIFICATION_FAILED", "memory_id": memory_id, "reason": reason})
                    return False, reason

                if not step_ev_id:
                    item.verification_status = VerificationStatus.UNVERIFIED
                    item.lifecycle_state = MemoryLifecycleState.REJECTED
                    reason = f"Repair step {matched_prop_idx+1} lacks valid event_id in trajectory."
                    self.audit_log.append({"event": "VERIFICATION_FAILED", "memory_id": memory_id, "reason": reason})
                    return False, reason

                evidence_refs.append(step_ev_id)
                matched_prop_idx += 1

        if matched_prop_idx < len(prop_steps):
            item.verification_status = VerificationStatus.UNVERIFIED
            item.lifecycle_state = MemoryLifecycleState.REJECTED
            reason = f"Incomplete repair execution: matched {matched_prop_idx}/{len(prop_steps)} proposed steps."
            self.audit_log.append({"event": "VERIFICATION_FAILED", "memory_id": memory_id, "reason": reason})
            return False, reason

        # 4. Check expected effects (Unknown effects are rejected)
        eff_to_check = expected_effects or item.expected_effects
        if not eff_to_check:
            item.verification_status = VerificationStatus.UNVERIFIED
            item.lifecycle_state = MemoryLifecycleState.REJECTED
            reason = "No expected effects specified for verification."
            self.audit_log.append({"event": "VERIFICATION_FAILED", "memory_id": memory_id, "reason": reason})
            return False, reason

        final_step = executed_repair_steps[-1]
        final_obs = final_step.get("result", {}).get("observation", {}) if isinstance(final_step.get("result"), dict) else {}
        final_loc = final_step.get("robot_location_after") or final_step.get("robot_location")

        for eff in eff_to_check:
            if eff.startswith("at_location("):
                exp_loc = eff[len("at_location("):-1]
                loc_reached = any(
                    s.get("robot_location_after") == exp_loc
                    or s.get("robot_location") == exp_loc
                    or (s.get("tool") == "navigate" and s.get("params", {}).get("target_zone") == exp_loc and s.get("result", {}).get("success"))
                    or (s.get("result", {}).get("observation", {}).get("current_location") == exp_loc)
                    for s in executed_repair_steps
                ) or (final_loc == exp_loc)
                if not loc_reached:
                    item.verification_status = VerificationStatus.UNVERIFIED
                    item.lifecycle_state = MemoryLifecycleState.REJECTED
                    reason = f"Expected effect '{eff}' not satisfied (final location: '{final_loc}')."
                    self.audit_log.append({"event": "VERIFICATION_FAILED", "memory_id": memory_id, "reason": reason})
                    return False, reason

            elif eff.startswith("has_credential("):
                exp_cred = eff[len("has_credential("):-1]
                cred_acquired = any(
                    s.get("tool") == "acquire_credential"
                    and s.get("params", {}).get("credential_name") == exp_cred
                    and (s.get("result", {}).get("success") if isinstance(s.get("result"), dict) else False)
                    for s in executed_repair_steps
                ) or any(
                    exp_cred in (s.get("result", {}).get("observation", {}).get("credentials", []) if isinstance(s.get("result"), dict) else [])
                    for s in executed_repair_steps
                )
                if not cred_acquired:
                    item.verification_status = VerificationStatus.UNVERIFIED
                    item.lifecycle_state = MemoryLifecycleState.REJECTED
                    reason = f"Expected effect '{eff}' not satisfied."
                    self.audit_log.append({"event": "VERIFICATION_FAILED", "memory_id": memory_id, "reason": reason})
                    return False, reason

            elif eff.startswith("holding("):
                exp_pkg = eff[len("holding("):-1]
                pkg_held = any(
                    s.get("tool") == "pickup"
                    and s.get("params", {}).get("package_id") == exp_pkg
                    and (s.get("result", {}).get("success") if isinstance(s.get("result"), dict) else False)
                    for s in executed_repair_steps
                ) or any(
                    exp_pkg in (s.get("result", {}).get("observation", {}).get("inventory", []) if isinstance(s.get("result"), dict) else [])
                    for s in executed_repair_steps
                )
                if not pkg_held:
                    item.verification_status = VerificationStatus.UNVERIFIED
                    item.lifecycle_state = MemoryLifecycleState.REJECTED
                    reason = f"Expected effect '{eff}' not satisfied."
                    self.audit_log.append({"event": "VERIFICATION_FAILED", "memory_id": memory_id, "reason": reason})
                    return False, reason

            elif eff.startswith("delivered("):
                exp_pkg = eff[len("delivered("):-1]
                pkg_delivered = any(
                    s.get("tool") == "deliver"
                    and s.get("params", {}).get("package_id") == exp_pkg
                    and (s.get("result", {}).get("success") if isinstance(s.get("result"), dict) else False)
                    for s in executed_repair_steps
                )
                if not pkg_delivered:
                    item.verification_status = VerificationStatus.UNVERIFIED
                    item.lifecycle_state = MemoryLifecycleState.REJECTED
                    reason = f"Expected effect '{eff}' not satisfied."
                    self.audit_log.append({"event": "VERIFICATION_FAILED", "memory_id": memory_id, "reason": reason})
                    return False, reason
            else:
                # Unknown effect type cannot silently pass
                item.verification_status = VerificationStatus.UNVERIFIED
                item.lifecycle_state = MemoryLifecycleState.REJECTED
                reason = f"Unknown effect type '{eff}' cannot be verified."
                self.audit_log.append({"event": "VERIFICATION_FAILED", "memory_id": memory_id, "reason": reason})
                return False, reason

        # Verification Passed! Upgrade to VERIFIED
        item.execution_evidence_refs = evidence_refs
        item.verification_evidence = {
            "verified": True,
            "evidence_event_ids": evidence_refs,
            "failure_step_index": fail_step_idx,
            "repaired_steps_count": len(evidence_refs),
            "verified_effects": list(eff_to_check),
        }
        item.verification_status = VerificationStatus.VERIFIED
        item.lifecycle_state = MemoryLifecycleState.VERIFIED_EFFECT
        item.success_count += 1

        self.audit_log.append({
            "event": "VERIFIED_AND_PROMOTED",
            "memory_id": memory_id,
            "evidence_refs": evidence_refs,
            "effects": eff_to_check,
        })
        return True, "Verification successful. Memory promoted to VERIFIED."

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
        """
        Registers a repair experience proposal.
        ALWAYS starts as UNVERIFIED. Direct verified bypassing is strictly prohibited.
        Only verify_and_promote can promote a memory to VERIFIED.
        """
        ev_fail = failure_event or failure_signature or {}
        prop = repair_proposal or repair_steps or []
        app = applicability or {}
        inv = invalidation_conditions or {}
        eff = expected_effects or []

        return self.propose_repair(
            memory_id=memory_id,
            source_task_id=source_task_id,
            failure_event=ev_fail,
            repair_proposal=prop,
            applicability=app,
            required_facts=required_facts,
            invalidation_conditions=inv,
            expected_effects=eff,
        )

    def update_with_observation(self, observation: Dict[str, Any]):
        """Evaluates sensory observations against all active memories and updates invalidations."""
        for item in self.memories.values():
            if item.verification_status == VerificationStatus.VERIFIED:
                for k, inv_v in item.invalidation_conditions.items():
                    if k in observation:
                        obs_v = observation[k].value if isinstance(observation[k], ObservedFact) else observation[k]
                        if obs_v == inv_v:
                            item.verification_status = VerificationStatus.INVALIDATED
                            item.lifecycle_state = MemoryLifecycleState.INVALIDATED
                            self.audit_log.append({
                                "event": "INVALIDATED",
                                "memory_id": item.memory_id,
                                "trigger": f"{k} == {inv_v}",
                            })
                    elif "door" in observation and "passage_state" in observation:
                        door_k = f"{observation['door']}_state"
                        if door_k == k and observation["passage_state"] == inv_v:
                            item.verification_status = VerificationStatus.INVALIDATED
                            item.lifecycle_state = MemoryLifecycleState.INVALIDATED
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
        Tracks lifecycle: RETRIEVED -> INSTANTIATED.
        """
        target = failed_params.get("target_zone") or failed_params.get("package_id") or failed_params.get("credential_name")
        robot_loc = current_state.get("robot_location", "Lobby")

        for item in self.memories.values():
            if item.verification_status != VerificationStatus.VERIFIED:
                continue

            sig = item.failure_event
            # Check action and error code match
            if sig.get("action_name") != failed_tool or sig.get("error_code") != error_code:
                continue

            # Check target match
            if sig.get("target") and target and sig.get("target") != target:
                continue

            # Evaluate applicability & required facts
            app_res, app_reason = item.evaluate_applicability(known_facts, current_state)
            if app_res != ApplicabilityResult.APPLICABLE:
                item.lifecycle_state = MemoryLifecycleState.REJECTED
                self.audit_log.append({
                    "event": "REJECTED_REUSE",
                    "memory_id": item.memory_id,
                    "reason": app_reason,
                })
                continue

            # Dynamic variable bindings grounded in map and actual entities
            adj = adjacency_map or {
                "Lobby": ["Corridor_North", "Corridor_South"],
                "Corridor_North": ["Lobby", "Office_A", "Office_B", "Corridor_South"],
                "Corridor_South": ["Lobby", "Corridor_North", "Office_A", "Lab_Secure"],
                "Office_A": ["Corridor_North", "Corridor_South"],
                "Office_B": ["Corridor_North"],
                "Lab_Secure": ["Corridor_South"],
            }
            alt_neighbors = [n for n in adj.get(robot_loc, []) if n != target]
            detour_zone = alt_neighbors[0] if alt_neighbors else robot_loc

            bindings = {
                "origin": robot_loc,
                "target": target,
                "detour_zone": detour_zone,
            }
            # Add any known facts or parameter bindings from failure sig
            for k, v in sig.items():
                bindings[k] = v

            item.lifecycle_state = MemoryLifecycleState.RETRIEVED
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

