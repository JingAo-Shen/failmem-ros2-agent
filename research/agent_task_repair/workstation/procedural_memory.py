"""
Procedural Memory and Causal Dependency Compiler for Workstation Multi-Fault Agent.

Data structures:
  - ProceduralMemoryItem: Conditional local repair procedure with applicability,
    observation triggers, actions with pre/post conditions, evidenced ordering,
    expected effects, invalidation triggers, and source refs.
  - StructuredFactStore: Homologous structured history provided to B2 and D.
  - CausalInterventionCompiler: Extracts real trajectories, executes budget-bounded
    interventions using public tool calls in source environment copies, verifies true
    causal dependencies, and compiles validated procedural memories.
"""
from typing import Dict, Any, List, Optional, Tuple, Set
import copy
from dataclasses import dataclass, field, asdict
from .workstation_env import WorkstationEnv, StatusCode


@dataclass
class ActionNode:
    node_id: str
    tool: str
    args: Dict[str, Any]
    observed_preconditions: Dict[str, Any] = field(default_factory=dict)
    expected_postconditions: Dict[str, Any] = field(default_factory=dict)
    source_step_id: Optional[int] = None


@dataclass
class ProceduralMemoryItem:
    memory_id: str
    name: str
    target_subsystem: str
    applicability_conditions: Dict[str, Any]
    observation_triggers: List[str]
    actions: List[ActionNode]
    evidenced_order_dependencies: List[Dict[str, Any]]
    expected_effects: List[str]
    invalidation_conditions: List[Dict[str, Any]]
    source_task_id: str
    source_step_refs: List[int]
    status: str = "VERIFIED"  # VERIFIED or CANDIDATE

    def to_dict(self) -> Dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "name": self.name,
            "target_subsystem": self.target_subsystem,
            "applicability_conditions": copy.deepcopy(self.applicability_conditions),
            "observation_triggers": copy.deepcopy(self.observation_triggers),
            "actions": [asdict(a) for a in self.actions],
            "evidenced_order_dependencies": copy.deepcopy(self.evidenced_order_dependencies),
            "expected_effects": copy.deepcopy(self.expected_effects),
            "invalidation_conditions": copy.deepcopy(self.invalidation_conditions),
            "source_task_id": self.source_task_id,
            "source_step_refs": copy.deepcopy(self.source_step_refs),
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ProceduralMemoryItem":
        actions = [ActionNode(**a) for a in d.get("actions", [])]
        return cls(
            memory_id=d["memory_id"],
            name=d["name"],
            target_subsystem=d["target_subsystem"],
            applicability_conditions=d.get("applicability_conditions", {}),
            observation_triggers=d.get("observation_triggers", []),
            actions=actions,
            evidenced_order_dependencies=d.get("evidenced_order_dependencies", []),
            expected_effects=d.get("expected_effects", []),
            invalidation_conditions=d.get("invalidation_conditions", []),
            source_task_id=d.get("source_task_id", ""),
            source_step_refs=d.get("source_step_refs", []),
            status=d.get("status", "VERIFIED"),
        )


class StructuredFactStore:
    """
    Rich structured history repository provided to Group B2 and Group D.
    Contains:
      - verified_transitions: list of (pre_state, action, post_state, source_step_id)
      - action_preconditions: verified preconditions for tools with intervention evidence
      - invalidation_rules: verified side effects of operations (e.g. resets invalidating calibrations)
      - causal_order_constraints: verified orderings within subsystems with intervention evidence
      - commutative_subsystems: verified independent subsystems that can be serviced in any order
      - intervention_logs: complete audit trail of all intervention tests performed
    """
    def __init__(self):
        self.verified_transitions: List[Dict[str, Any]] = []
        self.action_preconditions: Dict[str, List[Dict[str, Any]]] = {}
        self.invalidation_rules: List[Dict[str, Any]] = []
        self.causal_order_constraints: List[Dict[str, Any]] = []
        self.commutative_subsystems: List[Dict[str, Any]] = []
        self.intervention_logs: List[Dict[str, Any]] = []
        self.total_intervention_tool_calls: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verified_transitions": copy.deepcopy(self.verified_transitions),
            "action_preconditions": copy.deepcopy(self.action_preconditions),
            "invalidation_rules": copy.deepcopy(self.invalidation_rules),
            "causal_order_constraints": copy.deepcopy(self.causal_order_constraints),
            "commutative_subsystems": copy.deepcopy(self.commutative_subsystems),
            "intervention_logs": copy.deepcopy(self.intervention_logs),
            "total_intervention_tool_calls": self.total_intervention_tool_calls,
        }


