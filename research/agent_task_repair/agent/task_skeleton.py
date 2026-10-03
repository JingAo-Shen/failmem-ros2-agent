"""
Minimal Public Task Skeleton & Explicit Subgoal Derivation for FailMem Stage 2.
Maintains public task obligations, dependency graphs, and structured active subgoals
without reading any hidden environment ground truth.
"""
from typing import Dict, Any, List, Optional, Set, Tuple
from dataclasses import dataclass, field


@dataclass
class DeliveryObligation:
    package_id: str
    pickup_location: str
    target_room: str
    recipient: str
    is_delivered: bool = False
    in_inventory: bool = False

    @property
    def status_str(self) -> str:
        if self.is_delivered:
            return "DELIVERED"
        if self.in_inventory:
            return "HELD_IN_INVENTORY"
        return f"AT_PICKUP_LOCATION ({self.pickup_location})"


@dataclass
class Subgoal:
    id: str
    type: str  # "PICKUP", "NAVIGATE", "DELIVER", "RECHARGE", "ACQUIRE_CREDENTIAL", "OBSERVE"
    target: str  # Destination zone, package id, or recipient
    package_id: Optional[str] = None
    recipient: Optional[str] = None
    preconditions: List[str] = field(default_factory=list)
    completion_conditions: List[str] = field(default_factory=list)
    priority_reason: str = ""
    is_ready: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "action_type": self.type.lower(),
            "target": self.target,
            "package_id": self.package_id,
            "recipient": self.recipient,
            "preconditions": self.preconditions,
            "completion_conditions": self.completion_conditions,
            "priority_reason": self.priority_reason,
            "is_ready": self.is_ready,
        }

    def __getitem__(self, key: str) -> Any:
        if key == "action_type":
            return self.type.lower()
        if hasattr(self, key):
            return getattr(self, key)
        raise KeyError(key)

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except (KeyError, AttributeError):
            return default

    def __contains__(self, key: str) -> bool:
        return key == "action_type" or hasattr(self, key)

    @property
    def summary_str(self) -> str:
        if self.type == "PICKUP":
            return f"PICKUP(package={self.package_id}, from={self.target})"
        elif self.type == "DELIVER":
            return f"DELIVER(package={self.package_id}, recipient={self.recipient}, room={self.target})"
        elif self.type == "NAVIGATE":
            return f"NAVIGATE_TO({self.target})"
        elif self.type == "RECHARGE":
            return f"RECHARGE_BATTERY(at={self.target})"
        elif self.type == "ACQUIRE_CREDENTIAL":
            return f"ACQUIRE_CREDENTIAL({self.target})"
        elif self.type == "OBSERVE":
            return f"OBSERVE({self.target})"
        return f"{self.type}({self.target})"


