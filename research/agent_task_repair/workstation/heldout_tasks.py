"""
Held-Out Benchmark Task Definitions (24 New Instances across 4 Transfer Categories).

Structure:
  4 Categories x 3 Distinct Behavioral Templates x 2 Valid Instances = 24 Instances.

Categories:
  1. Cat 1: Seen mechanism, different valid initial states (6 instances)
  2. Cat 2: New combinations of seen fault mechanisms (6 instances)
  3. Cat 3: Modeled cross-subsystem prerequisite dependencies (6 instances)
  4. Cat 4: Historically unrelated or only partially applicable (6 instances)
"""
from typing import Dict, Any, List
import hashlib
import json


def get_heldout_tasks() -> List[Dict[str, Any]]:
    tasks: List[Dict[str, Any]] = []

    # =========================================================================
    # Category 1: Seen mechanism, different valid initial states (6 instances)
    # =========================================================================
    # Template 1.1: Pneumatic overpressure with distinct operating pressures
    tasks.append({
        "task_id": "heldout_cat1_tpl1_inst1_pneu_high",
        "category": "Cat1_seen_mechanism_new_state",
        "template_id": "cat1_tpl1_pneumatic_overpressure",
        "name": "Heldout 1.1A: Pneumatic Pressure Spike (7.8 bar)",
        "goal": "Diagnose workstation, isolate pneumatic line, clear overpressure fault, re-energize line, perform self-test, and resume production.",
        "initial_state": {
            "power_unit": {"status": "nominal", "isolated": False, "voltage_v": 24.0},
            "pneumatic_line": {"status": "overpressure_fault", "isolated": False, "pressure_bar": 7.8},
            "arm_gripper": {"status": "nominal", "holding_load": False, "calibrated": True},
            "camera_sensor": {"status": "nominal", "calibrated": True, "drift_offset_mm": 0.0},
            "controller": {"status": "nominal", "self_test_passed": False, "resumed": False},
        },
        "expected_faults": ["pneumatic_line:overpressure_fault"],
    })
    tasks.append({
        "task_id": "heldout_cat1_tpl1_inst2_pneu_extreme",
        "category": "Cat1_seen_mechanism_new_state",
        "template_id": "cat1_tpl1_pneumatic_overpressure",
        "name": "Heldout 1.1B: Pneumatic Extreme Pressure Spike (9.4 bar)",
        "goal": "Diagnose workstation, isolate pneumatic line, clear overpressure fault, re-energize line, perform self-test, and resume production.",
        "initial_state": {
            "power_unit": {"status": "nominal", "isolated": False, "voltage_v": 24.0},
            "pneumatic_line": {"status": "overpressure_fault", "isolated": False, "pressure_bar": 9.4},
            "arm_gripper": {"status": "nominal", "holding_load": False, "calibrated": True},
            "camera_sensor": {"status": "nominal", "calibrated": True, "drift_offset_mm": 0.0},
            "controller": {"status": "nominal", "self_test_passed": False, "resumed": False},
        },
        "expected_faults": ["pneumatic_line:overpressure_fault"],
    })

    # Template 1.2: Gripper misalignment with varied kinematics
    tasks.append({
        "task_id": "heldout_cat1_tpl2_inst1_gripper_misaligned_light",
        "category": "Cat1_seen_mechanism_new_state",
        "template_id": "cat1_tpl2_gripper_misalignment",
        "name": "Heldout 1.2A: Gripper Misalignment (Minor Angular Offset)",
        "goal": "Diagnose workstation, clear gripper misalignment fault, home arm gripper mechanism, self-test, and resume production.",
        "initial_state": {
            "power_unit": {"status": "nominal", "isolated": False, "voltage_v": 24.0},
            "pneumatic_line": {"status": "nominal", "isolated": False, "pressure_bar": 5.0},
            "arm_gripper": {"status": "misaligned", "holding_load": False, "calibrated": False},
            "camera_sensor": {"status": "nominal", "calibrated": True, "drift_offset_mm": 0.0},
            "controller": {"status": "nominal", "self_test_passed": False, "resumed": False},
        },
        "expected_faults": ["arm_gripper:misaligned"],
    })
    tasks.append({
        "task_id": "heldout_cat1_tpl2_inst2_gripper_misaligned_severe",
        "category": "Cat1_seen_mechanism_new_state",
        "template_id": "cat1_tpl2_gripper_misalignment",
        "name": "Heldout 1.2B: Gripper Misalignment (Severe Axis Drift)",
        "goal": "Diagnose workstation, clear gripper misalignment fault, home arm gripper mechanism, self-test, and resume production.",
        "initial_state": {
            "power_unit": {"status": "nominal", "isolated": False, "voltage_v": 24.0},
            "pneumatic_line": {"status": "nominal", "isolated": False, "pressure_bar": 5.0},
            "arm_gripper": {"status": "misaligned", "holding_load": False, "calibrated": False},
            "camera_sensor": {"status": "nominal", "calibrated": True, "drift_offset_mm": 0.0},
            "controller": {"status": "nominal", "self_test_passed": False, "resumed": False},
        },
        "expected_faults": ["arm_gripper:misaligned"],
    })

    # Template 1.3: Camera sensor optical drift with varied offsets
    tasks.append({
        "task_id": "heldout_cat1_tpl3_inst1_sensor_drift_low",
        "category": "Cat1_seen_mechanism_new_state",
        "template_id": "cat1_tpl3_sensor_drift",
        "name": "Heldout 1.3A: Vision Sensor Drift (1.7 mm)",
        "goal": "Diagnose workstation, clear vision sensor fault, calibrate camera optical matrix, self-test, and resume production.",
        "initial_state": {
            "power_unit": {"status": "nominal", "isolated": False, "voltage_v": 24.0},
            "pneumatic_line": {"status": "nominal", "isolated": False, "pressure_bar": 5.0},
            "arm_gripper": {"status": "nominal", "holding_load": False, "calibrated": True},
            "camera_sensor": {"status": "optical_drift", "calibrated": False, "drift_offset_mm": 1.7},
            "controller": {"status": "nominal", "self_test_passed": False, "resumed": False},
        },
        "expected_faults": ["camera_sensor:optical_drift"],
    })
    tasks.append({
        "task_id": "heldout_cat1_tpl3_inst2_sensor_drift_high",
        "category": "Cat1_seen_mechanism_new_state",
        "template_id": "cat1_tpl3_sensor_drift",
        "name": "Heldout 1.3B: Vision Sensor Drift (3.6 mm)",
        "goal": "Diagnose workstation, clear vision sensor fault, calibrate camera optical matrix, self-test, and resume production.",
        "initial_state": {
            "power_unit": {"status": "nominal", "isolated": False, "voltage_v": 24.0},
            "pneumatic_line": {"status": "nominal", "isolated": False, "pressure_bar": 5.0},
            "arm_gripper": {"status": "nominal", "holding_load": False, "calibrated": True},
            "camera_sensor": {"status": "optical_drift", "calibrated": False, "drift_offset_mm": 3.6},
            "controller": {"status": "nominal", "self_test_passed": False, "resumed": False},
        },
        "expected_faults": ["camera_sensor:optical_drift"],
    })

    # =========================================================================
    # Category 2: New combinations of seen fault mechanisms (6 instances)
    # =========================================================================
    # Template 2.1: Pneumatics Leak + Gripper Jammed
    tasks.append({
        "task_id": "heldout_cat2_tpl1_inst1_pneu_gripper_combo_a",
        "category": "Cat2_new_fault_combinations",
        "template_id": "cat2_tpl1_pneumatics_and_gripper",
        "name": "Heldout 2.1A: Pneumatic Pressure Drop (1.4 bar) and Gripper Jam",
        "goal": "Diagnose workstation, repair pneumatic leak, clear gripper jam, self-test, and resume production.",
        "initial_state": {
            "power_unit": {"status": "nominal", "isolated": False, "voltage_v": 24.0},
            "pneumatic_line": {"status": "leak_fault", "isolated": False, "pressure_bar": 1.4},
            "arm_gripper": {"status": "jammed", "holding_load": False, "calibrated": False},
            "camera_sensor": {"status": "nominal", "calibrated": True, "drift_offset_mm": 0.0},
            "controller": {"status": "nominal", "self_test_passed": False, "resumed": False},
        },
        "expected_faults": ["pneumatic_line:leak_fault", "arm_gripper:jammed"],
    })
    tasks.append({
        "task_id": "heldout_cat2_tpl1_inst2_pneu_gripper_combo_b",
        "category": "Cat2_new_fault_combinations",
        "template_id": "cat2_tpl1_pneumatics_and_gripper",
        "name": "Heldout 2.1B: Pneumatic Overpressure (8.6 bar) and Gripper Jam",
        "goal": "Diagnose workstation, repair pneumatic overpressure, clear gripper jam, self-test, and resume production.",
        "initial_state": {
            "power_unit": {"status": "nominal", "isolated": False, "voltage_v": 24.0},
            "pneumatic_line": {"status": "overpressure_fault", "isolated": False, "pressure_bar": 8.6},
            "arm_gripper": {"status": "jammed", "holding_load": False, "calibrated": False},
            "camera_sensor": {"status": "nominal", "calibrated": True, "drift_offset_mm": 0.0},
            "controller": {"status": "nominal", "self_test_passed": False, "resumed": False},
        },
        "expected_faults": ["pneumatic_line:overpressure_fault", "arm_gripper:jammed"],
    })

    # Template 2.2: Power Trip + Pneumatic Overpressure
    tasks.append({
        "task_id": "heldout_cat2_tpl2_inst1_power_pneu_combo_a",
        "category": "Cat2_new_fault_combinations",
        "template_id": "cat2_tpl2_power_and_pneumatic",
        "name": "Heldout 2.2A: Power Supply Trip and Pneumatic Overpressure",
        "goal": "Diagnose workstation, restore power relay, discharge and clear pneumatic overpressure, self-test, and resume production.",
        "initial_state": {
            "power_unit": {"status": "tripped", "isolated": False, "voltage_v": 0.0},
            "pneumatic_line": {"status": "overpressure_fault", "isolated": False, "pressure_bar": 9.1},
            "arm_gripper": {"status": "nominal", "holding_load": False, "calibrated": True},
            "camera_sensor": {"status": "nominal", "calibrated": True, "drift_offset_mm": 0.0},
            "controller": {"status": "nominal", "self_test_passed": False, "resumed": False},
        },
        "expected_faults": ["power_unit:tripped", "pneumatic_line:overpressure_fault"],
    })
    tasks.append({
        "task_id": "heldout_cat2_tpl2_inst2_power_pneu_combo_b",
        "category": "Cat2_new_fault_combinations",
        "template_id": "cat2_tpl2_power_and_pneumatic",
        "name": "Heldout 2.2B: Power Supply Trip and Pneumatic Pressure Decay",
        "goal": "Diagnose workstation, restore power relay, repair pneumatic pressure decay, self-test, and resume production.",
        "initial_state": {
            "power_unit": {"status": "tripped", "isolated": False, "voltage_v": 0.0},
            "pneumatic_line": {"status": "leak_fault", "isolated": False, "pressure_bar": 0.8},
            "arm_gripper": {"status": "nominal", "holding_load": False, "calibrated": True},
            "camera_sensor": {"status": "nominal", "calibrated": True, "drift_offset_mm": 0.0},
            "controller": {"status": "nominal", "self_test_passed": False, "resumed": False},
        },
        "expected_faults": ["power_unit:tripped", "pneumatic_line:leak_fault"],
    })

    # Template 2.3: Triple combination: Pneumatics + Gripper + Sensor
    tasks.append({
        "task_id": "heldout_cat2_tpl3_inst1_triple_combo_a",
        "category": "Cat2_new_fault_combinations",
        "template_id": "cat2_tpl3_triple_actuator_sensor",
        "name": "Heldout 2.3A: Pneumatic Decay, Gripper Misaligned, and Optical Drift",
        "goal": "Diagnose workstation, repair pneumatic decay, clear gripper misalignment, calibrate vision sensor, self-test, and resume.",
        "initial_state": {
            "power_unit": {"status": "nominal", "isolated": False, "voltage_v": 24.0},
            "pneumatic_line": {"status": "leak_fault", "isolated": False, "pressure_bar": 1.5},
            "arm_gripper": {"status": "misaligned", "holding_load": False, "calibrated": False},
            "camera_sensor": {"status": "optical_drift", "calibrated": False, "drift_offset_mm": 2.1},
            "controller": {"status": "nominal", "self_test_passed": False, "resumed": False},
        },
        "expected_faults": ["pneumatic_line:leak_fault", "arm_gripper:misaligned", "camera_sensor:optical_drift"],
    })
    tasks.append({
        "task_id": "heldout_cat2_tpl3_inst2_triple_combo_b",
        "category": "Cat2_new_fault_combinations",
        "template_id": "cat2_tpl3_triple_actuator_sensor",
        "name": "Heldout 2.3B: Pneumatic Overpressure, Gripper Jam, and Optical Drift",
        "goal": "Diagnose workstation, clear overpressure, clear gripper jam, calibrate vision sensor, self-test, and resume.",
        "initial_state": {
            "power_unit": {"status": "nominal", "isolated": False, "voltage_v": 24.0},
            "pneumatic_line": {"status": "overpressure_fault", "isolated": False, "pressure_bar": 8.9},
            "arm_gripper": {"status": "jammed", "holding_load": False, "calibrated": False},
            "camera_sensor": {"status": "optical_drift", "calibrated": False, "drift_offset_mm": 3.4},
            "controller": {"status": "nominal", "self_test_passed": False, "resumed": False},
        },
        "expected_faults": ["pneumatic_line:overpressure_fault", "arm_gripper:jammed", "camera_sensor:optical_drift"],
    })

    # =========================================================================
    # Category 3: Modeled cross-subsystem prerequisite dependencies (6 instances)
    # =========================================================================
    # Template 3.1: Power trip blocking gripper homing and camera calibration
    tasks.append({
        "task_id": "heldout_cat3_tpl1_inst1_power_blocks_gripper_sensor_a",
        "category": "Cat3_cross_subsystem_dependencies",
        "template_id": "cat3_tpl1_power_interlock_cascade",
        "name": "Heldout 3.1A: Tripped Power Interlocking Jammed Gripper and Vision",
        "goal": "Diagnose workstation, restore power unit before servicing arm gripper and camera calibration, self-test, and resume.",
        "initial_state": {
            "power_unit": {"status": "tripped", "isolated": False, "voltage_v": 0.0},
            "pneumatic_line": {"status": "nominal", "isolated": False, "pressure_bar": 5.0},
            "arm_gripper": {"status": "jammed", "holding_load": False, "calibrated": False},
            "camera_sensor": {"status": "optical_drift", "calibrated": False, "drift_offset_mm": 2.7},
            "controller": {"status": "nominal", "self_test_passed": False, "resumed": False},
        },
        "expected_faults": ["power_unit:tripped", "arm_gripper:jammed", "camera_sensor:optical_drift"],
    })
    tasks.append({
        "task_id": "heldout_cat3_tpl1_inst2_power_blocks_gripper_sensor_b",
        "category": "Cat3_cross_subsystem_dependencies",
        "template_id": "cat3_tpl1_power_interlock_cascade",
        "name": "Heldout 3.1B: Tripped Power Interlocking Misaligned Gripper and Vision",
        "goal": "Diagnose workstation, restore power unit before servicing arm gripper and camera calibration, self-test, and resume.",
        "initial_state": {
            "power_unit": {"status": "tripped", "isolated": False, "voltage_v": 0.0},
            "pneumatic_line": {"status": "nominal", "isolated": False, "pressure_bar": 5.0},
            "arm_gripper": {"status": "misaligned", "holding_load": False, "calibrated": False},
            "camera_sensor": {"status": "optical_drift", "calibrated": False, "drift_offset_mm": 1.9},
            "controller": {"status": "nominal", "self_test_passed": False, "resumed": False},
        },
        "expected_faults": ["power_unit:tripped", "arm_gripper:misaligned", "camera_sensor:optical_drift"],
    })

    # Template 3.2: Gripper holding load under tripped power supply (Double Interlock)
    tasks.append({
        "task_id": "heldout_cat3_tpl2_inst1_double_interlock_load_power_a",
        "category": "Cat3_cross_subsystem_dependencies",
        "template_id": "cat3_tpl2_double_interlock_load_power",
        "name": "Heldout 3.2A: Gripper Holding Load with Tripped Main Power",
        "goal": "Diagnose workstation, restore power unit, release gripper load safely before homing, self-test, and resume.",
        "initial_state": {
            "power_unit": {"status": "tripped", "isolated": False, "voltage_v": 0.0},
            "pneumatic_line": {"status": "nominal", "isolated": False, "pressure_bar": 5.0},
            "arm_gripper": {"status": "jammed", "holding_load": True, "calibrated": False},
            "camera_sensor": {"status": "nominal", "calibrated": True, "drift_offset_mm": 0.0},
            "controller": {"status": "nominal", "self_test_passed": False, "resumed": False},
        },
        "expected_faults": ["power_unit:tripped", "arm_gripper:jammed", "arm_gripper:holding_load"],
    })
    tasks.append({
        "task_id": "heldout_cat3_tpl2_inst2_double_interlock_load_power_b",
        "category": "Cat3_cross_subsystem_dependencies",
        "template_id": "cat3_tpl2_double_interlock_load_power",
        "name": "Heldout 3.2B: Gripper Holding Load with Tripped Power and Vision Drift",
        "goal": "Diagnose workstation, restore power unit, release gripper load safely before homing, calibrate vision, self-test, and resume.",
        "initial_state": {
            "power_unit": {"status": "tripped", "isolated": False, "voltage_v": 0.0},
            "pneumatic_line": {"status": "nominal", "isolated": False, "pressure_bar": 5.0},
            "arm_gripper": {"status": "jammed", "holding_load": True, "calibrated": False},
            "camera_sensor": {"status": "optical_drift", "calibrated": False, "drift_offset_mm": 2.2},
            "controller": {"status": "nominal", "self_test_passed": False, "resumed": False},
        },
        "expected_faults": ["power_unit:tripped", "arm_gripper:jammed", "arm_gripper:holding_load", "camera_sensor:optical_drift"],
    })

    # Template 3.3: Pneumatics + Power + Sensor Multistage Interlock
    tasks.append({
        "task_id": "heldout_cat3_tpl3_inst1_multistage_interlock_a",
        "category": "Cat3_cross_subsystem_dependencies",
        "template_id": "cat3_tpl3_multistage_interlock",
        "name": "Heldout 3.3A: Pneumatic Isolation and Power Interlocked Vision Recovery",
        "goal": "Diagnose workstation, repair pneumatic overpressure and power trip, calibrate vision sensor, self-test, and resume.",
        "initial_state": {
            "power_unit": {"status": "tripped", "isolated": False, "voltage_v": 0.0},
            "pneumatic_line": {"status": "overpressure_fault", "isolated": False, "pressure_bar": 8.3},
            "arm_gripper": {"status": "nominal", "holding_load": False, "calibrated": True},
            "camera_sensor": {"status": "optical_drift", "calibrated": False, "drift_offset_mm": 3.1},
            "controller": {"status": "nominal", "self_test_passed": False, "resumed": False},
        },
        "expected_faults": ["power_unit:tripped", "pneumatic_line:overpressure_fault", "camera_sensor:optical_drift"],
    })
    tasks.append({
        "task_id": "heldout_cat3_tpl3_inst2_multistage_interlock_b",
        "category": "Cat3_cross_subsystem_dependencies",
        "template_id": "cat3_tpl3_multistage_interlock",
        "name": "Heldout 3.3B: Pneumatic Leak and Power Interlocked Vision Recovery",
        "goal": "Diagnose workstation, repair pneumatic leak and power trip, calibrate vision sensor, self-test, and resume.",
        "initial_state": {
            "power_unit": {"status": "tripped", "isolated": False, "voltage_v": 0.0},
            "pneumatic_line": {"status": "leak_fault", "isolated": False, "pressure_bar": 1.0},
            "arm_gripper": {"status": "nominal", "holding_load": False, "calibrated": True},
            "camera_sensor": {"status": "optical_drift", "calibrated": False, "drift_offset_mm": 1.6},
            "controller": {"status": "nominal", "self_test_passed": False, "resumed": False},
        },
        "expected_faults": ["power_unit:tripped", "pneumatic_line:leak_fault", "camera_sensor:optical_drift"],
    })

    # =========================================================================
    # Category 4: Historically unrelated or only partially applicable (6 instances)
    # =========================================================================
    # Template 4.1: Controller Counter Overflow / Watchdog Error
    tasks.append({
        "task_id": "heldout_cat4_tpl1_inst1_controller_counter_overflow",
        "category": "Cat4_irrelevant_or_partial",
        "template_id": "cat4_tpl1_controller_maintenance",
        "name": "Heldout 4.1A: Controller Maintenance Counter Reset",
        "goal": "Inspect workstation, reset controller internal maintenance counter, run self-test, and resume production.",
        "initial_state": {
            "power_unit": {"status": "nominal", "isolated": False, "voltage_v": 24.0},
            "pneumatic_line": {"status": "nominal", "isolated": False, "pressure_bar": 5.0},
            "arm_gripper": {"status": "nominal", "holding_load": False, "calibrated": True},
            "camera_sensor": {"status": "nominal", "calibrated": True, "drift_offset_mm": 0.0},
            "controller": {"status": "counter_overflow", "self_test_passed": False, "resumed": False},
        },
        "expected_faults": ["controller:counter_overflow"],
    })
    tasks.append({
        "task_id": "heldout_cat4_tpl1_inst2_controller_watchdog_fault",
        "category": "Cat4_irrelevant_or_partial",
        "template_id": "cat4_tpl1_controller_maintenance",
        "name": "Heldout 4.1B: Controller Sequence Watchdog Reset",
        "goal": "Inspect workstation, reset controller internal sequence error, run self-test, and resume production.",
        "initial_state": {
            "power_unit": {"status": "nominal", "isolated": False, "voltage_v": 24.0},
            "pneumatic_line": {"status": "nominal", "isolated": False, "pressure_bar": 5.0},
            "arm_gripper": {"status": "nominal", "holding_load": False, "calibrated": True},
            "camera_sensor": {"status": "nominal", "calibrated": True, "drift_offset_mm": 0.0},
            "controller": {"status": "watchdog_error", "self_test_passed": False, "resumed": False},
        },
        "expected_faults": ["controller:watchdog_error"],
    })

    # Template 4.2: Camera Sensor Optical Drift only (no actuator / energy fault)
    tasks.append({
        "task_id": "heldout_cat4_tpl2_inst1_clean_system_sensor_drift_a",
        "category": "Cat4_irrelevant_or_partial",
        "template_id": "cat4_tpl2_isolated_sensor_drift",
        "name": "Heldout 4.2A: Isolated Vision Sensor Calibration (Nominal Actuators)",
        "goal": "Inspect workstation, calibrate vision camera sensor without touching nominal actuators, run self-test, and resume.",
        "initial_state": {
            "power_unit": {"status": "nominal", "isolated": False, "voltage_v": 24.0},
            "pneumatic_line": {"status": "nominal", "isolated": False, "pressure_bar": 5.0},
            "arm_gripper": {"status": "nominal", "holding_load": False, "calibrated": True},
            "camera_sensor": {"status": "optical_drift", "calibrated": False, "drift_offset_mm": 2.8},
            "controller": {"status": "nominal", "self_test_passed": False, "resumed": False},
        },
        "expected_faults": ["camera_sensor:optical_drift"],
    })
    tasks.append({
        "task_id": "heldout_cat4_tpl2_inst2_clean_system_sensor_drift_b",
        "category": "Cat4_irrelevant_or_partial",
        "template_id": "cat4_tpl2_isolated_sensor_drift",
        "name": "Heldout 4.2B: Isolated Vision Sensor Calibration (Sub-millimeter Drift)",
        "goal": "Inspect workstation, calibrate vision camera sensor without touching nominal actuators, run self-test, and resume.",
        "initial_state": {
            "power_unit": {"status": "nominal", "isolated": False, "voltage_v": 24.0},
            "pneumatic_line": {"status": "nominal", "isolated": False, "pressure_bar": 5.0},
            "arm_gripper": {"status": "nominal", "holding_load": False, "calibrated": True},
            "camera_sensor": {"status": "optical_drift", "calibrated": False, "drift_offset_mm": 1.2},
            "controller": {"status": "nominal", "self_test_passed": False, "resumed": False},
        },
        "expected_faults": ["camera_sensor:optical_drift"],
    })

    # Template 4.3: Clean Workstation Startup with varied nominal pressures/voltages
    tasks.append({
        "task_id": "heldout_cat4_tpl3_inst1_nominal_startup_standard",
        "category": "Cat4_irrelevant_or_partial",
        "template_id": "cat4_tpl3_nominal_startup",
        "name": "Heldout 4.3A: Fully Nominal Workstation Clean Startup (Standard)",
        "goal": "Inspect workstation, verify all nominal states, run comprehensive self-test, and resume production.",
        "initial_state": {
            "power_unit": {"status": "nominal", "isolated": False, "voltage_v": 24.0},
            "pneumatic_line": {"status": "nominal", "isolated": False, "pressure_bar": 5.0},
            "arm_gripper": {"status": "nominal", "holding_load": False, "calibrated": True},
            "camera_sensor": {"status": "nominal", "calibrated": True, "drift_offset_mm": 0.0},
            "controller": {"status": "nominal", "self_test_passed": False, "resumed": False},
        },
        "expected_faults": [],
    })
    tasks.append({
        "task_id": "heldout_cat4_tpl3_inst2_nominal_startup_high_pneu",
        "category": "Cat4_irrelevant_or_partial",
        "template_id": "cat4_tpl3_nominal_startup",
        "name": "Heldout 4.3B: Fully Nominal Workstation Clean Startup (High Nominal Pressure)",
        "goal": "Inspect workstation, verify all nominal states, run comprehensive self-test, and resume production.",
        "initial_state": {
            "power_unit": {"status": "nominal", "isolated": False, "voltage_v": 24.0},
            "pneumatic_line": {"status": "nominal", "isolated": False, "pressure_bar": 6.0},
            "arm_gripper": {"status": "nominal", "holding_load": False, "calibrated": True},
            "camera_sensor": {"status": "nominal", "calibrated": True, "drift_offset_mm": 0.0},
            "controller": {"status": "nominal", "self_test_passed": False, "resumed": False},
        },
        "expected_faults": [],
    })

    return tasks


def generate_heldout_manifest():
    tasks = get_heldout_tasks()
    serialized = json.dumps(tasks, sort_keys=True)
    manifest_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    
    cat_counts = {}
    tpl_counts = {}
    for t in tasks:
        cat_counts[t["category"]] = cat_counts.get(t["category"], 0) + 1
        tpl_counts[t["template_id"]] = tpl_counts.get(t["template_id"], 0) + 1

    manifest = {
        "benchmark_name": "Workstation Multi-Fault Heldout Evaluation Benchmark",
        "total_instances": len(tasks),
        "manifest_sha256": manifest_hash,
        "category_distribution": cat_counts,
        "template_distribution": tpl_counts,
        "task_manifest": [
            {"task_id": t["task_id"], "category": t["category"], "template_id": t["template_id"], "name": t["name"]}
            for t in tasks
        ]
    }
    return manifest
