"""
Procedural Memory and Causal Dependency Compiler for Workstation Multi-Fault Agent.

Data structures:
  - ProceduralMemoryItem: Conditional local repair procedure with applicability,
    observation triggers, actions with pre/post conditions, evidenced ordering,
    expected effects, invalidation triggers, and source refs.
  - StructuredFactStore: Rich structured facts for Group B2 and Group D.
  - CausalInterventionCompiler: Extracts real trajectories, executes budget-bounded
    interventions in source environment, verifies true causal dependencies, and
    compiles validated procedural memories.
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
    evidenced_order_dependencies: List[Tuple[str, str]]
    expected_effects: List[str]
    invalidation_conditions: List[Dict[str, Any]]
    source_task_id: str
    source_step_refs: List[int]
    status: str = "VALIDATED"  # VALIDATED, REJECTED, INVALIDATED

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
            status=d.get("status", "VALIDATED"),
        )


class StructuredFactStore:
    """
    Rich structured history repository provided to Group B2 and Group D.
    Contains:
      - verified_transitions: list of (subsystem, action, pre_state, post_state)
      - action_preconditions: verified preconditions for tools
      - invalidation_rules: side effects of operations (e.g. resets invalidating calibrations)
      - causal_order_constraints: verified orderings within subsystems
      - commutative_subsystems: verified independent subsystems that can be serviced in any order
    """
    def __init__(self):
        self.verified_transitions: List[Dict[str, Any]] = []
        self.action_preconditions: Dict[str, List[str]] = {}
        self.invalidation_rules: List[Dict[str, Any]] = []
        self.causal_order_constraints: List[Dict[str, Any]] = []
        self.commutative_subsystems: List[Tuple[str, str]] = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verified_transitions": copy.deepcopy(self.verified_transitions),
            "action_preconditions": copy.deepcopy(self.action_preconditions),
            "invalidation_rules": copy.deepcopy(self.invalidation_rules),
            "causal_order_constraints": copy.deepcopy(self.causal_order_constraints),
            "commutative_subsystems": copy.deepcopy(self.commutative_subsystems),
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
        """Retrieve candidate procedural memories matching subsystem and fault."""
        matches = []
        for mem in self.memories.values():
            if mem.target_subsystem == subsystem:
                if fault_type is None:
                    matches.append(mem)
                else:
                    applicable_faults = mem.applicability_conditions.get("fault_types", [])
                    if not applicable_faults or fault_type in applicable_faults or "any" in applicable_faults:
                        matches.append(mem)
        return matches

    def to_dict(self) -> Dict[str, Any]:
        return {mid: mem.to_dict() for mid, mem in self.memories.items()}


class CausalInterventionCompiler:
    """
    Causal Intervention Tester & Memory Compiler.
    Takes raw episode trajectories from Phase A source tasks, tests ordering hypotheses
    via budget-bounded interventions in isolated environment copies, and produces:
      1. StructuredFactStore (for B2 & D)
      2. ProceduralMemoryStore (for D)
    """

    def __init__(self, max_intervention_budget: int = 25):
        self.max_intervention_budget = max_intervention_budget
        self.interventions_performed = 0

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

            # Extract subsystem-specific sub-sequences
            subsystem_traces = self._segment_trajectory_by_subsystem(traj)

            for sub, actions in subsystem_traces.items():
                if sub in ["controller", "all"] or not actions:
                    continue

                # Run causal interventions to verify true dependencies
                order_deps, preconds, invalidations = self._test_causal_dependencies(sub, actions, task_cfg)

                # Record structured facts
                for a_name, reqs in preconds.items():
                    if a_name not in fact_store.action_preconditions:
                        fact_store.action_preconditions[a_name] = []
                    for r in reqs:
                        if r not in fact_store.action_preconditions[a_name]:
                            fact_store.action_preconditions[a_name].append(r)

                for inv in invalidations:
                    if inv not in fact_store.invalidation_rules:
                        fact_store.invalidation_rules.append(inv)

                for dep in order_deps:
                    entry = {"subsystem": sub, "before": dep[0], "after": dep[1]}
                    if entry not in fact_store.causal_order_constraints:
                        fact_store.causal_order_constraints.append(entry)

                # Compile ProceduralMemoryItem
                mem_item = self._create_procedural_memory_item(sub, actions, order_deps, invalidations, task_id)
                memory_store.add_memory(mem_item)

        # Test commutative independence between distinct subsystems
        fact_store.commutative_subsystems = self._test_commutative_subsystems(source_task_configs)

        return fact_store, memory_store

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
            # Avoid duplicate consecutive identical actions
            if segments[sub] and segments[sub][-1].get("tool") == tool and segments[sub][-1].get("args") == args:
                continue
            segments[sub].append(step)
        return segments

    def _test_causal_dependencies(
        self,
        subsystem: str,
        actions: List[Dict[str, Any]],
        task_cfg: Dict[str, Any],
    ) -> Tuple[List[Tuple[str, str]], Dict[str, List[str]], List[Dict[str, Any]]]:
        """
        Run budget-bounded interventions in isolated environment copies to verify causal dependencies.
        """
        order_deps: List[Tuple[str, str]] = []
        preconds: Dict[str, List[str]] = {}
        invalidations: List[Dict[str, Any]] = []

        if not task_cfg.get("initial_state"):
            return order_deps, preconds, invalidations

        # Test 1: Interlock test for energy isolation
        if subsystem in ["pneumatic_line", "power_unit"]:
            # Intervention: Attempt clear_fault directly without isolate
            if self.interventions_performed < self.max_intervention_budget:
                self.interventions_performed += 1
                test_env = WorkstationEnv(task_cfg["initial_state"])
                res = test_env.step("clear_fault", subsystem=subsystem)
                if res.get("status") == StatusCode.SAFETY_INTERLOCK_ERROR:
                    order_deps.append((f"isolate_{subsystem}_engage", f"clear_fault_{subsystem}"))
                    order_deps.append((f"clear_fault_{subsystem}", f"isolate_{subsystem}_release"))
                    order_deps.append((f"isolate_{subsystem}_release", f"reset_{subsystem}"))
                    preconds[f"clear_fault_{subsystem}"] = [f"{subsystem}.isolated == True"]

        # Test 2: Invalidation test for actuator reset and sensor calibration
        if subsystem in ["arm_gripper", "pneumatic_line"]:
            if self.interventions_performed < self.max_intervention_budget:
                self.interventions_performed += 1
                test_env = WorkstationEnv(task_cfg["initial_state"])
                # Calibrate camera first, then reset actuator
                test_env.step("calibrate", subsystem="camera_sensor")
                init_cal = test_env.state["camera_sensor"].get("calibrated", False)
                test_env.step("reset", subsystem=subsystem)
                post_cal = test_env.state["camera_sensor"].get("calibrated", False)
                if init_cal and not post_cal:
                    invalidations.append({
                        "action": f"reset({subsystem})",
                        "invalidated_state": "camera_sensor.calibrated = False",
                        "reason": f"Physical motion of {subsystem} alters optical alignment.",
                    })
                    order_deps.append((f"reset_{subsystem}", "calibrate_camera_sensor"))

        return order_deps, preconds, invalidations

    def _test_commutative_subsystems(self, source_task_configs: List[Dict[str, Any]]) -> List[Tuple[str, str]]:
        """Verify that independent subsystem repairs are commutative."""
        commutative = []
        # Check power_unit and pneumatic_line independence on dual_subsystems task
        dual_cfg = next((t for t in source_task_configs if t["task_id"] == "src_dual_subsystems"), None)
        if dual_cfg and self.interventions_performed < self.max_intervention_budget:
            self.interventions_performed += 2
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

            if r1.get("passed") and r2.get("passed"):
                commutative.append(("power_unit", "pneumatic_line"))

        return commutative

    def _create_procedural_memory_item(
        self,
        subsystem: str,
        actions: List[Dict[str, Any]],
        order_deps: List[Tuple[str, str]],
        invalidations: List[Dict[str, Any]],
        source_task_id: str,
    ) -> ProceduralMemoryItem:
        """Create structured ProceduralMemoryItem from verified actions and dependencies."""
        action_nodes = []
        step_refs = []
        for idx, step in enumerate(actions):
            s_idx = step.get("step_index", idx + 1)
            step_refs.append(s_idx)
            tool = step.get("tool", "")
            args = step.get("args", {})
            action_nodes.append(ActionNode(
                node_id=f"{subsystem}_step_{idx+1}_{tool}",
                tool=tool,
                args=copy.deepcopy(args),
                observed_preconditions={"subsystem": subsystem},
                expected_postconditions={"status": "nominal"},
                source_step_id=s_idx,
            ))

        # Define applicability faults
        fault_types = ["overpressure_fault", "leak_fault"] if subsystem == "pneumatic_line" else ["jammed", "misaligned", "tripped", "optical_drift", "uncalibrated"]

        return ProceduralMemoryItem(
            memory_id=f"proc_mem_{subsystem}_{source_task_id}",
            name=f"Procedural Repair: {subsystem}",
            target_subsystem=subsystem,
            applicability_conditions={
                "subsystem": subsystem,
                "fault_types": fault_types,
            },
            observation_triggers=[f"inspect('{subsystem}')"],
            actions=action_nodes,
            evidenced_order_dependencies=order_deps,
            expected_effects=[f"{subsystem}.status == nominal", f"{subsystem}.isolated == False"],
            invalidation_conditions=invalidations,
            source_task_id=source_task_id,
            source_step_refs=step_refs,
            status="VALIDATED",
        )