class PublicTaskSkeleton:
    """
    Public task state tracker and explicit subgoal derivation engine.
    Operates strictly on visible robot state and tool-returned evidence (known_state).
    """
    def __init__(
        self,
        adjacency_map: Dict[str, List[str]],
        max_inventory_capacity: int = 2,
        charger_location: str = "Lobby",
    ):
        self.adjacency_map = adjacency_map
        self.max_inventory_capacity = max_inventory_capacity
        self.charger_location = charger_location

    def parse_obligations(
        self,
        current_state: Dict[str, Any],
        step_history: List[Dict[str, Any]],
    ) -> List[DeliveryObligation]:
        inventory = set(current_state.get("inventory", []))
        avail_pkgs = current_state.get("available_packages", [])

        # Check delivered packages from step history
        delivered_pids = set()
        for h in step_history:
            if h.get("tool") == "deliver" and h.get("result", {}).get("success"):
                pid = h.get("params", {}).get("package_id")
                if pid:
                    delivered_pids.add(pid)

        obligations = []
        for p in avail_pkgs:
            pid = p["id"]
            is_deliv = pid in delivered_pids
            in_inv = pid in inventory
            obligations.append(DeliveryObligation(
                package_id=pid,
                pickup_location=p.get("pickup_location", "Lobby"),
                target_room=p.get("target_room", ""),
                recipient=p.get("recipient", ""),
                is_delivered=is_deliv,
                in_inventory=in_inv,
            ))
        return obligations

    def evaluate_dependencies_and_subgoals(
        self,
        current_state: Dict[str, Any],
        known_state: Dict[str, Any],
        obligations: List[DeliveryObligation],
    ) -> Dict[str, Any]:
        robot_loc = current_state.get("robot_location", "Lobby")
        inventory = current_state.get("inventory", [])
        battery = current_state.get("battery", 100)
        max_cap = current_state.get("max_inventory_capacity", self.max_inventory_capacity)

        unsatisfied_dependencies = []
        candidate_subgoals: List[Subgoal] = []
        active_subgoal: Optional[Subgoal] = None

        # Priority 1: Critical Battery Recharge
        # If battery is low (<= 25% or below safe round-trip threshold)
        if battery <= 25:
            if robot_loc == self.charger_location:
                sg_recharge = Subgoal(
                    id="sg_recharge_battery",
                    type="RECHARGE",
                    target=self.charger_location,
                    preconditions=[f"at_location({self.charger_location})"],
                    completion_conditions=["battery_level(100)"],
                    priority_reason=f"Battery is critically low ({battery}%). Recharging at {self.charger_location} is mandatory.",
                    is_ready=True,
                )
                candidate_subgoals.append(sg_recharge)
                active_subgoal = sg_recharge
            else:
                unsatisfied_dependencies.append(
                    f"Recharge battery ({battery}%): Robot is at '{robot_loc}', charger is at '{self.charger_location}'. Must navigate to charger first."
                )
                sg_nav_charger = Subgoal(
                    id="sg_nav_to_charger",
                    type="NAVIGATE",
                    target=self.charger_location,
                    preconditions=[],
                    completion_conditions=[f"at_location({self.charger_location})"],
                    priority_reason=f"Battery is low ({battery}%). Must navigate to {self.charger_location} charger.",
                    is_ready=True,
                )
                candidate_subgoals.append(sg_nav_charger)
                active_subgoal = sg_nav_charger

        # Priority 2: Immediate Delivery of held packages in current room
        if active_subgoal is None:
            for ob in obligations:
                if ob.is_delivered:
                    continue
                if ob.in_inventory and robot_loc == ob.target_room:
                    sg_deliver = Subgoal(
                        id=f"sg_deliver_{ob.package_id}",
                        type="DELIVER",
                        target=ob.target_room,
                        package_id=ob.package_id,
                        recipient=ob.recipient,
                        preconditions=[f"holding({ob.package_id})", f"at_location({ob.target_room})"],
                        completion_conditions=[f"delivered({ob.package_id})"],
                        priority_reason=f"Robot is holding {ob.package_id} and is at destination room {ob.target_room}.",
                        is_ready=True,
                    )
                    candidate_subgoals.append(sg_deliver)
                    if active_subgoal is None:
                        active_subgoal = sg_deliver

        # Priority 3: Navigate to Deliver held packages if inventory is full or delivery is pending
        if active_subgoal is None:
            for ob in obligations:
                if ob.is_delivered:
                    continue
                if ob.in_inventory:
                    # We are holding this package but in a different room
                    unsatisfied_dependencies.append(
                        f"Deliver {ob.package_id} to {ob.recipient}: Robot holds package at '{robot_loc}', required room is '{ob.target_room}'."
                    )
                    sg_nav_deliv = Subgoal(
                        id=f"sg_nav_to_deliver_{ob.package_id}",
                        type="NAVIGATE",
                        target=ob.target_room,
                        package_id=ob.package_id,
                        recipient=ob.recipient,
                        preconditions=[f"holding({ob.package_id})"],
                        completion_conditions=[f"at_location({ob.target_room})"],
                        priority_reason=f"Robot holds {ob.package_id}. Navigating to target room {ob.target_room}.",
                        is_ready=True,
                    )
                    candidate_subgoals.append(sg_nav_deliv)
                    if active_subgoal is None and len(inventory) >= max_cap:
                        active_subgoal = sg_nav_deliv

        # Priority 4: Pickup available packages in current room
        for ob in obligations:
            if ob.is_delivered or ob.in_inventory:
                continue
            if robot_loc == ob.pickup_location:
                if len(inventory) < max_cap:
                    sg_pickup = Subgoal(
                        id=f"sg_pickup_{ob.package_id}",
                        type="PICKUP",
                        target=ob.pickup_location,
                        package_id=ob.package_id,
                        recipient=ob.recipient,
                        preconditions=[f"at_location({ob.pickup_location})", f"inventory_space(<{max_cap})"],
                        completion_conditions=[f"holding({ob.package_id})"],
                        priority_reason=f"Package {ob.package_id} is present in current room {ob.pickup_location} and inventory has space.",
                        is_ready=True,
                    )
                    candidate_subgoals.append(sg_pickup)
                    if active_subgoal is None or active_subgoal.type == "NAVIGATE":
                        active_subgoal = sg_pickup
                else:
                    unsatisfied_dependencies.append(
                        f"Pickup {ob.package_id}: Inventory is full ({len(inventory)}/{max_cap}). Cannot pick up more packages."
                    )

        # Priority 5: Navigate to pickup location for remaining undelivered packages
        for ob in obligations:
            if ob.is_delivered or ob.in_inventory:
                continue
            if robot_loc != ob.pickup_location:
                unsatisfied_dependencies.append(
                    f"Pickup {ob.package_id}: Robot at '{robot_loc}', package at '{ob.pickup_location}'. Must navigate to pickup location '{ob.pickup_location}' first."
                )
                if active_subgoal is None:
                    sg_nav_pickup = Subgoal(
                        id=f"sg_nav_to_pickup_{ob.package_id}",
                        type="NAVIGATE",
                        target=ob.pickup_location,
                        package_id=ob.package_id,
                        preconditions=[],
                        completion_conditions=[f"at_location({ob.pickup_location})"],
                        priority_reason=f"Navigating to {ob.pickup_location} to pick up {ob.package_id}.",
                        is_ready=True,
                    )
                    candidate_subgoals.append(sg_nav_pickup)
                    active_subgoal = sg_nav_pickup

        # Fallback default subgoal
        if active_subgoal is None and candidate_subgoals:
            active_subgoal = candidate_subgoals[0]

        return {
            "obligations": obligations,
            "unsatisfied_dependencies": unsatisfied_dependencies,
            "candidate_subgoals": candidate_subgoals,
            "active_subgoal": active_subgoal,
        }

    def evaluate_dependencies(
        self,
        current_state: Dict[str, Any],
        known_state: Dict[str, Any],
        obligations: List[DeliveryObligation],
    ) -> Dict[str, Any]:
        """Backward-compatible alias for evaluate_dependencies_and_subgoals."""
        return self.evaluate_dependencies_and_subgoals(current_state, known_state, obligations)

    def format_skeleton_prompt_section(
        self,
        current_state: Dict[str, Any],
        known_state: Dict[str, Any],
        step_history: List[Dict[str, Any]],
    ) -> Tuple[str, Optional[Subgoal]]:
        """Formats the public task skeleton checklist and returns (prompt_section_str, active_subgoal)."""
        obligations = self.parse_obligations(current_state, step_history)
        eval_res = self.evaluate_dependencies_and_subgoals(current_state, known_state, obligations)

        lines = ["### Task Skeleton & Public Dependency Status:"]
        
        # 1. Active Subgoal
        active_sg = eval_res.get("active_subgoal")
        if active_sg:
            lines.append(f"- Current Active Subgoal: [{active_sg.id}] {active_sg.summary_str}")
            lines.append(f"  * Rationale: {active_sg.priority_reason}")
            if active_sg.preconditions:
                lines.append(f"  * Preconditions: {active_sg.preconditions}")

        # 2. Obligations list
        lines.append("- Pending Delivery Obligations:")
        for ob in obligations:
            lines.append(f"  * Package {ob.package_id}: [Status: {ob.status_str}] -> Target: {ob.recipient} in {ob.target_room}")

        # 3. Unsatisfied dependencies
        if eval_res["unsatisfied_dependencies"]:
            lines.append("- Unsatisfied Preconditions / Blockers:")
            for dep in eval_res["unsatisfied_dependencies"]:
                lines.append(f"  * {dep}")

        # 4. Actionable candidate subgoals
        lines.append("- Actionable Candidate Subgoals for Current State:")
        for sg in eval_res["candidate_subgoals"]:
            lines.append(f"  * [{sg.id}] {sg.summary_str}")

        return "\n".join(lines), active_sg
