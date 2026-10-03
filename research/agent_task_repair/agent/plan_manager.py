"""
Persistent Plan Manager for FailMem Stage 2 Stateful Agent Architecture.
Maintains:
  - Explicit multi-step plan nodes with dependencies, preconditions, and expected effects.
  - Plan persistence across steps (avoids regenerating the plan from scratch each turn).
  - Local plan repair and node insertion upon failure or new facts.
  - Strict preservation of all task obligations.
"""
from typing import Dict, Any, List, Optional, Set, Tuple
from dataclasses import dataclass, field
from enum import Enum
import copy
from .task_state import TaskStateTracker, ObligationStatus
from .planner import MAP_ADJACENCY


class PlanNodeStatus(str, Enum):
    PENDING = "PENDING"
    READY = "READY"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    INVALIDATED = "INVALIDATED"


@dataclass
class PlanNode:
    id: str
    goal: str
    action_type: str  # "pickup", "navigate", "deliver", "recharge", "acquire_credential", "observe"
    target: str
    params: Dict[str, Any] = field(default_factory=dict)
    package_id: Optional[str] = None
    recipient: Optional[str] = None
    preconditions: List[str] = field(default_factory=list)
    expected_effects: List[str] = field(default_factory=list)
    status: PlanNodeStatus = PlanNodeStatus.PENDING
    evidence_refs: List[str] = field(default_factory=list)
    is_repair_node: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "goal": self.goal,
            "action_type": self.action_type,
            "target": self.target,
            "params": copy.deepcopy(self.params),
            "package_id": self.package_id,
            "recipient": self.recipient,
            "preconditions": list(self.preconditions),
            "expected_effects": list(self.expected_effects),
            "status": self.status.value,
            "evidence_refs": list(self.evidence_refs),
            "is_repair_node": self.is_repair_node,
        }

    @property
    def summary_str(self) -> str:
        return f"[{self.status.value}] Node {self.id}: {self.action_type.upper()}({self.target}) -> {self.goal}"


