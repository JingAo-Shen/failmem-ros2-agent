"""
Five Standardized Memory Baseline Modules for FailMem Stage 2:
  - B0: No Cross-Task Memory
  - B1: Unstructured Natural Language Retrieval
  - B2: Static Condition-Aware Memory (No Invalidation)
  - B3: Unstructured Memory with TTL / Step-Decay
  - F:  Full Condition-Aware Memory with Perceptual Invalidation & Plan Repair
"""
from typing import Dict, Any, List, Optional
from .memory_store import (
    ConditionAwareMemoryStore,
    FailureMemoryItem,
    EpistemicLevel,
    MemoryStatus,
)


class BaseMemoryAdapter:
    """Standardized memory interface used by the Agent Planner."""
    def __init__(self, method_name: str):
        self.method_name = method_name

    def on_task_start(self, task_id: str, task_index: int):
        pass

    def record_action_failure(
        self,
        task_id: str,
        action_name: str,
        target: str,
        error_code: str,
        raw_message: str,
        observation: Dict[str, Any],
        sim_time: float,
    ):
        pass

    def record_observation(self, observation: Dict[str, Any], sim_time: float):
        pass

    def record_repair_success(self, failed_action: str, target: str, repair_action: Dict[str, Any]):
        pass

    def retrieve_relevant_memories(self, current_action_context: Dict[str, Any]) -> List[str]:
        """Returns formatted string prompts to be injected into the LLM context."""
        return []

    def get_stats(self) -> Dict[str, Any]:
        return {"method": self.method_name}


# =============================================================================
# B0: No Cross-Task Memory
# =============================================================================
class B0_NoMemory(BaseMemoryAdapter):
    """B0 maintains zero cross-task memory. Memory is cleared between tasks."""
    def __init__(self):
        super().__init__("B0_NoMemory")

    def on_task_start(self, task_id: str, task_index: int):
        pass

    def retrieve_relevant_memories(self, current_action_context: Dict[str, Any]) -> List[str]:
        return []


# =============================================================================
# B1: Unstructured Natural Language Memory Retrieval
# =============================================================================
class B1_UnstructuredNLMemory(BaseMemoryAdapter):
    """
    Stores free-text descriptions of failures.
    Retrieves top matches based on token/keyword overlap without checking conditions or invalidating.
    """
    def __init__(self):
        super().__init__("B1_UnstructuredNLMemory")
        self.text_records: List[Dict[str, Any]] = []

    def record_action_failure(
        self,
        task_id: str,
        action_name: str,
        target: str,
        error_code: str,
        raw_message: str,
        observation: Dict[str, Any],
        sim_time: float,
    ):
        entry = {
            "text": f"FAILED {action_name}({target}) with error '{error_code}': {raw_message}",
            "action": action_name,
            "target": target,
            "task_id": task_id,
        }
        self.text_records.append(entry)

    def retrieve_relevant_memories(self, current_action_context: Dict[str, Any]) -> List[str]:
        target = current_action_context.get("target_zone") or current_action_context.get("target") or ""
        results = []
        for r in self.text_records:
            # Semantic keyword overlap
            if target and target.lower() in r["text"].lower():
                results.append(f"[Past Experience] {r['text']}")
            elif r["action"] == current_action_context.get("action_name"):
                results.append(f"[Past Experience] {r['text']}")
        return results[:3]

    def get_stats(self) -> Dict[str, Any]:
        return {"method": self.method_name, "total_records": len(self.text_records)}


# =============================================================================
# B2: Static Condition-Aware Memory (No Invalidation / No Update)
# =============================================================================
class B2_StaticConditionalMemory(BaseMemoryAdapter):
    """
    Stores condition-aware structured failure records.
    Filters by conditions at retrieval time, but NEVER updates or invalidates entries.
    """
    def __init__(self):
        super().__init__("B2_StaticConditionalMemory")
        self.store = ConditionAwareMemoryStore()

    def record_action_failure(
        self,
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
            task_id=task_id,
            action_name=action_name,
            target=target,
            error_code=error_code,
            observable_conditions=conditions,
            raw_message=raw_message,
            epistemic_level=EpistemicLevel.FACT,
            sim_time=sim_time,
        )

    def record_observation(self, observation: Dict[str, Any], sim_time: float):
        # B2 explicitly IGNORES new observations and never invalidates!
        pass

    def retrieve_relevant_memories(self, current_action_context: Dict[str, Any]) -> List[str]:
        target = current_action_context.get("target_zone") or current_action_context.get("target") or ""
        active = self.store.get_active_memories(current_action_context)
        res = []
        for m in active:
            if not target or m.target == target or target in m.observable_conditions:
                res.append(m.format_for_prompt())
        return res[:3]

    def get_stats(self) -> Dict[str, Any]:
        return {"method": self.method_name, "total_memories": len(self.store.get_all_memories())}


