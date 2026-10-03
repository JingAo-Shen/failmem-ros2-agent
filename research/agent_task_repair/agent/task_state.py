"""
Task State Tracker for FailMem Stage 2 Stateful Agent Architecture.
Maintains:
  - Explicit task delivery obligations and their lifecycle (PENDING, ACTIVE, BLOCKED, DONE).
  - Physical state: robot location, battery, inventory, credentials, capacity.
  - Epistemic facts and evidence sources (evidence_refs).
  - Strict tool-evidence confirmation for completion.
"""
from typing import Dict, Any, List, Optional, Set, Tuple
from dataclasses import dataclass, field
import copy
from enum import Enum


class ObligationStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"
    DONE = "DONE"


@dataclass
class TaskObligation:
    id: str
    package_id: str
    pickup_location: str
    target_room: str
    recipient: str
    status: ObligationStatus = ObligationStatus.PENDING
    evidence_refs: List[str] = field(default_factory=list)
    completion_event: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "package_id": self.package_id,
            "pickup_location": self.pickup_location,
            "target_room": self.target_room,
            "recipient": self.recipient,
            "status": self.status.value,
            "evidence_refs": list(self.evidence_refs),
            "is_done": self.status == ObligationStatus.DONE,
        }


@dataclass
class ObservedFact:
    key: str
    value: Any
    evidence_ref: str
    sim_time: float
    source_tool: str
    epistemic_level: str = "FACT"  # FACT or CONJECTURE

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "value": self.value,
            "evidence_ref": self.evidence_ref,
            "sim_time": self.sim_time,
            "source_tool": self.source_tool,
            "epistemic_level": self.epistemic_level,
        }


class TaskStateTracker:
    def __init__(
        self,
        task_instruction: str,
        initial_state: Dict[str, Any],
        max_inventory_capacity: int = 2,
        charger_location: str = "Lobby",
    ):
        self.task_instruction = task_instruction
        self.robot_location: str = initial_state.get("robot_location", "Lobby")
        self.battery: int = int(initial_state.get("battery", 100))
        self.inventory: List[str] = list(initial_state.get("inventory", []))
        self.credentials: Set[str] = set(initial_state.get("credentials", []))
        self.max_inventory_capacity: int = int(initial_state.get("max_inventory_capacity", max_inventory_capacity))
        self.charger_location: str = charger_location

        # Parse obligations from initial public state
        self.obligations: Dict[str, TaskObligation] = {}
        avail_pkgs = initial_state.get("available_packages", [])
        for p in avail_pkgs:
            pid = p["id"]
            self.obligations[pid] = TaskObligation(
                id=f"ob_{pid}",
                package_id=pid,
                pickup_location=p.get("pickup_location", "Lobby"),
                target_room=p.get("target_room", ""),
                recipient=p.get("recipient", ""),
                status=ObligationStatus.PENDING,
            )

        # Observed facts store: key -> ObservedFact
        self.observed_facts: Dict[str, ObservedFact] = {}
        self.step_counter: int = 0
        self.constraint_violations: List[str] = []

    def update_from_tool_result(
        self,
        tool_name: str,
        params: Dict[str, Any],
        result: Dict[str, Any],
        event_id: str,
        sim_time: float,
    ):
        """Updates internal physical and epistemic state from authentic tool execution result."""
        self.step_counter += 1
        success = result.get("success", False)
        obs = result.get("observation", {})
        status = result.get("status", "")

        # 1. Update physical state
        if success:
            if tool_name == "navigate":
                target_zone = params.get("target_zone")
                if target_zone:
                    self.robot_location = target_zone
                    if "door" in obs and "passage_state" in obs:
                        k = f"{obs['door']}_state"
                        self.observed_facts[k] = ObservedFact(
                            key=k, value=obs["passage_state"], evidence_ref=event_id, sim_time=sim_time, source_tool=tool_name
                        )

            elif tool_name == "pickup":
                pid = params.get("package_id")
                if pid and pid not in self.inventory:
                    self.inventory.append(pid)
                    if pid in self.obligations:
                        self.obligations[pid].status = ObligationStatus.ACTIVE
                        self.obligations[pid].evidence_refs.append(event_id)

            elif tool_name == "deliver":
                pid = params.get("package_id")
                recip = params.get("recipient")
                if pid and pid in self.inventory:
                    self.inventory.remove(pid)
                if pid in self.obligations:
                    self.obligations[pid].status = ObligationStatus.DONE
                    self.obligations[pid].evidence_refs.append(event_id)
                    self.obligations[pid].completion_event = {"tool": "deliver", "params": params, "event_id": event_id}

            elif tool_name == "acquire_credential":
                cname = params.get("credential_name")
                if cname:
                    self.credentials.add(cname)
                    self.observed_facts[f"credential_{cname}"] = ObservedFact(
                        key=f"credential_{cname}", value="ACQUIRED", evidence_ref=event_id, sim_time=sim_time, source_tool=tool_name
                    )

            elif tool_name == "recharge":
                self.battery = 100
                self.observed_facts["battery_state"] = ObservedFact(
                    key="battery_state", value=100, evidence_ref=event_id, sim_time=sim_time, source_tool=tool_name
                )

        else:
            # Failure event logging
            if tool_name == "navigate" and status == "DOOR_BLOCKED":
                door = obs.get("door", params.get("target_zone"))
                k = f"{door}_state"
                self.observed_facts[k] = ObservedFact(
                    key=k, value="OCCUPIED", evidence_ref=event_id, sim_time=sim_time, source_tool=tool_name
                )
            elif tool_name == "navigate" and status == "ACCESS_DENIED_NO_BADGE":
                door = obs.get("door", params.get("target_zone"))
                k = f"{door}_credential_required"
                self.observed_facts[k] = ObservedFact(
                    key=k, value=obs.get("required_credential", "security_badge"), evidence_ref=event_id, sim_time=sim_time, source_tool=tool_name
                )

        # Update sensor observations
        if obs:
            if "battery" in obs:
                self.battery = int(obs["battery"])
            if "door" in obs and "passage_state" in obs:
                k = f"{obs['door']}_state"
                self.observed_facts[k] = ObservedFact(
                    key=k, value=obs["passage_state"], evidence_ref=event_id, sim_time=sim_time, source_tool=tool_name
                )
            if "recipient_status" in obs:
                rec = obs.get("recipient", params.get("entity"))
                if rec:
                    k = f"{rec}_status"
                    self.observed_facts[k] = ObservedFact(
                        key=k, value=obs["recipient_status"], evidence_ref=event_id, sim_time=sim_time, source_tool=tool_name
                    )

    def is_all_completed(self) -> bool:
        """Verifies if all obligations are verified DONE with tool evidence."""
        if not self.obligations:
            return False
        return all(ob.status == ObligationStatus.DONE for ob in self.obligations.values())

    def get_public_state_summary(self) -> Dict[str, Any]:
        return {
            "robot_location": self.robot_location,
            "battery": self.battery,
            "inventory": list(self.inventory),
            "max_inventory_capacity": self.max_inventory_capacity,
            "credentials": list(self.credentials),
            "obligations": {pid: ob.to_dict() for pid, ob in self.obligations.items()},
            "pending_obligations_count": sum(1 for ob in self.obligations.values() if ob.status != ObligationStatus.DONE),
            "done_obligations_count": sum(1 for ob in self.obligations.values() if ob.status == ObligationStatus.DONE),
            "is_all_done": self.is_all_completed(),
            "known_facts": {k: (f.to_dict() if hasattr(f, "to_dict") else f) for k, f in self.observed_facts.items()},
        }
