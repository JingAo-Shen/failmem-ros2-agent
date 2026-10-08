"""
Unified Agent Runner with Common Local Plan Executor, Constraint Lifecycle Tracking,
and D-gated Procedural Memory Execution Engine.

Supported Groups:
  1. Group_B2_step: Structured facts + single-step LLM planning.
  2. Group_B2_plan: Structured facts + multi-step LLM planning via CommonLocalPlanExecutor.
  3. Group_B1_plan: Full raw source trajectories + intervention facts + multi-step LLM planning.
  4. Group_Replay: Naive trajectory replay matching observed fault via CommonLocalPlanExecutor.
  5. Group_D_current: Structured facts + conditional procedural memory (Stage 3 baseline).
  6. Group_D_gated: Gated procedural memory (Check -> Defer -> State-Change Re-evaluate -> Execute).
  7. Group_D_gated_no_filter: Ablation 1 (no applicability filter).
  8. Group_D_gated_no_reeval: Ablation 2 (no deferred memory re-evaluation).

All groups share:
  - Unified action execution pipeline (Pop -> Precondition Validation -> env.step -> Known State Update -> Postcondition Verify)
  - CommonLocalPlanExecutor (max plan length = 4, chunked with cursor tracking)
  - ConstraintTracker with strict state-based lifecycle (no arbitrary clear on tool SUCCESS)
  - Stagnation & No-Progress detection with state-diff hash
  - Unified budget (32 LLM / 40 Tools / 1800s timeout)
"""
from typing import Dict, Any, List, Optional, Tuple, Set
import json
import time
import copy
import re
import hashlib
from dataclasses import dataclass, field, asdict

from .workstation_env import WorkstationEnv, StatusCode
from .procedural_memory import (
    ProceduralMemoryItem,
    ProceduralMemoryStore,
    StructuredFactStore,
    ActionNode,
)
from ..agent.llm_backend import LLMBackend


MAX_PLAN_LEN = 4

WORKSTATION_SYSTEM_PROMPT_STEP = """You are an autonomous robotic workstation diagnostic and recovery agent in a simulated environment.
The workstation consists of 5 subsystems:
  1. power_unit (Primary power & safety relay)
  2. pneumatic_line (Compressed air supply)
  3. arm_gripper (Robotic end-effector)
  4. camera_sensor (Vision inspection sensor)
  5. controller (Safety & sequence controller)

Available Tools:
  - inspect(subsystem="all"|"power_unit"|"pneumatic_line"|"arm_gripper"|"camera_sensor"|"controller"): Query diagnostic state.
  - isolate(subsystem="power_unit"|"pneumatic_line", action="engage"|"release"): Safety lockout (engage) or restore energy line (release). Energy lines MUST be isolated (engage) before clearing faults.
  - clear_fault(subsystem="power_unit"|"pneumatic_line"|"arm_gripper"|"camera_sensor"|"controller"): Clear active fault. For power_unit/pneumatic_line: requires isolate 'engage' first, then clear_fault, then isolate 'release'.
  - reset(subsystem="power_unit"|"pneumatic_line"|"arm_gripper"|"camera_sensor"|"controller"): Reset subsystem to operating/home state (e.g. power voltage to 24V, line pressure to 5.0 bar, arm to home). Note: reset does NOT clear tripped or faulted status; clear_fault is required for faults.
  - calibrate(subsystem="camera_sensor"|"arm_gripper"): Run precision calibration (requires nominal, unisolated power and no active faults).
  - self_test(target="workstation"): Run comprehensive safety self-test (all subsystems must be nominal and calibrated).
  - resume(target="workstation"): Resume normal production (requires successful self_test).

Response Format:
Respond with a JSON object strictly following this schema:
```json
{
  "thought": "Your step-by-step diagnostic reasoning...",
  "tool": "<tool_name>",
  "args": {<argument_key>: <argument_value>}
}
```
"""

WORKSTATION_SYSTEM_PROMPT_PLAN = """You are an autonomous robotic workstation diagnostic and recovery agent in a simulated environment.
The workstation consists of 5 subsystems:
  1. power_unit (Primary power & safety relay)
  2. pneumatic_line (Compressed air supply)
  3. arm_gripper (Robotic end-effector)
  4. camera_sensor (Vision inspection sensor)
  5. controller (Safety & sequence controller)

Available Tools:
  - inspect(subsystem="all"|"power_unit"|"pneumatic_line"|"arm_gripper"|"camera_sensor"|"controller"): Query diagnostic state.
  - isolate(subsystem="power_unit"|"pneumatic_line", action="engage"|"release"): Safety lockout (engage) or restore energy line (release). Energy lines MUST be isolated (engage) before clearing faults.
  - clear_fault(subsystem="power_unit"|"pneumatic_line"|"arm_gripper"|"camera_sensor"|"controller"): Clear active fault. For power_unit/pneumatic_line: requires isolate 'engage' first, then clear_fault, then isolate 'release'.
  - reset(subsystem="power_unit"|"pneumatic_line"|"arm_gripper"|"camera_sensor"|"controller"): Reset subsystem to operating/home state (e.g. power voltage to 24V, line pressure to 5.0 bar, arm to home). Note: reset does NOT clear tripped or faulted status; clear_fault is required for faults.
  - calibrate(subsystem="camera_sensor"|"arm_gripper"): Run precision calibration (requires nominal, unisolated power and no active faults).
  - self_test(target="workstation"): Run comprehensive safety self-test (all subsystems must be nominal and calibrated).
  - resume(target="workstation"): Resume normal production (requires successful self_test).

Response Format:
You can plan up to 4 local steps at once. Respond with a JSON object strictly following this schema:
```json
{
  "thought": "Your step-by-step diagnostic reasoning...",
  "plan": [
    {"tool": "<tool_name_1>", "args": {<arg_key>: <arg_val>}},
    {"tool": "<tool_name_2>", "args": {<arg_key>: <arg_val>}}
  ]
}
```
"""


@dataclass
class ActiveConstraint:
    constraint_id: str
    predicate: str
    subsystem: str
    required_condition: Dict[str, Any]  # e.g. {"field": "status", "expected": "nominal"}
    evidence_source: str                # e.g. "precondition_interlock", "tool_execution_error", "inspect_observation"
    status: str = "ACTIVE"             # "ACTIVE", "SATISFIED", "VIOLATED"
    created_step: int = 0
    cleared_step: Optional[int] = None

    def check_satisfaction(self, known_state: Dict[str, Any]) -> bool:
        sub_data = known_state.get(self.subsystem, {})
        if not isinstance(sub_data, dict):
            return False
        field_name = self.required_condition.get("field")
        expected = self.required_condition.get("expected")
        if field_name in sub_data and sub_data[field_name] == expected:
            # Check secondary condition if present
            if "secondary_field" in self.required_condition:
                sec_f = self.required_condition["secondary_field"]
                sec_exp = self.required_condition["secondary_expected"]
                if sub_data.get(sec_f) != sec_exp:
                    return False
            return True
        return False


