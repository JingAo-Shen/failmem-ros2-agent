"""
Discrete-event multi-location robotic delivery task simulator for FailMem Stage 2.
Enforces hidden ground-truth state, structured tool responses, battery/time accounting,
and rigorous constraint violation detection.
"""
from typing import Dict, Any, List, Set, Optional, Tuple
import copy
from .tools import StatusCode, ActionResult


class DeliveryTaskEnv:
    def __init__(self, config: Dict[str, Any]):
        self.initial_config = copy.deepcopy(config)
        self.reset()

    def reset(self) -> Dict[str, Any]:
        cfg = copy.deepcopy(self.initial_config)
        
        # Robot State
        self.robot_location: str = cfg.get("robot_start_location", "Lobby")
        self.battery: int = int(cfg.get("robot_start_battery", 100))
        self.inventory: List[str] = list(cfg.get("robot_start_inventory", []))
        self.max_inventory_capacity: int = int(cfg.get("max_inventory_capacity", 2))
        self.credentials: Set[str] = set(cfg.get("robot_start_credentials", []))
        
        # Environment State (Ground Truth, Hidden from Agent)
        self.doors: Dict[str, Dict[str, Any]] = cfg.get("doors", {
            "door_north": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_North")},
            "door_south": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_South")},
            "door_office_a": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_A")},
            "door_office_b": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_B")},
            "door_lab": {"blocked": False, "requires_badge": True, "connects": ("Corridor_South", "Lab_Secure")},
        })
        
        # Topo Connections (Room -> Connected Rooms via doors)
        self.adj_graph: Dict[str, Dict[str, Dict[str, Any]]] = {
            "Lobby": {
                "Corridor_North": {"door": "door_north", "time": 8.0, "battery": 7},
                "Corridor_South": {"door": "door_south", "time": 14.0, "battery": 11},
            },
            "Corridor_North": {
                "Lobby": {"door": "door_north", "time": 8.0, "battery": 7},
                "Office_A": {"door": "door_office_a", "time": 6.0, "battery": 5},
                "Office_B": {"door": "door_office_b", "time": 6.0, "battery": 5},
                "Corridor_South": {"door": None, "time": 10.0, "battery": 8},
            },
            "Corridor_South": {
                "Lobby": {"door": "door_south", "time": 14.0, "battery": 11},
                "Corridor_North": {"door": None, "time": 10.0, "battery": 8},
                "Office_A": {"door": None, "time": 12.0, "battery": 9},
                "Lab_Secure": {"door": "door_lab", "time": 8.0, "battery": 6},
            },
            "Office_A": {
                "Corridor_North": {"door": "door_office_a", "time": 6.0, "battery": 5},
                "Corridor_South": {"door": None, "time": 12.0, "battery": 9},
            },
            "Office_B": {
                "Corridor_North": {"door": "door_office_b", "time": 6.0, "battery": 5},
            },
            "Lab_Secure": {
                "Corridor_South": {"door": "door_lab", "time": 8.0, "battery": 6},
            },
        }

        # Packages ground truth: id -> {location, target_room, recipient, delivered}
        self.packages: Dict[str, Dict[str, Any]] = copy.deepcopy(cfg.get("packages", {
            "pkg_docs": {"location": "Lobby", "target_room": "Office_A", "recipient": "Alice", "delivered": False},
            "pkg_hardware": {"location": "Lobby", "target_room": "Lab_Secure", "recipient": "Bob", "delivered": False},
        }))
        
        # Recipients ground truth: name -> {room, status, schedule}
        self.recipients: Dict[str, Dict[str, Any]] = copy.deepcopy(cfg.get("recipients", {
            "Alice": {"room": "Office_A", "status": "available"},
            "Bob": {"room": "Lab_Secure", "status": "available"},
            "Charlie": {"room": "Office_B", "status": "available"},
        }))

        # Available items in rooms (e.g. security badge in Office_A)
        self.room_items: Dict[str, Set[str]] = {
            room: set(items) for room, items in cfg.get("room_items", {"Office_A": ["security_badge"]}).items()
        }

        # Simulation metrics & accounting
        self.sim_time_s: float = 0.0
        self.cumulative_battery_consumed: int = 0
        self.time_limit_s: float = float(cfg.get("time_limit_s", 300.0))
        self.step_count: int = 0
        self.consecutive_failed_actions: int = 0
        self.last_failed_action_sig: Optional[str] = None
        self.history_log: List[Dict[str, Any]] = []
        self.constraint_violations: List[str] = []
        self.is_terminated: bool = False
        
        return self.get_agent_initial_state()

    def get_agent_initial_state(self) -> Dict[str, Any]:
        """Visible initial state provided to Agent."""
        return {
            "robot_location": self.robot_location,
            "battery": self.battery,
            "inventory": list(self.inventory),
            "credentials": list(self.credentials),
            "available_packages": [
                {"id": pid, "pickup_location": pdata["location"], "target_room": pdata["target_room"], "recipient": pdata["recipient"]}
                for pid, pdata in self.packages.items() if not pdata["delivered"]
            ],
            "known_zones": list(self.adj_graph.keys()),
        }

    def _consume_resources(self, time_cost: float, battery_cost: int):
        self.sim_time_s += time_cost
        self.battery = max(0, self.battery - battery_cost)
        self.cumulative_battery_consumed += battery_cost
        if self.battery == 0 and not any("BATTERY_DEPLETED" in v for v in self.constraint_violations):
            self.constraint_violations.append("BATTERY_DEPLETED: Robot ran out of battery during operation.")

    def step(self, tool_name: str, params: Dict[str, Any]) -> ActionResult:
        if self.is_terminated:
            return ActionResult(
                status=StatusCode.ACTION_TIMEOUT,
                success=False,
                message="Task has already terminated.",
                time_cost_s=0.0,
                battery_cost_pct=0,
            )

        if self.battery <= 0:
            self.is_terminated = True
            return ActionResult(
                status=StatusCode.BATTERY_DEPLETED,
                success=False,
                message="Robot battery depleted to 0%. Critical constraint violation.",
                time_cost_s=0.0,
                battery_cost_pct=0,
            )

        if self.sim_time_s >= self.time_limit_s:
            self.is_terminated = True
            return ActionResult(
                status=StatusCode.ACTION_TIMEOUT,
                success=False,
                message=f"Simulation time limit ({self.time_limit_s}s) exceeded.",
                time_cost_s=0.0,
                battery_cost_pct=0,
            )

        self.step_count += 1
        res: ActionResult

        if tool_name == "navigate":
            res = self._execute_navigate(params.get("target_zone"))
        elif tool_name == "observe":
            res = self._execute_observe(params.get("target"))
        elif tool_name == "query_status":
            res = self._execute_query_status(params.get("entity"))
        elif tool_name == "pickup":
            res = self._execute_pickup(params.get("package_id"), params.get("from_location"))
        elif tool_name == "deliver":
            res = self._execute_deliver(params.get("package_id"), params.get("recipient"))
        elif tool_name == "recharge":
            res = self._execute_recharge()
        elif tool_name == "acquire_credential":
            res = self._execute_acquire_credential(params.get("credential_name"))
        else:
            res = ActionResult(
                status=StatusCode.INVALID_PARAMETER,
                success=False,
                message=f"Unknown tool name: {tool_name}",
                time_cost_s=1.0,
                battery_cost_pct=1,
            )
            self._consume_resources(res.time_cost_s, res.battery_cost_pct)

        # Track consecutive failures for dead-loop detection
        act_sig = f"{tool_name}:{params}"
        if not res.success:
            if act_sig == self.last_failed_action_sig:
                self.consecutive_failed_actions += 1
            else:
                self.last_failed_action_sig = act_sig
                self.consecutive_failed_actions = 1
        else:
            self.consecutive_failed_actions = 0
            self.last_failed_action_sig = None

        # Check termination
        if self.is_all_delivered():
            self.is_terminated = True
        elif self.battery <= 0 or self.sim_time_s >= self.time_limit_s:
            self.is_terminated = True
        elif self.consecutive_failed_actions >= 3:
            self.constraint_violations.append(f"DEAD_LOOP_ABORT: Repeatedly executed failing action: {act_sig}")
            self.is_terminated = True

        # Log event
        self.history_log.append({
            "step": self.step_count,
            "tool": tool_name,
            "params": params,
            "result": res.to_dict(),
            "robot_location": self.robot_location,
            "battery": self.battery,
            "sim_time_s": self.sim_time_s,
        })

        return res

    def _execute_navigate(self, target_zone: Optional[str]) -> ActionResult:
        if not target_zone or target_zone not in self.adj_graph:
            self._consume_resources(1.0, 1)
            return ActionResult(
                status=StatusCode.INVALID_PARAMETER,
                success=False,
                message=f"Invalid target zone: {target_zone}",
                time_cost_s=1.0,
                battery_cost_pct=1,
            )

        if target_zone == self.robot_location:
            self._consume_resources(0.5, 0)
            return ActionResult(
                status=StatusCode.INVALID_PARAMETER,
                success=False,
                message=f"Robot is already at {target_zone}. Choose a different adjacent zone.",
                time_cost_s=0.5,
                battery_cost_pct=0,
            )

        if target_zone not in self.adj_graph[self.robot_location]:
            self._consume_resources(1.0, 1)
            return ActionResult(
                status=StatusCode.INVALID_PARAMETER,
                success=False,
                message=f"No direct transit path between {self.robot_location} and {target_zone}.",
                time_cost_s=1.0,
                battery_cost_pct=1,
            )

        edge = self.adj_graph[self.robot_location][target_zone]
        door_id = edge.get("door")

        # Check door conditions
        if door_id and door_id in self.doors:
            door_state = self.doors[door_id]
            if door_state.get("blocked", False):
                self._consume_resources(3.0, 2)
                return ActionResult(
                    status=StatusCode.DOOR_BLOCKED,
                    success=False,
                    message=f"Navigation failed: doorway {door_id} to {target_zone} is physically blocked by an obstacle.",
                    observation={"door": door_id, "passage_state": "OCCUPIED", "blocked_target": target_zone},
                    time_cost_s=3.0,
                    battery_cost_pct=2,
                    error_code="DOORWAY_BLOCKED",
                )
            if door_state.get("requires_badge", False) and "security_badge" not in self.credentials:
                self._consume_resources(2.0, 1)
                return ActionResult(
                    status=StatusCode.ACCESS_DENIED_NO_BADGE,
                    success=False,
                    message=f"Navigation failed: {door_id} to {target_zone} requires security_badge credential.",
                    observation={"door": door_id, "access_status": "LOCKED_REQUIRES_BADGE", "required_credential": "security_badge"},
                    time_cost_s=2.0,
                    battery_cost_pct=1,
                    error_code="SECURITY_BADGE_REQUIRED",
                )

        # Successful transit
        time_cost = edge["time"]
        battery_cost = edge["battery"]
        self._consume_resources(time_cost, battery_cost)
        self.robot_location = target_zone
        obs = {"current_location": self.robot_location, "battery": self.battery}
        if door_id:
            obs["door"] = door_id
            obs["passage_state"] = "FREE"
        return ActionResult(
            status=StatusCode.SUCCESS,
            success=True,
            message=f"Successfully navigated to {target_zone}.",
            observation=obs,
            time_cost_s=time_cost,
            battery_cost_pct=battery_cost,
        )

    def _execute_observe(self, target: Optional[str]) -> ActionResult:
        """Active sensor observation of doors or rooms."""
        self._consume_resources(2.0, 1)
        if not target:
            return ActionResult(
                status=StatusCode.INVALID_PARAMETER,
                success=False,
                message="Target parameter required for observe (e.g., 'door_north', 'door_lab', 'Office_A').",
                time_cost_s=2.0,
                battery_cost_pct=1,
            )

        if target in self.doors:
            door = self.doors[target]
            # Robot must be at one of the connected rooms to observe door
            r1, r2 = door["connects"]
            if self.robot_location not in (r1, r2):
                return ActionResult(
                    status=StatusCode.WRONG_LOCATION,
                    success=False,
                    message=f"Cannot observe {target} from {self.robot_location}. Must be in {r1} or {r2}.",
                    time_cost_s=2.0,
                    battery_cost_pct=1,
                )
            obs = {
                "door": target,
                "passage_state": "OCCUPIED" if door.get("blocked", False) else "FREE",
                "requires_badge": door.get("requires_badge", False),
            }
            return ActionResult(
                status=StatusCode.SUCCESS,
                success=True,
                message=f"Observed {target}: passage_state={obs['passage_state']}, requires_badge={obs['requires_badge']}.",
                observation=obs,
                time_cost_s=2.0,
                battery_cost_pct=1,
            )

        if target in self.adj_graph:
            # Observe room contents
            if self.robot_location != target:
                return ActionResult(
                    status=StatusCode.WRONG_LOCATION,
                    success=False,
                    message=f"Cannot inspect {target} from {self.robot_location}. Must navigate to {target} first.",
                    time_cost_s=2.0,
                    battery_cost_pct=1,
                )
            items = list(self.room_items.get(target, []))
            present_recipients = [name for name, data in self.recipients.items() if data["room"] == target]
            return ActionResult(
                status=StatusCode.SUCCESS,
                success=True,
                message=f"Room {target} inspection: items={items}, present_people={present_recipients}.",
                observation={"room": target, "items": items, "present_people": present_recipients},
                time_cost_s=2.0,
                battery_cost_pct=1,
            )

        return ActionResult(
            status=StatusCode.INVALID_PARAMETER,
            success=False,
            message=f"Unknown observation target: {target}",
            time_cost_s=2.0,
            battery_cost_pct=1,
        )

    def _execute_query_status(self, entity: Optional[str]) -> ActionResult:
        """Query simulated directory/service for recipient or battery."""
        self._consume_resources(1.0, 1)
        if not entity:
            return ActionResult(
                status=StatusCode.INVALID_PARAMETER,
                success=False,
                message="Entity parameter required for query_status (e.g. 'Alice', 'Bob', 'battery').",
                time_cost_s=1.0,
                battery_cost_pct=1,
            )

        if entity == "battery":
            return ActionResult(
                status=StatusCode.SUCCESS,
                success=True,
                message=f"Current battery level: {self.battery}%. Location: {self.robot_location}.",
                observation={"battery": self.battery, "location": self.robot_location},
                time_cost_s=1.0,
                battery_cost_pct=1,
            )

        if entity in self.recipients:
            rec = self.recipients[entity]
            return ActionResult(
                status=StatusCode.SUCCESS,
                success=True,
                message=f"Directory status for {entity}: room={rec['room']}, status={rec['status']}.",
                observation={"recipient": entity, "room": rec["room"], "status": rec["status"]},
                time_cost_s=1.0,
                battery_cost_pct=1,
            )

        return ActionResult(
            status=StatusCode.INVALID_PARAMETER,
            success=False,
            message=f"Entity not found in directory: {entity}",
            time_cost_s=1.0,
            battery_cost_pct=1,
        )

    def _execute_pickup(self, package_id: Optional[str], from_location: Optional[str]) -> ActionResult:
        self._consume_resources(3.0, 2)
        if not package_id or package_id not in self.packages:
            return ActionResult(
                status=StatusCode.PACKAGE_NOT_FOUND,
                success=False,
                message=f"Package ID '{package_id}' not found.",
                time_cost_s=3.0,
                battery_cost_pct=2,
            )

        pkg = self.packages[package_id]
        if pkg["delivered"]:
            return ActionResult(
                status=StatusCode.INVALID_PARAMETER,
                success=False,
                message=f"Package '{package_id}' is already delivered.",
                time_cost_s=3.0,
                battery_cost_pct=2,
            )

        if package_id in self.inventory:
            return ActionResult(
                status=StatusCode.INVALID_PARAMETER,
                success=False,
                message=f"Robot is already carrying '{package_id}'.",
                time_cost_s=3.0,
                battery_cost_pct=2,
            )

        if len(self.inventory) >= self.max_inventory_capacity:
            return ActionResult(
                status=StatusCode.INVENTORY_FULL,
                success=False,
                message=f"Cannot pickup '{package_id}': Inventory is full (max {self.max_inventory_capacity} items).",
                time_cost_s=3.0,
                battery_cost_pct=2,
            )

        if self.robot_location != pkg["location"]:
            return ActionResult(
                status=StatusCode.WRONG_LOCATION,
                success=False,
                message=f"Cannot pickup '{package_id}' from {self.robot_location}. Package is at {pkg['location']}.",
                time_cost_s=3.0,
                battery_cost_pct=2,
            )

        self.inventory.append(package_id)
        pkg["location"] = "robot_inventory"
        return ActionResult(
            status=StatusCode.SUCCESS,
            success=True,
            message=f"Picked up package '{package_id}'. Current inventory: {self.inventory}.",
            observation={"inventory": list(self.inventory), "picked_package": package_id},
            time_cost_s=3.0,
            battery_cost_pct=2,
        )

    def _execute_deliver(self, package_id: Optional[str], recipient: Optional[str]) -> ActionResult:
        self._consume_resources(4.0, 3)
        if not package_id or package_id not in self.inventory:
            return ActionResult(
                status=StatusCode.NOT_HOLDING_PACKAGE,
                success=False,
                message=f"Robot is not holding package '{package_id}'. Current inventory: {self.inventory}.",
                time_cost_s=4.0,
                battery_cost_pct=3,
            )

        pkg = self.packages[package_id]
        expected_recipient = pkg["recipient"]
        expected_room = pkg["target_room"]

        if self.robot_location != expected_room:
            return ActionResult(
                status=StatusCode.WRONG_LOCATION,
                success=False,
                message=f"Cannot deliver '{package_id}' in {self.robot_location}. Target delivery room is {expected_room}.",
                time_cost_s=4.0,
                battery_cost_pct=3,
            )

        if recipient != expected_recipient:
            self.constraint_violations.append(f"WRONG_RECIPIENT_DELIVERY: Handed {package_id} to {recipient} instead of {expected_recipient}.")
            return ActionResult(
                status=StatusCode.INVALID_PARAMETER,
                success=False,
                message=f"Delivery rejected: {recipient} is not the designated recipient for '{package_id}' (expected {expected_recipient}).",
                time_cost_s=4.0,
                battery_cost_pct=3,
            )

        rec_data = self.recipients.get(recipient, {})
        rec_status = rec_data.get("status", "available")
        if rec_status == "in_meeting":
            return ActionResult(
                status=StatusCode.RECIPIENT_BUSY,
                success=False,
                message=f"Delivery failed: Recipient {recipient} is currently in a closed meeting and cannot sign for {package_id}.",
                observation={"recipient": recipient, "recipient_status": "in_meeting", "room": self.robot_location},
                time_cost_s=4.0,
                battery_cost_pct=3,
                error_code="RECIPIENT_IN_MEETING",
            )
        elif rec_status == "away":
            return ActionResult(
                status=StatusCode.RECIPIENT_AWAY,
                success=False,
                message=f"Delivery failed: Recipient {recipient} is away from desk.",
                observation={"recipient": recipient, "recipient_status": "away", "room": self.robot_location},
                time_cost_s=4.0,
                battery_cost_pct=3,
                error_code="RECIPIENT_AWAY",
            )

        # Successful delivery
        self.inventory.remove(package_id)
        pkg["delivered"] = True
        pkg["location"] = f"delivered_to_{recipient}"
        return ActionResult(
            status=StatusCode.SUCCESS,
            success=True,
            message=f"Successfully delivered package '{package_id}' to {recipient} in {expected_room}.",
            observation={"delivered_package": package_id, "recipient": recipient, "remaining_inventory": list(self.inventory)},
            time_cost_s=4.0,
            battery_cost_pct=3,
        )

    def _execute_recharge(self) -> ActionResult:
        if self.robot_location != "Lobby":
            self._consume_resources(1.0, 1)
            return ActionResult(
                status=StatusCode.NOT_AT_CHARGER,
                success=False,
                message=f"Recharge failed: Charging station is located in 'Lobby', but robot is currently in '{self.robot_location}'.",
                time_cost_s=1.0,
                battery_cost_pct=1,
            )

        charge_needed = 100 - self.battery
        time_cost = float(charge_needed) * 0.3  # e.g. 50% charge = 15s
        self.sim_time_s += time_cost
        self.battery = 100
        return ActionResult(
            status=StatusCode.SUCCESS,
            success=True,
            message="Robot fully recharged to 100% battery at Lobby charging station.",
            observation={"battery": 100, "location": "Lobby"},
            time_cost_s=time_cost,
            battery_cost_pct=0,
        )

    def _execute_acquire_credential(self, credential_name: Optional[str]) -> ActionResult:
        self._consume_resources(2.0, 1)
        if not credential_name:
            return ActionResult(
                status=StatusCode.INVALID_PARAMETER,
                success=False,
                message="credential_name required (e.g. 'security_badge').",
                time_cost_s=2.0,
                battery_cost_pct=1,
            )

        room_items = self.room_items.get(self.robot_location, set())
        if credential_name not in room_items:
            return ActionResult(
                status=StatusCode.PACKAGE_NOT_FOUND,
                success=False,
                message=f"Credential '{credential_name}' is not available in {self.robot_location}.",
                time_cost_s=2.0,
                battery_cost_pct=1,
            )

        self.credentials.add(credential_name)
        return ActionResult(
            status=StatusCode.SUCCESS,
            success=True,
            message=f"Acquired credential '{credential_name}'. Current credentials: {list(self.credentials)}.",
            observation={"credentials": list(self.credentials)},
            time_cost_s=2.0,
            battery_cost_pct=1,
        )

    def is_all_delivered(self) -> bool:
        return all(p["delivered"] for p in self.packages.values())

    def get_summary(self) -> Dict[str, Any]:
        return {
            "success": self.is_all_delivered() and len(self.constraint_violations) == 0,
            "all_packages_delivered": self.is_all_delivered(),
            "delivered_count": sum(1 for p in self.packages.values() if p["delivered"]),
            "total_packages": len(self.packages),
            "final_battery": self.battery,
            "cumulative_battery_consumed": self.cumulative_battery_consumed,
            "final_sim_time_s": self.sim_time_s,
            "total_steps": self.step_count,
            "constraint_violations": list(self.constraint_violations),
            "terminated": self.is_terminated,
        }
