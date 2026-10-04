"""
Local Repair Controller for FailMem Stage 2 Stateful Agent Architecture.
Handles:
  - Failure diagnosis & affected plan node identification.
  - Integration with repair_memory (retrieving evidence-backed repair templates).
  - Online fallback repair synthesis (grounded in map topology & observed facts, without unobserved location conjectures).
  - Plan surgery: inserting local repair sub-nodes and replanning downstream navigation.
  - Rigorous dead-loop prevention under unchanged epistemic fact states and versions.
"""
from typing import Dict, Any, List, Optional, Tuple, Set
import copy
from .task_state import TaskStateTracker, ObligationStatus, ObservedFact
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

        # 1. Dead-loop detection: check exact fact contents & versions rather than just count
        fact_signature = frozenset(
            (k, getattr(v, "value", str(v)), getattr(v, "version", 1))
            for k, v in task_state.observed_facts.items()
        )
        action_sig = (robot_loc, failed_tool, str(sorted(failed_params.items())), error_code, fact_signature)
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

        # 3. Online Local Repair Synthesis (if no verified memory template retrieved)
        if not repair_nodes:
            if error_code in ("DOORWAY_BLOCKED", "DOOR_BLOCKED"):
                blocked_target = failed_params.get("target_zone")
                # Identify next non-navigation goal destination
                final_dest = None
                for n in plan.nodes[plan.current_node_index:]:
                    if n.action_type in ("pickup", "deliver", "recharge"):
                        final_dest = n.target
                        break
                final_dest = final_dest or blocked_target

                # Compute detour avoiding blocked target doorway
                avoid_set = {blocked_target} if blocked_target else set()
                detour_path = plan.find_path(robot_loc, final_dest, avoid=avoid_set)

                if detour_path:
                    for h_idx, hop in enumerate(detour_path, start=1):
                        repair_nodes.append(PlanNode(
                            id=f"repair_detour_{h_idx:02d}_{hop}",
                            goal=f"Detour via {hop} to bypass blocked doorway to {blocked_target}",
                            action_type="navigate",
                            target=hop,
                            params={"target_zone": hop},
                            preconditions=[f"at_location({robot_loc if h_idx==1 else detour_path[h_idx-2]})"],
                            expected_effects=[f"at_location({hop})"],
                            status=PlanNodeStatus.READY if h_idx == 1 else PlanNodeStatus.PENDING,
                            is_repair_node=True,
                        ))

            elif error_code in ("SECURITY_BADGE_REQUIRED", "ACCESS_DENIED_NO_BADGE"):
                # Credential required: check if badge location is known from observations
                known_badge_loc = None
                for k, v in task_state.observed_facts.items():
                    if k.startswith("room_items_") and isinstance(getattr(v, "value", v), list):
                        items = getattr(v, "value", v)
                        if "security_badge" in items:
                            known_badge_loc = k.replace("room_items_", "")
                            break

                if known_badge_loc:
                    # Grounded path to known badge location
                    if robot_loc != known_badge_loc:
                        nav_path = plan.find_path(robot_loc, known_badge_loc)
                        for hop in nav_path:
                            repair_nodes.append(PlanNode(
                                id=f"repair_nav_cred_{hop}",
                                goal=f"Navigate to {hop} en route to acquire security_badge at {known_badge_loc}",
                                action_type="navigate",
                                target=hop,
                                params={"target_zone": hop},
                                status=PlanNodeStatus.READY if len(repair_nodes) == 0 else PlanNodeStatus.PENDING,
                                is_repair_node=True,
                            ))
                    repair_nodes.append(PlanNode(
                        id="repair_acquire_badge",
                        goal="Acquire security_badge credential",
                        action_type="acquire_credential",
                        target="security_badge",
                        params={"credential_name": "security_badge"},
                        status=PlanNodeStatus.READY if len(repair_nodes) == 0 else PlanNodeStatus.PENDING,
                        is_repair_node=True,
                    ))
                else:
                    # Location unknown: generate observation step first without assuming Office_A
                    repair_nodes.append(PlanNode(
                        id="repair_observe_items",
                        goal="Observe current room for available credentials",
                        action_type="observe",
                        target="room_items",
                        params={"target": "room_items"},
                        status=PlanNodeStatus.READY,
                        is_repair_node=True,
                    ))

            elif error_code in ("BATTERY_LOW", "NOT_AT_CHARGER", "BATTERY_DEPLETED"):
                # Recharge repair
                if robot_loc != task_state.charger_location:
                    nav_path = plan.find_path(robot_loc, task_state.charger_location)
                    for hop in nav_path:
                        repair_nodes.append(PlanNode(
                            id=f"repair_nav_charger_{hop}",
                            goal=f"Navigate to {hop} en route to charger",
                            action_type="navigate",
                            target=hop,
                            params={"target_zone": hop},
                            status=PlanNodeStatus.READY if len(repair_nodes) == 0 else PlanNodeStatus.PENDING,
                            is_repair_node=True,
                        ))
                repair_nodes.append(PlanNode(
                    id="repair_recharge_battery",
                    goal="Recharge battery to 100%",
                    action_type="recharge",
                    target=task_state.charger_location,
                    params={},
                    status=PlanNodeStatus.READY if len(repair_nodes) == 0 else PlanNodeStatus.PENDING,
                    is_repair_node=True,
                ))

        # 4. Insert repair nodes and update downstream navigation
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
