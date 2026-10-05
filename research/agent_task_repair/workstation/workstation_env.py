"""
Simulated Robot Workstation Multi-Fault Diagnosis and Recovery Environment.

NOTE: This is a discrete, simulated benchmark environment for evaluating agentic
planning and procedural memory with non-trivial causal dependencies, interlocks,
and state invalidation. It is NOT a physical robot deployment.
"""
from typing import Dict, Any, List, Optional, Tuple
import copy


class StatusCode:
    SUCCESS = "SUCCESS"
    SAFETY_INTERLOCK_ERROR = "SAFETY_INTERLOCK_ERROR"
    POWER_INTERLOCK_ERROR = "POWER_INTERLOCK_ERROR"
    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    PRECONDITION_NOT_MET = "PRECONDITION_NOT_MET"
    SYSTEM_NOT_READY = "SYSTEM_NOT_READY"


class WorkstationEnv:
    """
    Simulated Workstation with 5 Subsystems:
      1. power_unit (Primary power & safety relay)
      2. pneumatic_line (Pneumatic pressure supply)
      3. arm_gripper (Robotic arm & gripper actuator)
      4. camera_sensor (Vision & inspection sensor)
      5. controller (Workstation safety & sequence controller)
    """

    DEFAULT_CONFIG = {
        "power_unit": {"status": "nominal", "isolated": False, "voltage_v": 24.0},
        "pneumatic_line": {"status": "nominal", "isolated": False, "pressure_bar": 5.0},
        "arm_gripper": {"status": "nominal", "holding_load": False, "calibrated": True},
        "camera_sensor": {"status": "nominal", "calibrated": True, "drift_offset_mm": 0.0},
        "controller": {"status": "nominal", "self_test_passed": False, "resumed": False},
    }

    def __init__(self, initial_config: Optional[Dict[str, Any]] = None):
        self.initial_config = copy.deepcopy(initial_config) if initial_config else copy.deepcopy(self.DEFAULT_CONFIG)
        self.state: Dict[str, Any] = {}
        self.step_history: List[Dict[str, Any]] = []
        self.invalidation_events: List[Dict[str, Any]] = []
        self.reset()

    def reset(self) -> Dict[str, Any]:
        """Reset environment to initial state."""
        self.state = copy.deepcopy(self.initial_config)
        for sub, default_props in self.DEFAULT_CONFIG.items():
            if sub not in self.state:
                self.state[sub] = copy.deepcopy(default_props)
            else:
                for k, v in default_props.items():
                    if k not in self.state[sub]:
                        self.state[sub][k] = copy.deepcopy(v)
        self.step_history = []
        self.invalidation_events = []
        return self.get_summary()

    def get_summary(self) -> Dict[str, Any]:
        """Return high-level status summary for environment."""
        return {
            "subsystems": {sub: copy.deepcopy(data) for sub, data in self.state.items() if sub != "controller"},
            "self_test_passed": self.state["controller"]["self_test_passed"],
            "resumed": self.state["controller"]["resumed"],
        }

    # -------------------------------------------------------------------------
    # Tool 1: inspect
    # -------------------------------------------------------------------------
    def inspect(self, subsystem: str) -> Dict[str, Any]:
        """
        Inspect the status of a subsystem or all subsystems.
        Allowed values for subsystem: 'power_unit', 'pneumatic_line', 'arm_gripper', 'camera_sensor', 'controller', 'all'.
        """
        subsystem = subsystem.strip().lower()
        if subsystem == "all":
            res = {
                "status": StatusCode.SUCCESS,
                "data": {sub: copy.deepcopy(props) for sub, props in self.state.items()},
                "message": "Full workstation inspection report generated.",
            }
            self._record_step("inspect", {"subsystem": subsystem}, res)
            return res

        if subsystem not in self.state:
            res = {
                "status": StatusCode.INVALID_ARGUMENT,
                "error": f"Unknown subsystem '{subsystem}'. Valid subsystems: {list(self.state.keys()) + ['all']}",
            }
            self._record_step("inspect", {"subsystem": subsystem}, res)
            return res

        sub_data = copy.deepcopy(self.state[subsystem])
        res = {
            "status": StatusCode.SUCCESS,
            "subsystem": subsystem,
            "data": sub_data,
            "message": f"Inspection of '{subsystem}' complete.",
        }
        self._record_step("inspect", {"subsystem": subsystem}, res)
        return res

    # -------------------------------------------------------------------------
    # Tool 2: isolate
    # -------------------------------------------------------------------------
    def isolate(self, subsystem: str, action: str) -> Dict[str, Any]:
        """
        Engage or release safety isolation (lockout/tagout) on a subsystem.
        subsystem: 'power_unit' or 'pneumatic_line'
        action: 'engage' (isolate) or 'release' (restore)
        """
        subsystem = subsystem.strip().lower()
        action = action.strip().lower()

        if subsystem not in ["power_unit", "pneumatic_line"]:
            res = {
                "status": StatusCode.INVALID_ARGUMENT,
                "error": f"Isolation only applicable to energy lines: 'power_unit' or 'pneumatic_line'. Given: '{subsystem}'",
            }
            self._record_step("isolate", {"subsystem": subsystem, "action": action}, res)
            return res

        if action not in ["engage", "release"]:
            res = {
                "status": StatusCode.INVALID_ARGUMENT,
                "error": f"Action must be 'engage' (isolate) or 'release' (reopen). Given: '{action}'",
            }
            self._record_step("isolate", {"subsystem": subsystem, "action": action}, res)
            return res

        if action == "engage":
            self.state[subsystem]["isolated"] = True
            if subsystem == "pneumatic_line":
                self.state[subsystem]["pressure_bar"] = 0.0
            elif subsystem == "power_unit":
                self.state[subsystem]["voltage_v"] = 0.0
            res = {
                "status": StatusCode.SUCCESS,
                "subsystem": subsystem,
                "isolated": True,
                "effects": {"isolated": True, "pressure_bar" if subsystem == "pneumatic_line" else "voltage_v": 0.0},
                "message": f"Safety isolation ENGAGED on '{subsystem}'. Energy discharged to zero.",
            }
        else:  # release
            self.state[subsystem]["isolated"] = False
            if subsystem == "pneumatic_line":
                if self.state[subsystem]["status"] == "nominal":
                    self.state[subsystem]["pressure_bar"] = 5.0
                elif self.state[subsystem]["status"] == "overpressure_fault":
                    self.state[subsystem]["pressure_bar"] = 8.5
                elif self.state[subsystem]["status"] == "leak_fault":
                    self.state[subsystem]["pressure_bar"] = 1.2
            elif subsystem == "power_unit":
                self.state[subsystem]["voltage_v"] = 24.0 if self.state[subsystem]["status"] == "nominal" else 0.0
            res = {
                "status": StatusCode.SUCCESS,
                "subsystem": subsystem,
                "isolated": False,
                "effects": {"isolated": False, "pressure_bar" if subsystem == "pneumatic_line" else "voltage_v": self.state[subsystem].get("pressure_bar" if subsystem == "pneumatic_line" else "voltage_v")},
                "message": f"Safety isolation RELEASED on '{subsystem}'. Line re-energized.",
            }

        self._record_step("isolate", {"subsystem": subsystem, "action": action}, res)
        return res

    # -------------------------------------------------------------------------
    # Tool 3: clear_fault
    # -------------------------------------------------------------------------
    def clear_fault(self, subsystem: str) -> Dict[str, Any]:
        """
        Clear physical or software fault on a subsystem.
        Physical interlock rules:
          - pneumatic_line: Must be isolated before clearing fault (safety lockout).
          - power_unit: Must be isolated before servicing power relay/fuse.
          - arm_gripper: If holding_load is True, clearing fault releases the jammed load safely.
          - camera_sensor: Requires power_unit to be active/nominal.
        """
        subsystem = subsystem.strip().lower()
        if subsystem not in self.state:
            res = {
                "status": StatusCode.INVALID_ARGUMENT,
                "error": f"Unknown subsystem '{subsystem}'.",
            }
            self._record_step("clear_fault", {"subsystem": subsystem}, res)
            return res

        # Interlock checks
        if subsystem == "pneumatic_line":
            if not self.state["pneumatic_line"].get("isolated", False):
                res = {
                    "status": StatusCode.SAFETY_INTERLOCK_ERROR,
                    "error": "Safety Interlock: Cannot service pneumatic_line while pressurized! You MUST call isolate(subsystem='pneumatic_line', action='engage') first.",
                }
                self._record_step("clear_fault", {"subsystem": subsystem}, res)
                return res

        elif subsystem == "power_unit":
            if not self.state["power_unit"].get("isolated", False):
                res = {
                    "status": StatusCode.SAFETY_INTERLOCK_ERROR,
                    "error": "Safety Interlock: Cannot replace power fuse/relay under live circuit! You MUST call isolate(subsystem='power_unit', action='engage') first.",
                }
                self._record_step("clear_fault", {"subsystem": subsystem}, res)
                return res

        elif subsystem in ["camera_sensor", "controller"]:
            if self.state["power_unit"].get("status") != "nominal" or self.state["power_unit"].get("isolated", False):
                res = {
                    "status": StatusCode.POWER_INTERLOCK_ERROR,
                    "error": f"Power Interlock: Cannot clear {subsystem} fault while power_unit is tripped or isolated.",
                }
                self._record_step("clear_fault", {"subsystem": subsystem}, res)
                return res

        # Perform fault clearing
        old_status = self.state[subsystem].get("status")
        self.state[subsystem]["status"] = "nominal"

        effects: Dict[str, Any] = {"status": "nominal"}

        # Side effect on load
        if subsystem == "arm_gripper" and self.state["arm_gripper"].get("holding_load", False):
            self.state["arm_gripper"]["holding_load"] = False
            effects["holding_load"] = False

        # Invalidation trigger: Clearing hardware faults on arm_gripper or pneumatic_line
        # physically shifts mechanisms, invalidating existing sensor calibration and self_test!
        if subsystem in ["arm_gripper", "pneumatic_line"]:
            if self.state["camera_sensor"].get("calibrated", False):
                self.state["camera_sensor"]["calibrated"] = False
                effects["camera_sensor_calibrated_invalidated"] = False
                inv = {
                    "trigger_action": f"clear_fault({subsystem})",
                    "invalidated_target": "camera_sensor.calibrated",
                    "reason": f"Physical movement during {subsystem} repair altered mechanical alignment.",
                }
                self.invalidation_events.append(inv)

        self.state["controller"]["self_test_passed"] = False

        res = {
            "status": StatusCode.SUCCESS,
            "subsystem": subsystem,
            "previous_status": old_status,
            "current_status": "nominal",
            "effects": effects,
            "message": f"Fault on '{subsystem}' successfully cleared." + (" Workpiece load safely released." if effects.get("holding_load") is False else ""),
        }
        self._record_step("clear_fault", {"subsystem": subsystem}, res)
        return res

    # -------------------------------------------------------------------------
    # Tool 4: reset
    # -------------------------------------------------------------------------
    def reset_subsystem(self, subsystem: str) -> Dict[str, Any]:
        """
        Reset physical mechanism or controller state for a subsystem.
        Rules:
          - pneumatic_line: Restores operating pressure once isolation is released.
          - power_unit: Closes main contactor once isolation is released.
          - arm_gripper: Returns arm to home position. Requires power_unit nominal and not isolated.
            Invalidates camera_sensor calibration.
          - controller: Resets error logs and counters.
        """
        subsystem = subsystem.strip().lower()
        if subsystem not in self.state:
            res = {
                "status": StatusCode.INVALID_ARGUMENT,
                "error": f"Unknown subsystem '{subsystem}'.",
            }
            self._record_step("reset", {"subsystem": subsystem}, res)
            return res

        effects: Dict[str, Any] = {"reset": True}

        if subsystem == "pneumatic_line":
            if self.state["pneumatic_line"].get("isolated", False):
                res = {
                    "status": StatusCode.PRECONDITION_NOT_MET,
                    "error": "Pneumatic line is still isolated. Release isolation before reset.",
                }
                self._record_step("reset", {"subsystem": subsystem}, res)
                return res
            self.state["pneumatic_line"]["pressure_bar"] = 5.0
            effects["pressure_bar"] = 5.0

        elif subsystem == "power_unit":
            if self.state["power_unit"].get("isolated", False):
                res = {
                    "status": StatusCode.PRECONDITION_NOT_MET,
                    "error": "Power unit is still isolated. Release isolation before reset.",
                }
                self._record_step("reset", {"subsystem": subsystem}, res)
                return res
            self.state["power_unit"]["voltage_v"] = 24.0
            effects["voltage_v"] = 24.0

        elif subsystem == "arm_gripper":
            if self.state["power_unit"].get("status") != "nominal" or self.state["power_unit"].get("isolated", False):
                res = {
                    "status": StatusCode.POWER_INTERLOCK_ERROR,
                    "error": "Power Interlock: Cannot reset arm_gripper without nominal power.",
                }
                self._record_step("reset", {"subsystem": subsystem}, res)
                return res
            if self.state["arm_gripper"].get("holding_load", False):
                res = {
                    "status": StatusCode.SAFETY_INTERLOCK_ERROR,
                    "error": "Safety Interlock: Cannot home arm_gripper while holding unsecured workpiece. Clear fault / release load first.",
                }
                self._record_step("reset", {"subsystem": subsystem}, res)
                return res

            # Invalidation trigger: Arm homing invalidates camera alignment calibration!
            if self.state["camera_sensor"].get("calibrated", False):
                self.state["camera_sensor"]["calibrated"] = False
                effects["camera_sensor_calibrated_invalidated"] = False
                inv = {
                    "trigger_action": "reset(arm_gripper)",
                    "invalidated_target": "camera_sensor.calibrated",
                    "reason": "Homing motion changed mechanical reference frame; camera sensor calibration invalidated.",
                }
                self.invalidation_events.append(inv)

        self.state["controller"]["self_test_passed"] = False
        res = {
            "status": StatusCode.SUCCESS,
            "subsystem": subsystem,
            "effects": effects,
            "message": f"Subsystem '{subsystem}' successfully reset to home/operating state.",
        }
        self._record_step("reset", {"subsystem": subsystem}, res)
        return res

    # -------------------------------------------------------------------------
    # Tool 5: calibrate
    # -------------------------------------------------------------------------
    def calibrate(self, subsystem: str) -> Dict[str, Any]:
        """
        Perform calibration sequence on camera_sensor or arm_gripper.
        Preconditions:
          - Subsystem must be nominal (no active faults).
          - power_unit must be nominal and not isolated.
        """
        subsystem = subsystem.strip().lower()
        if subsystem not in ["camera_sensor", "arm_gripper"]:
            res = {
                "status": StatusCode.INVALID_ARGUMENT,
                "error": f"Calibration only supported for 'camera_sensor' or 'arm_gripper'. Given: '{subsystem}'",
            }
            self._record_step("calibrate", {"subsystem": subsystem}, res)
            return res

        if self.state["power_unit"].get("status") != "nominal" or self.state["power_unit"].get("isolated", False):
            res = {
                "status": StatusCode.POWER_INTERLOCK_ERROR,
                "error": f"Power Interlock: Cannot calibrate {subsystem} when power_unit is tripped or isolated.",
            }
            self._record_step("calibrate", {"subsystem": subsystem}, res)
            return res

        if self.state[subsystem].get("status") != "nominal":
            res = {
                "status": StatusCode.PRECONDITION_NOT_MET,
                "error": f"Precondition Failed: Cannot calibrate '{subsystem}' with active fault status '{self.state[subsystem].get('status')}'. Must clear fault first.",
            }
            self._record_step("calibrate", {"subsystem": subsystem}, res)
            return res

        self.state[subsystem]["calibrated"] = True
        effects: Dict[str, Any] = {"calibrated": True}
        if subsystem == "camera_sensor":
            self.state["camera_sensor"]["drift_offset_mm"] = 0.0
            effects["drift_offset_mm"] = 0.0

        res = {
            "status": StatusCode.SUCCESS,
            "subsystem": subsystem,
            "calibrated": True,
            "effects": effects,
            "message": f"Calibration of '{subsystem}' completed successfully.",
        }
        self._record_step("calibrate", {"subsystem": subsystem}, res)
        return res

    # -------------------------------------------------------------------------
    # Tool 6: self_test
    # -------------------------------------------------------------------------
    def self_test(self, target: str = "workstation") -> Dict[str, Any]:
        """
        Run workstation integration self-test.
        Verifies all 5 subsystems are nominal, not isolated, and calibrated.
        """
        target = target.strip().lower()
        errors = []

        # Check power
        if self.state["power_unit"].get("status") != "nominal":
            errors.append("power_unit status is not nominal (tripped)")
        if self.state["power_unit"].get("isolated", False):
            errors.append("power_unit is still isolated (safety lockout active)")

        # Check pneumatics
        if self.state["pneumatic_line"].get("status") != "nominal":
            errors.append(f"pneumatic_line has active fault: {self.state['pneumatic_line'].get('status')}")
        if self.state["pneumatic_line"].get("isolated", False):
            errors.append("pneumatic_line is still isolated (supply valve closed)")
        elif self.state["pneumatic_line"].get("pressure_bar", 0.0) < 4.0:
            errors.append(f"pneumatic pressure low ({self.state['pneumatic_line'].get('pressure_bar')} bar < 4.0 bar)")

        # Check arm
        if self.state["arm_gripper"].get("status") != "nominal":
            errors.append(f"arm_gripper has active fault: {self.state['arm_gripper'].get('status')}")
        if self.state["arm_gripper"].get("holding_load", False):
            errors.append("arm_gripper is holding unsecured load")

        # Check camera
        if self.state["camera_sensor"].get("status") != "nominal":
            errors.append(f"camera_sensor has active fault: {self.state['camera_sensor'].get('status')}")
        if not self.state["camera_sensor"].get("calibrated", False):
            errors.append("camera_sensor is NOT calibrated")

        if errors:
            self.state["controller"]["self_test_passed"] = False
            res = {
                "status": StatusCode.SYSTEM_NOT_READY,
                "passed": False,
                "unmet_conditions": errors,
                "effects": {"self_test_passed": False},
                "message": f"Workstation self-test FAILED ({len(errors)} unmet condition(s)).",
            }
        else:
            self.state["controller"]["self_test_passed"] = True
            res = {
                "status": StatusCode.SUCCESS,
                "passed": True,
                "effects": {"self_test_passed": True},
                "message": "All 5 subsystems passed self-test. Ready for resumption.",
            }

        self._record_step("self_test", {"target": target}, res)
        return res

    # -------------------------------------------------------------------------
    # Tool 7: resume
    # -------------------------------------------------------------------------
    def resume(self, target: str = "workstation") -> Dict[str, Any]:
        """
        Resume workstation production.
        Precondition: self_test_passed must be True.
        """
        target = target.strip().lower()
        if not self.state["controller"].get("self_test_passed", False):
            res = {
                "status": StatusCode.SAFETY_INTERLOCK_ERROR,
                "error": "Safety Interlock: Cannot resume workstation without a successful self_test. Call self_test('workstation') first.",
            }
            self._record_step("resume", {"target": target}, res)
            return res

        self.state["controller"]["resumed"] = True
        res = {
            "status": StatusCode.SUCCESS,
            "resumed": True,
            "effects": {"resumed": True},
            "message": "Workstation production RESUMED successfully. Task objective achieved.",
        }
        self._record_step("resume", {"target": target}, res)
        return res

    # -------------------------------------------------------------------------
    # Unified step dispatcher
    # -------------------------------------------------------------------------
    def step(self, tool_name: str, **kwargs) -> Dict[str, Any]:
        """Execute a tool action by name."""
        tool_map = {
            "inspect": lambda: self.inspect(kwargs.get("subsystem", "all")),
            "isolate": lambda: self.isolate(kwargs.get("subsystem", ""), kwargs.get("action", "")),
            "clear_fault": lambda: self.clear_fault(kwargs.get("subsystem", "")),
            "reset": lambda: self.reset_subsystem(kwargs.get("subsystem", "")),
            "calibrate": lambda: self.calibrate(kwargs.get("subsystem", "")),
            "self_test": lambda: self.self_test(kwargs.get("target", "workstation")),
            "resume": lambda: self.resume(kwargs.get("target", "workstation")),
        }

        if tool_name not in tool_map:
            res = {
                "status": StatusCode.INVALID_ARGUMENT,
                "error": f"Unknown tool '{tool_name}'. Available tools: {list(tool_map.keys())}",
            }
            self._record_step(tool_name, kwargs, res)
            return res

        return tool_map[tool_name]()

    def _record_step(self, tool: str, args: Dict[str, Any], result: Dict[str, Any]):
        self.step_history.append({
            "step_index": len(self.step_history) + 1,
            "tool": tool,
            "args": copy.deepcopy(args),
            "result": copy.deepcopy(result),
            "is_error": result.get("status") != StatusCode.SUCCESS,
        })

    def is_task_completed(self) -> bool:
        """Check if production has resumed successfully."""
        return bool(self.state["controller"].get("resumed", False))
