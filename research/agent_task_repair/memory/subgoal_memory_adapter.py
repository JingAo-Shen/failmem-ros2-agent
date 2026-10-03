"""
Subgoal-Aware Memory Adapter and Retrieval Scoper for FailMem Stage 2.
Supports 4 Injection Modes:
  - 'none' (Group A: No memory)
  - 'global' (Group B: Global memory injection)
  - 'phase_heuristic' (Group C: H, phase heuristic baseline)
  - 'explicit_subgoal' (Group D: G, explicit subgoal-scoped memory filter)

Eliminates hardcoded room names and capacity constants.
Maintains rigorous structured audit logs for every decision step.
"""
from typing import Dict, Any, List, Optional, Tuple, Set
from .baselines import BaseMemoryAdapter
from .memory_store import (
    ConditionAwareMemoryStore,
    FailureMemoryItem,
    EpistemicLevel,
    MemoryStatus,
    ConditionMatchResult,
)


class SubgoalMemoryAdapter(BaseMemoryAdapter):
    def __init__(
        self,
        injection_mode: str = "explicit_subgoal",  # 'none', 'global', 'phase_heuristic', 'explicit_subgoal'
        store_mode: str = "F",                      # 'F' (dynamic invalidation) or 'B2' (static without invalidation)
        adjacency_map: Optional[Dict[str, List[str]]] = None,
    ):
        name = f"{store_mode}_{injection_mode.upper()}"
        super().__init__(name)
        self.injection_mode = injection_mode.lower()
        # Aliases for convenience
        if self.injection_mode in ("g", "explicit_subgoal", "explicit_subgoal_scoped"):
            self.injection_mode = "explicit_subgoal"
        elif self.injection_mode in ("h", "subgoal", "heuristic", "phase_heuristic", "m2"):
            self.injection_mode = "phase_heuristic"
        elif self.injection_mode in ("m1", "global"):
            self.injection_mode = "global"
        elif self.injection_mode in ("m0", "none"):
            self.injection_mode = "none"

        self.store_mode = store_mode
        self.store = ConditionAwareMemoryStore()
        self.adjacency_map = adjacency_map or {}
        self.retrieval_audit_log: List[Dict[str, Any]] = []
        self.invalidation_log: List[Dict[str, Any]] = []

    def record_action_failure(
        self,
        event_id: str,
        task_id: str,
        action_name: str,
        target: str,
        error_code: str,
        raw_message: str,
        observation: Dict[str, Any],
        sim_time: float,
    ):
        conditions = {}
        if "passage_state" in observation:
            door = observation.get("door", target)
            conditions[f"{door}_state"] = observation["passage_state"]
        if "access_status" in observation:
            conditions["required_credential"] = observation.get("required_credential", "security_badge")
        if "recipient_status" in observation:
            rec = observation.get("recipient", target)
            conditions[f"{rec}_status"] = observation["recipient_status"]

        self.store.record_failure(
            event_id=event_id,
            task_id=task_id,
            action_name=action_name,
            target=target,
            error_code=error_code,
            observable_conditions=conditions,
            raw_message=raw_message,
            epistemic_level=EpistemicLevel.FACT,
            sim_time=sim_time,
            task_index=self.current_task_index,
            evidence_ref=f"obs_{int(sim_time*10)}",
        )

    def record_observation(self, event_id: str, observation: Dict[str, Any], sim_time: float):
        if self.store_mode == "B2":
            # B2 static baseline explicitly ignores new observations
            return

        invalidated_ids = self.store.update_with_observation(
            observation=observation,
            current_sim_time=sim_time,
            obs_event_id=event_id,
        )
        if invalidated_ids:
            self.invalidation_log.append({
                "sim_time": sim_time,
                "event_id": event_id,
                "invalidated_memories": invalidated_ids,
                "trigger_observation": observation,
            })

    def record_repair_success(
        self,
        failed_event_id: str,
        repair_event_id: str,
        repair_action: Dict[str, Any],
    ):
        self.store.mark_repair_success(failed_event_id, repair_event_id, repair_action)

    def retrieve_relevant_memories(
        self,
        known_state: Dict[str, Any],
        context_query: Dict[str, Any],
    ) -> List[str]:
        """
        Retrieves relevant failure memories according to the active injection mode.
        Logs comprehensive structured audit entry.
        """
        # 1. Mode A: No memory (M0)
        if self.injection_mode == "none":
            self.retrieval_audit_log.append({
                "step_index": context_query.get("step_index", 0),
                "injection_mode": "none",
                "injected_count": 0,
                "retrieved_memories": [],
                "reason": "M0: Cross-task memory disabled.",
            })
            return []

        all_memories = self.store.get_all_memories()
        evaluated_records = []
        injected_records = []
        excluded_records = []

        candidate_entities = context_query.get("candidate_entities") or []
        robot_loc = context_query.get("current_location", "Lobby")
        inventory = context_query.get("inventory", [])
        pickable_here = context_query.get("pickable_here") or []
        deliverable_here = context_query.get("deliverable_here") or []
        adjacent_zones = set(context_query.get("adjacent_zones", []))
        task_targets = set(context_query.get("task_targets", []))
        task_recipients = set(context_query.get("task_recipients", []))

        active_subgoal = context_query.get("active_subgoal")
        # Extract active subgoal fields if present
        sg_type = None
        sg_target = None
        sg_pkg = None
        sg_recip = None
        if active_subgoal:
            if isinstance(active_subgoal, dict):
                sg_type = active_subgoal.get("type")
                sg_target = active_subgoal.get("target")
                sg_pkg = active_subgoal.get("package_id")
                sg_recip = active_subgoal.get("recipient")
            elif hasattr(active_subgoal, "type"):
                sg_type = active_subgoal.type
                sg_target = active_subgoal.target
                sg_pkg = active_subgoal.package_id
                sg_recip = active_subgoal.recipient

        has_local_pickup = bool(pickable_here) and len(inventory) < context_query.get("max_inventory_capacity", 2)
        has_local_delivery = bool(deliverable_here)

        for item in all_memories:
            if item.status != MemoryStatus.ACTIVE:
                excluded_records.append({
                    "mem_id": item.mem_id,
                    "target": item.target,
                    "action": item.action_name,
                    "reason": f"Status is {item.status.value} (not ACTIVE).",
                })
                continue

            match_res = item.evaluate_applicability(known_state)
            evaluated_records.append({
                "mem_id": item.mem_id,
                "target": item.target,
                "action": item.action_name,
                "match_result": match_res.value,
                "conditions": item.observable_conditions,
            })

            if match_res == ConditionMatchResult.MISMATCH:
                excluded_records.append({
                    "mem_id": item.mem_id,
                    "target": item.target,
                    "action": item.action_name,
                    "reason": "Preconditions contradict current known state (MISMATCH).",
                })
                continue

            # -------------------------------------------------------------
            # Mode B: Global Memory Injection (M1)
            # -------------------------------------------------------------
            if self.injection_mode == "global":
                entity_terms = set(e.lower() for e in candidate_entities if isinstance(e, str))
                target_match = (
                    item.target.lower() in entity_terms
                    or any(t in item.target.lower() for t in entity_terms)
                    or any(any(t in k.lower() for t in entity_terms) for k in item.observable_conditions)
                )
                if target_match:
                    injected_records.append((item, match_res, "M1: Global entity match"))
                else:
                    excluded_records.append({
                        "mem_id": item.mem_id,
                        "target": item.target,
                        "action": item.action_name,
                        "reason": "M1: Target entity does not overlap with candidate entities.",
                    })

            # -------------------------------------------------------------
            # Mode C: Phase Heuristic Filtering (H / Baseline M2)
            # -------------------------------------------------------------
            elif self.injection_mode == "phase_heuristic":
                is_nav_memory = (item.action_name == "navigate" or "door" in item.target.lower())
                is_access_memory = ("badge" in item.target.lower() or "credential" in item.target.lower() or "required_credential" in item.observable_conditions)
                is_recipient_memory = (item.action_name == "deliver" or "recipient" in item.target.lower() or any("status" in k for k in item.observable_conditions))

                if has_local_pickup and not inventory and is_nav_memory:
                    excluded_records.append({
                        "mem_id": item.mem_id,
                        "target": item.target,
                        "action": item.action_name,
                        "reason": "H: Heuristic: Robot is at origin with pickable item; navigation memory excluded (scoped out to prevent pickup preemption).",
                    })
                elif is_nav_memory:
                    if item.target in adjacent_zones or any(item.target in z for z in adjacent_zones):
                        injected_records.append((item, match_res, "H: Relevant to adjacent candidate zones"))
                    else:
                        excluded_records.append({
                            "mem_id": item.mem_id,
                            "target": item.target,
                            "action": item.action_name,
                            "reason": f"H: Target '{item.target}' not in adjacent zones {adjacent_zones}.",
                        })
                elif is_access_memory:
                    if item.target in task_targets or any(item.target in t or t in item.target for t in task_targets):
                        injected_records.append((item, match_res, "H: Relevant to target room access"))
                    else:
                        excluded_records.append({
                            "mem_id": item.mem_id,
                            "target": item.target,
                            "action": item.action_name,
                            "reason": f"H: Protected room '{item.target}' not in task targets {task_targets}.",
                        })
                elif is_recipient_memory:
                    if item.target in task_recipients or any(item.target in r for r in task_recipients):
                        injected_records.append((item, match_res, "H: Relevant to target recipient status"))
                    else:
                        excluded_records.append({
                            "mem_id": item.mem_id,
                            "target": item.target,
                            "action": item.action_name,
                            "reason": f"H: Recipient '{item.target}' not in task recipients {task_recipients}.",
                        })
                else:
                    injected_records.append((item, match_res, "H: General action match"))

            # -------------------------------------------------------------
            # Mode D: Explicit Subgoal Scoping (G)
            # -------------------------------------------------------------
            elif self.injection_mode == "explicit_subgoal":
                is_nav_memory = (item.action_name == "navigate" or "door" in item.target.lower())
                is_access_memory = ("credential" in item.observable_conditions or "badge" in item.target.lower() or "required_credential" in item.observable_conditions)
                is_recipient_memory = (item.action_name == "deliver" or any("status" in k for k in item.observable_conditions))
                is_pickup_memory = (item.action_name == "pickup")

                # If no active subgoal derived, fall back to target matching
                if not sg_type:
                    injected_records.append((item, match_res, "G: Fallback match (no active subgoal)"))
                    continue

                if sg_type == "PICKUP":
                    # Subgoal is PICKUP: only memories concerning package pickup at this location are relevant
                    if is_pickup_memory and (item.target == sg_pkg or item.target == sg_target):
                        injected_records.append((item, match_res, f"G: Relevant to active pickup subgoal [{sg_pkg}]"))
                    else:
                        excluded_records.append({
                            "mem_id": item.mem_id,
                            "target": item.target,
                            "action": item.action_name,
                            "reason": f"G: Active subgoal is PICKUP({sg_pkg}); memory for {item.action_name}({item.target}) is excluded.",
                        })

                elif sg_type == "NAVIGATE":
                    # Subgoal is NAVIGATE to sg_target (or intermediate zone)
                    if is_nav_memory:
                        is_target_nav = False
                        if item.target == sg_target or (sg_target and item.target in sg_target) or (sg_target and sg_target in item.target):
                            is_target_nav = True
                        elif item.target in adjacent_zones:
                            if sg_target in adjacent_zones:
                                is_target_nav = (item.target == sg_target)
                            else:
                                # Multi-step destination (e.g. Office_B)
                                if self.adjacency_map and item.target in self.adjacency_map:
                                    neighbors = set(self.adjacency_map.get(item.target, []))
                                    if sg_target in neighbors or any(sg_target in self.adjacency_map.get(n, []) for n in neighbors):
                                        is_target_nav = True
                                    else:
                                        is_target_nav = False
                                else:
                                    is_target_nav = True

                        if is_target_nav:
                            injected_records.append((item, match_res, f"G: Relevant to active navigation subgoal -> {sg_target}"))
                        else:
                            excluded_records.append({
                                "mem_id": item.mem_id,
                                "target": item.target,
                                "action": item.action_name,
                                "reason": f"G: Navigation memory '{item.target}' is not along route/adjacent to active target '{sg_target}'.",
                            })

                    # Access/Credential requirements for entering sg_target (NOT masked by nav category!)
                    elif is_access_memory:
                        if item.target == sg_target or (sg_target and item.target in sg_target) or (sg_target and sg_target in item.target):
                            injected_records.append((item, match_res, f"G: Access credential requirement for active navigation target {sg_target}"))
                        else:
                            excluded_records.append({
                                "mem_id": item.mem_id,
                                "target": item.target,
                                "action": item.action_name,
                                "reason": f"G: Credential requirement for '{item.target}' not relevant to active navigation target '{sg_target}'.",
                            })
                    else:
                        excluded_records.append({
                            "mem_id": item.mem_id,
                            "target": item.target,
                            "action": item.action_name,
                            "reason": f"G: Active subgoal is NAVIGATE; memory {item.action_name}({item.target}) is irrelevant.",
                        })

                elif sg_type == "DELIVER":
                    # Subgoal is DELIVER package to recipient
                    if is_recipient_memory:
                        if (sg_recip and item.target == sg_recip) or (sg_pkg and item.target == sg_pkg):
                            injected_records.append((item, match_res, f"G: Recipient status memory for active delivery recipient {sg_recip}"))
                        else:
                            excluded_records.append({
                                "mem_id": item.mem_id,
                                "target": item.target,
                                "action": item.action_name,
                                "reason": f"G: Recipient memory '{item.target}' does not match active recipient '{sg_recip}'.",
                            })
                    else:
                        excluded_records.append({
                            "mem_id": item.mem_id,
                            "target": item.target,
                            "action": item.action_name,
                            "reason": f"G: Active subgoal is DELIVER; non-delivery memory {item.action_name}({item.target}) excluded.",
                        })

                elif sg_type == "RECHARGE":
                    # Subgoal is RECHARGE
                    if item.action_name == "recharge" or "charger" in item.target.lower():
                        injected_records.append((item, match_res, "G: Relevant to active recharge subgoal"))
                    else:
                        excluded_records.append({
                            "mem_id": item.mem_id,
                            "target": item.target,
                            "action": item.action_name,
                            "reason": f"G: Active subgoal is RECHARGE; memory {item.action_name}({item.target}) excluded.",
                        })

                elif sg_type == "ACQUIRE_CREDENTIAL":
                    if is_access_memory:
                        injected_records.append((item, match_res, "G: Relevant to active credential acquisition subgoal"))
                    else:
                        excluded_records.append({
                            "mem_id": item.mem_id,
                            "target": item.target,
                            "action": item.action_name,
                            "reason": f"G: Active subgoal is ACQUIRE_CREDENTIAL; memory {item.action_name}({item.target}) excluded.",
                        })

                else:
                    injected_records.append((item, match_res, "G: General action scope match"))

        formatted_prompts = [item.format_for_prompt(match_res) for item, match_res, _ in injected_records[:3]]

        # Record structured audit log entry
        self.retrieval_audit_log.append({
            "step_index": context_query.get("step_index", 0),
            "injection_mode": self.injection_mode,
            "current_location": robot_loc,
            "active_subgoal": active_subgoal.to_dict() if hasattr(active_subgoal, "to_dict") else (active_subgoal if isinstance(active_subgoal, dict) else str(active_subgoal)),
            "evaluated_records": evaluated_records,
            "injected_records": [{"mem_id": item.mem_id, "target": item.target, "reason": reason} for item, _, reason in injected_records],
            "excluded_records": excluded_records,
            "formatted_prompts": formatted_prompts,
        })

        return formatted_prompts

    def get_stats(self) -> Dict[str, Any]:
        return {
            "method": self.method_name,
            "injection_mode": self.injection_mode,
            "store_mode": self.store_mode,
            "total_memories": len(self.store.get_all_memories()),
            "total_retrieval_calls": len(self.retrieval_audit_log),
            "invalidations_count": len(self.invalidation_log),
        }