class PersistentPlan:
    def __init__(
        self,
        task_state: TaskStateTracker,
        adjacency_map: Optional[Dict[str, List[str]]] = None,
    ):
        self.task_state = task_state
        self.adjacency_map = adjacency_map or MAP_ADJACENCY
        self.nodes: List[PlanNode] = []
        self.current_node_index: int = 0
        self.plan_version: int = 1
        self.revision_history: List[Dict[str, Any]] = []

    def find_path(self, start: str, goal: str, avoid: Optional[Set[str]] = None) -> List[str]:
        """Finds shortest topological path avoiding specified nodes."""
        if start == goal:
            return []
        avoid_set = set(avoid or [])
        from collections import deque
        queue = deque([[start]])
        visited = {start} | avoid_set
        while queue:
            path = queue.popleft()
            node = path[-1]
            for neighbor in self.adjacency_map.get(node, []):
                if neighbor == goal:
                    return path[1:] + [goal]
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(path + [neighbor])
        # If no path found without avoid_set, try unrestricted fallback
        if avoid_set:
            return self.find_path(start, goal, avoid=None)
        return [goal]

    def initialize_initial_plan(self):
        """Constructs an initial structured plan decomposition with pathfinding and batching."""
        self.nodes.clear()
        node_id = 1
        sim_loc = self.task_state.robot_location
        obs_list = [ob for ob in self.task_state.obligations.values() if ob.status != ObligationStatus.DONE]
        cap = self.task_state.max_inventory_capacity

        # 1. Check critical battery first
        if self.task_state.battery <= 25:
            if sim_loc != self.task_state.charger_location:
                for hop in self.find_path(sim_loc, self.task_state.charger_location):
                    self.nodes.append(PlanNode(
                        id=f"node_{node_id:02d}_nav_{hop}",
                        goal=f"Navigate to {hop} en route to charger",
                        action_type="navigate",
                        target=hop,
                        params={"target_zone": hop},
                        status=PlanNodeStatus.READY if node_id == 1 else PlanNodeStatus.PENDING,
                    ))
                    node_id += 1
                sim_loc = self.task_state.charger_location

            self.nodes.append(PlanNode(
                id=f"node_{node_id:02d}_recharge",
                goal="Recharge battery to 100%",
                action_type="recharge",
                target=self.task_state.charger_location,
                params={},
                preconditions=[f"at_location({self.task_state.charger_location})"],
                expected_effects=["battery_level(100)"],
                status=PlanNodeStatus.READY if node_id == 1 else PlanNodeStatus.PENDING,
            ))
            node_id += 1

        # 2. Batch obligations according to vehicle capacity
        # Split obligations into batches of size <= cap
        batches = []
        for i in range(0, len(obs_list), cap):
            batches.append(obs_list[i:i + cap])

        for batch_idx, batch in enumerate(batches):
            # Phase A: Pickup all items in batch
            for ob in batch:
                if ob.package_id not in self.task_state.inventory:
                    if sim_loc != ob.pickup_location:
                        for hop in self.find_path(sim_loc, ob.pickup_location):
                            self.nodes.append(PlanNode(
                                id=f"node_{node_id:02d}_nav_{hop}",
                                goal=f"Navigate to {hop} to collect {ob.package_id}",
                                action_type="navigate",
                                target=hop,
                                params={"target_zone": hop},
                                package_id=ob.package_id,
                                status=PlanNodeStatus.READY if node_id == 1 else PlanNodeStatus.PENDING,
                            ))
                            node_id += 1
                        sim_loc = ob.pickup_location

                    self.nodes.append(PlanNode(
                        id=f"node_{node_id:02d}_pickup_{ob.package_id}",
                        goal=f"Pick up {ob.package_id} at {ob.pickup_location}",
                        action_type="pickup",
                        target=ob.pickup_location,
                        params={"package_id": ob.package_id, "from_location": ob.pickup_location},
                        package_id=ob.package_id,
                        recipient=ob.recipient,
                        preconditions=[f"at_location({ob.pickup_location})", "inventory_space_available"],
                        expected_effects=[f"holding({ob.package_id})"],
                        status=PlanNodeStatus.READY if node_id == 1 else PlanNodeStatus.PENDING,
                    ))
                    node_id += 1

            # Phase B: Deliver all items in batch
            for ob in batch:
                if sim_loc != ob.target_room:
                    for hop in self.find_path(sim_loc, ob.target_room):
                        self.nodes.append(PlanNode(
                            id=f"node_{node_id:02d}_nav_{hop}",
                            goal=f"Navigate to {hop} to deliver {ob.package_id}",
                            action_type="navigate",
                            target=hop,
                            params={"target_zone": hop},
                            package_id=ob.package_id,
                            recipient=ob.recipient,
                            preconditions=[f"holding({ob.package_id})"],
                            status=PlanNodeStatus.READY if node_id == 1 else PlanNodeStatus.PENDING,
                        ))
                        node_id += 1
                    sim_loc = ob.target_room

                self.nodes.append(PlanNode(
                    id=f"node_{node_id:02d}_deliver_{ob.package_id}",
                    goal=f"Deliver {ob.package_id} to {ob.recipient} in {ob.target_room}",
                    action_type="deliver",
                    target=ob.target_room,
                    params={"package_id": ob.package_id, "recipient": ob.recipient},
                    package_id=ob.package_id,
                    recipient=ob.recipient,
                    preconditions=[f"holding({ob.package_id})", f"at_location({ob.target_room})"],
                    expected_effects=[f"delivered({ob.package_id})"],
                    status=PlanNodeStatus.READY if node_id == 1 else PlanNodeStatus.PENDING,
                ))
                node_id += 1

        if self.nodes:
            self.nodes[0].status = PlanNodeStatus.READY
        self.current_node_index = 0

    def get_current_active_node(self) -> Optional[PlanNode]:
        for idx, node in enumerate(self.nodes):
            if node.status in (PlanNodeStatus.READY, PlanNodeStatus.IN_PROGRESS):
                self.current_node_index = idx
                return node
        # If no ready node, look for first pending
        for idx, node in enumerate(self.nodes):
            if node.status == PlanNodeStatus.PENDING:
                node.status = PlanNodeStatus.READY
                self.current_node_index = idx
                return node
        return None

    def on_step_success(self, tool_name: str, params: Dict[str, Any], event_id: str):
        """Marks active node completed if effects satisfied and advances to next node."""
        active_node = self.get_current_active_node()
        if active_node and active_node.action_type == tool_name:
            active_node.status = PlanNodeStatus.COMPLETED
            active_node.evidence_refs.append(event_id)

        # Update remaining node statuses
        active_node = self.get_current_active_node()

    def insert_repair_nodes(self, repair_nodes: List[PlanNode], reason: str):
        """Inserts local repair nodes before the currently blocked node."""
        curr_idx = self.current_node_index
        for r_node in repair_nodes:
            r_node.is_repair_node = True
        self.nodes[curr_idx:curr_idx] = repair_nodes
        self.plan_version += 1
        self.revision_history.append({
            "version": self.plan_version,
            "reason": reason,
            "inserted_nodes_count": len(repair_nodes),
            "inserted_node_ids": [n.id for n in repair_nodes],
        })
        if self.nodes:
            self.nodes[curr_idx].status = PlanNodeStatus.READY

    def format_plan_prompt_section(self) -> str:
        lines = [f"### Persistent Task Plan (Version {self.plan_version}):"]
        for idx, node in enumerate(self.nodes):
            marker = " -> [ACTIVE]" if idx == self.current_node_index else ""
            lines.append(f"{idx+1}. {node.summary_str}{marker}")
            if node.preconditions:
                lines.append(f"   Preconditions: {node.preconditions}")
        return "\n".join(lines)
