"""
Pre-Execution Action Validator for FailMem Stage 2 Stateful Agent.
Enforces known preconditions, physical affordances, capacity limits, and schema correctness.
Returns PASS / FAIL / UNKNOWN.
Does NOT read hidden environment state or generate arbitrary optimal routes.
"""
from typing import Dict, Any, List, Optional, Tuple, Set
from dataclasses import dataclass, field
from enum import Enum
from .planner import TOOL_SCHEMAS, MAP_ADJACENCY
from .task_state import ObservedFact, ConstraintEvent


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
    is_schema_error: bool = False
    constraint_type: Optional[str] = None
    constraint_event: Optional[ConstraintEvent] = None
    missing_preconditions: List[str] = field(default_factory=list)

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
        active_plan_node: Optional[Any] = None,
    ) -> ValidationResult:
        # 1. Schema Check
        if tool_name not in TOOL_SCHEMAS:
            return ValidationResult(
                status=ValidationStatus.FAIL,
                reason=f"Unknown tool '{tool_name}'. Allowed tools: {list(TOOL_SCHEMAS.keys())}.",
                conflicting_precondition="tool_exists",
                is_schema_error=True,
                constraint_type="UNKNOWN_TOOL",
            )

        schema = TOOL_SCHEMAS[tool_name]
        for req in schema["required"]:
            if req not in params or params[req] is None or params[req] == "":
                return ValidationResult(
                    status=ValidationStatus.FAIL,
                    reason=f"Missing required parameter '{req}' for tool '{tool_name}'.",
                    conflicting_precondition=f"param_required({req})",
                    is_schema_error=True,
                    constraint_type="MISSING_PARAMETER",
                )

        robot_loc = current_state.get("robot_location", "Lobby")
        inventory = current_state.get("inventory", [])
        credentials = set(current_state.get("credentials", []))
        battery = current_state.get("battery", 100)
        max_cap = current_state.get("max_inventory_capacity", 2)
        avail_pkgs = current_state.get("available_packages", [])

        # 1.5 Active Plan Node Obligation Checks (Observation / Credential Search)
        if active_plan_node and getattr(active_plan_node, "action_type", "") == "observe":
            obs_target = getattr(active_plan_node, "target", "") or getattr(active_plan_node, "params", {}).get("target", "")
            if obs_target == robot_loc and tool_name != "observe":
                return ValidationResult(
                    status=ValidationStatus.FAIL,
                    reason=f"Active observation obligation in current room '{robot_loc}' must be completed before performing '{tool_name}'.",
                    conflicting_precondition=f"observed({robot_loc})",
                    suggested_revision={"action": "observe", "params": {"target": robot_loc}},
                )

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
                # Provide shortest hop suggestion
                from .plan_manager import find_path_bfs
                path_hops = find_path_bfs(robot_loc, target_zone, self.adjacency_map)
                suggested_hop = path_hops[0] if path_hops else (allowed_neighbors[0] if allowed_neighbors else None)
                sug = {"action": "navigate", "params": {"target_zone": suggested_hop}} if suggested_hop else None
                return ValidationResult(
                    status=ValidationStatus.FAIL,
                    reason=f"No direct transit connection from '{robot_loc}' to '{target_zone}'. Allowed adjacent zones: {allowed_neighbors}.",
                    conflicting_precondition=f"is_adjacent({robot_loc}, {target_zone})",
                    suggested_revision=sug,
                )

            # Check known door credential requirements
            known_door_creds = {
                "Lab_Secure": ("door_lab", "security_badge"),
            }
            if target_zone in known_door_creds:
                door_name, required_cred = known_door_creds[target_zone]
                req_fact = known_facts.get(f"requires_credential({door_name},{required_cred})")
                req_val = req_fact.value if isinstance(req_fact, ObservedFact) else req_fact
                if req_val is True and required_cred not in credentials:
                    ev_refs = [req_fact.evidence_ref] if isinstance(req_fact, ObservedFact) and req_fact.evidence_ref else []
                    c_event = ConstraintEvent(
                        origin="pre_execution",
                        constraint_type="SECURITY_BADGE_REQUIRED",
                        proposed_action={"tool": tool_name, "params": params},
                        affected_goal_id=getattr(active_plan_node, "id", None),
                        evidence_refs=ev_refs,
                        missing_preconditions=[f"has_credential({required_cred})"],
                        current_state_version=current_state.get("step_counter", 0),
                        target_door=door_name,
                        required_credential=required_cred,
                        reason=f"Door '{door_name}' to '{target_zone}' requires credential '{required_cred}' which robot does not possess.",
                    )
                    return ValidationResult(
                        status=ValidationStatus.FAIL,
                        reason=f"Door '{door_name}' to '{target_zone}' requires credential '{required_cred}' which robot does not possess.",
                        conflicting_precondition=f"has_credential({required_cred})",
                        is_schema_error=False,
                        constraint_type="SECURITY_BADGE_REQUIRED",
                        constraint_event=c_event,
                        missing_preconditions=[f"has_credential({required_cred})"],
                    )

            # Check known door blockages
            door_blocked_key = f"door_{target_zone.lower()}_state"
            door_fact = known_facts.get(door_blocked_key)
            door_val = door_fact.value if isinstance(door_fact, ObservedFact) else door_fact
            if door_val == "OCCUPIED":
                ev_refs = [door_fact.evidence_ref] if isinstance(door_fact, ObservedFact) and door_fact.evidence_ref else []
                c_event = ConstraintEvent(
                    origin="pre_execution",
                    constraint_type="DOORWAY_BLOCKED",
                    proposed_action={"tool": tool_name, "params": params},
                    affected_goal_id=getattr(active_plan_node, "id", None),
                    evidence_refs=ev_refs,
                    missing_preconditions=[f"passage_free({target_zone})"],
                    current_state_version=current_state.get("step_counter", 0),
                    blocked_edge=(robot_loc, target_zone),
                    reason=f"Door to '{target_zone}' is known to be blocked by an obstacle.",
                )
                return ValidationResult(
                    status=ValidationStatus.FAIL,
                    reason=f"Door to '{target_zone}' is known to be blocked by an obstacle.",
                    conflicting_precondition=f"passage_free({target_zone})",
                    is_schema_error=False,
                    constraint_type="DOORWAY_BLOCKED",
                    constraint_event=c_event,
                    missing_preconditions=[f"passage_free({target_zone})"],
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