class ConstraintTracker:
    """
    Tracks constraint lifecycle. Constraints are NEVER cleared by arbitrary tool SUCCESS.
    Only explicit observation confirming the required condition satisfies the constraint.
    """
    def __init__(self):
        self.constraints: Dict[str, ActiveConstraint] = {}
        self.history: List[Dict[str, Any]] = []

    def add_constraint(self, constraint: ActiveConstraint, step_index: int):
        if constraint.constraint_id not in self.constraints:
            self.constraints[constraint.constraint_id] = constraint
            self.history.append({
                "step": step_index,
                "event": "CONSTRAINT_ADDED",
                "constraint_id": constraint.constraint_id,
                "predicate": constraint.predicate,
                "evidence_source": constraint.evidence_source,
            })
        else:
            existing = self.constraints[constraint.constraint_id]
            if existing.status != "ACTIVE":
                existing.status = "ACTIVE"
                existing.cleared_step = None
                self.history.append({
                    "step": step_index,
                    "event": "CONSTRAINT_REACTIVATED",
                    "constraint_id": constraint.constraint_id,
                })

    def update_with_observation(self, known_state: Dict[str, Any], step_index: int):
        for c_id, c in list(self.constraints.items()):
            if c.status == "ACTIVE":
                if c.check_satisfaction(known_state):
                    c.status = "SATISFIED"
                    c.cleared_step = step_index
                    self.history.append({
                        "step": step_index,
                        "event": "CONSTRAINT_SATISFIED",
                        "constraint_id": c_id,
                        "predicate": c.predicate,
                    })

    def get_active_constraints(self) -> List[ActiveConstraint]:
        return [c for c in self.constraints.values() if c.status == "ACTIVE"]

    def to_prompt_str(self) -> str:
        active = self.get_active_constraints()
        if not active:
            return ""
        lines = ["=== Active Constraint & Interlock Feedback ==="]
        for c in active:
            lines.append(f"- [{c.constraint_id}] Requires: {c.predicate} (Evidence: {c.evidence_source}, Created at Step {c.created_step})")
        return "\n".join(lines)


@dataclass
class ConstraintEvent:
    event_type: str  # PRECONDITION_BLOCKED, TOOL_EXECUTION_ERROR, POSTCONDITION_MISMATCH, STAGNATION_LOOP, MEMORY_DEFERRED
    blocked_action: Dict[str, Any]
    unmet_conditions: List[str]
    condition_status: str  # FALSE, UNKNOWN
    cancellation_reason: str
    observed_evidence: Dict[str, Any] = field(default_factory=dict)
    tried_invalid_repairs: List[Dict[str, Any]] = field(default_factory=list)

    def to_prompt_str(self) -> str:
        lines = [f"[{self.event_type}]: Action {self.blocked_action.get('tool')}({self.blocked_action.get('args')}) blocked/failed."]
        if self.unmet_conditions:
            lines.append(f"  - Required: {'; '.join(self.unmet_conditions)}")
        if self.cancellation_reason:
            lines.append(f"  - Detail: {self.cancellation_reason}")
        return "\n".join(lines)


@dataclass
class DecisionEvent:
    relevant_state_hash: str
    action_signature: str
    unmet_predicates: Tuple[str, ...]
    result_category: str  # "PRECONDITION_BLOCKED", "TOOL_EXECUTION_ERROR", "NO_PROGRESS", "PROGRESS_SUCCESS", "POSTCONDITION_MISMATCH"
    reason: str = ""


@dataclass
class ActiveMemoryExecution:
    memory_id: str
    source_tag: str  # "procedural_memory" | "naive_replay"
    actions: List[Dict[str, Any]]
    cursor: int = 0
    total_actions: int = 0
    status: str = "RUNNING"  # "RUNNING", "COMPLETED", "DEFERRED", "INVALIDATED"

    def has_next_chunk(self) -> bool:
        return self.cursor < len(self.actions)

    def get_next_chunk(self, max_chunk_len: int = MAX_PLAN_LEN) -> List[Dict[str, Any]]:
        end = min(self.cursor + max_chunk_len, len(self.actions))
        chunk = self.actions[self.cursor:end]
        self.cursor = end
        return chunk

    def is_fully_executed(self) -> bool:
        return self.cursor >= len(self.actions)


