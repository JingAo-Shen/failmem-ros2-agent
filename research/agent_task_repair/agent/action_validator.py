"""
Pre-Execution Action Validator for FailMem Stage 2 Stateful Agent.
Enforces known preconditions, physical affordances, capacity limits, and schema correctness.
Returns PASS / FAIL / UNKNOWN.
Does NOT read hidden environment state or generate arbitrary optimal routes.
"""
from typing import Dict, Any, List, Optional, Tuple, Set
from dataclasses import dataclass
from enum import Enum
from .planner import TOOL_SCHEMAS, MAP_ADJACENCY


class ValidationStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


@dataclass
class ValidationResult:
    status: ValidationStatus
    reason: str
    conflicting_precondition: Optional[str] = None
    suggested_revision: Optional[Dict[str, Any]] = None

    @property
    def is_valid(self) -> bool:
        return self.status in (ValidationStatus.PASS, ValidationStatus.UNKNOWN)


class ActionValidator:
    def __init__(
        self,
        adjacency_map: Optional[Dict[str, List[str]]] = None,
        charger_location: str = "Lobby",
    ):
        self.adjacency_map = adjacency_map or MAP_ADJACENCY
        self.charger_location = charger_location

    def validate_action(
        self,
        tool_name: str,
        params: Dict[str, Any],
        current_state: Dict[str, Any],
        known_facts: Dict[str, Any],
    ) -> ValidationResult:
        # 1. Schema Check
        if tool_name not in TOOL_SCHEMAS:
            return ValidationResult(
                status=ValidationStatus.FAIL,
                reason=f"Unknown tool '{tool_name}'. Allowed tools: {list(TOOL_SCHEMAS.keys())}.",
                conflicting_precondition="tool_exists",
            )

        schema = TOOL_SCHEMAS[tool_name]
        for req in schema["required"]:
            if req not in params or params[req] is None or params[req] == "":
                return ValidationResult(
                    status=ValidationStatus.FAIL,
                    reason=f"Missing required parameter '{req}' for tool '{tool_name}'.",
                    conflicting_precondition=f"param_required({req})",
                )

        robot_loc = current_state.get("robot_location", "Lobby")
        inventory = current_state.get("inventory", [])
        credentials = set(current_state.get("credentials", []))
        battery = current_state.get("battery", 100)
        max_cap = current_state.get("max_inventory_capacity", 2)
        avail_pkgs = current_state.get("available_packages", [])

        # 2. Specific Tool Precondition Checks
        if tool_name == "pickup":
            pid = params.get("package_id")
            from_loc = params.get("from_location")

            if len(inventory) >= max_cap:
                return ValidationResult(
                    status=ValidationStatus.FAIL,
                    reason=f"Inventory is full ({len(inventory)}/{max_cap}). Cannot pick up '{pid}'.",
                    conflicting_precondition="inventory_space_available",
                )

            if pid in inventory:
                return ValidationResult(
                    status=ValidationStatus.FAIL,
                    reason=f"Package '{pid}' is already in robot inventory.",
                    conflicting_precondition="package_not_in_inventory",
                )

            pkg_info = next((p for p in avail_pkgs if p["id"] == pid), None)
            if pkg_info:
                expected_loc = pkg_info.get("pickup_location", "Lobby")
                if robot_loc != expected_loc:
                    return ValidationResult(
                        status=ValidationStatus.FAIL,
                        reason=f"Cannot pickup '{pid}' from '{robot_loc}'. Package is at '{expected_loc}'. Must navigate to '{expected_loc}' first.",
                        conflicting_precondition=f"at_location({expected_loc})",
                        suggested_revision={"action": "navigate", "params": {"target_zone": expected_loc}},
                    )

        elif tool_name == "deliver":
            pid = params.get("package_id")
            recip = params.get("recipient")

            if pid not in inventory:
                return ValidationResult(
                    status=ValidationStatus.FAIL,
                    reason=f"Robot is not holding package '{pid}'. Current inventory: {inventory}.",
                    conflicting_precondition=f"holding_package({pid})",
                )

            pkg_info = next((p for p in avail_pkgs if p["id"] == pid), None)
            if pkg_info:
                target_room = pkg_info.get("target_room")
                if target_room and robot_loc != target_room:
                    return ValidationResult(
                        status=ValidationStatus.FAIL,
                        reason=f"Cannot deliver '{pid}' in '{robot_loc}'. Target delivery room is '{target_room}'.",
                        conflicting_precondition=f"at_location({target_room})",
                        suggested_revision={"action": "navigate", "params": {"target_zone": target_room}},
                    )

        elif tool_name == "observe":
            target = params.get("target")
            known_doors = {
                "door_north": ("Lobby", "Corridor_North"),
                "door_south": ("Lobby", "Corridor_South"),
                "door_office_a": ("Corridor_North", "Office_A"),
                "door_office_b": ("Corridor_North", "Office_B"),
                "door_lab": ("Corridor_South", "Lab_Secure"),
            }
            if target in known_doors:
                connects = known_doors[target]
                if robot_loc not in connects:
                    return ValidationResult(
                        status=ValidationStatus.FAIL,
                        reason=f"Cannot observe door '{target}' from '{robot_loc}'. Robot must be in {connects}.",
                        conflicting_precondition=f"at_door_connector({target})",
                    )
            elif target in self.adjacency_map:
                if robot_loc != target:
                    return ValidationResult(
                        status=ValidationStatus.FAIL,
                        reason=f"Cannot observe room '{target}' from '{robot_loc}'. Robot must navigate to '{target}' first.",
                        conflicting_precondition=f"at_location({target})",
                        suggested_revision={"action": "navigate", "params": {"target_zone": target}},
                    )
            else:
                return ValidationResult(
                    status=ValidationStatus.FAIL,
                    reason=f"Invalid observation target '{target}'. Allowed targets are current room ('{robot_loc}') or adjacent doors.",
                    conflicting_precondition="valid_observation_target",
                )

        elif tool_name == "acquire_credential":
            cname = params.get("credential_name")
            if cname in credentials:
                return ValidationResult(
                    status=ValidationStatus.FAIL,
                    reason=f"Robot already possesses credential '{cname}'.",
                    conflicting_precondition=f"not_holding_credential({cname})",
                )
            # Check if this room has already been checked and confirmed empty of credentials
            if known_facts.get(f"room_checked_empty_{robot_loc}") or known_facts.get(f"credential_not_found_in_{robot_loc}"):
                return ValidationResult(
                    status=ValidationStatus.FAIL,
                    reason=f"Room '{robot_loc}' was already inspected and contains no credentials. Do not repeat acquire_credential here.",
                    conflicting_precondition=f"credential_present({cname}, {robot_loc})",
                )

        elif tool_name == "navigate":
            target_zone = params.get("target_zone")

            if target_zone == robot_loc:
                return ValidationResult(
                    status=ValidationStatus.FAIL,
                    reason=f"Robot is already at '{target_zone}'. Choose a different adjacent zone.",
                    conflicting_precondition=f"not_at_location({target_zone})",
                )

            allowed_neighbors = self.adjacency_map.get(robot_loc, [])
            if target_zone not in allowed_neighbors:
                return ValidationResult(
                    status=ValidationStatus.FAIL,
                    reason=f"No direct transit connection from '{robot_loc}' to '{target_zone}'. Allowed adjacent zones: {allowed_neighbors}.",
                    conflicting_precondition=f"is_adjacent({robot_loc}, {target_zone})",
                )

            # Check known door blockages
            door_blocked_key = f"door_{target_zone.lower()}_state"
            if known_facts.get(door_blocked_key) == "OCCUPIED":
                return ValidationResult(
                    status=ValidationStatus.FAIL,
                    reason=f"Door to '{target_zone}' is known to be blocked by an obstacle.",
                    conflicting_precondition=f"passage_free({target_zone})",
                )

        elif tool_name == "recharge":
            if robot_loc != self.charger_location:
                return ValidationResult(
                    status=ValidationStatus.FAIL,
                    reason=f"Charging station is at '{self.charger_location}', but robot is currently at '{robot_loc}'. Must navigate to charger first.",
                    conflicting_precondition=f"at_location({self.charger_location})",
                    suggested_revision={"action": "navigate", "params": {"target_zone": self.charger_location}},
                )

        return ValidationResult(
            status=ValidationStatus.PASS,
            reason="All known preconditions and schema requirements passed.",
        )
