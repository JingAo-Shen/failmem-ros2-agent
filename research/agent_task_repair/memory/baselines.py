"""
Standardized Memory Baseline Modules for FailMem Stage 2:
  - B0: No Cross-Task Memory
  - B1: Unstructured Natural Language Retrieval
  - B2: Static Condition-Aware Memory (No Invalidation)
  - B3: Unstructured Memory with TTL / Step-Decay
  - F:  Full Condition-Aware Memory with Perceptual Invalidation
"""
from typing import Dict, Any, List, Optional, Tuple
from .memory_store import (
    ConditionAwareMemoryStore,
    FailureMemoryItem,
    EpistemicLevel,
    MemoryStatus,
    ConditionMatchResult,
)


class BaseMemoryAdapter:
    """Standardized memory interface used by the Agent Planner."""
    def __init__(self, method_name: str):
        self.method_name = method_name
        self.current_task_index: int = 0
        self.current_task_id: str = ""

    def on_task_start(self, task_id: str, task_index: int):
        self.current_task_id = task_id
        self.current_task_index = task_index

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
        pass

    def record_observation(self, event_id: str, observation: Dict[str, Any], sim_time: float):
        pass

    def record_repair_success(
        self,
        failed_event_id: str,
        repair_event_id: str,
        repair_action: Dict[str, Any],
    ):
        pass

    def retrieve_relevant_memories(
        self,
        known_state: Dict[str, Any],
        context_query: Dict[str, Any],
    ) -> List[str]:
        """Returns formatted string prompts to be injected into the LLM context."""
        return []

    def get_stats(self) -> Dict[str, Any]:
        return {"method": self.method_name}


# =============================================================================
# B0: No Cross-Task Memory
# =============================================================================
class B0_NoMemory(BaseMemoryAdapter):
    """B0 maintains zero cross-task memory."""
    def __init__(self):
        super().__init__("B0_NoMemory")

    def retrieve_relevant_memories(
        self,
        known_state: Dict[str, Any],
        context_query: Dict[str, Any],
    ) -> List[str]:
        return []


# =============================================================================
# B1: Unstructured Natural Language Memory Retrieval
# =============================================================================
class B1_UnstructuredNLMemory(BaseMemoryAdapter):
    """
    Stores free-text descriptions of failures.
    Retrieves matches based on keyword/entity overlap without condition checking or invalidation.
    """
    def __init__(self):
        super().__init__("B1_UnstructuredNLMemory")
        self.text_records: List[Dict[str, Any]] = []

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
        entry = {
            "event_id": event_id,
            "task_id": task_id,
            "action": action_name,
            "target": target,
            "error_code": error_code,
            "message": raw_message,
            "text": f"[{event_id}] FAILED {action_name}({target}) with error '{error_code}': {raw_message}",
        }
        self.text_records.append(entry)

    def retrieve_relevant_memories(
        self,
        known_state: Dict[str, Any],
        context_query: Dict[str, Any],
    ) -> List[str]:
        query_targets = set()
        for v in context_query.values():
            if isinstance(v, str) and v:
                query_targets.add(v.lower())
            elif isinstance(v, list):
                for item in v:
                    if isinstance(item, str) and item:
                        query_targets.add(item.lower())

        results = []
        for r in self.text_records:
            # Check if any query term appears in text record
            matched = False
            for term in query_targets:
                if term in r["text"].lower():
                    matched = True
                    break
            if matched or not query_targets:
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
    Filters by conditions at retrieval time using 3-valued matching, but NEVER updates or invalidates entries.
    """
    def __init__(self):
        super().__init__("B2_StaticConditionalMemory")
        self.store = ConditionAwareMemoryStore()

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
        )

    def record_observation(self, event_id: str, observation: Dict[str, Any], sim_time: float):
        # B2 explicitly IGNORES new observations and never invalidates!
        pass

    def retrieve_relevant_memories(
        self,
        known_state: Dict[str, Any],
        context_query: Dict[str, Any],
    ) -> List[str]:
        candidate_entities = context_query.get("candidate_entities") or []
        target = context_query.get("target_zone") or context_query.get("target") or None
        matches = self.store.retrieve_memories(known_state, candidate_entities=candidate_entities, query_target=target)
        return [item.format_for_prompt(match_res) for item, match_res in matches[:3]]

    def get_stats(self) -> Dict[str, Any]:
        return {"method": self.method_name, "total_memories": len(self.store.get_all_memories())}


# =============================================================================
# B3: Decay / Time-To-Live Memory
# =============================================================================
class B3_DecayMemory(BaseMemoryAdapter):
    """
    Unstructured memory that automatically expires after a fixed TTL (calibrated to 1 task).
    Records created in Task T expire when current_task_index > T + ttl_tasks.
    """
    def __init__(self, ttl_tasks: int = 1):
        super().__init__("B3_DecayMemory")
        self.ttl_tasks = ttl_tasks
        self.records: List[Dict[str, Any]] = []

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
        self.records.append({
            "event_id": event_id,
            "task_id": task_id,
            "action": action_name,
            "target": target,
            "error_code": error_code,
            "message": raw_message,
            "created_task_index": self.current_task_index,
            "text": f"[{event_id}] FAILED {action_name}({target}) with error '{error_code}': {raw_message}",
        })

    def retrieve_relevant_memories(
        self,
        known_state: Dict[str, Any],
        context_query: Dict[str, Any],
    ) -> List[str]:
        query_targets = set()
        for v in context_query.values():
            if isinstance(v, str) and v:
                query_targets.add(v.lower())
            elif isinstance(v, list):
                for item in v:
                    if isinstance(item, str) and item:
                        query_targets.add(item.lower())

        results = []
        for r in self.records:
            age_in_tasks = self.current_task_index - r["created_task_index"]
            # Check TTL: active only while age <= ttl_tasks
            if age_in_tasks <= self.ttl_tasks:
                matched = False
                for term in query_targets:
                    if term in r["text"].lower():
                        matched = True
                        break
                if matched or not query_targets:
                    results.append(f"[Active Memory (Age: {age_in_tasks} tasks)] {r['text']}")

        return results[:3]

    def get_stats(self) -> Dict[str, Any]:
        return {
            "method": self.method_name,
            "total_records": len(self.records),
            "ttl_tasks": self.ttl_tasks,
        }


# =============================================================================
# F: Full Condition-Aware Memory with Perceptual Invalidation
# =============================================================================
class F_ConditionAwareMemory(BaseMemoryAdapter):
    """
    Full Condition-Aware Memory:
      - Epistemic tagging (FACT vs CONJECTURE)
      - 3-valued condition matching
      - Observation-driven active invalidation
      - Traceable event linking
    """
    def __init__(self):
        super().__init__("F_ConditionAwareMemory")
        self.store = ConditionAwareMemoryStore()
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
        candidate_entities = context_query.get("candidate_entities") or []
        target = context_query.get("target_zone") or context_query.get("target") or None
        matches = self.store.retrieve_memories(known_state, candidate_entities=candidate_entities, query_target=target)
        return [item.format_for_prompt(match_res) for item, match_res in matches[:3]]

    def get_stats(self) -> Dict[str, Any]:
        return {
            "method": self.method_name,
            "total_memories": len(self.store.get_all_memories()),
            "invalidations_count": len(self.invalidation_log),
        }