class CommonLocalPlanExecutor:
    """
    Common Local Plan Execution & Verification Engine.
    Used uniformly across all groups (B2_step, B2_plan, B1_plan, Replay, D_current, D_gated).
    """
    MAX_QUEUE_LEN = MAX_PLAN_LEN

    def __init__(self, fact_store: Optional[StructuredFactStore] = None):
        self.fact_store = fact_store
        self.action_queue: List[Dict[str, Any]] = []

    def clear(self):
        self.action_queue.clear()

    def is_empty(self) -> bool:
        return len(self.action_queue) == 0

    def enqueue_plan(self, actions: List[Dict[str, Any]], source_tag: str = "llm_plan"):
        for a in actions[:self.MAX_QUEUE_LEN]:
            if not isinstance(a, dict) or "tool" not in a:
                continue
            self.action_queue.append({
                "tool": a.get("tool"),
                "args": copy.deepcopy(a.get("args", {})),
                "source_tag": source_tag,
                "expected_effects": copy.deepcopy(a.get("expected_effects", {})),
                "thought": a.get("thought", ""),
            })

    def pop(self) -> Optional[Dict[str, Any]]:
        if self.action_queue:
            return self.action_queue.pop(0)
        return None

    def validate_precondition(
        self,
        action: Dict[str, Any],
        known_state: Dict[str, Any],
        tried_repairs: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[bool, Optional[ConstraintEvent], Optional[ActiveConstraint]]:
        """
        Check public known state against verified domain preconditions.
        Returns (valid, constraint_event, active_constraint).
        Applies identically to all groups.
        """
        tool = action.get("tool")
        args = action.get("args", {})
        sub = args.get("subsystem")

        # Check 1: Clearing energy faults requires isolation
        if tool == "clear_fault" and sub == "pneumatic_line":
            iso = known_state.get("pneumatic_line", {}).get("isolated")
            if iso is False:
                evt = ConstraintEvent(
                    event_type="PRECONDITION_BLOCKED",
                    blocked_action={"tool": tool, "args": args},
                    unmet_conditions=["pneumatic_line.isolated == True"],
                    condition_status="FALSE",
                    cancellation_reason="pneumatic_line is not isolated; cannot clear fault while pressurized.",
                    observed_evidence=copy.deepcopy(known_state.get("pneumatic_line", {})),
                    tried_invalid_repairs=copy.deepcopy(tried_repairs or []),
                )
                cstr = ActiveConstraint(
                    constraint_id="pneumatic_line_isolation_required",
                    predicate="pneumatic_line.isolated == True",
                    subsystem="pneumatic_line",
                    required_condition={"field": "isolated", "expected": True},
                    evidence_source="precondition_interlock",
                )
                return False, evt, cstr
            elif iso is None:
                evt = ConstraintEvent(
                    event_type="PRECONDITION_BLOCKED",
                    blocked_action={"tool": tool, "args": args},
                    unmet_conditions=["pneumatic_line.isolated state is UNKNOWN"],
                    condition_status="UNKNOWN",
                    cancellation_reason="pneumatic_line isolation state is unknown; inspect workstation first.",
                    observed_evidence=copy.deepcopy(known_state),
                    tried_invalid_repairs=copy.deepcopy(tried_repairs or []),
                )
                return False, evt, None

        if tool == "clear_fault" and sub == "power_unit":
            iso = known_state.get("power_unit", {}).get("isolated")
            if iso is False:
                evt = ConstraintEvent(
                    event_type="PRECONDITION_BLOCKED",
                    blocked_action={"tool": tool, "args": args},
                    unmet_conditions=["power_unit.isolated == True"],
                    condition_status="FALSE",
                    cancellation_reason="power_unit is not isolated; cannot service live power relay.",
                    observed_evidence=copy.deepcopy(known_state.get("power_unit", {})),
                    tried_invalid_repairs=copy.deepcopy(tried_repairs or []),
                )
                cstr = ActiveConstraint(
                    constraint_id="power_unit_isolation_required",
                    predicate="power_unit.isolated == True",
                    subsystem="power_unit",
                    required_condition={"field": "isolated", "expected": True},
                    evidence_source="precondition_interlock",
                )
                return False, evt, cstr
            elif iso is None:
                evt = ConstraintEvent(
                    event_type="PRECONDITION_BLOCKED",
                    blocked_action={"tool": tool, "args": args},
                    unmet_conditions=["power_unit.isolated state is UNKNOWN"],
                    condition_status="UNKNOWN",
                    cancellation_reason="power_unit isolation state is unknown; inspect workstation first.",
                    observed_evidence=copy.deepcopy(known_state),
                    tried_invalid_repairs=copy.deepcopy(tried_repairs or []),
                )
                return False, evt, None

        # Check 2: Resetting arm gripper requires releasing load
        if tool == "reset" and sub == "arm_gripper":
            holding = known_state.get("arm_gripper", {}).get("holding_load")
            if holding is True:
                evt = ConstraintEvent(
                    event_type="PRECONDITION_BLOCKED",
                    blocked_action={"tool": tool, "args": args},
                    unmet_conditions=["arm_gripper.holding_load == False"],
                    condition_status="FALSE",
                    cancellation_reason="arm_gripper is holding unsecured load; clear fault / release load first.",
                    observed_evidence=copy.deepcopy(known_state.get("arm_gripper", {})),
                    tried_invalid_repairs=copy.deepcopy(tried_repairs or []),
                )
                cstr = ActiveConstraint(
                    constraint_id="arm_gripper_load_release_required",
                    predicate="arm_gripper.holding_load == False",
                    subsystem="arm_gripper",
                    required_condition={"field": "holding_load", "expected": False},
                    evidence_source="precondition_interlock",
                )
                return False, evt, cstr

        # Check 3: Calibration, Arm Reset, and Sensor/Controller Fault Clear requires active nominal power
        if (tool == "calibrate" and sub in ["camera_sensor", "arm_gripper"]) or (tool == "reset" and sub == "arm_gripper") or (tool == "clear_fault" and sub in ["camera_sensor", "controller"]):
            pw_stat = known_state.get("power_unit", {}).get("status")
            pw_iso = known_state.get("power_unit", {}).get("isolated")
            if pw_stat == "tripped" or pw_iso is True:
                evt = ConstraintEvent(
                    event_type="PRECONDITION_BLOCKED",
                    blocked_action={"tool": tool, "args": args},
                    unmet_conditions=["power_unit.status == nominal", "power_unit.isolated == False"],
                    condition_status="FALSE",
                    cancellation_reason=f"power_unit is unpowered or isolated; restore power before {tool}({sub}).",
                    observed_evidence=copy.deepcopy(known_state.get("power_unit", {})),
                    tried_invalid_repairs=copy.deepcopy(tried_repairs or []),
                )
                cstr = ActiveConstraint(
                    constraint_id="power_unit_nominal_required",
                    predicate="power_unit.status == nominal and power_unit.isolated == False",
                    subsystem="power_unit",
                    required_condition={"field": "status", "expected": "nominal", "secondary_field": "isolated", "secondary_expected": False},
                    evidence_source="precondition_interlock",
                )
                return False, evt, cstr

        return True, None, None


class WorkstationAgentRunner:
    def __init__(
        self,
        group_id: str,
        llm_backend: Optional[LLMBackend] = None,
        max_llm_calls: int = 32,
        max_tool_calls: int = 40,
        time_limit_s: float = 1800.0,
        allow_fallback: bool = False,
        enable_constraint_repair_planning: bool = True,
    ):
        self.group_id = group_id
        self.llm_backend = llm_backend
        self.max_llm_calls = max_llm_calls
        self.max_tool_calls = max_tool_calls
        self.time_limit_s = time_limit_s
        self.allow_fallback = allow_fallback
        self.enable_constraint_repair_planning = enable_constraint_repair_planning

    def run_task(
        self,
        task_config: Dict[str, Any],
        raw_source_episodes: Optional[List[Dict[str, Any]]] = None,
        structured_facts: Optional[StructuredFactStore] = None,
        procedural_memory_store: Optional[ProceduralMemoryStore] = None,
    ) -> Dict[str, Any]:
        """
        Execute one evaluation run on task_config with strictly unified execution pipeline.
        """
        t0 = time.time()
        env = WorkstationEnv(task_config.get("initial_state"))

        # State tracking
        known_state: Dict[str, Any] = {}
        trajectory: List[Dict[str, Any]] = []
        audit_events: List[Dict[str, Any]] = []
        active_constraint_events: List[ConstraintEvent] = []
        constraint_tracker = ConstraintTracker()
        tried_invalid_repairs: List[Dict[str, Any]] = []

        # Stagnation & state change tracking
        stagnation_history: List[Dict[str, Any]] = []
        stagnation_replan_count = 0
        MAX_STAGNATION_REPLANS = 6

        # Procedural Memory & Deferred Management
        active_memory_exec: Optional[ActiveMemoryExecution] = None
        deferred_memories: Dict[str, Dict[str, Any]] = {}  # mem_id -> {memory, waiting_for, deferred_state}
        invalidated_memories: Set[str] = set()
        deferred_state_hashes: Dict[str, str] = {}  # mem_id -> hash of known_state when deferred

        # Counters
        llm_calls = 0
        prompt_tokens_total = 0
        gen_tokens_total = 0
        tool_errors_count = 0
        plan_deviations = 0

        # Decision Event & Repetition Tracking
        last_failure_event: Optional[DecisionEvent] = None
        consecutive_repeat_count = 0

        # LLM detailed call records
        llm_call_records: List[Dict[str, Any]] = []

        memory_selected_count = 0
        memory_action_executed_count = 0
        memory_postcondition_verified_count = 0
        memory_invalidated_count = 0
        memory_deferred_count = 0
        memory_resumed_count = 0
        online_recovery_attempted_count = 0
        online_recovery_succeeded = False
        has_invalidation_occurred = False

        executor = CommonLocalPlanExecutor(fact_store=structured_facts)
        success = False
        termination_reason = "RUNNING"

        # Latency milestones
        completed_at_300s = False
        completed_at_600s = False
        completed_at_1800s = False

        while True:
            elapsed_time = time.time() - t0

            # 1. Strict Timeout Check
            if elapsed_time >= self.time_limit_s:
                termination_reason = "TIME_LIMIT_EXCEEDED"
                success = False
                break

            # 2. Task Completion Check
            if env.is_task_completed():
                success = True
                termination_reason = "TASK_COMPLETED"
                if elapsed_time <= 300.0:
                    completed_at_300s = True
                if elapsed_time <= 600.0:
                    completed_at_600s = True
                completed_at_1800s = True
                if has_invalidation_occurred:
                    online_recovery_succeeded = True
                break

            # 3. Tool Budget Check
            if len(trajectory) >= self.max_tool_calls:
                termination_reason = "TOOL_BUDGET_EXHAUSTED"
                break

            # -------------------------------------------------------------
            # Stage A: Populate Execution Queue if Empty
            # -------------------------------------------------------------
            if executor.is_empty():
                # A.1: Continue next chunk of active procedural memory / replay if exists
                if active_memory_exec and active_memory_exec.has_next_chunk() and active_memory_exec.status == "RUNNING":
                    next_chunk = active_memory_exec.get_next_chunk()
                    executor.enqueue_plan(next_chunk, source_tag=active_memory_exec.source_tag)

                # A.2: Check D-gated Candidate or Re-evaluation
                elif self.group_id in ["Group_D_gated", "Group_D_gated_no_filter", "Group_D_gated_no_reeval"] and procedural_memory_store:
                    # Check deferred memories first (if reeval enabled)
                    resumed_mem = None
                    if self.group_id != "Group_D_gated_no_reeval" and deferred_memories:
                        for def_id, def_data in list(deferred_memories.items()):
                            mem_item = def_data["memory"]
                            cur_app, _ = self._evaluate_memory_applicability(mem_item, known_state)
                            if cur_app == "TRUE":
                                resumed_mem = mem_item
                                del deferred_memories[def_id]
                                memory_resumed_count += 1
                                audit_events.append({
                                    "event": "PROCEDURAL_MEMORY_RESUMED",
                                    "memory_id": mem_item.memory_id,
                                    "step": len(trajectory) + 1,
                                })
                                break

                    if resumed_mem:
                        active_memory_exec = self._build_memory_execution(resumed_mem, "procedural_memory")
                        first_chunk = active_memory_exec.get_next_chunk()
                        executor.enqueue_plan(first_chunk, source_tag="procedural_memory")
                    else:
                        # Find new matching candidate memory
                        cand_mem = self._find_matching_memory(known_state, procedural_memory_store, invalidated_memories, deferred_memories)
                        if cand_mem:
                            state_hash = self._hash_state(known_state)
                            # If no-filter ablation, skip applicability check
                            if self.group_id == "Group_D_gated_no_filter":
                                memory_selected_count += 1
                                active_memory_exec = self._build_memory_execution(cand_mem, "procedural_memory")
                                first_chunk = active_memory_exec.get_next_chunk()
                                executor.enqueue_plan(first_chunk, source_tag="procedural_memory")
                            else:
                                app_status, unmet = self._evaluate_memory_applicability(cand_mem, known_state)
                                if app_status == "TRUE":
                                    memory_selected_count += 1
                                    active_memory_exec = self._build_memory_execution(cand_mem, "procedural_memory")
                                    first_chunk = active_memory_exec.get_next_chunk()
                                    executor.enqueue_plan(first_chunk, source_tag="procedural_memory")
                                elif app_status == "UNKNOWN":
                                    executor.enqueue_plan([{"tool": "inspect", "args": {"subsystem": cand_mem.target_subsystem}, "thought": "Inspect state to verify memory applicability."}], source_tag="procedural_memory")
                                else:  # FALSE -> DEFER
                                    if deferred_state_hashes.get(cand_mem.memory_id) != state_hash:
                                        memory_deferred_count += 1
                                        deferred_memories[cand_mem.memory_id] = {
                                            "memory": cand_mem,
                                            "waiting_for": unmet,
                                            "deferred_state": copy.deepcopy(known_state),
                                        }
                                        deferred_state_hashes[cand_mem.memory_id] = state_hash
                                        def_evt = ConstraintEvent(
                                            event_type="MEMORY_DEFERRED_PRECONDITION_UNMET",
                                            blocked_action={"tool": cand_mem.actions[0].tool if cand_mem.actions else "unknown", "args": cand_mem.actions[0].args if cand_mem.actions else {}},
                                            unmet_conditions=unmet,
                                            condition_status="FALSE",
                                            cancellation_reason=f"Procedural memory {cand_mem.memory_id} deferred: prerequisites not yet satisfied.",
                                            observed_evidence=copy.deepcopy(known_state),
                                        )
                                        active_constraint_events.append(def_evt)
                                        audit_events.append(asdict(def_evt))

                # A.3: Group D Current (Stage 3 baseline)
                elif self.group_id == "Group_D_current" and procedural_memory_store:
                    cand_mem = self._find_matching_memory(known_state, procedural_memory_store, invalidated_memories, deferred_memories)
                    if cand_mem:
                        memory_selected_count += 1
                        active_memory_exec = self._build_memory_execution(cand_mem, "procedural_memory")
                        first_chunk = active_memory_exec.get_next_chunk()
                        executor.enqueue_plan(first_chunk, source_tag="procedural_memory")

                # A.4: Group Replay
                elif self.group_id == "Group_Replay" and raw_source_episodes:
                    replay_plan = self._match_naive_replay_segment(known_state, raw_source_episodes, invalidated_memories)
                    if replay_plan:
                        memory_selected_count += 1
                        active_memory_exec = ActiveMemoryExecution(
                            memory_id=replay_plan["segment_id"],
                            source_tag="naive_replay",
                            actions=copy.deepcopy(replay_plan["actions"]),
                            total_actions=len(replay_plan["actions"]),
                        )
                        first_chunk = active_memory_exec.get_next_chunk()
                        executor.enqueue_plan(first_chunk, source_tag="naive_replay")

                # A.5: LLM Planning (For B2_step, B2_plan, B1_plan, or when memory queue is empty/deferred)
                if executor.is_empty():
                    if llm_calls >= self.max_llm_calls:
                        termination_reason = "LLM_BUDGET_EXHAUSTED"
                        break

                    llm_calls += 1
                    is_multistep = self.group_id in ["Group_B2_plan", "Group_B1_plan", "Group_D_current", "Group_D_gated", "Group_D_gated_no_filter", "Group_D_gated_no_reeval", "Group_Replay"]
                    prompt = self._construct_prompt(
                        task_config=task_config,
                        known_state=known_state,
                        trajectory=trajectory,
                        raw_source_episodes=raw_source_episodes,
                        structured_facts=structured_facts,
                        procedural_memory_store=procedural_memory_store if "Group_D" in self.group_id else None,
                        active_constraint_events=active_constraint_events,
                        constraint_tracker=constraint_tracker,
                        is_multistep=is_multistep,
                    )

                    response_text, p_tok, g_tok = self._call_llm(
                        prompt,
                        is_multistep=is_multistep,
                        call_type="standard_planning" if is_multistep else "step_planning",
                        llm_call_records=llm_call_records,
                    )
                    prompt_tokens_total += p_tok
                    gen_tokens_total += g_tok

                    parsed = self._parse_llm_response(response_text)
                    plan_acts = []
                    if parsed:
                        if isinstance(parsed, dict) and "plan" in parsed and isinstance(parsed["plan"], list) and len(parsed["plan"]) > 0:
                            for raw_a in parsed["plan"]:
                                norm_a = self._normalize_action(raw_a, default_thought=parsed.get("thought", ""))
                                if norm_a:
                                    plan_acts.append(norm_a)
                        elif isinstance(parsed, list):
                            for raw_a in parsed:
                                norm_a = self._normalize_action(raw_a)
                                if norm_a:
                                    plan_acts.append(norm_a)
                        elif isinstance(parsed, dict):
                            norm_a = self._normalize_action(parsed)
                            if norm_a:
                                plan_acts.append(norm_a)

                    if not plan_acts:
                        plan_acts = [{"tool": "inspect", "args": {"subsystem": "all"}, "thought": "Inspect workstation status."}]

                    executor.enqueue_plan(plan_acts, source_tag="llm_plan")

            if executor.is_empty():
                termination_reason = "NO_ACTIONS_GENERATED"
                break

            # -------------------------------------------------------------
            # Stage B: Unified Action Pop & Precondition Validation
            # -------------------------------------------------------------
            cand_action = executor.pop()
            if not cand_action:
                continue

            tool_name = cand_action.get("tool", "inspect")
            tool_args = cand_action.get("args", {})
            action_source = cand_action.get("source_tag", "llm_plan")
            thought = cand_action.get("thought", "")
            expected_effects = cand_action.get("expected_effects", {})

            # Stagnation & No-Progress Check
            state_before_hash = self._hash_state(known_state)
            act_sig = f"{tool_name}:{json.dumps(tool_args, sort_keys=True)}"

            # Precondition Validation (Identical across all groups)
            valid, constraint_event, active_cstr = executor.validate_precondition(cand_action, known_state, tried_invalid_repairs)
            if not valid and constraint_event:
                if active_cstr:
                    constraint_tracker.add_constraint(active_cstr, step_index=len(trajectory) + 1)
                
                unmet_preds = tuple(sorted(constraint_event.unmet_conditions))
                rel_state_hash = self._hash_relevant_state(known_state, tool_args.get("subsystem"))
                d_evt = DecisionEvent(
                    relevant_state_hash=rel_state_hash,
                    action_signature=act_sig,
                    unmet_predicates=unmet_preds,
                    result_category="PRECONDITION_BLOCKED",
                    reason=constraint_event.cancellation_reason,
                )
                audit_events.append(asdict(constraint_event))
                tried_invalid_repairs.append({"tool": tool_name, "args": tool_args, "reason": constraint_event.cancellation_reason})

                if action_source in ["procedural_memory", "naive_replay"]:
                    memory_invalidated_count += 1
                    has_invalidation_occurred = True
                    online_recovery_attempted_count += 1
                    if active_memory_exec:
                        invalidated_memories.add(active_memory_exec.memory_id)
                        active_memory_exec.status = "INVALIDATED"
                        active_memory_exec = None

                executor.clear()

                # Repetition check
                is_same = (
                    last_failure_event is not None
                    and last_failure_event.relevant_state_hash == d_evt.relevant_state_hash
                    and last_failure_event.action_signature == d_evt.action_signature
                    and last_failure_event.unmet_predicates == d_evt.unmet_predicates
                    and last_failure_event.result_category == d_evt.result_category
                )
                if is_same:
                    consecutive_repeat_count += 1
                else:
                    consecutive_repeat_count = 1
                    last_failure_event = d_evt

                if consecutive_repeat_count == 1:
                    active_constraint_events.append(constraint_event)
                    continue
                elif consecutive_repeat_count == 2:
                    if constraint_event.to_prompt_str() not in [e.to_prompt_str() for e in active_constraint_events]:
                        active_constraint_events.append(constraint_event)
                    continue
                elif consecutive_repeat_count == 3:
                    if self.enable_constraint_repair_planning and llm_calls < self.max_llm_calls:
                        llm_calls += 1
                        repair_acts = self._plan_constraint_repair(
                            task_config=task_config,
                            known_state=known_state,
                            blocked_action={"tool": tool_name, "args": tool_args},
                            unmet_predicates=list(unmet_preds),
                            cancellation_reason=constraint_event.cancellation_reason,
                            structured_facts=structured_facts,
                            llm_call_records=llm_call_records,
                        )
                        if repair_acts:
                            executor.enqueue_plan(repair_acts, source_tag="constraint_repair_plan")
                    continue
                else:
                    termination_reason = "REPEATED_CONSTRAINT_VIOLATION"
                    break

            # -------------------------------------------------------------
            # Stage C: Execute Action (env.step)
            # -------------------------------------------------------------
            if action_source in ["procedural_memory", "naive_replay"]:
                memory_action_executed_count += 1

            tool_res = env.step(tool_name, **tool_args)
            is_err = (tool_res.get("status") != StatusCode.SUCCESS)

            # Update public known state
            self._update_known_state(known_state, tool_name, tool_args, tool_res)
            state_after_hash = self._hash_state(known_state)

            # Update constraint tracker with new observations (ONLY clears when explicitly satisfied)
            constraint_tracker.update_with_observation(known_state, step_index=len(trajectory) + 1)

            # Check for stagnation / no-progress
            is_no_progress = (not is_err) and (state_before_hash == state_after_hash)
            stagnation_history.append({
                "act_sig": act_sig,
                "no_progress": is_no_progress,
                "is_err": is_err,
                "tool": tool_name,
            })

            # Record step in trajectory
            step_record = {
                "step_index": len(trajectory) + 1,
                "action_source": action_source,
                "tool": tool_name,
                "args": copy.deepcopy(tool_args),
                "thought": thought,
                "result": copy.deepcopy(tool_res),
                "is_error": is_err,
                "known_state_after": copy.deepcopy(known_state),
                "active_constraints_count": len(constraint_tracker.get_active_constraints()),
            }
            trajectory.append(step_record)

            if is_err:
                tool_errors_count += 1
                err_msg = tool_res.get("error", "Tool execution error")
                err_evt = ConstraintEvent(
                    event_type="TOOL_EXECUTION_ERROR",
                    blocked_action={"tool": tool_name, "args": tool_args},
                    unmet_conditions=[err_msg],
                    condition_status="FALSE",
                    cancellation_reason=err_msg,
                    observed_evidence=copy.deepcopy(known_state),
                    tried_invalid_repairs=copy.deepcopy(tried_invalid_repairs),
                )
                active_constraint_events.append(err_evt)
                audit_events.append(asdict(err_evt))

                if action_source in ["procedural_memory", "naive_replay"]:
                    memory_invalidated_count += 1
                    has_invalidation_occurred = True
                    online_recovery_attempted_count += 1
                    if active_memory_exec:
                        invalidated_memories.add(active_memory_exec.memory_id)
                        active_memory_exec.status = "INVALIDATED"
                        active_memory_exec = None
                executor.clear()

                rel_state_hash = self._hash_relevant_state(known_state, tool_args.get("subsystem"))
                d_evt = DecisionEvent(
                    relevant_state_hash=rel_state_hash,
                    action_signature=act_sig,
                    unmet_predicates=(err_msg,),
                    result_category="TOOL_EXECUTION_ERROR",
                    reason=err_msg,
                )
                is_same = (
                    last_failure_event is not None
                    and last_failure_event.relevant_state_hash == d_evt.relevant_state_hash
                    and last_failure_event.action_signature == d_evt.action_signature
                    and last_failure_event.unmet_predicates == d_evt.unmet_predicates
                    and last_failure_event.result_category == d_evt.result_category
                )
                if is_same:
                    consecutive_repeat_count += 1
                else:
                    consecutive_repeat_count = 1
                    last_failure_event = d_evt

                if consecutive_repeat_count == 1:
                    continue
                elif consecutive_repeat_count == 2:
                    continue
                elif consecutive_repeat_count == 3:
                    if self.enable_constraint_repair_planning and llm_calls < self.max_llm_calls:
                        llm_calls += 1
                        repair_acts = self._plan_constraint_repair(
                            task_config=task_config,
                            known_state=known_state,
                            blocked_action={"tool": tool_name, "args": tool_args},
                            unmet_predicates=[err_msg],
                            cancellation_reason=err_msg,
                            structured_facts=structured_facts,
                            llm_call_records=llm_call_records,
                        )
                        if repair_acts:
                            executor.enqueue_plan(repair_acts, source_tag="constraint_repair_plan")
                    continue
                else:
                    termination_reason = "REPEATED_CONSTRAINT_VIOLATION"
                    break

            elif is_no_progress:
                stag_reasons = f"Action {tool_name}({tool_args}) repeated without state progress. Diagnose workstation or try alternative strategy."
                stag_evt = ConstraintEvent(
                    event_type="STAGNATION_LOOP",
                    blocked_action={"tool": tool_name, "args": tool_args},
                    unmet_conditions=["Repeated action yielded no state progress or cleared faults."],
                    condition_status="FALSE",
                    cancellation_reason=stag_reasons,
                    observed_evidence=copy.deepcopy(known_state),
                )
                active_constraint_events.append(stag_evt)
                audit_events.append(asdict(stag_evt))

                if action_source in ["procedural_memory", "naive_replay"]:
                    memory_invalidated_count += 1
                    has_invalidation_occurred = True
                    online_recovery_attempted_count += 1
                    if active_memory_exec:
                        invalidated_memories.add(active_memory_exec.memory_id)
                        active_memory_exec.status = "INVALIDATED"
                        active_memory_exec = None
                executor.clear()

                rel_state_hash = self._hash_relevant_state(known_state, tool_args.get("subsystem"))
                d_evt = DecisionEvent(
                    relevant_state_hash=rel_state_hash,
                    action_signature=act_sig,
                    unmet_predicates=("No state progress observed",),
                    result_category="NO_PROGRESS",
                    reason=stag_reasons,
                )
                is_same = (
                    last_failure_event is not None
                    and last_failure_event.relevant_state_hash == d_evt.relevant_state_hash
                    and last_failure_event.action_signature == d_evt.action_signature
                    and last_failure_event.unmet_predicates == d_evt.unmet_predicates
                    and last_failure_event.result_category == d_evt.result_category
                )
                if is_same:
                    consecutive_repeat_count += 1
                else:
                    consecutive_repeat_count = 1
                    last_failure_event = d_evt

                if consecutive_repeat_count == 1:
                    continue
                elif consecutive_repeat_count == 2:
                    continue
                elif consecutive_repeat_count == 3:
                    if self.enable_constraint_repair_planning and llm_calls < self.max_llm_calls:
                        llm_calls += 1
                        repair_acts = self._plan_constraint_repair(
                            task_config=task_config,
                            known_state=known_state,
                            blocked_action={"tool": tool_name, "args": tool_args},
                            unmet_predicates=["No state progress observed: action repeated without state change"],
                            cancellation_reason=stag_reasons,
                            structured_facts=structured_facts,
                            llm_call_records=llm_call_records,
                        )
                        if repair_acts:
                            executor.enqueue_plan(repair_acts, source_tag="constraint_repair_plan")
                    continue
                else:
                    termination_reason = "REPEATED_CONSTRAINT_VIOLATION"
                    break

            else:
                # Genuine state progress was achieved! Reset repetition streak
                consecutive_repeat_count = 0
                last_failure_event = None
                active_constraint_events = [e for e in active_constraint_events if e.event_type not in ["STAGNATION_LOOP", "TOOL_EXECUTION_ERROR"]]

                # -------------------------------------------------------------
                # Stage D: Postcondition Verification
                # -------------------------------------------------------------
                if expected_effects and isinstance(expected_effects, dict):
                    postcond_status, mismatches = self._verify_postconditions(expected_effects, tool_res, known_state, tool_args.get("subsystem", ""))
                    if postcond_status == "TRUE":
                        if action_source in ["procedural_memory", "naive_replay"]:
                            memory_postcondition_verified_count += 1
                    elif postcond_status == "FALSE":
                        post_evt = ConstraintEvent(
                            event_type="POSTCONDITION_MISMATCH",
                            blocked_action={"tool": tool_name, "args": tool_args},
                            unmet_conditions=mismatches,
                            condition_status="FALSE",
                            cancellation_reason="Postcondition mismatch after action execution.",
                            observed_evidence=copy.deepcopy(known_state),
                        )
                        active_constraint_events.append(post_evt)
                        audit_events.append(asdict(post_evt))
                        if action_source in ["procedural_memory", "naive_replay"]:
                            memory_invalidated_count += 1
                            has_invalidation_occurred = True
                            if active_memory_exec:
                                invalidated_memories.add(active_memory_exec.memory_id)
                                active_memory_exec.status = "INVALIDATED"
                                active_memory_exec = None
                        executor.clear()

                if active_memory_exec and active_memory_exec.is_fully_executed() and not executor.action_queue:
                    active_memory_exec.status = "COMPLETED"
                    invalidated_memories.add(active_memory_exec.memory_id)
                    active_memory_exec = None

        wall_time_s = round(time.time() - t0, 2)

        return {
            "group_id": self.group_id,
            "task_id": task_config.get("task_id"),
            "transfer_class": task_config.get("transfer_class", "source"),
            "success": success,
            "termination_reason": termination_reason,
            "step_count": len(trajectory),
            "llm_calls": llm_calls,
            "total_prompt_tokens": prompt_tokens_total,
            "total_generated_tokens": gen_tokens_total,
            "wall_time_s": wall_time_s,
            "completed_at_300s": completed_at_300s,
            "completed_at_600s": completed_at_600s,
            "completed_at_1800s": completed_at_1800s,
            "tool_errors_count": tool_errors_count,
            "plan_deviations_count": plan_deviations,
            "memory_selected_count": memory_selected_count,
            "memory_action_executed_count": memory_action_executed_count,
            "memory_postcondition_verified_count": memory_postcondition_verified_count,
            "memory_invalidated_count": memory_invalidated_count,
            "memory_deferred_count": memory_deferred_count,
            "memory_resumed_count": memory_resumed_count,
            "online_recovery_attempted_count": online_recovery_attempted_count,
            "online_recovery_succeeded": online_recovery_succeeded,
            "trajectory": trajectory,
            "audit_events": audit_events,
            "constraint_history": constraint_tracker.history,
            "final_env_summary": env.get_summary(),
            "llm_call_records": llm_call_records,
        }

    def _normalize_action(self, raw: Any, default_thought: str = "") -> Optional[Dict[str, Any]]:
        if not isinstance(raw, dict):
            return None
        raw_tool = raw.get("tool") or raw.get("action") or raw.get("name")
        if not raw_tool or not isinstance(raw_tool, str):
            return None

        tool_str = raw_tool.strip().lower()
        tool_map = {
            "inspect": "inspect",
            "isolate": "isolate",
            "clear_fault": "clear_fault",
            "clear": "clear_fault",
            "clearfault": "clear_fault",
            "reset": "reset",
            "calibrate": "calibrate",
            "calibration": "calibrate",
            "self_test": "self_test",
            "run_self_test": "self_test",
            "selftest": "self_test",
            "resume": "resume",
            "resume_operation": "resume",
            "resume_production": "resume",
        }
        tool = tool_map.get(tool_str, tool_str)

        args = {}
        if isinstance(raw.get("args"), dict):
            args.update(copy.deepcopy(raw["args"]))
        elif isinstance(raw.get("parameters"), dict):
            args.update(copy.deepcopy(raw["parameters"]))
        elif isinstance(raw.get("arguments"), dict):
            args.update(copy.deepcopy(raw["arguments"]))

        for k, v in raw.items():
            if k not in ["tool", "action", "name", "args", "parameters", "arguments", "thought", "reasoning", "expected_effects", "source_tag"]:
                if k not in args:
                    args[k] = copy.deepcopy(v)

        if tool in ["isolate", "clear_fault", "reset", "calibrate"]:
            if "subsystem" not in args:
                sub = args.get("target") or args.get("component")
                if sub:
                    args["subsystem"] = sub

        if tool == "inspect" and "subsystem" not in args:
            args["subsystem"] = "all"

        thought = raw.get("thought") or raw.get("reasoning") or default_thought

        return {
            "tool": tool,
            "args": args,
            "thought": thought,
            "expected_effects": copy.deepcopy(raw.get("expected_effects", {})),
        }

    def _hash_state(self, state: Dict[str, Any]) -> str:
        s = json.dumps(state, sort_keys=True)
        return hashlib.md5(s.encode("utf-8")).hexdigest()

    def _hash_relevant_state(self, known_state: Dict[str, Any], subsystem: Optional[str] = None) -> str:
        if subsystem and subsystem in known_state:
            rel = {
                subsystem: known_state.get(subsystem),
                "power_unit": known_state.get("power_unit"),
            }
        else:
            rel = known_state
        return hashlib.md5(json.dumps(rel, sort_keys=True, default=str).encode("utf-8")).hexdigest()

    def _build_memory_execution(self, mem: ProceduralMemoryItem, source_tag: str) -> ActiveMemoryExecution:
        actions = [
            {
                "tool": a.tool,
                "args": copy.deepcopy(a.args),
                "expected_effects": copy.deepcopy(a.expected_postconditions),
                "thought": f"Execute {mem.memory_id} node {a.node_id}",
            }
            for a in mem.actions
        ]
        return ActiveMemoryExecution(
            memory_id=mem.memory_id,
            source_tag=source_tag,
            actions=actions,
            total_actions=len(actions),
        )

    def _find_matching_memory(
        self,
        known_state: Dict[str, Any],
        memory_store: ProceduralMemoryStore,
        invalidated_memories: Set[str],
        deferred_memories: Dict[str, Any],
    ) -> Optional[ProceduralMemoryItem]:
        for sub, data in known_state.items():
            if not isinstance(data, dict):
                continue
            status = data.get("status")
            if status and status != "nominal":
                candidates = memory_store.retrieve(subsystem=sub, fault_type=status)
                for cand in candidates:
                    if cand.memory_id not in invalidated_memories and cand.memory_id not in deferred_memories:
                        return cand
        return None

    def _evaluate_memory_applicability(
        self,
        mem: ProceduralMemoryItem,
        known_state: Dict[str, Any],
    ) -> Tuple[str, List[str]]:
        """
        Evaluates whether procedural memory applicability and domain interlocks are satisfied.
        Returns ("TRUE" | "FALSE" | "UNKNOWN", unmet_reasons).
        """
        unmet = []
        target_sub = mem.target_subsystem
        sub_state = known_state.get(target_sub)

        # 1. Target Subsystem Check
        if not sub_state:
            return "UNKNOWN", [f"{target_sub} state is UNKNOWN; inspect required"]

        expected_faults = mem.applicability_conditions.get("fault_types", [])
        cur_status = sub_state.get("status")
        if expected_faults and cur_status not in expected_faults:
            return "FALSE", [f"{target_sub} status is '{cur_status}', expected one of {expected_faults}"]

        # 2. Prerequisite Interlock Check
        if target_sub in ["camera_sensor", "arm_gripper"]:
            pw = known_state.get("power_unit")
            if pw is None:
                return "UNKNOWN", ["power_unit state is UNKNOWN; inspect required"]
            if pw.get("status") != "nominal" or pw.get("isolated") is True:
                return "FALSE", ["power_unit must be nominal and not isolated before servicing " + target_sub]

        if target_sub == "arm_gripper":
            if sub_state.get("holding_load") is True:
                if mem.actions and mem.actions[0].tool == "reset":
                    return "FALSE", ["arm_gripper holding load must be cleared before homing/resetting"]

        return "TRUE", []

    def _verify_postconditions(
        self,
        expected_effects: Dict[str, Any],
        tool_res: Dict[str, Any],
        known_state: Dict[str, Any],
        subsystem: str,
    ) -> Tuple[str, List[str]]:
        """
        Verifies expected effects against tool results and updated known state.
        Returns ("TRUE" | "FALSE" | "UNKNOWN", mismatches).
        """
        mismatches = []
        has_unknown = False
        for k, exp_v in expected_effects.items():
            actual_v = tool_res.get("effects", {}).get(k)
            if actual_v is None and subsystem:
                actual_v = known_state.get(subsystem, {}).get(k)
            if actual_v is None:
                has_unknown = True
            elif actual_v != exp_v:
                mismatches.append(f"{k}: expected {exp_v}, observed {actual_v}")

        if mismatches:
            return "FALSE", mismatches
        if has_unknown:
            return "UNKNOWN", []
        return "TRUE", []

    def _match_naive_replay_segment(
        self,
        known_state: Dict[str, Any],
        raw_source_episodes: List[Dict[str, Any]],
        invalidated_memories: Set[str],
    ) -> Optional[Dict[str, Any]]:
        for sub, data in known_state.items():
            if not isinstance(data, dict):
                continue
            status = data.get("status")
            if status and status != "nominal":
                for ep in raw_source_episodes:
                    if not ep.get("success"):
                        continue
                    seg_id = f"replay_{sub}_{ep.get('task_id')}"
                    if seg_id in invalidated_memories:
                        continue
                    acts = []
                    for step in ep.get("trajectory", []):
                        if step.get("args", {}).get("subsystem") == sub and not step.get("is_error"):
                            acts.append({
                                "tool": step.get("tool"),
                                "args": copy.deepcopy(step.get("args", {})),
                                "expected_effects": copy.deepcopy(step.get("result", {}).get("effects", {})),
                                "thought": f"Naive replay action from {ep.get('task_id')}",
                            })
                    if acts:
                        return {"segment_id": seg_id, "actions": acts}
        return None

    def _update_known_state(
        self,
        known_state: Dict[str, Any],
        tool_name: str,
        tool_args: Dict[str, Any],
        tool_res: Dict[str, Any],
    ):
        if tool_res.get("status") != StatusCode.SUCCESS:
            return

        if tool_name == "inspect":
            sub = tool_args.get("subsystem", "all")
            data = tool_res.get("data", {})
            if sub == "all" and isinstance(data, dict):
                for k, v in data.items():
                    if isinstance(v, dict):
                        known_state[k] = copy.deepcopy(v)
            elif isinstance(data, dict):
                if sub in data and isinstance(data[sub], dict):
                    sub_dict = data[sub]
                else:
                    sub_dict = data
                if sub not in known_state:
                    known_state[sub] = {}
                known_state[sub].update(copy.deepcopy(sub_dict))

        effects = tool_res.get("effects", {})
        sub = tool_args.get("subsystem")
        if isinstance(effects, dict):
            # Bug 1 fix: Route camera sensor invalidation to camera_sensor
            if "camera_sensor_calibrated_invalidated" in effects:
                if "camera_sensor" not in known_state:
                    known_state["camera_sensor"] = {}
                known_state["camera_sensor"]["calibrated"] = False

            # Update subsystem properties without polluting with cross-subsystem keys
            cleaned_effects = {k: v for k, v in effects.items() if not k.endswith("_invalidated")}
            if sub and cleaned_effects:
                if sub not in known_state:
                    known_state[sub] = {}
                known_state[sub].update(copy.deepcopy(cleaned_effects))

        if tool_name == "self_test":
            if "controller" not in known_state:
                known_state["controller"] = {}
            known_state["controller"]["self_test_passed"] = tool_res.get("passed", False)

        if tool_name == "resume":
            if "controller" not in known_state:
                known_state["controller"] = {}
            known_state["controller"]["resumed"] = True

    def _construct_prompt(
        self,
        task_config: Dict[str, Any],
        known_state: Dict[str, Any],
        trajectory: List[Dict[str, Any]],
        raw_source_episodes: Optional[List[Dict[str, Any]]] = None,
        structured_facts: Optional[StructuredFactStore] = None,
        procedural_memory_store: Optional[ProceduralMemoryStore] = None,
        active_constraint_events: Optional[List[ConstraintEvent]] = None,
        constraint_tracker: Optional[ConstraintTracker] = None,
        is_multistep: bool = False,
    ) -> str:
        sys_prompt = WORKSTATION_SYSTEM_PROMPT_PLAN if is_multistep else WORKSTATION_SYSTEM_PROMPT_STEP
        parts = [sys_prompt, "\n=== Current Task Objective ==="]
        parts.append(f"Goal: {task_config.get('goal')}")

        # Group B1: Append full raw source episodes with homologous intervention logs
        if self.group_id in ["Group_B1_plan", "Group_Replay"] and raw_source_episodes:
            parts.append("\n=== Prior Cross-Task Experience (Complete Raw Trajectories & Interventions) ===")
            for idx, ep in enumerate(raw_source_episodes):
                succ_tag = "SUCCESS" if ep.get("success") else "FAILED"
                parts.append(f"\n--- Episode {idx+1} ({ep.get('task_id')}, Status={succ_tag}) ---")
                for s in ep.get("trajectory", []):
                    r_obj = s.get("result", {})
                    msg = r_obj.get("message") or r_obj.get("error") or r_obj.get("status")
                    eff = r_obj.get("effects", {})
                    eff_str = f", Effects: {eff}" if eff else ""
                    parts.append(f"  Step {s.get('step_index')}: {s.get('tool')}({s.get('args')}) -> {r_obj.get('status')} ({msg}{eff_str})")

        # Group B2 / Group D: Append rich structured facts with intervention evidence
        if (self.group_id in ["Group_B2_step", "Group_B2_plan", "Group_B1_plan"] or "Group_D" in self.group_id) and structured_facts:
            facts_dict = structured_facts.to_dict()
            parts.append("\n=== Verified Structured Domain Facts (With Intervention Evidence) ===")
            if facts_dict.get("verified_transitions"):
                parts.append("Verified State Transitions:")
                for tr in facts_dict["verified_transitions"]:
                    parts.append(f"  - Action {tr.get('action')}: yielded effects {tr.get('observed_effects')}")
            if facts_dict.get("negative_preconditions"):
                parts.append("Observed Negative Preconditions & Failures:")
                for neg in facts_dict["negative_preconditions"]:
                    parts.append(f"  - Failed Action {neg.get('action')}: yielded {neg.get('error_status')} ({neg.get('error_message')})")
            if facts_dict.get("action_preconditions"):
                parts.append("Verified Action Preconditions:")
                for act, req_list in facts_dict["action_preconditions"].items():
                    req_strs = [f"{r.get('condition')} [Status: {r.get('status')}]" for r in req_list]
                    parts.append(f"  - {act}: requires {', '.join(req_strs)}")
            if facts_dict.get("invalidation_rules"):
                parts.append("Verified Invalidation Rules:")
                for inv in facts_dict["invalidation_rules"]:
                    parts.append(f"  - {inv.get('action')}: causes {inv.get('invalidated_state')} ({inv.get('reason')}) [Status: {inv.get('status')}]")
            if facts_dict.get("causal_order_constraints"):
                parts.append("Verified Causal Order Dependencies:")
                for dep in facts_dict["causal_order_constraints"]:
                    parts.append(f"  - In subsystem '{dep.get('subsystem')}': {dep.get('before')} must precede {dep.get('after')} [Status: {dep.get('status')}]")
            if facts_dict.get("commutative_subsystems"):
                parts.append("Commutative Independent Subsystems:")
                for c in facts_dict["commutative_subsystems"]:
                    parts.append(f"  - Subsystems {c.get('subsystems')} can be serviced in any order [Status: {c.get('status')}]")

        # Active Constraints from tracker
        if constraint_tracker:
            cstr_str = constraint_tracker.to_prompt_str()
            if cstr_str:
                parts.append(f"\n{cstr_str}")

        # Active Interlock Feedback from events (deduplicated, bounded to recent 4)
        if active_constraint_events:
            parts.append("\n=== Recent Interlock Feedback & Warnings ===")
            seen_prompts = set()
            unique_recent = []
            for evt in reversed(active_constraint_events):
                p_str = evt.to_prompt_str()
                if p_str not in seen_prompts:
                    seen_prompts.add(p_str)
                    unique_recent.append(p_str)
                if len(unique_recent) >= 4:
                    break
            for p_str in reversed(unique_recent):
                parts.append(p_str)

        # Public Known State
        parts.append("\n=== Current Known Workstation State (Public Observations) ===")
        if known_state:
            parts.append(json.dumps(known_state, indent=2))
        else:
            parts.append("Workstation state unknown. Diagnostic inspect required.")

        # Trajectory History (windowed to recent 10 steps to maintain bounded prompt context)
        parts.append("\n=== Current Episode Execution History ===")
        if not trajectory:
            parts.append("No actions executed yet.")
        else:
            recent_trajectory = trajectory[-10:] if len(trajectory) > 10 else trajectory
            if len(trajectory) > 10:
                parts.append(f"[Note: {len(trajectory) - 10} earlier steps omitted for conciseness; current cumulative status is reflected in Known Workstation State above]")
            for s in recent_trajectory:
                r_obj = s.get("result", {})
                msg = r_obj.get("message") or r_obj.get("error") or r_obj.get("status")
                parts.append(f"Step {s.get('step_index')}: [{s.get('action_source')}] {s.get('tool')}({s.get('args')}) -> {r_obj.get('status')} ({msg})")

        parts.append("\nWhat action should be taken next? Respond strictly in JSON.")
        return "\n".join(parts)

    def _call_llm(
        self,
        prompt: str,
        is_multistep: bool = False,
        call_type: str = "standard_planning",
        llm_call_records: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[str, int, int]:
        t_call_start = time.time()
        if not self.llm_backend:
            mock_res = json.dumps({"thought": "Inspect workstation.", "plan": [{"tool": "inspect", "args": {"subsystem": "all"}}]}) if is_multistep else json.dumps({"thought": "Inspect workstation.", "tool": "inspect", "args": {"subsystem": "all"}})
            p_tok = len(prompt) // 4
            g_tok = len(mock_res) // 4
            latency_s = round(time.time() - t_call_start, 3)
            parsed = self._parse_llm_response(mock_res)
            if llm_call_records is not None:
                llm_call_records.append({
                    "call_index": len(llm_call_records) + 1,
                    "timestamp": time.time(),
                    "call_type": call_type,
                    "prompt": prompt,
                    "raw_output": mock_res,
                    "parsed_output": parsed,
                    "prompt_tokens": p_tok,
                    "generated_tokens": g_tok,
                    "latency_s": latency_s,
                })
            return mock_res, p_tok, g_tok

        res = self.llm_backend.generate(prompt)
        text_out = res.get("content") or res.get("text") or res.get("raw_output", "")
        p_tok = res.get("prompt_tokens", len(prompt) // 4)
        g_tok = res.get("generated_tokens", len(text_out) // 4)
        latency_s = round(time.time() - t_call_start, 3)
        parsed = self._parse_llm_response(text_out)
        if llm_call_records is not None:
            llm_call_records.append({
                "call_index": len(llm_call_records) + 1,
                "timestamp": time.time(),
                "call_type": call_type,
                "prompt": prompt,
                "raw_output": text_out,
                "parsed_output": parsed,
                "prompt_tokens": p_tok,
                "generated_tokens": g_tok,
                "latency_s": latency_s,
            })
        return text_out, p_tok, g_tok

    def _plan_constraint_repair(
        self,
        task_config: Dict[str, Any],
        known_state: Dict[str, Any],
        blocked_action: Dict[str, Any],
        unmet_predicates: List[str],
        cancellation_reason: str,
        structured_facts: Optional[StructuredFactStore] = None,
        llm_call_records: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        tool = blocked_action.get("tool", "")
        args = blocked_action.get("args", {})
        
        prompt_parts = [
            WORKSTATION_SYSTEM_PROMPT_PLAN,
            "\n=== Current Task Objective ===",
            f"Goal: {task_config.get('goal')}",
            "\n=== CRITICAL CONSTRAINT REPAIR TRIGGERED ===",
            f"A recurring failure occurred when attempting: {tool}({args})",
            f"Unmet Predicates / Interlock: {'; '.join(unmet_predicates)}",
            f"Failure Reason: {cancellation_reason}",
            "\nDomain Interlock Protocols:",
            "  1. Power Unit: If power_unit is tripped, call isolate('power_unit', 'engage') -> clear_fault('power_unit') -> isolate('power_unit', 'release').",
            "  2. Pneumatic Line: If pneumatic_line has a fault, call isolate('pneumatic_line', 'engage') -> clear_fault('pneumatic_line') -> isolate('pneumatic_line', 'release').",
            "  3. Gripper Load: If arm_gripper is jammed or holding load, call clear_fault('arm_gripper') to release load before resetting/homing.",
            "  4. Sensor Calibration: Camera calibration requires power_unit to be nominal and not isolated.",
            "\n=== Current Known Workstation State ===",
            json.dumps(known_state, indent=2),
            "\nPlease formulate a 1 to 4 step corrective action plan to satisfy the unmet preconditions and unblock the system.",
            "Respond strictly in JSON format with a 'plan' array."
        ]
        prompt = "\n".join(prompt_parts)
        
        raw_res, _, _ = self._call_llm(
            prompt,
            is_multistep=True,
            call_type="constraint_repair_planning",
            llm_call_records=llm_call_records,
        )
        parsed = self._parse_llm_response(raw_res)
        plan_acts = []
        if parsed and isinstance(parsed, dict) and "plan" in parsed and isinstance(parsed["plan"], list):
            for raw_a in parsed["plan"]:
                norm_a = self._normalize_action(raw_a, default_thought=parsed.get("thought", ""))
                if norm_a:
                    plan_acts.append(norm_a)
        return plan_acts

    def _parse_llm_response(self, text: str) -> Optional[Dict[str, Any]]:
        cleaned = text.strip()
        code_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned)
        if code_match:
            cleaned = code_match.group(1).strip()
        try:
            return json.loads(cleaned)
        except Exception:
            return None
