"""
Procedural Memory and Causal Dependency Compiler for Workstation Multi-Fault Agent.

Data structures:
  - ProceduralMemoryItem: Conditional local repair procedure with applicability,
    observation triggers, actions with pre/post conditions, evidenced ordering,
    expected effects, invalidation triggers, and source refs.
  - StructuredFactStore: Homologous structured history provided to B2, B1, and D.
  - CausalInterventionCompiler: Extracts real trajectories, executes budget-bounded
    interventions using public tool calls in source environment copies, verifies true
    causal dependencies, and compiles validated procedural memories.
"""
from typing import Dict, Any, List, Optional, Tuple, Set
import copy
import hashlib
import json
from dataclasses import dataclass, field, asdict
from .workstation_env import WorkstationEnv, StatusCode


@dataclass
class ActionNode:
    node_id: str
    tool: str
    args: Dict[str, Any]
    observed_preconditions: Dict[str, Any] = field(default_factory=dict)
    expected_postconditions: Dict[str, Any] = field(default_factory=dict)
    source_evidence_id: Optional[str] = None  # task_id:attempt:step_id


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
    evidence_ids: List[str] = field(default_factory=list)
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
            "evidence_ids": copy.deepcopy(self.evidence_ids),
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
            evidence_ids=d.get("evidence_ids", []),
            status=d.get("status", "VERIFIED"),
        )


class StructuredFactStore:
    """
    Rich structured history repository provided to Group B2, Group B1, and Group D.
    Contains:
      - verified_transitions: list of (evidence_id, action, observed_effects, message)
      - negative_preconditions: errors / interlocks learned from failed attempts
      - action_preconditions: verified preconditions for tools with intervention evidence
      - invalidation_rules: verified side effects of operations (e.g. resets invalidating calibrations)
      - causal_order_constraints: verified orderings within subsystems with intervention evidence
      - commutative_subsystems: verified independent subsystems that can be serviced in any order
      - intervention_logs: complete audit trail of all intervention tests performed
      - total_intervention_tool_calls: exact tool call count executed during compilation
    """
    def __init__(self):
        self.verified_transitions: List[Dict[str, Any]] = []
        self.negative_preconditions: List[Dict[str, Any]] = []
        self.action_preconditions: Dict[str, List[Dict[str, Any]]] = {}
        self.invalidation_rules: List[Dict[str, Any]] = []
        self.causal_order_constraints: List[Dict[str, Any]] = []
        self.commutative_subsystems: List[Dict[str, Any]] = []
        self.intervention_logs: List[Dict[str, Any]] = []
        self.total_intervention_tool_calls: int = 0
        self.metadata: Dict[str, Any] = {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "metadata": copy.deepcopy(self.metadata),
            "verified_transitions": copy.deepcopy(self.verified_transitions),
            "negative_preconditions": copy.deepcopy(self.negative_preconditions),
            "action_preconditions": copy.deepcopy(self.action_preconditions),
            "invalidation_rules": copy.deepcopy(self.invalidation_rules),
            "causal_order_constraints": copy.deepcopy(self.causal_order_constraints),
            "commutative_subsystems": copy.deepcopy(self.commutative_subsystems),
            "intervention_logs": copy.deepcopy(self.intervention_logs),
            "total_intervention_tool_calls": self.total_intervention_tool_calls,
        }

    def compute_hash(self) -> str:
        s = json.dumps(self.to_dict(), sort_keys=True)
        return hashlib.sha256(s.encode("utf-8")).hexdigest()


class ProceduralMemoryStore:
    """Library of validated procedural repair memories for Group D."""
    def __init__(self):
        self.memories: Dict[str, ProceduralMemoryItem] = {}
        self.metadata: Dict[str, Any] = {}

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
        return {
            "metadata": copy.deepcopy(self.metadata),
            "memories": {mid: mem.to_dict() for mid, mem in self.memories.items()}
        }

    def compute_hash(self) -> str:
        s = json.dumps(self.to_dict(), sort_keys=True)
        return hashlib.sha256(s.encode("utf-8")).hexdigest()


