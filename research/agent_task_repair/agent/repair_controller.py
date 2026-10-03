"""
Local Repair Controller for FailMem Stage 2 Stateful Agent Architecture.
Handles:
  - Failure diagnosis & affected plan node identification.
  - Integration with repair_memory (retrieving evidence-backed repair templates).
  - Online fallback repair synthesis.
  - Plan surgery: inserting local repair sub-nodes before the blocked node.
  - Rigorous dead-loop prevention under unchanged epistemic evidence.
"""
from typing import Dict, Any, List, Optional, Tuple, Set
import copy
from .task_state import TaskStateTracker, ObligationStatus
from .plan_manager import PersistentPlan, PlanNode, PlanNodeStatus
from .planner import MAP_ADJACENCY


class RepairController:
    def __init__(
        self,
        adjacency_map: Optional[Dict[str, List[str]]] = None,
        max_repeated_attempts: int = 3,
    ):
        self.adjacency_map = adjacency_map or MAP_ADJACENCY
        self.max_repeated_attempts = max_repeated_attempts
        self.failed_action_history: List[Dict[str, Any]] = []
        self.repair_history: List[Dict[str, Any]] = []

    def handle_failure(
        self,
        failed_tool: str,
        failed_params: Dict[str, Any],
        error_code: str,
        observation: Dict[str, Any],
        task_state: TaskStateTracker,
        plan: PersistentPlan,
        repair_memory_adapter: Optional[Any] = None,
    ) -> Tuple[bool, str, List[PlanNode]]:
        """
        Executes local plan repair.
        Returns: (should_abort, reason_message, generated_repair_nodes)
        """
        robot_loc = task_state.robot_location
        active_node = plan.get_current_active_node()

        # 1. Dead-loop detection: check if identical action failed in identical state without new evidence
        action_sig = (robot_loc, failed_tool, str(failed_params), error_code, len(task_state.observed_facts))
        repeat_count = sum(1 for h in self.failed_action_history if h.get("signature") == action_sig)
        
        self.failed_action_history.append({
            "signature": action_sig,
            "tool": failed_tool,
            "params": failed_params,
            "error_code": error_code,
            "step": task_state.step_counter,
        })

        if repeat_count >= self.max_repeated_attempts - 1:
            return True, f"DEAD_LOOP_ABORT: Action {failed_tool}({failed_params}) failed {repeat_count+1} times in state '{robot_loc}' with no new evidence.", []

        # 2. Check for matching repair memory if adapter provided (Group D)
        repair_nodes: List[PlanNode] = []
        memory_used = False

        if repair_memory_adapter and hasattr(repair_memory_adapter, "retrieve_repair_plan"):
            matching_repair = repair_memory_adapter.retrieve_repair_plan(
                failed_tool=failed_tool,
                failed_params=failed_params,
                error_code=error_code,
                current_state=task_state.get_public_state_summary(),
                known_facts=task_state.observed_facts,
            )
            if matching_repair:
                repair_nodes = matching_repair
                memory_used = True

        # 3. Online Local Repair Synthesis (if no memory template used)
        if not repair_nodes:
            if error_code == "DOORWAY_BLOCKED" or "DOOR_BLOCKED" in error_code:
                blocked_target = failed_params.get("target_zone")
                # Synthesize alternate detour route via adjacency graph
                alt_neighbors = [z for z in self.adjacency_map.get(robot_loc, []) if z != blocked_target]
                if alt_neighbors:
                    detour_zone = alt_neighbors[0]
                    # Check if destination target was specified
                    dest_target = active_node.target if active_node else blocked_target
                    repair_nodes.append(PlanNode(
                        id=f"repair_detour_{detour_zone}",
                        goal=f"Detour via {detour_zone} to bypass blocked doorway to {blocked_target}",
                        action_type="navigate",
                        target=detour_zone,
                        params={"target_zone": detour_zone},
                        preconditions=[f"at_location({robot_loc})"],
                        expected_effects=[f"at_location({detour_zone})"],
                        status=PlanNodeStatus.READY,
                        is_repair_node=True,
                    ))

            elif error_code in ("SECURITY_BADGE_REQUIRED", "ACCESS_DENIED_NO_BADGE"):
                # Missing security badge: acquire credential from available location
                # Check known credential locations or Lobby
                cred_loc = "Lobby" if robot_loc == "Lobby" else "Office_A"
                if robot_loc != cred_loc and robot_loc != "Lobby":
                    repair_nodes.append(PlanNode(
                        id=f"repair_nav_cred_{cred_loc}",
                        goal=f"Navigate to {cred_loc} to acquire security_badge",
                        action_type="navigate",
                        target=cred_loc,
                        params={"target_zone": cred_loc},
                        status=PlanNodeStatus.READY,
                        is_repair_node=True,
                    ))
                repair_nodes.append(PlanNode(
                    id="repair_acquire_badge",
                    goal="Acquire security_badge credential",
                    action_type="acquire_credential",
                    target="security_badge",
                    params={"credential_name": "security_badge"},
                    status=PlanNodeStatus.PENDING,
                    is_repair_node=True,
                ))

            elif error_code in ("BATTERY_LOW", "NOT_AT_CHARGER"):
                # Battery recharge repair
                if robot_loc != "Lobby":
                    repair_nodes.append(PlanNode(
                        id="repair_nav_charger",
                        goal="Navigate to Lobby charging station",
                        action_type="navigate",
                        target="Lobby",
                        params={"target_zone": "Lobby"},
                        status=PlanNodeStatus.READY,
                        is_repair_node=True,
                    ))
                repair_nodes.append(PlanNode(
                    id="repair_recharge_battery",
                    goal="Recharge battery to 100%",
                    action_type="recharge",
                    target="Lobby",
                    params={},
                    status=PlanNodeStatus.PENDING,
                    is_repair_node=True,
                ))

        # 4. Insert repair nodes into plan
        if repair_nodes:
            plan.insert_repair_nodes(repair_nodes, reason=f"Repaired failure on {failed_tool}: {error_code} (MemoryUsed={memory_used})")
            self.repair_history.append({
                "step": task_state.step_counter,
                "failed_tool": failed_tool,
                "error_code": error_code,
                "memory_used": memory_used,
                "repair_nodes": [n.to_dict() for n in repair_nodes],
            })
            return False, f"Local repair synthesized ({len(repair_nodes)} nodes inserted).", repair_nodes

        return False, f"No specific repair synthesized for error '{error_code}'.", []
