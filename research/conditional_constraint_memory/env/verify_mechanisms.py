"""
Automated Verification Suite for the 3 CPU Container Failure Mechanisms across 4 States (A, B, C, D).
Asserts:
- State A: Observed condition persistently holds -> APPLICABLE -> Target action fails with genuine error.
- State B: Original condition cleared -> NOT_APPLICABLE -> Target action succeeds.
- State C: Only irrelevant attribute changes -> APPLICABLE -> Target action still fails.
- State D: Observation incomplete or expired (Delta t > TTL) -> UNKNOWN.

Logs comprehensive diagnostic results to verification_log.txt.
"""
import sys
import time
from pathlib import Path

# Add current dir to path
sys.path.insert(0, str(Path(__file__).parent))

from mechanisms import (
    PortOccupancyMechanism,
    FilePermissionMechanism,
    ConfigVersionMismatchMechanism
)

LOG_FILE = Path(__file__).parent / "verification_log.txt"

def evaluate_applicability(mechanism_type: str, probe_data: dict, ttl: float = 2.0) -> str:
    """Evaluates rule applicability state based on probe data and freshness."""
    if not probe_data:
        return "UNKNOWN"
    
    # Check freshness
    ts = probe_data.get("timestamp", 0)
    if time.time() - ts > ttl:
        return "UNKNOWN"

    if mechanism_type == "port_occupancy":
        if "is_occupied" not in probe_data:
            return "UNKNOWN"
        return "APPLICABLE" if probe_data["is_occupied"] else "NOT_APPLICABLE"

    elif mechanism_type == "file_permission":
        if not probe_data.get("exists") or "writable_by_non_root" not in probe_data:
            return "UNKNOWN"
        # If not writable, constraint holds (write will fail)
        return "APPLICABLE" if not probe_data["writable_by_non_root"] else "NOT_APPLICABLE"

    elif mechanism_type == "config_version":
        if not probe_data.get("exists") or "is_compatible" not in probe_data:
            return "UNKNOWN"
        # If not compatible (ver != 2.0), constraint holds (build will fail)
        return "APPLICABLE" if not probe_data["is_compatible"] else "NOT_APPLICABLE"

    return "UNKNOWN"

def run_verification():
    log_lines = []
    def log(msg):
        print(msg)
        log_lines.append(msg)

    log("=" * 80)
    log("FAILMEM CPU CONTAINER MECHANISM VERIFICATION SUITE")
    log(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
    log("Testing 3 Real Container Failure Mechanisms across 4 States: A, B, C, D")
    log("=" * 80)

    mechanisms = [
        ("Mechanism 1: Port Occupancy (Socket Listener)", "port_occupancy", PortOccupancyMechanism()),
        ("Mechanism 2: File Permission (0444 vs 0664)", "file_permission", FilePermissionMechanism()),
        ("Mechanism 3: Config Protocol Version (build script)", "config_version", ConfigVersionMismatchMechanism()),
    ]

    all_passed = True

    for name, mtype, mech in mechanisms:
        log(f"\n--- Testing {name} ---")
        try:
            # === State A: Condition Persistently Holds ===
            log("  [State A]: Setting up persistent condition...")
            mech.setup_state_a()
            probe_a = mech.probe()
            app_a = evaluate_applicability(mtype, probe_a)
            action_a = mech.execute_target_action()
            log(f"    Probe Data: {probe_a}")
            log(f"    Applicability Evaluation: {app_a}")
            log(f"    Target Action Result: success={action_a['success']}, code={action_a['error_code']}, stderr='{action_a['stderr']}'")
            
            assert app_a == "APPLICABLE", f"State A must evaluate to APPLICABLE, got {app_a}"
            assert not action_a["success"], f"State A action must fail, got success"
            log("    -> [State A PASSED]")

            # === State B: Condition Cleared, Action Feasible ===
            log("  [State B]: Clearing condition...")
            mech.setup_state_b()
            probe_b = mech.probe()
            app_b = evaluate_applicability(mtype, probe_b)
            action_b = mech.execute_target_action()
            log(f"    Probe Data: {probe_b}")
            log(f"    Applicability Evaluation: {app_b}")
            log(f"    Target Action Result: success={action_b['success']}, code={action_b['error_code']}")
            
            assert app_b == "NOT_APPLICABLE", f"State B must evaluate to NOT_APPLICABLE, got {app_b}"
            assert action_b["success"], f"State B action must succeed, got failure: {action_b['stderr']}"
            log("    -> [State B PASSED]")

            # === State C: Irrelevant Attribute Changes, Constraint Still Applies ===
            log("  [State C]: Modifying only irrelevant attributes...")
            mech.setup_state_c()
            probe_c = mech.probe()
            app_c = evaluate_applicability(mtype, probe_c)
            action_c = mech.execute_target_action()
            log(f"    Probe Data: {probe_c}")
            log(f"    Applicability Evaluation: {app_c}")
            log(f"    Target Action Result: success={action_c['success']}, code={action_c['error_code']}, stderr='{action_c['stderr']}'")
            
            assert app_c == "APPLICABLE", f"State C must evaluate to APPLICABLE, got {app_c}"
            assert not action_c["success"], f"State C action must still fail, got success"
            log("    -> [State C PASSED]")

            # === State D: Observation Incomplete or Expired -> UNKNOWN ===
            log("  [State D]: Testing observation expiration and uninspected state...")
            # Case D1: Artificially expired observation (Delta t > TTL)
            expired_probe = dict(probe_a)
            expired_probe["timestamp"] = time.time() - 10.0  # 10s ago, TTL=2.0s
            app_d1 = evaluate_applicability(mtype, expired_probe, ttl=2.0)
            log(f"    Case D1 (Expired probe delta_t=10s > TTL=2s): {app_d1}")
            assert app_d1 == "UNKNOWN", f"Expired probe must evaluate to UNKNOWN, got {app_d1}"

            # Case D2: Incomplete/missing observation
            app_d2 = evaluate_applicability(mtype, {})
            log(f"    Case D2 (Missing probe data): {app_d2}")
            assert app_d2 == "UNKNOWN", f"Empty probe must evaluate to UNKNOWN, got {app_d2}"
            log("    -> [State D PASSED]")

        except Exception as e:
            log(f"    ❌ FAILED: {e}")
            all_passed = False
        finally:
            mech.teardown()

    log("\n" + "=" * 80)
    if all_passed:
        log(">>> ALL 3 MECHANISMS ACROSS ALL 4 STATES (A, B, C, D) 100% VERIFIED SUCCESSFUL!")
    else:
        log(">>> VERIFICATION FAILED ON ONE OR MORE TESTS.")
    log("=" * 80)

    with open(LOG_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(log_lines) + "\n")
    print(f"\nVerification log saved to {LOG_FILE}")
    
    return all_passed

if __name__ == "__main__":
    success = run_verification()
    sys.exit(0 if success else 1)