class CausalInterventionCompiler:
    """
    Causal Intervention Tester & Homologous Memory Compiler.
    Takes raw episode trajectories from Phase A source tasks, tests ordering & invalidation
    hypotheses via budget-bounded interventions in isolated environment copies using public
    inspection tools, and produces:
      1. StructuredFactStore (for B2, B1, and D)
      2. ProceduralMemoryStore (for D)
    """

    def __init__(self, max_intervention_budget: int = 60):
        self.max_intervention_budget = max_intervention_budget
        self.intervention_tool_calls = 0

    def _step_env(self, env: WorkstationEnv, tool: str, **args) -> Optional[Dict[str, Any]]:
        """Wrapper around env.step that strictly and automatically increments the intervention counter."""
        if self.intervention_tool_calls >= self.max_intervention_budget:
            return None
        self.intervention_tool_calls += 1
        return env.step(tool, **args)

    def compile_from_source_episodes(
        self,
        source_episodes: List[Dict[str, Any]],
        source_task_configs: List[Dict[str, Any]],
    ) -> Tuple[StructuredFactStore, ProceduralMemoryStore]:
        """
        Compile raw source trajectories into StructuredFactStore and ProceduralMemoryStore.
        Preserves all 4 source attempts (including failed attempts) and extracts positive & negative facts.
        """
        fact_store = StructuredFactStore()
        memory_store = ProceduralMemoryStore()

        config_by_id = {t["task_id"]: t for t in source_task_configs}

        attempt_tracker: Dict[str, int] = {}

        for ep in source_episodes:
            traj = ep.get("trajectory", [])
            task_id = ep.get("task_id", "")
            task_cfg = config_by_id.get(task_id, {})
            attempt_tracker[task_id] = attempt_tracker.get(task_id, 0) + 1
            attempt_idx = attempt_tracker[task_id]

            # 1. Extract verified state transitions and negative errors with unique (task_id, attempt, step_id) IDs
            for step in traj:
                step_idx = step.get("step_index", 0)
                evidence_id = f"{task_id}:att{attempt_idx}:step{step_idx}"
                tool = step.get("tool")
                args = step.get("args", {})
                res = step.get("result", {})
                is_err = step.get("is_error", False) or res.get("status") != StatusCode.SUCCESS

                if tool == "inspect":
                    continue

                if not is_err and res.get("status") == StatusCode.SUCCESS:
                    tr = {
                        "evidence_id": evidence_id,
                        "task_id": task_id,
                        "attempt": attempt_idx,
                        "step_id": step_idx,
                        "action": {"tool": tool, "args": copy.deepcopy(args)},
                        "result_status": res.get("status"),
                        "observed_effects": copy.deepcopy(res.get("effects", {})),
                        "message": res.get("message", ""),
                    }
                    if tr not in fact_store.verified_transitions:
                        fact_store.verified_transitions.append(tr)
                else:
                    neg_fact = {
                        "evidence_id": evidence_id,
                        "task_id": task_id,
                        "attempt": attempt_idx,
                        "step_id": step_idx,
                        "action": {"tool": tool, "args": copy.deepcopy(args)},
                        "error_status": res.get("status"),
                        "error_message": res.get("error", ""),
                    }
                    if neg_fact not in fact_store.negative_preconditions:
                        fact_store.negative_preconditions.append(neg_fact)

            if not ep.get("success", False):
                continue

            observed_faults = self._extract_observed_faults(traj)
            subsystem_traces = self._segment_trajectory_by_subsystem(traj)

            for sub, actions in subsystem_traces.items():
                if sub in ["controller", "all"] or not actions:
                    continue

                sub_fault = observed_faults.get(sub)
                if not sub_fault:
                    continue

                order_deps, preconds, invalidations = self._test_causal_dependencies(
                    sub, actions, task_cfg, fact_store, task_id, attempt_idx
                )

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

                mem_item = self._create_procedural_memory_item(
                    sub, sub_fault, actions, order_deps, invalidations, task_id, attempt_idx
                )
                memory_store.add_memory(mem_item)

        commutative = self._test_commutative_subsystems(source_task_configs, fact_store)
        fact_store.commutative_subsystems = commutative
        fact_store.total_intervention_tool_calls = self.intervention_tool_calls

        fact_store.metadata = {
            "compiler_config": {"max_intervention_budget": self.max_intervention_budget},
            "total_intervention_tool_calls": self.intervention_tool_calls,
            "source_episodes_count": len(source_episodes),
        }
        memory_store.metadata = {
            "compiler_config": {"max_intervention_budget": self.max_intervention_budget},
            "total_intervention_tool_calls": self.intervention_tool_calls,
            "compiled_memories_count": len(memory_store.memories),
        }

        return fact_store, memory_store

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
        task_id: str,
        attempt_idx: int,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, List[Dict[str, Any]]], List[Dict[str, Any]]]:
        """
        Run budget-bounded interventions in isolated environment copies to verify causal dependencies.
        Uses ONLY public inspect/tool interactions and tracks tool calls automatically.
        """
        order_deps: List[Dict[str, Any]] = []
        preconds: Dict[str, List[Dict[str, Any]]] = {}
        invalidations: List[Dict[str, Any]] = []

        if not task_cfg.get("initial_state"):
            return order_deps, preconds, invalidations

        # Test 1: Interlock test for energy isolation
        if subsystem in ["pneumatic_line", "power_unit"]:
            test_env = WorkstationEnv(task_cfg["initial_state"])
            res = self._step_env(test_env, "clear_fault", subsystem=subsystem)
            if res is not None:
                test_id = f"intervention_{task_id}_att{attempt_idx}_interlock_{subsystem}"
                inv_log = {
                    "test_id": test_id,
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
                        "evidence_ref": test_id,
                    }
                    order_deps.append(dep1)
                    preconds[f"clear_fault_{subsystem}"] = [{
                        "condition": f"{subsystem}.isolated == True",
                        "status": "VERIFIED",
                        "evidence_ref": test_id,
                    }]

                    # Test 2: Test reset while still isolated
                    env_iso = WorkstationEnv(task_cfg["initial_state"])
                    self._step_env(env_iso, "isolate", subsystem=subsystem, action="engage")
                    self._step_env(env_iso, "clear_fault", subsystem=subsystem)
                    res_reset_iso = self._step_env(env_iso, "reset", subsystem=subsystem)
                    if res_reset_iso is not None:
                        test_id_reset = f"intervention_{task_id}_att{attempt_idx}_reset_iso_{subsystem}"
                        inv_log2 = {
                            "test_id": test_id_reset,
                            "subsystem": subsystem,
                            "action": "reset",
                            "intervention": f"Attempt reset({subsystem}) while still isolated",
                            "tool_status": res_reset_iso.get("status"),
                            "observed_message": res_reset_iso.get("error", ""),
                        }
                        fact_store.intervention_logs.append(inv_log2)
                        
                        if res_reset_iso.get("status") in [StatusCode.SAFETY_INTERLOCK_ERROR, StatusCode.PRECONDITION_NOT_MET]:
                            order_deps.append({
                                "subsystem": subsystem,
                                "before": f"isolate({subsystem}, release)",
                                "after": f"reset({subsystem})",
                                "status": "VERIFIED",
                                "evidence_ref": test_id_reset,
                            })
                        else:
                            order_deps.append({
                                "subsystem": subsystem,
                                "before": f"isolate({subsystem}, release)",
                                "after": f"reset({subsystem})",
                                "status": "CANDIDATE",
                            })

                    # Test 3: Test clear_fault after release vs before release
                    env_rel = WorkstationEnv(task_cfg["initial_state"])
                    self._step_env(env_rel, "isolate", subsystem=subsystem, action="engage")
                    self._step_env(env_rel, "isolate", subsystem=subsystem, action="release")
                    res_cf_rel = self._step_env(env_rel, "clear_fault", subsystem=subsystem)
                    if res_cf_rel is not None:
                        test_id_cf = f"intervention_{task_id}_att{attempt_idx}_clear_after_release_{subsystem}"
                        inv_log3 = {
                            "test_id": test_id_cf,
                            "subsystem": subsystem,
                            "action": "clear_fault",
                            "intervention": f"Attempt clear_fault({subsystem}) after isolate released",
                            "tool_status": res_cf_rel.get("status"),
                            "observed_message": res_cf_rel.get("error", ""),
                        }
                        fact_store.intervention_logs.append(inv_log3)
                        if res_cf_rel.get("status") == StatusCode.SAFETY_INTERLOCK_ERROR:
                            order_deps.append({
                                "subsystem": subsystem,
                                "before": f"clear_fault({subsystem})",
                                "after": f"isolate({subsystem}, release)",
                                "status": "VERIFIED",
                                "evidence_ref": test_id_cf,
                            })

        # Test 4: Invalidation test for actuator reset and sensor calibration
        if subsystem in ["arm_gripper", "pneumatic_line"]:
            test_env = WorkstationEnv(task_cfg["initial_state"])
            test_id_inv = f"intervention_{task_id}_att{attempt_idx}_invalidation_{subsystem}_camera"
            
            # Step 1: Calibrate camera
            r_cal = self._step_env(test_env, "calibrate", subsystem="camera_sensor")
            # Step 2: Public inspection of camera to check if prep succeeded
            insp_pre = self._step_env(test_env, "inspect", subsystem="camera_sensor")
            cal_pre = insp_pre.get("data", {}).get("calibrated", False) if insp_pre else False
            
            prep_succeeded = (r_cal is not None and r_cal.get("status") == StatusCode.SUCCESS and cal_pre is True)

            if prep_succeeded:
                # Step 3: Reset actuator
                r_reset = self._step_env(test_env, "reset", subsystem=subsystem)
                # Step 4: Public inspection after reset
                insp_post = self._step_env(test_env, "inspect", subsystem="camera_sensor")
                cal_post = insp_post.get("data", {}).get("calibrated", False) if insp_post else False

                inv_log = {
                    "test_id": test_id_inv,
                    "subsystem": subsystem,
                    "action": f"reset({subsystem})",
                    "intervention": f"Inspect camera_sensor.calibrated before and after reset({subsystem})",
                    "prep_succeeded": prep_succeeded,
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
                        "evidence_ref": test_id_inv,
                    }
                    invalidations.append(inv_rule)
                    order_deps.append({
                        "subsystem": "cross_system",
                        "before": f"reset({subsystem})",
                        "after": "calibrate(camera_sensor)",
                        "status": "VERIFIED",
                        "evidence_ref": test_id_inv,
                    })
            else:
                inv_log = {
                    "test_id": test_id_inv,
                    "subsystem": subsystem,
                    "action": f"reset({subsystem})",
                    "intervention": f"Prep calibration on camera_sensor failed (cannot test invalidation)",
                    "prep_succeeded": False,
                }
                fact_store.intervention_logs.append(inv_log)

        return order_deps, preconds, invalidations

    def _test_commutative_subsystems(
        self,
        source_task_configs: List[Dict[str, Any]],
        fact_store: StructuredFactStore,
    ) -> List[Dict[str, Any]]:
        """Verify that independent subsystem repairs are commutative via public self_test."""
        commutative = []
        dual_cfg = next((t for t in source_task_configs if t["task_id"] == "src_dual_subsystems"), None)
        if dual_cfg and (self.intervention_tool_calls + 18 <= self.max_intervention_budget):
            # Order 1: Power first, then pneumatic
            env1 = WorkstationEnv(dual_cfg["initial_state"])
            self._step_env(env1, "isolate", subsystem="power_unit", action="engage")
            self._step_env(env1, "clear_fault", subsystem="power_unit")
            self._step_env(env1, "isolate", subsystem="power_unit", action="release")
            self._step_env(env1, "reset", subsystem="power_unit")
            self._step_env(env1, "isolate", subsystem="pneumatic_line", action="engage")
            self._step_env(env1, "clear_fault", subsystem="pneumatic_line")
            self._step_env(env1, "isolate", subsystem="pneumatic_line", action="release")
            self._step_env(env1, "reset", subsystem="pneumatic_line")
            r1 = self._step_env(env1, "self_test", target="workstation")

            # Order 2: Pneumatic first, then power
            env2 = WorkstationEnv(dual_cfg["initial_state"])
            self._step_env(env2, "isolate", subsystem="pneumatic_line", action="engage")
            self._step_env(env2, "clear_fault", subsystem="pneumatic_line")
            self._step_env(env2, "isolate", subsystem="pneumatic_line", action="release")
            self._step_env(env2, "reset", subsystem="pneumatic_line")
            self._step_env(env2, "isolate", subsystem="power_unit", action="engage")
            self._step_env(env2, "clear_fault", subsystem="power_unit")
            self._step_env(env2, "isolate", subsystem="power_unit", action="release")
            self._step_env(env2, "reset", subsystem="power_unit")
            r2 = self._step_env(env2, "self_test", target="workstation")

            if r1 is not None and r2 is not None:
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
        attempt_idx: int,
    ) -> ProceduralMemoryItem:
        """Create structured ProceduralMemoryItem from verified actions and real observed fault."""
        action_nodes = []
        step_refs = []
        evidence_ids = []
        for idx, step in enumerate(actions):
            s_idx = step.get("step_index", idx + 1)
            step_refs.append(s_idx)
            e_id = f"{source_task_id}:att{attempt_idx}:step{s_idx}"
            evidence_ids.append(e_id)
            tool = step.get("tool", "")
            args = step.get("args", {})
            effects = step.get("result", {}).get("effects", {})
            action_nodes.append(ActionNode(
                node_id=f"{subsystem}_step_{idx+1}_{tool}",
                tool=tool,
                args=copy.deepcopy(args),
                observed_preconditions={"subsystem": subsystem},
                expected_postconditions=copy.deepcopy(effects),
                source_evidence_id=e_id,
            ))

        return ProceduralMemoryItem(
            memory_id=f"proc_mem_{subsystem}_{source_task_id}",
            name=f"Procedural Repair: {subsystem} ({observed_fault})",
            target_subsystem=subsystem,
            applicability_conditions={
                "subsystem": subsystem,
                "fault_types": [observed_fault],
            },
            observation_triggers=[f"inspect({subsystem})"],
            actions=action_nodes,
            evidenced_order_dependencies=order_deps,
            expected_effects=[f"{subsystem}.status == nominal", f"{subsystem}.isolated == False"],
            invalidation_conditions=invalidations,
            source_task_id=source_task_id,
            source_step_refs=step_refs,
            evidence_ids=evidence_ids,
            status="VERIFIED",
        )
