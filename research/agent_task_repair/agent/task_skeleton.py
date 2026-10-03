"""
Minimal Public Task Skeleton for FailMem Stage 2 Robot Agent.
Maintains public task obligations, dependency graphs, and candidate subgoals
without reading any hidden environment ground truth.
"""
from typing import Dict, Any, List, Optional, Set
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


class PublicTaskSkeleton:
    """
    Public task state tracker and precondition checker.
    Operates strictly on visible robot state and tool-returned evidence (known_state).
    """
    def __init__(self, adjacency_map: Dict[str, List[str]], max_inventory_capacity: int = 2):
        self.adjacency_map = adjacency_map
        self.max_inventory_capacity = max_inventory_capacity

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

    def evaluate_dependencies(
        self,
        current_state: Dict[str, Any],
        known_state: Dict[str, Any],
        obligations: List[DeliveryObligation],
    ) -> Dict[str, Any]:
        robot_loc = current_state.get("robot_location", "Lobby")
        inventory = current_state.get("inventory", [])
        battery = current_state.get("battery", 100)
        credentials = set(current_state.get("credentials", []))

        unsatisfied_dependencies = []
        candidate_subgoals = []

        # 1. Evaluate Deliveries
        for ob in obligations:
            if ob.is_delivered:
                continue

            if ob.in_inventory:
                # We hold the package!
                if robot_loc == ob.target_room:
                    # Satisfied! Ready to deliver
                    candidate_subgoals.append({
                        "subgoal": f"DELIVER_PACKAGE({ob.package_id}, recipient={ob.recipient}, room={ob.target_room})",
                        "action_type": "deliver",
                        "target": ob.recipient,
                        "package_id": ob.package_id,
                        "ready": True,
                        "missing_preconditions": [],
                    })
                else:
                    unsatisfied_dependencies.append(
                        f"Deliver {ob.package_id} to {ob.recipient}: Robot is holding package but is at '{robot_loc}' (requires being at '{ob.target_room}')."
                    )
                    candidate_subgoals.append({
                        "subgoal": f"NAVIGATE_TO_DELIVERY_ROOM({ob.target_room}) for package {ob.package_id}",
                        "action_type": "navigate",
                        "target": ob.target_room,
                        "ready": True,
                        "missing_preconditions": [],
                    })
            else:
                # Package is at pickup location
                if robot_loc == ob.pickup_location:
                    if len(inventory) < self.max_inventory_capacity:
                        candidate_subgoals.append({
                            "subgoal": f"PICKUP_PACKAGE({ob.package_id}, from={ob.pickup_location})",
                            "action_type": "pickup",
                            "target": ob.pickup_location,
                            "package_id": ob.package_id,
                            "ready": True,
                            "missing_preconditions": [],
                        })
                    else:
                        unsatisfied_dependencies.append(
                            f"Pickup {ob.package_id}: Inventory is full ({len(inventory)}/{self.max_inventory_capacity}). Must deliver held packages first."
                        )
                else:
                    unsatisfied_dependencies.append(
                        f"Pickup {ob.package_id}: Robot is at '{robot_loc}', package is at '{ob.pickup_location}'. Must navigate to pickup location first."
                    )
                    candidate_subgoals.append({
                        "subgoal": f"NAVIGATE_TO_PICKUP_LOCATION({ob.pickup_location}) for package {ob.package_id}",
                        "action_type": "navigate",
                        "target": ob.pickup_location,
                        "ready": True,
                        "missing_preconditions": [],
                    })

        # 2. Battery & Charging Subgoals
        if battery <= 30:
            if robot_loc == "Lobby":
                candidate_subgoals.append({
                    "subgoal": "RECHARGE_BATTERY() at Lobby charging station",
                    "action_type": "recharge",
                    "target": "Lobby",
                    "ready": True,
                    "missing_preconditions": [],
                })
            else:
                unsatisfied_dependencies.append(
                    f"Recharge battery ({battery}%): Robot is at '{robot_loc}', charging station is at 'Lobby'."
                )
                candidate_subgoals.append({
                    "subgoal": "NAVIGATE_TO_CHARGER(Lobby)",
                    "action_type": "navigate",
                    "target": "Lobby",
                    "ready": True,
                    "missing_preconditions": [],
                })

        return {
            "obligations": obligations,
            "unsatisfied_dependencies": unsatisfied_dependencies,
            "candidate_subgoals": candidate_subgoals,
        }

    def format_skeleton_prompt_section(
        self,
        current_state: Dict[str, Any],
        known_state: Dict[str, Any],
        step_history: List[Dict[str, Any]],
    ) -> str:
        """Formats the public task skeleton checklist for prompt injection."""
        obligations = self.parse_obligations(current_state, step_history)
        eval_res = self.evaluate_dependencies(current_state, known_state, obligations)

        lines = ["### Task Skeleton & Public Dependency Status:"]
        
        # 1. Obligations table
        lines.append("- Pending Delivery Obligations:")
        for ob in obligations:
            lines.append(f"  * Package {ob.package_id}: [Status: {ob.status_str}] -> Target: {ob.recipient} in {ob.target_room}")

        # 2. Unsatisfied dependencies
        if eval_res["unsatisfied_dependencies"]:
            lines.append("- Active Precondition Dependencies:")
            for dep in eval_res["unsatisfied_dependencies"]:
                lines.append(f"  * {dep}")

        # 3. Actionable subgoals
        lines.append("- Actionable Candidate Subgoals for Current State:")
        for sg in eval_res["candidate_subgoals"]:
            lines.append(f"  * {sg['subgoal']}")

        return "\n".join(lines)
