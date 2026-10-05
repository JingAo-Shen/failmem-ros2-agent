"""
Task Definitions for Robot Workstation Multi-Fault Diagnosis and Recovery.

Defines:
  - 3 Source Tasks (Phase A) for experience acquisition and causal intervention testing
  - 8 Target Tasks (Phase B) across 4 Transfer Classes (A, B, C, D)
"""
from typing import Dict, Any, List


def get_source_tasks() -> List[Dict[str, Any]]:
    """
    3 Source Tasks for experience generation:
      1. src_pneumatic: Single fault on pneumatic_line (overpressure_fault)
      2. src_sensor_actuator: Dual faults on arm_gripper (jammed) and camera_sensor (optical_drift)
      3. src_dual_subsystems: Dual faults on power_unit (tripped) and pneumatic_line (leak_fault)
    """
    return [
        {
            "task_id": "src_pneumatic",
            "name": "Source 1: Pneumatic Overpressure Recovery",
            "goal": "Diagnose workstation status, clear pneumatic line overpressure fault, perform self-test, and resume production.",
            "initial_state": {
                "power_unit": {"status": "nominal", "isolated": False, "voltage_v": 24.0},
                "pneumatic_line": {"status": "overpressure_fault", "isolated": False, "pressure_bar": 8.5},
                "arm_gripper": {"status": "nominal", "holding_load": False, "calibrated": True},
                "camera_sensor": {"status": "nominal", "calibrated": True, "drift_offset_mm": 0.0},
                "controller": {"status": "nominal", "self_test_passed": False, "resumed": False},
            },
            "expected_faults": ["pneumatic_line:overpressure_fault"],
        },
        {
            "task_id": "src_sensor_actuator",
            "name": "Source 2: Actuator Jam and Sensor Drift",
            "goal": "Diagnose workstation status, clear gripper jam, recalibrate camera sensor, perform self-test, and resume production.",
            "initial_state": {
                "power_unit": {"status": "nominal", "isolated": False, "voltage_v": 24.0},
                "pneumatic_line": {"status": "nominal", "isolated": False, "pressure_bar": 5.0},
                "arm_gripper": {"status": "jammed", "holding_load": False, "calibrated": False},
                "camera_sensor": {"status": "optical_drift", "calibrated": False, "drift_offset_mm": 2.4},
                "controller": {"status": "nominal", "self_test_passed": False, "resumed": False},
            },
            "expected_faults": ["arm_gripper:jammed", "camera_sensor:optical_drift"],
        },
        {
            "task_id": "src_dual_subsystems",
            "name": "Source 3: Power Trip and Pneumatic Leak",
            "goal": "Diagnose workstation status, restore power relay, repair pneumatic leak, perform self-test, and resume production.",
            "initial_state": {
                "power_unit": {"status": "tripped", "isolated": False, "voltage_v": 0.0},
                "pneumatic_line": {"status": "leak_fault", "isolated": False, "pressure_bar": 1.2},
                "arm_gripper": {"status": "nominal", "holding_load": False, "calibrated": True},
                "camera_sensor": {"status": "nominal", "calibrated": True, "drift_offset_mm": 0.0},
                "controller": {"status": "nominal", "self_test_passed": False, "resumed": False},
            },
            "expected_faults": ["power_unit:tripped", "pneumatic_line:leak_fault"],
        },
    ]