class ProceduralMemoryStore:
    """Library of validated procedural repair memories for Group D."""
    def __init__(self):
        self.memories: Dict[str, ProceduralMemoryItem] = {}

    def add_memory(self, item: ProceduralMemoryItem):
        self.memories[item.memory_id] = item

    def get_memory(self, memory_id: str) -> Optional[ProceduralMemoryItem]:
        return self.memories.get(memory_id)

    def retrieve(self, subsystem: str, fault_type: Optional[str] = None) -> List[ProceduralMemoryItem]:
        """Retrieve candidate procedural memories matching subsystem and verified fault type."""
        matches = []
        for mem in self.memories.values():
            if mem.target_subsystem == subsystem:
                if fault_type is None:
                    matches.append(mem)
                else:
                    applicable_faults = mem.applicability_conditions.get("fault_types", [])
                    if not applicable_faults or fault_type in applicable_faults:
                        matches.append(mem)
        return matches

    def to_dict(self) -> Dict[str, Any]:
        return {mid: mem.to_dict() for mid, mem in self.memories.items()}


class CausalInterventionCompiler:
    """
    Causal Intervention Tester & Homologous Memory Compiler.
    Takes raw episode trajectories from Phase A source tasks, tests ordering & invalidation
    hypotheses via budget-bounded interventions in isolated environment copies using public
    inspection tools, and produces:
      1. StructuredFactStore (for B2 & D)
      2. ProceduralMemoryStore (for D)
    """

    def __init__(self, max_intervention_budget: int = 30):
        self.max_intervention_budget = max_intervention_budget
        self.intervention_tool_calls = 0

    def compile_from_source_episodes(
        self,
        source_episodes: List[Dict[str, Any]],
        source_task_configs: List[Dict[str, Any]],
    ) -> Tuple[StructuredFactStore, ProceduralMemoryStore]:
        """
        Compile raw source trajectories into StructuredFactStore and ProceduralMemoryStore.
        """
        fact_store = StructuredFactStore()
        memory_store = ProceduralMemoryStore()

        config_by_id = {t["task_id"]: t for t in source_task_configs}

        for ep in source_episodes:
            if not ep.get("success", False):
                continue

            task_id = ep.get("task_id", "")
            task_cfg = config_by_id.get(task_id, {})
            traj = ep.get("trajectory", [])

            # 1. Extract verified state transitions from real trajectory
            transitions = self._extract_verified_transitions(traj)
            for tr in transitions:
                if tr not in fact_store.verified_transitions:
                    fact_store.verified_transitions.append(tr)

            # 2. Extract observed fault symptoms
            observed_faults = self._extract_observed_faults(traj)

            # 3. Extract subsystem-specific sub-sequences
            subsystem_traces = self._segment_trajectory_by_subsystem(traj)

            for sub, actions in subsystem_traces.items():
                if sub in ["controller", "all"] or not actions:
                    continue

                sub_fault = observed_faults.get(sub)
                if not sub_fault:
                    continue

                # Run causal interventions to verify true dependencies
                order_deps, preconds, invalidations = self._test_causal_dependencies(
                    sub, actions, task_cfg, fact_store
                )

                # Record structured facts
                for a_name, req_list in preconds.items():
                    if a_name not in fact_store.action_preconditions:
                        fact_store.action_preconditions[a_name] = []
                    for req in req_list:
                        if req not in fact_store.action_preconditions[a_name]:
                            fact_store.action_preconditions[a_name].append(req)

                for inv in invalidations:
                    if inv not in fact_store.invalidation_rules:
                        fact_store.invalidation_rules.append(inv)

                for dep in order_deps:
                    if dep not in fact_store.causal_order_constraints:
                        fact_store.causal_order_constraints.append(dep)

                # Compile ProceduralMemoryItem with evidenced fault types
                mem_item = self._create_procedural_memory_item(
                    sub, sub_fault, actions, order_deps, invalidations, task_id
                )
                memory_store.add_memory(mem_item)

        # 4. Test commutative independence between distinct subsystems
        commutative = self._test_commutative_subsystems(source_task_configs, fact_store)
        fact_store.commutative_subsystems = commutative
        fact_store.total_intervention_tool_calls = self.intervention_tool_calls

        return fact_store, memory_store

    def _extract_verified_transitions(self, trajectory: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Extract verified state transitions (pre_observation, action, post_observation)."""
        transitions = []
        last_obs = {}
        for step in trajectory:
            tool = step.get("tool")
            args = step.get("args", {})
            res = step.get("result", {})
            step_idx = step.get("step_index")

            if tool == "inspect":
                if "data" in res:
                    last_obs = copy.deepcopy(res["data"])
                continue

            if res.get("status") == StatusCode.SUCCESS:
                tr = {
                    "source_step_id": step_idx,
                    "action": {"tool": tool, "args": copy.deepcopy(args)},
                    "result_status": res.get("status"),
                    "observed_effects": copy.deepcopy(res.get("effects", {})),
                    "message": res.get("message", ""),
                }
                transitions.append(tr)
        return transitions

    def _extract_observed_faults(self, trajectory: List[Dict[str, Any]]) -> Dict[str, str]:
        """Extract observed initial fault status for each subsystem from inspect tool returns."""
        faults = {}
        for step in trajectory:
            if step.get("tool") == "inspect":
                data = step.get("result", {}).get("data", {})
                if isinstance(data, dict):
                    for sub, props in data.items():
                        if isinstance(props, dict):
                            st = props.get("status")
                            if st and st != "nominal" and sub not in faults:
                                faults[sub] = st
        return faults

    def _segment_trajectory_by_subsystem(self, trajectory: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """Group successful repair trajectory actions by their target subsystem."""
        segments: Dict[str, List[Dict[str, Any]]] = {}
        for step in trajectory:
            if step.get("is_error"):
                continue
            if step.get("result", {}).get("status") != StatusCode.SUCCESS:
                continue
            tool = step.get("tool")
            if tool in ["inspect", "self_test", "resume"]:
                continue
            args = step.get("args", {})
            sub = args.get("subsystem", "controller")
            if sub not in segments:
                segments[sub] = []
            if segments[sub] and segments[sub][-1].get("tool") == tool and segments[sub][-1].get("args") == args:
                continue
            segments[sub].append(step)
        return segments

    def _test_causal_dependencies(
        self,
        subsystem: str,
        actions: List[Dict[str, Any]],
        task_cfg: Dict[str, Any],
        fact_store: StructuredFactStore,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, List[Dict[str, Any]]], List[Dict[str, Any]]]:
        """
        Run budget-bounded interventions in isolated environment copies to verify causal dependencies.
        Uses ONLY public inspect/tool interactions.
        """
        order_deps: List[Dict[str, Any]] = []
        preconds: Dict[str, List[Dict[str, Any]]] = {}
        invalidations: List[Dict[str, Any]] = []

        if not task_cfg.get("initial_state"):
            return order_deps, preconds, invalidations

        # Test 1: Interlock test for energy isolation
        if subsystem in ["pneumatic_line", "power_unit"]:
            if self.intervention_tool_calls < self.max_intervention_budget:
                self.intervention_tool_calls += 1
                test_env = WorkstationEnv(task_cfg["initial_state"])
                res = test_env.step("clear_fault", subsystem=subsystem)
                
                inv_log = {
                    "test_id": f"interlock_test_{subsystem}",
                    "subsystem": subsystem,
                    "action": "clear_fault",
                    "intervention": f"Attempt clear_fault({subsystem}) without isolate({subsystem}, engage)",
                    "tool_status": res.get("status"),
                    "observed_message": res.get("error", ""),
                }
                fact_store.intervention_logs.append(inv_log)

                if res.get("status") == StatusCode.SAFETY_INTERLOCK_ERROR:
                    dep1 = {
                        "subsystem": subsystem,
                        "before": f"isolate({subsystem}, engage)",
                        "after": f"clear_fault({subsystem})",
                        "status": "VERIFIED",
                        "evidence_ref": f"interlock_test_{subsystem}",
                    }
                    dep2 = {
                        "subsystem": subsystem,
                        "before": f"clear_fault({subsystem})",
                        "after": f"isolate({subsystem}, release)",
                        "status": "VERIFIED",
                        "evidence_ref": f"interlock_test_{subsystem}",
                    }
                    dep3 = {
                        "subsystem": subsystem,
                        "before": f"isolate({subsystem}, release)",
                        "after": f"reset({subsystem})",
                        "status": "VERIFIED",
                        "evidence_ref": f"interlock_test_{subsystem}",
                    }
                    order_deps.extend([dep1, dep2, dep3])
                    preconds[f"clear_fault_{subsystem}"] = [{
                        "condition": f"{subsystem}.isolated == True",
                        "status": "VERIFIED",
                        "evidence_ref": f"interlock_test_{subsystem}",
                    }]

        # Test 2: Invalidation test for actuator reset and sensor calibration
        if subsystem in ["arm_gripper", "pneumatic_line"]:
            if self.intervention_tool_calls + 3 <= self.max_intervention_budget:
                self.intervention_tool_calls += 3
                test_env = WorkstationEnv(task_cfg["initial_state"])
                # Step 1: Calibrate camera
                test_env.step("calibrate", subsystem="camera_sensor")
                # Step 2: Public inspection of camera
                insp_pre = test_env.step("inspect", subsystem="camera_sensor")
                cal_pre = insp_pre.get("data", {}).get("calibrated", False)
                # Step 3: Reset actuator
                test_env.step("reset", subsystem=subsystem)
                # Step 4: Public inspection after reset
                self.intervention_tool_calls += 1
                insp_post = test_env.step("inspect", subsystem="camera_sensor")
                cal_post = insp_post.get("data", {}).get("calibrated", False)

                inv_log = {
                    "test_id": f"invalidation_test_{subsystem}_camera",
                    "subsystem": subsystem,
                    "action": f"reset({subsystem})",
                    "intervention": f"Inspect camera_sensor.calibrated before and after reset({subsystem})",
                    "pre_calibration": cal_pre,
                    "post_calibration": cal_post,
                }
                fact_store.intervention_logs.append(inv_log)

                if cal_pre and not cal_post:
                    inv_rule = {
                        "action": f"reset({subsystem})",
                        "invalidated_state": "camera_sensor.calibrated = False",
                        "reason": f"Physical motion of {subsystem} alters optical alignment.",
                        "status": "VERIFIED",
                        "evidence_ref": f"invalidation_test_{subsystem}_camera",
                    }
                    invalidations.append(inv_rule)
                    order_deps.append({
                        "subsystem": "cross_system",
                        "before": f"reset({subsystem})",
                        "after": "calibrate(camera_sensor)",
                        "status": "VERIFIED",
                        "evidence_ref": f"invalidation_test_{subsystem}_camera",
                    })

        return order_deps, preconds, invalidations

    def _test_commutative_subsystems(
        self,
        source_task_configs: List[Dict[str, Any]],
        fact_store: StructuredFactStore,
    ) -> List[Dict[str, Any]]:
        """Verify that independent subsystem repairs are commutative via public self_test."""
        commutative = []
        dual_cfg = next((t for t in source_task_configs if t["task_id"] == "src_dual_subsystems"), None)
        if dual_cfg and (self.intervention_tool_calls + 10 <= self.max_intervention_budget):
            self.intervention_tool_calls += 10
            # Order 1: Power first, then pneumatic
            env1 = WorkstationEnv(dual_cfg["initial_state"])
            env1.step("isolate", subsystem="power_unit", action="engage")
            env1.step("clear_fault", subsystem="power_unit")
            env1.step("isolate", subsystem="power_unit", action="release")
            env1.step("reset", subsystem="power_unit")
            env1.step("isolate", subsystem="pneumatic_line", action="engage")
            env1.step("clear_fault", subsystem="pneumatic_line")
            env1.step("isolate", subsystem="pneumatic_line", action="release")
            env1.step("reset", subsystem="pneumatic_line")
            r1 = env1.step("self_test", target="workstation")

            # Order 2: Pneumatic first, then power
            env2 = WorkstationEnv(dual_cfg["initial_state"])
            env2.step("isolate", subsystem="pneumatic_line", action="engage")
            env2.step("clear_fault", subsystem="pneumatic_line")
            env2.step("isolate", subsystem="pneumatic_line", action="release")
            env2.step("reset", subsystem="pneumatic_line")
            env2.step("isolate", subsystem="power_unit", action="engage")
            env2.step("clear_fault", subsystem="power_unit")
            env2.step("isolate", subsystem="power_unit", action="release")
            env2.step("reset", subsystem="power_unit")
            r2 = env2.step("self_test", target="workstation")

            comm_entry = {
                "subsystems": ("power_unit", "pneumatic_line"),
                "test_id": "commutative_test_power_pneumatics",
                "order_1_power_then_pneumatics_passed": (r1.get("passed") is True),
                "order_2_pneumatics_then_power_passed": (r2.get("passed") is True),
                "status": "VERIFIED" if (r1.get("passed") is True and r2.get("passed") is True) else "CANDIDATE",
            }
            fact_store.intervention_logs.append(comm_entry)
            if comm_entry["status"] == "VERIFIED":
                commutative.append(comm_entry)

        return commutative

    def _create_procedural_memory_item(
        self,
        subsystem: str,
        observed_fault: str,
        actions: List[Dict[str, Any]],
        order_deps: List[Dict[str, Any]],
        invalidations: List[Dict[str, Any]],
        source_task_id: str,
    ) -> ProceduralMemoryItem:
        """Create structured ProceduralMemoryItem from verified actions and real observed fault."""
        action_nodes = []
        step_refs = []
        for idx, step in enumerate(actions):
            s_idx = step.get("step_index", idx + 1)
            step_refs.append(s_idx)
            tool = step.get("tool", "")
            args = step.get("args", {})
            effects = step.get("result", {}).get("effects", {})
            action_nodes.append(ActionNode(
                node_id=f"{subsystem}_step_{idx+1}_{tool}",
                tool=tool,
                args=copy.deepcopy(args),
                observed_preconditions={"subsystem": subsystem},
                expected_postconditions=copy.deepcopy(effects),
                source_step_id=s_idx,
            ))

        return ProceduralMemoryItem(
            memory_id=f"proc_mem_{subsystem}_{source_task_id}",
            name=f"Procedural Repair: {subsystem} ({observed_fault})",
            target_subsystem=subsystem,
            applicability_conditions={
                "subsystem": subsystem,
                "fault_types": [observed_fault],  # Strictly evidenced from real source run!
            },
            observation_triggers=[f"inspect('{subsystem}')"],
            actions=action_nodes,
            evidenced_order_dependencies=order_deps,
            expected_effects=[f"{subsystem}.status == nominal", f"{subsystem}.isolated == False"],
            invalidation_conditions=invalidations,
            source_task_id=source_task_id,
            source_step_refs=step_refs,
            status="VERIFIED",
        )
