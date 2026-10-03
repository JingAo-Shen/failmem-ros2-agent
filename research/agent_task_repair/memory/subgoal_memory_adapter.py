"""
Subgoal-Aware Memory Adapter and Retrieval Scoper for FailMem Stage 2.
Implements the 3 injection modes (M0: None, M1: Global, M2: Subgoal-Aware)
and records detailed traceable retrieval audits for every decision step.
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
    """
    Unified Memory Adapter supporting M0 (None), M1 (Global), and M2 (Subgoal-Aware) scoping.
    Can operate under either B2 (static conditions, no invalidation) or F (active dynamic invalidation) store rules.
    """
    def __init__(
        self,
        injection_mode: str = "subgoal",  # 'none' (M0), 'global' (M1), 'subgoal' (M2)
        store_mode: str = "F",            # 'F' (with active invalidation) or 'B2' (static without invalidation)
    ):
        name = f"{store_mode}_{injection_mode.upper()}"
        super().__init__(name)
        self.injection_mode = injection_mode.lower()
        self.store_mode = store_mode
        self.store = ConditionAwareMemoryStore()
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
        Retrieves relevant failure memories and records a comprehensive audit entry.
        """
        if self.injection_mode == "none":
            self.retrieval_audit_log.append({
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
        candidate_subgoals = context_query.get("candidate_subgoals") or []
        pickable_here = context_query.get("pickable_here") or []
        deliverable_here = context_query.get("deliverable_here") or []
        robot_loc = context_query.get("current_location", "Lobby")
        inventory = context_query.get("inventory", [])

        # Determine primary local task phase
        # If there are items pickable in the current room and inventory has space, pickup is available locally
        has_local_pickup = bool(pickable_here) and len(inventory) < 2
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

            # M1: Global Memory Injection Mode
            if self.injection_mode == "global":
                # Check entity overlap
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

            # M2: Subgoal-Aware Memory Injection Mode
            elif self.injection_mode == "subgoal":
                # Scoping logic:
                # 1. If agent is currently considering a pickup subgoal at the current room,
                #    navigation failure memories to other rooms do NOT block local pickup!
                # 2. Navigation failure memories are injected when considering navigation to adjacent zones.
                # 3. Delivery / credential memories are injected when considering delivery or access to protected rooms.
                
                is_nav_memory = (item.action_name == "navigate" or "door" in item.target.lower())
                is_access_memory = ("badge" in item.target.lower() or "required_credential" in item.observable_conditions)
                is_recipient_memory = (item.action_name == "deliver" or "recipient" in item.target.lower() or any("status" in k for k in item.observable_conditions))

                # Check if this memory is relevant to current active subgoal candidates:
                if has_local_pickup and not inventory and is_nav_memory:
                    # Robot is at origin with package, inventory empty -> immediate action is pickup.
                    # Exclude navigation obstacle memory to prevent preempting pickup!
                    excluded_records.append({
                        "mem_id": item.mem_id,
                        "target": item.target,
                        "action": item.action_name,
                        "reason": "M2: Robot is at origin with pickable item; navigation obstacle scoped out to prevent pickup preemption.",
                    })
                elif is_nav_memory:
                    # Navigation memory is relevant if target zone or connected door is in adjacent candidate zones
                    adjacent_zones = set(context_query.get("adjacent_zones", []))
                    if item.target in adjacent_zones or any(item.target in z for z in adjacent_zones):
                        injected_records.append((item, match_res, "M2: Relevant to candidate navigation transition"))
                    else:
                        excluded_records.append({
                            "mem_id": item.mem_id,
                            "target": item.target,
                            "action": item.action_name,
                            "reason": f"M2: Navigation target '{item.target}' is not in adjacent candidate zones {adjacent_zones}.",
                        })
                elif is_access_memory:
                    # Access memory relevant only if target room requiring credential is in candidate targets
                    task_targets = set(context_query.get("task_targets", []))
                    if item.target in task_targets or "Lab_Secure" in task_targets:
                        injected_records.append((item, match_res, "M2: Relevant to protected target room access"))
                    else:
                        excluded_records.append({
                            "mem_id": item.mem_id,
                            "target": item.target,
                            "action": item.action_name,
                            "reason": f"M2: Protected room '{item.target}' is not in current task targets {task_targets}.",
                        })
                elif is_recipient_memory:
                    # Recipient memory relevant only if recipient matches undelivered package recipients
                    task_recipients = set(context_query.get("task_recipients", []))
                    if item.target in task_recipients or any(item.target in r for r in task_recipients):
                        injected_records.append((item, match_res, "M2: Relevant to target recipient status"))
                    else:
                        excluded_records.append({
                            "mem_id": item.mem_id,
                            "target": item.target,
                            "action": item.action_name,
                            "reason": f"M2: Recipient '{item.target}' is not in active delivery recipients {task_recipients}.",
                        })
                else:
                    # Fallback general match
                    injected_records.append((item, match_res, "M2: General action scope match"))

        formatted_prompts = [item.format_for_prompt(match_res) for item, match_res, _ in injected_records[:3]]

        # Record structured audit log entry
        self.retrieval_audit_log.append({
            "step_index": context_query.get("step_index", 0),
            "injection_mode": self.injection_mode,
            "current_location": robot_loc,
            "has_local_pickup": has_local_pickup,
            "has_local_delivery": has_local_delivery,
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