def get_target_tasks() -> List[Dict[str, Any]]:
    """
    8 Target Tasks across 4 Transfer Classes (2 per class):
      - Class A (Same mechanism, diff object/state):
          target_A1_pneumatic_leak
          target_A2_gripper_misalign
      - Class B (New combination of seen mechanisms):
          target_B1_composed_faults (3 faults: pneumatic + gripper + sensor)
          target_B2_power_and_sensor (power + sensor)
      - Class C (Key condition changed, requiring adaptation):
          target_C1_gripper_with_load (gripper jammed with load interlock)
          target_C2_sensor_power_order (sensor drift while power tripped)
      - Class D (Irrelevant history, reject reuse):
          target_D1_clean_startup (nominal startup, 0 faults)
          target_D2_routine_maintenance (controller counter overflow only)
    """
    return [
        # -------------------------------------------------------------
        # Transfer Class A: Same mechanism, different object / initial state
        # -------------------------------------------------------------
        {
            "task_id": "target_A1_pneumatic_leak",
            "transfer_class": "Class_A_same_mechanism",
            "name": "Target A1: Pneumatic Leak Repair",
            "goal": "Diagnose workstation status, repair pneumatic pressure leak, perform self-test, and resume production.",
            "initial_state": {
                "power_unit": {"status": "nominal", "isolated": False, "voltage_v": 24.0},
                "pneumatic_line": {"status": "leak_fault", "isolated": False, "pressure_bar": 1.1},
                "arm_gripper": {"status": "nominal", "holding_load": False, "calibrated": True},
                "camera_sensor": {"status": "nominal", "calibrated": True, "drift_offset_mm": 0.0},
                "controller": {"status": "nominal", "self_test_passed": False, "resumed": False},
            },
            "expected_faults": ["pneumatic_line:leak_fault"],
            "relevance_to_sources": "high_pneumatic",
        },
        {
            "task_id": "target_A2_gripper_misalign",
            "transfer_class": "Class_A_same_mechanism",
            "name": "Target A2: Gripper Misalignment and Sensor Recalibration",
            "goal": "Diagnose workstation status, resolve gripper misalignment, calibrate sensor, perform self-test, and resume production.",
            "initial_state": {
                "power_unit": {"status": "nominal", "isolated": False, "voltage_v": 24.0},
                "pneumatic_line": {"status": "nominal", "isolated": False, "pressure_bar": 5.0},
                "arm_gripper": {"status": "misaligned", "holding_load": False, "calibrated": False},
                "camera_sensor": {"status": "uncalibrated", "calibrated": False, "drift_offset_mm": 1.5},
                "controller": {"status": "nominal", "self_test_passed": False, "resumed": False},
            },
            "expected_faults": ["arm_gripper:misaligned", "camera_sensor:uncalibrated"],
            "relevance_to_sources": "high_gripper_sensor",
        },

        # -------------------------------------------------------------
        # Transfer Class B: New combination of seen mechanisms
        # -------------------------------------------------------------
        {
            "task_id": "target_B1_composed_faults",
            "transfer_class": "Class_B_combination",
            "name": "Target B1: Triple Subsystem Faults (Pneumatics + Gripper + Sensor)",
            "goal": "Diagnose full workstation, repair pneumatic overpressure, clear gripper jam, recalibrate camera, self-test and resume.",
            "initial_state": {
                "power_unit": {"status": "nominal", "isolated": False, "voltage_v": 24.0},
                "pneumatic_line": {"status": "overpressure_fault", "isolated": False, "pressure_bar": 8.8},
                "arm_gripper": {"status": "jammed", "holding_load": False, "calibrated": False},
                "camera_sensor": {"status": "optical_drift", "calibrated": False, "drift_offset_mm": 3.1},
                "controller": {"status": "nominal", "self_test_passed": False, "resumed": False},
            },
            "expected_faults": ["pneumatic_line:overpressure_fault", "arm_gripper:jammed", "camera_sensor:optical_drift"],
            "relevance_to_sources": "composite_pneumatic_gripper_sensor",
        },
        {
            "task_id": "target_B2_power_and_sensor",
            "transfer_class": "Class_B_combination",
            "name": "Target B2: Power Contactor Trip and Uncalibrated Sensor",
            "goal": "Diagnose workstation, restore power unit contactor, calibrate camera sensor, self-test and resume.",
            "initial_state": {
                "power_unit": {"status": "tripped", "isolated": False, "voltage_v": 0.0},
                "pneumatic_line": {"status": "nominal", "isolated": False, "pressure_bar": 5.0},
                "arm_gripper": {"status": "nominal", "holding_load": False, "calibrated": True},
                "camera_sensor": {"status": "uncalibrated", "calibrated": False, "drift_offset_mm": 0.8},
                "controller": {"status": "nominal", "self_test_passed": False, "resumed": False},
            },
            "expected_faults": ["power_unit:tripped", "camera_sensor:uncalibrated"],
            "relevance_to_sources": "composite_power_sensor",
        },

        # -------------------------------------------------------------
        # Transfer Class C: Key condition changed, requiring repair modification
        # -------------------------------------------------------------
        {
            "task_id": "target_C1_gripper_with_load",
            "transfer_class": "Class_C_condition_changed",
            "name": "Target C1: Gripper Jammed with Active Workpiece Load",
            "goal": "Diagnose workstation, repair pneumatic leak and clear gripper jam with active workpiece load safely, calibrate, self-test, resume.",
            "initial_state": {
                "power_unit": {"status": "nominal", "isolated": False, "voltage_v": 24.0},
                "pneumatic_line": {"status": "leak_fault", "isolated": False, "pressure_bar": 1.3},
                "arm_gripper": {"status": "jammed", "holding_load": True, "calibrated": False},
                "camera_sensor": {"status": "nominal", "calibrated": True, "drift_offset_mm": 0.0},
                "controller": {"status": "nominal", "self_test_passed": False, "resumed": False},
            },
            "expected_faults": ["pneumatic_line:leak_fault", "arm_gripper:jammed", "arm_gripper:holding_load"],
            "relevance_to_sources": "modified_gripper_load",
        },
        {
            "task_id": "target_C2_sensor_power_order",
            "transfer_class": "Class_C_condition_changed",
            "name": "Target C2: Sensor Drift under Tripped Power Supply",
            "goal": "Diagnose workstation, handle power trip before sensor calibration, calibrate camera, self-test, and resume.",
            "initial_state": {
                "power_unit": {"status": "tripped", "isolated": False, "voltage_v": 0.0},
                "pneumatic_line": {"status": "nominal", "isolated": False, "pressure_bar": 5.0},
                "arm_gripper": {"status": "nominal", "holding_load": False, "calibrated": True},
                "camera_sensor": {"status": "optical_drift", "calibrated": False, "drift_offset_mm": 2.9},
                "controller": {"status": "nominal", "self_test_passed": False, "resumed": False},
            },
            "expected_faults": ["power_unit:tripped", "camera_sensor:optical_drift"],
            "relevance_to_sources": "modified_power_sensor_order",
        },

        # -------------------------------------------------------------
        # Transfer Class D: History irrelevant, reject reuse
        # -------------------------------------------------------------
        {
            "task_id": "target_D1_clean_startup",
            "transfer_class": "Class_D_irrelevant",
            "name": "Target D1: Routine Clean Workstation Startup",
            "goal": "Inspect workstation, verify all nominal subsystems, run self-test, and resume production.",
            "initial_state": {
                "power_unit": {"status": "nominal", "isolated": False, "voltage_v": 24.0},
                "pneumatic_line": {"status": "nominal", "isolated": False, "pressure_bar": 5.0},
                "arm_gripper": {"status": "nominal", "holding_load": False, "calibrated": True},
                "camera_sensor": {"status": "nominal", "calibrated": True, "drift_offset_mm": 0.0},
                "controller": {"status": "nominal", "self_test_passed": False, "resumed": False},
            },
            "expected_faults": [],
            "relevance_to_sources": "irrelevant_clean",
        },
        {
            "task_id": "target_D2_routine_maintenance",
            "transfer_class": "Class_D_irrelevant",
            "name": "Target D2: Routine Software Counter Reset",
            "goal": "Inspect workstation, reset controller maintenance counters, run self-test, and resume production.",
            "initial_state": {
                "power_unit": {"status": "nominal", "isolated": False, "voltage_v": 24.0},
                "pneumatic_line": {"status": "nominal", "isolated": False, "pressure_bar": 5.0},
                "arm_gripper": {"status": "nominal", "holding_load": False, "calibrated": True},
                "camera_sensor": {"status": "nominal", "calibrated": True, "drift_offset_mm": 0.0},
                "controller": {"status": "counter_overflow", "self_test_passed": False, "resumed": False},
            },
            "expected_faults": ["controller:counter_overflow"],
            "relevance_to_sources": "irrelevant_counter",
        },
    ]