# =============================================================================
# B3: Decay / Time-To-Live Memory
# =============================================================================
class B3_DecayMemory(BaseMemoryAdapter):
    """
    Unstructured memory that automatically expires after a fixed TTL (calibrated to 1 episode/task).
    """
    def __init__(self, ttl_tasks: int = 1):
        super().__init__("B3_DecayMemory")
        self.ttl_tasks = ttl_tasks
        self.current_task_index: int = 0
        self.records: List[Dict[str, Any]] = []

    def on_task_start(self, task_id: str, task_index: int):
        self.current_task_index = task_index

    def record_action_failure(
        self,
        task_id: str,
        action_name: str,
        target: str,
        error_code: str,
        raw_message: str,
        observation: Dict[str, Any],
        sim_time: float,
    ):
        self.records.append({
            "text": f"FAILED {action_name}({target}) with error '{error_code}': {raw_message}",
            "action": action_name,
            "target": target,
            "created_task_index": self.current_task_index,
        })

    def retrieve_relevant_memories(self, current_action_context: Dict[str, Any]) -> List[str]:
        target = current_action_context.get("target_zone") or current_action_context.get("target") or ""
        results = []
        for r in self.records:
            # Check TTL
            age_in_tasks = self.current_task_index - r["created_task_index"]
            if age_in_tasks <= self.ttl_tasks:
                if target and target.lower() in r["text"].lower():
                    results.append(f"[Recent Memory (Age: {age_in_tasks} task)] {r['text']}")
                elif r["action"] == current_action_context.get("action_name"):
                    results.append(f"[Recent Memory (Age: {age_in_tasks} task)] {r['text']}")
        return results[:3]

    def get_stats(self) -> Dict[str, Any]:
        return {"method": self.method_name, "total_records": len(self.records), "ttl_tasks": self.ttl_tasks}


# =============================================================================
# F: Full Condition-Aware Memory with Perceptual Invalidation & Plan Repair
# =============================================================================
class F_ConditionAwareMemory(BaseMemoryAdapter):
    """
    Full FailMem implementation:
      - Epistemic tagging (FACT vs CONJECTURE)
      - Dynamic invalidation on verified sensor/tool observations
      - Tracks verified repair actions and injects repair guidance
    """
    def __init__(self):
        super().__init__("F_ConditionAwareMemory")
        self.store = ConditionAwareMemoryStore()
        self.invalidation_log: List[Dict[str, Any]] = []

    def record_action_failure(
        self,
        task_id: str,
        action_name: str,
        target: str,
        error_code: str,
        raw_message: str,
        observation: Dict[str, Any],
        sim_time: float,
    ):
        conditions = {}
        suggested_repair = None

        if "passage_state" in observation:
            door = observation.get("door", target)
            conditions[f"{door}_state"] = observation["passage_state"]
            # Suggest detour if door north is blocked
            if door == "door_north":
                suggested_repair = {"action": "navigate", "target_zone": "Corridor_South", "note": "Use southern corridor detour"}

        if "access_status" in observation:
            conditions["required_credential"] = observation.get("required_credential", "security_badge")
            suggested_repair = {"action": "navigate", "target_zone": "Office_A", "note": "Acquire security_badge from Office_A first"}

        if "recipient_status" in observation:
            rec = observation.get("recipient", target)
            conditions[f"{rec}_status"] = observation["recipient_status"]
            suggested_repair = {"action": "query_status", "entity": rec, "note": "Check recipient calendar before re-attempting"}

        self.store.record_failure(
            task_id=task_id,
            action_name=action_name,
            target=target,
            error_code=error_code,
            observable_conditions=conditions,
            raw_message=raw_message,
            epistemic_level=EpistemicLevel.FACT,
            sim_time=sim_time,
            suggested_repair=suggested_repair,
            evidence_ref=f"obs_{int(sim_time*10)}",
        )

    def record_observation(self, observation: Dict[str, Any], sim_time: float):
        invalidated_ids = self.store.update_with_observation(observation, sim_time)
        if invalidated_ids:
            self.invalidation_log.append({
                "sim_time": sim_time,
                "invalidated_memories": invalidated_ids,
                "trigger_observation": observation,
            })

    def record_repair_success(self, failed_action: str, target: str, repair_action: Dict[str, Any]):
        self.store.mark_repair_success(failed_action, target, repair_action)

    def retrieve_relevant_memories(self, current_action_context: Dict[str, Any]) -> List[str]:
        target = current_action_context.get("target_zone") or current_action_context.get("target") or ""
        active = self.store.get_active_memories(current_action_context)
        res = []
        for m in active:
            if not target or m.target == target or target in m.observable_conditions:
                res.append(m.format_for_prompt())
        return res[:3]

    def get_stats(self) -> Dict[str, Any]:
        return {
            "method": self.method_name,
            "total_memories": len(self.store.get_all_memories()),
            "invalidations_count": len(self.invalidation_log),
        }
