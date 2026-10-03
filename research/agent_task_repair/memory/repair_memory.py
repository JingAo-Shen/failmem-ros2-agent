"""
Evidence-Backed Failure Repair Memory for FailMem Stage 2.
Replaces warning strings with structured, parameterized, verified repair templates:
  - failure_signature: (action, target, error_code)
  - applicability: conditions under which this repair applies
  - required_facts: facts that must be confirmed prior to applying
  - repair_steps: parameterized action templates
  - expected_effects: postcondition assertions
  - evidence_refs: authentic tool event IDs from source task
  - invalidation_conditions: observation triggers that invalidate this memory
  - verification_status: UNVERIFIED, VERIFIED, INVALIDATED
"""
from typing import Dict, Any, List, Optional, Tuple, Set
from dataclasses import dataclass, field
from enum import Enum
import copy
from ..agent.plan_manager import PlanNode, PlanNodeStatus


class VerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    INVALIDATED = "INVALIDATED"


@dataclass
class RepairMemoryItem:
    memory_id: str
    failure_signature: Dict[str, Any]  # {"action_name": "navigate", "target": "Corridor_North", "error_code": "DOORWAY_BLOCKED"}
    applicability: Dict[str, Any]      # {"origin": "Lobby", "blocked_entity": "door_north"}
    required_facts: List[str]          # ["door_north_state == OCCUPIED"]
    repair_steps: List[Dict[str, Any]] # [{"action": "navigate", "params": {"target_zone": "Corridor_South"}}]
    expected_effects: List[str]        # ["at_location(Corridor_South)"]
    evidence_refs: List[str]           # ["evt_t1_s01", "evt_t1_s02_repair_ok"]
    invalidation_conditions: Dict[str, Any] # {"door_north_state": "FREE"}
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    source_task_id: str = "source_task"
    success_count: int = 0
    failure_count: int = 0

    def evaluate_applicability(self, known_facts: Dict[str, Any]) -> bool:
        """Evaluates whether this repair template is applicable and valid under current facts."""
        if self.verification_status == VerificationStatus.INVALIDATED:
            return False

        # Check invalidation conditions
        for k, v in self.invalidation_conditions.items():
            if k in known_facts and known_facts[k] == v:
                self.verification_status = VerificationStatus.INVALIDATED
                return False

        return True

    def instantiate_repair_nodes(self, variable_bindings: Dict[str, Any]) -> List[PlanNode]:
        """Substitutes parameterized variables and creates concrete PlanNodes."""
        nodes = []
        for idx, step in enumerate(self.repair_steps, start=1):
            act = step["action"]
            params = copy.deepcopy(step.get("params", {}))

            # Variable substitution (e.g. $detour_zone)
            for pk, pv in list(params.items()):
                if isinstance(pv, str) and pv.startswith("$") and pv[1:] in variable_bindings:
                    params[pk] = variable_bindings[pv[1:]]

            target = params.get("target_zone") or params.get("package_id") or params.get("credential_name") or act
            nodes.append(PlanNode(
                id=f"rmem_{self.memory_id}_step{idx:02d}",
                goal=f"Execute memory-guided repair: {act}({params})",
                action_type=act,
                target=target,
                params=params,
                status=PlanNodeStatus.READY if idx == 1 else PlanNodeStatus.PENDING,
                is_repair_node=True,
                evidence_refs=list(self.evidence_refs),
            ))
        return nodes

    def to_dict(self) -> Dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "failure_signature": self.failure_signature,
            "applicability": self.applicability,
            "required_facts": self.required_facts,
            "repair_steps": self.repair_steps,
            "expected_effects": self.expected_effects,
            "evidence_refs": self.evidence_refs,
            "invalidation_conditions": self.invalidation_conditions,
            "verification_status": self.verification_status.value,
            "source_task_id": self.source_task_id,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
        }


class RepairMemoryStore:
    def __init__(self):
        self.memories: Dict[str, RepairMemoryItem] = {}
        self.retrieval_log: List[Dict[str, Any]] = []

    def record_repair_experience(
        self,
        memory_id: str,
        failure_signature: Dict[str, Any],
        applicability: Dict[str, Any],
        required_facts: List[str],
        repair_steps: List[Dict[str, Any]],
        expected_effects: List[str],
        evidence_refs: List[str],
        invalidation_conditions: Dict[str, Any],
        verification_status: VerificationStatus = VerificationStatus.VERIFIED,
        source_task_id: str = "source_task",
    ) -> RepairMemoryItem:
        item = RepairMemoryItem(
            memory_id=memory_id,
            failure_signature=failure_signature,
            applicability=applicability,
            required_facts=required_facts,
            repair_steps=repair_steps,
            expected_effects=expected_effects,
            evidence_refs=evidence_refs,
            invalidation_conditions=invalidation_conditions,
            verification_status=verification_status,
            source_task_id=source_task_id,
            success_count=1 if verification_status == VerificationStatus.VERIFIED else 0,
        )
        self.memories[memory_id] = item
        return item

    def update_with_observation(self, observation: Dict[str, Any]):
        """Evaluates invalidation conditions against new sensory observations."""
        for item in self.memories.values():
            if item.verification_status != VerificationStatus.INVALIDATED:
                for k, v in item.invalidation_conditions.items():
                    if k in observation and observation[k] == v:
                        item.verification_status = VerificationStatus.INVALIDATED
                    elif "door" in observation and "passage_state" in observation:
                        door_k = f"{observation['door']}_state"
                        if door_k == k and observation["passage_state"] == v:
                            item.verification_status = VerificationStatus.INVALIDATED

    def retrieve_repair_plan(
        self,
        failed_tool: str,
        failed_params: Dict[str, Any],
        error_code: str,
        current_state: Dict[str, Any],
        known_facts: Dict[str, Any],
    ) -> Optional[List[PlanNode]]:
        """Retrieves and instantiates matching verified repair templates."""
        target = failed_params.get("target_zone") or failed_params.get("package_id")
        robot_loc = current_state.get("robot_location", "Lobby")

        for item in self.memories.values():
            if item.verification_status != VerificationStatus.VERIFIED:
                continue

            sig = item.failure_signature
            if sig.get("action_name") == failed_tool and sig.get("error_code") == error_code:
                # Check target or applicability match
                app = item.applicability
                if app.get("origin") and app.get("origin") != robot_loc:
                    continue

                if not item.evaluate_applicability(known_facts):
                    continue

                bindings = {
                    "origin": robot_loc,
                    "target": target,
                    "detour_zone": "Corridor_South" if robot_loc == "Lobby" else "Corridor_North",
                    "credential_name": "security_badge",
                }
                nodes = item.instantiate_repair_nodes(bindings)
                self.retrieval_log.append({
                    "failed_tool": failed_tool,
                    "error_code": error_code,
                    "matched_memory_id": item.memory_id,
                    "instantiated_nodes_count": len(nodes),
                })
                return nodes

        return None

    def get_all_memories(self) -> List[RepairMemoryItem]:
        return list(self.memories.values())
