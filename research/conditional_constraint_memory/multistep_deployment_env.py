"""
Multi-Step Service Deployment Environment.
Implements:
1. Discovery: discover_environment()
2. Placement: probe_port(), probe_directory()
3. Configuration: write_config() as non-root user
4. Service Management: start_service() launching real service daemon
5. Verification: check_health() and independent verifier verifying live daemon state & applied config
6. In-Episode Dynamic Events across 8 instances:
   - inst1: Persistent port conflict on 18080 -> deploy on 18081
   - inst2: Blockage cleared: 18080 occupied at step 1, clears at step 2 -> deploy on 18080
   - inst3: Permission fallback: /etc/service_demo is non-writable -> deploy in /home/agentuser/service_conf
   - inst4: Irrelevant background change -> deploy smoothly
   - inst5: Stale observation: 18080 free initially, occupied at step 2 -> adapt to 18081
   - inst6: Feasible counterexample: candidate rule warning is not applicable; port 18080 viable
   - inst7: Mid-episode port clash: 18080 grabbed mid-flight -> recover on 18082
   - inst8: Dual composition: /etc/service_demo non-writable AND 18080 occupied -> /home/agentuser/service_conf + 18081
"""

import os
import sys
import time
import json
import socket
import subprocess
import uuid
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

ENV_ROOT = Path("/tmp/multistep_env")
ENV_ROOT.mkdir(parents=True, exist_ok=True)
os.chmod(ENV_ROOT, 0o777)

SYS_CONF_DIR = Path("/etc/service_demo")
SYS_CONF_DIR.mkdir(parents=True, exist_ok=True)
os.chmod(SYS_CONF_DIR, 0o755)

USER_CONF_DIR = Path("/home/agentuser/service_conf")
USER_CONF_DIR.mkdir(parents=True, exist_ok=True)
try:
    os.chown(USER_CONF_DIR, 1001, 1001)
    os.chmod(USER_CONF_DIR, 0o750)
except Exception:
    pass

RUNTIME_DIR = Path("/tmp/service_runtime")
RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
os.chmod(RUNTIME_DIR, 0o777)

DAEMON_SCRIPT = Path(__file__).resolve().parent / "service_daemon.py"


def is_port_listening(port: int) -> bool:
    """Passively checks if a TCP port is in LISTEN state via /proc/net/tcp and /proc/net/tcp6."""
    port_hex = f":{port:04X}"
    for tcp_path in ("/proc/net/tcp", "/proc/net/tcp6"):
        if os.path.exists(tcp_path):
            try:
                with open(tcp_path, "r", encoding="utf-8") as f:
                    for line in f.readlines()[1:]:
                        parts = line.strip().split()
                        if len(parts) >= 4:
                            local_addr = parts[1]
                            state = parts[3]
                            if local_addr.endswith(port_hex) and state == "0A":
                                return True
            except Exception:
                pass
    return False


def wait_for_port(port: int, should_be_listening: bool = True, timeout: float = 3.0) -> bool:
    """Readiness check helper without hard-coded sleep."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        if is_port_listening(port) == should_be_listening:
            return True
        time.sleep(0.05)
    return is_port_listening(port) == should_be_listening


class MultiStepDeploymentEnv:
    def __init__(self, non_root_user: str = "agentuser"):
        self.non_root_user = non_root_user
        self.instance_id: Optional[str] = None
        self.step_count: int = 0
        self.daemon_process: Optional[subprocess.Popen] = None
        self.occupier_processes: Dict[int, subprocess.Popen] = {}
        self.deployed_config_path: Optional[str] = None
        self.deployed_port: Optional[int] = None
        self.tool_call_history: List[Dict[str, Any]] = []
        self.state_events_log: List[Dict[str, Any]] = []

    def setup(self, instance_id: str):
        """Prepares environment for the specified instance."""
        self.teardown()
        self.instance_id = instance_id
        self.step_count = 0
        self.tool_call_history = []
        self.state_events_log = []

        # Reset directories
        SYS_CONF_DIR.mkdir(parents=True, exist_ok=True)
        os.chmod(SYS_CONF_DIR, 0o755)
        try:
            os.chown(SYS_CONF_DIR, 0, 0)
        except Exception:
            pass
        # Clear existing configs in user dir
        if USER_CONF_DIR.exists():
            for f in USER_CONF_DIR.glob("*.json"):
                try:
                    f.unlink()
                except Exception:
                    pass

        # Instance-specific initial setups
        if instance_id in ("inst1_port_conflict_persistent", "inst2_blockage_cleared", "inst8_permission_and_port_composition"):
            # Port 18080 occupied
            self._start_occupier(18080, name="occupier_18080")
            wait_for_port(18080, should_be_listening=True, timeout=3.0)
        elif instance_id == "inst7_midepisode_port_clash":
            # Reserve port 18081 so only 18082 is viable when 18080 clashes mid-flight
            self._start_occupier(18081, name="reserved_18081")
            wait_for_port(18081, should_be_listening=True, timeout=3.0)
        elif instance_id in ("inst3_permission_fallback", "inst4_irrelevant_change", "inst6_counterexample_feasibility"):
            # Ports are free
            pass
        elif instance_id in ("inst5_stale_observation",):
            # Ports initially free, dynamic event triggers mid-episode
            pass

    def _start_occupier(self, port: int, name: str = "occupier"):
        """Starts a background process listening on port."""
        script = f"""
import socket, time
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(('127.0.0.1', {port}))
s.listen(5)
while True:
    try:
        conn, _ = s.accept()
        conn.sendall(b'OCCUPIED:{name}\\n')
        conn.close()
    except Exception:
        time.sleep(0.5)
"""
        proc = subprocess.Popen([sys.executable, "-c", script])
        self.occupier_processes[port] = proc

    def _stop_occupier(self, port: int):
        """Stops background process on port."""
        if port in self.occupier_processes:
            proc = self.occupier_processes.pop(port)
            try:
                proc.terminate()
                proc.wait(timeout=1.0)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            wait_for_port(port, should_be_listening=False, timeout=2.0)

    def _trigger_dynamic_events(self):
        """Evaluates and fires mid-episode dynamic events adhering to T_obs < T_change < T_decision."""
        self.step_count += 1
        now = time.time()

        if self.instance_id == "inst2_blockage_cleared" and self.step_count >= 3:
            if 18080 in self.occupier_processes:
                self._stop_occupier(18080)
                self.state_events_log.append({
                    "step": self.step_count,
                    "event": "BLOCKAGE_CLEARED",
                    "resource": "port:18080",
                    "timestamp": now,
                    "detail": "Background occupier on 18080 exited normally; port is now FREE."
                })

        elif self.instance_id == "inst4_irrelevant_change" and self.step_count >= 2:
            audit_file = RUNTIME_DIR / "audit.log"
            audit_file.write_text(f"Audit tick at {now}\n", encoding="utf-8")
            self.state_events_log.append({
                "step": self.step_count,
                "event": "IRRELEVANT_SYSTEM_TICK",
                "resource": str(audit_file),
                "timestamp": now,
                "detail": "System audit logger rotated background log; no service ports affected."
            })

        elif self.instance_id == "inst5_stale_observation" and self.step_count >= 3:
            if 18080 not in self.occupier_processes:
                self._start_occupier(18080, name="late_occupier_18080")
                wait_for_port(18080, should_be_listening=True, timeout=2.0)
                self.state_events_log.append({
                    "step": self.step_count,
                    "event": "RESOURCE_PREEMPTED",
                    "resource": "port:18080",
                    "timestamp": now,
                    "detail": "Collocated daemon spawned and bound to port 18080."
                })

        elif self.instance_id == "inst7_midepisode_port_clash" and self.step_count >= 3:
            if 18080 not in self.occupier_processes:
                self._start_occupier(18080, name="clash_occupier_18080")
                wait_for_port(18080, should_be_listening=True, timeout=2.0)
                self.state_events_log.append({
                    "step": self.step_count,
                    "event": "MID_EPISODE_PORT_CLASH",
                    "resource": "port:18080",
                    "timestamp": now,
                    "detail": "Emergency utility daemon seized port 18080."
                })

    def simulate_service_crash(self, reason: str = "SIGTERM_CRASH") -> Dict[str, Any]:
        """
        Simulates an observable runtime process crash for recovery scenarios.
        Terminates the running daemon process without removing the deployed config.
        """
        call_id = f"call_{uuid.uuid4().hex[:8]}"
        now = time.time()
        crashed = False
        if self.daemon_process and self.daemon_process.poll() is None:
            try:
                self.daemon_process.kill()
                self.daemon_process.wait(timeout=1.0)
                crashed = True
            except Exception:
                pass
            self.daemon_process = None

        res = {
            "call_id": call_id,
            "event": "RUNTIME_SERVICE_CRASH",
            "reason": reason,
            "crashed": crashed,
            "timestamp": now,
        }
        self.state_events_log.append(res)
        return res

    # -------------------------------------------------------------
    # AGENT TOOLS
    # -------------------------------------------------------------
    def discover_environment(self) -> Dict[str, Any]:
        """Discovers host configuration, candidate ports, and candidate directories."""
        self._trigger_dynamic_events()
        call_id = f"call_{uuid.uuid4().hex[:8]}"
        res = {
            "call_id": call_id,
            "user": self.non_root_user,
            "uid": 1001,
            "candidate_ports": [18080, 18081, 18082],
            "candidate_config_dirs": [
                "/etc/service_demo",
                "/home/agentuser/service_conf",
                "/tmp/service_runtime",
            ],
            "service_name": "telemetry_agent",
            "instructions": "Select an available port and a writable config directory to configure and start the service.",
            "timestamp": time.time(),
        }
        self.tool_call_history.append({
            "call_id": call_id,
            "step": self.step_count,
            "tool": "discover_environment",
            "params": {},
            "exit_code": 0,
            "result": res,
            "timestamp": res["timestamp"],
        })
        return res

    def probe_port(self, port: int) -> Dict[str, Any]:
        """Probes whether a port is currently listening."""
        self._trigger_dynamic_events()
        call_id = f"call_{uuid.uuid4().hex[:8]}"
        occupied = is_port_listening(port)
        res = {
            "call_id": call_id,
            "port": port,
            "status": "OCCUPIED" if occupied else "FREE",
            "is_occupied": occupied,
            "timestamp": time.time(),
        }
        self.tool_call_history.append({
            "call_id": call_id,
            "step": self.step_count,
            "tool": "probe_port",
            "params": {"port": port},
            "exit_code": 0,
            "result": res,
            "timestamp": res["timestamp"],
        })
        return res

    def probe_directory(self, dirpath: str) -> Dict[str, Any]:
        """Probes whether a directory exists and is writable by non-root user."""
        self._trigger_dynamic_events()
        call_id = f"call_{uuid.uuid4().hex[:8]}"
        p = Path(dirpath)
        if not p.exists():
            res = {
                "call_id": call_id,
                "dirpath": dirpath,
                "exists": False,
                "writable_by_user": False,
                "mode": "none",
                "timestamp": time.time(),
            }
        else:
            # Check write permission for non-root agentuser
            cmd_str = f"test -w '{dirpath}'"
            sub_res = subprocess.run(
                ["su", "-s", "/bin/bash", self.non_root_user, "-c", cmd_str],
                capture_output=True,
            )
            is_writable = (sub_res.returncode == 0)
            st = os.stat(p)
            res = {
                "call_id": call_id,
                "dirpath": dirpath,
                "exists": True,
                "writable_by_user": is_writable,
                "mode": oct(st.st_mode)[-4:],
                "owner_uid": st.st_uid,
                "timestamp": time.time(),
            }

        self.tool_call_history.append({
            "call_id": call_id,
            "step": self.step_count,
            "tool": "probe_directory",
            "params": {"dirpath": dirpath},
            "exit_code": 0,
            "result": res,
            "timestamp": res["timestamp"],
        })
        return res

    def probe_file(self, filepath: str) -> Dict[str, Any]:
        """
        Probes whether a target file path is writable by non-root user.
        Distinguishes:
        - Overwriting existing file: checks writability of target file.
        - Creating new file: checks existence and writability of parent directory.
        """
        self._trigger_dynamic_events()
        call_id = f"call_{uuid.uuid4().hex[:8]}"
        p = Path(filepath)
        file_exists = p.exists()
        parent_dir = str(p.parent)
        now = time.time()

        if file_exists:
            cmd_str = f"test -w '{filepath}'"
            sub_res = subprocess.run(
                ["su", "-s", "/bin/bash", self.non_root_user, "-c", cmd_str],
                capture_output=True,
            )
            is_writable = (sub_res.returncode == 0)
            try:
                st = os.stat(p)
                mode = oct(st.st_mode)[-4:]
                owner_uid = st.st_uid
            except Exception:
                mode = "none"
                owner_uid = None
            is_new = False
        else:
            is_new = True
            parent_p = Path(parent_dir)
            if not parent_p.exists():
                is_writable = False
                mode = "none"
                owner_uid = None
            else:
                cmd_str = f"test -w '{parent_dir}'"
                sub_res = subprocess.run(
                    ["su", "-s", "/bin/bash", self.non_root_user, "-c", cmd_str],
                    capture_output=True,
                )
                is_writable = (sub_res.returncode == 0)
                try:
                    st = os.stat(parent_p)
                    mode = oct(st.st_mode)[-4:]
                    owner_uid = st.st_uid
                except Exception:
                    mode = "none"
                    owner_uid = None

        res = {
            "call_id": call_id,
            "filepath": filepath,
            "exists": file_exists,
            "is_new": is_new,
            "parent_dir": parent_dir,
            "writable_by_user": is_writable,
            "mode": mode,
            "owner_uid": owner_uid,
            "timestamp": now,
        }
        self.tool_call_history.append({
            "call_id": call_id,
            "step": self.step_count,
            "tool": "probe_file",
            "params": {"filepath": filepath},
            "exit_code": 0,
            "result": res,
            "timestamp": now,
        })
        return res

    def write_config(self, config_path: str, port: int, service_name: str = "telemetry_agent") -> Dict[str, Any]:
        """Writes configuration file to disk as non-root user."""
        self._trigger_dynamic_events()
        call_id = f"call_{uuid.uuid4().hex[:8]}"
        target_path = Path(config_path)

        cfg_content = json.dumps({
            "service_name": service_name,
            "port": port,
            "worker_threads": 2,
            "created_at": time.time(),
        }, indent=2)

        # Attempt writing file as agentuser
        escaped_content = cfg_content.replace("'", "'\\''")
        cmd_str = f"cat << 'EOF' > '{config_path}'\n{cfg_content}\nEOF"
        sub_res = subprocess.run(
            ["su", "-s", "/bin/bash", self.non_root_user, "-c", cmd_str],
            capture_output=True,
            text=True,
        )

        now = time.time()
        raw_stderr = (sub_res.stderr or "").strip()
        raw_stdout = (sub_res.stdout or "").strip()
        if sub_res.returncode != 0:
            raw_lower = raw_stderr.lower()
            if "permission denied" in raw_lower:
                err_code = 13
                err_type = "PermissionDenied"
                err_msg = raw_stderr or f"Permission denied: unable to write configuration to {config_path}"
            elif "no such file or directory" in raw_lower:
                err_code = 2
                err_type = "FileNotFound"
                err_msg = raw_stderr or f"No such file or directory: {config_path}"
            elif "read-only file system" in raw_lower:
                err_code = 30
                err_type = "ReadOnly"
                err_msg = raw_stderr or f"Read-only file system: {config_path}"
            else:
                err_code = sub_res.returncode
                err_type = "CommandExecutionError"
                err_msg = raw_stderr or f"Command failed with exit code {sub_res.returncode}"

            res = {
                "call_id": call_id,
                "success": False,
                "exit_code": sub_res.returncode,
                "error_code": err_code,
                "error_type": err_type,
                "stderr": err_msg,
                "stdout": raw_stdout,
                "config_snapshot": {"service_name": service_name, "port": port},
                "resource_id": f"file:{config_path}",
                "timestamp": now,
            }
        else:
            self.deployed_config_path = str(target_path)
            res = {
                "call_id": call_id,
                "success": True,
                "exit_code": 0,
                "error_code": 0,
                "error_type": None,
                "config_path": str(target_path),
                "port": port,
                "config_snapshot": {"service_name": service_name, "port": port},
                "resource_id": f"file:{config_path}",
                "stderr": "",
                "stdout": f"Configuration successfully written to {config_path}",
                "timestamp": now,
            }

        self.tool_call_history.append({
            "call_id": call_id,
            "step": self.step_count,
            "tool": "write_config",
            "params": {"config_path": config_path, "port": port, "service_name": service_name},
            "exit_code": res["exit_code"],
            "result": res,
            "timestamp": now,
        })
        return res

    def start_service(self, config_path: str) -> Dict[str, Any]:
        """Launches the service daemon with specified config file."""
        self._trigger_dynamic_events()
        call_id = f"call_{uuid.uuid4().hex[:8]}"
        now = time.time()

        if not os.path.exists(config_path):
            res = {
                "call_id": call_id,
                "success": False,
                "exit_code": 1,
                "error_code": 2,
                "error_type": "FileNotFoundError",
                "stderr": f"FileNotFoundError: Config file not found: {config_path}",
                "stdout": "",
                "timestamp": now,
            }
            self.tool_call_history.append({
                "call_id": call_id,
                "step": self.step_count,
                "tool": "start_service",
                "params": {"config_path": config_path},
                "exit_code": res["exit_code"],
                "result": res,
                "timestamp": now,
            })
            return res

        # Check config readability by non-root user
        check_res = subprocess.run(
            ["su", "-s", "/bin/bash", self.non_root_user, "-c", f"test -r '{config_path}'"],
            capture_output=True,
        )
        if check_res.returncode != 0:
            res = {
                "call_id": call_id,
                "success": False,
                "exit_code": 13,
                "error_code": 13,
                "error_type": "PermissionDenied",
                "stderr": f"PermissionError: Permission denied reading config {config_path}",
                "stdout": "",
                "timestamp": now,
            }
            self.tool_call_history.append({
                "call_id": call_id,
                "step": self.step_count,
                "tool": "start_service",
                "params": {"config_path": config_path},
                "exit_code": res["exit_code"],
                "result": res,
                "timestamp": now,
            })
            return res

        # Read config to know target port
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            port = cfg["port"]
        except Exception as e:
            res = {
                "call_id": call_id,
                "success": False,
                "exit_code": 2,
                "error_code": 2,
                "error_type": "ValueError",
                "stderr": f"ValueError: Failed to parse config JSON: {e}",
                "stdout": "",
                "timestamp": now,
            }
            self.tool_call_history.append({
                "call_id": call_id,
                "step": self.step_count,
                "tool": "start_service",
                "params": {"config_path": config_path},
                "exit_code": res["exit_code"],
                "result": res,
                "timestamp": now,
            })
            return res

        # Terminate any previously running daemon
        if self.daemon_process:
            try:
                self.daemon_process.terminate()
                self.daemon_process.wait(timeout=1.0)
            except Exception:
                try:
                    self.daemon_process.kill()
                except Exception:
                    pass
            self.daemon_process = None

        # Launch daemon process
        proc = subprocess.Popen(
            [sys.executable, str(DAEMON_SCRIPT), "--config", config_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        # Wait briefly for startup or immediate exit (e.g. port bind failure)
        t0 = time.time()
        bind_failed = False
        err_msg = ""
        exit_code = 0
        error_type = None

        while time.time() - t0 < 1.5:
            ret = proc.poll()
            if ret is not None:
                # Process exited immediately
                bind_failed = True
                exit_code = ret
                _, stderr = proc.communicate()
                err_msg = stderr.strip()
                if "Address already in use" in err_msg or ret == 98:
                    error_type = "AddressAlreadyInUse"
                elif "Permission denied" in err_msg or ret == 13:
                    error_type = "PermissionDenied"
                else:
                    error_type = "ProcessExitError"
                break

            if is_port_listening(port):
                # Verify that it is OUR daemon listening and not an alien occupier process
                try:
                    s_chk = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s_chk.settimeout(0.2)
                    s_chk.connect(("127.0.0.1", port))
                    s_chk.sendall(b"HEALTH_CHECK\n")
                    chk_resp = s_chk.recv(1024).decode("utf-8", errors="ignore").strip()
                    s_chk.close()
                    if chk_resp.startswith("{"):
                        chk_data = json.loads(chk_resp)
                        if chk_data.get("pid") == proc.pid:
                            # Confirmed: our daemon is listening and healthy!
                            break
                except Exception:
                    pass

            time.sleep(0.05)

        if not bind_failed and proc.poll() is not None:
            bind_failed = True
            exit_code = proc.returncode
            _, stderr = proc.communicate()
            err_msg = stderr.strip()
            if "Address already in use" in err_msg or exit_code == 98:
                error_type = "AddressAlreadyInUse"
            elif "Permission denied" in err_msg or exit_code == 13:
                error_type = "PermissionDenied"
            else:
                error_type = "ProcessExitError"

        if bind_failed:
            res = {
                "call_id": call_id,
                "success": False,
                "exit_code": exit_code,
                "error_code": exit_code,
                "error_type": error_type,
                "stderr": err_msg or f"Service process exited prematurely with code {exit_code}",
                "stdout": "",
                "config_snapshot": {"port": port, "config_path": config_path},
                "resource_id": f"port:{port}",
                "timestamp": time.time(),
            }
        else:
            self.daemon_process = proc
            self.deployed_port = port
            self.deployed_config_path = config_path
            res = {
                "call_id": call_id,
                "success": True,
                "exit_code": 0,
                "error_code": 0,
                "error_type": None,
                "port": port,
                "config_path": config_path,
                "config_snapshot": {"port": port, "config_path": config_path},
                "resource_id": f"port:{port}",
                "pid": proc.pid,
                "stderr": "",
                "stdout": f"Service telemetry_agent successfully started and listening on 127.0.0.1:{port}",
                "timestamp": time.time(),
            }

        self.tool_call_history.append({
            "call_id": call_id,
            "step": self.step_count,
            "tool": "start_service",
            "params": {"config_path": config_path},
            "exit_code": res["exit_code"],
            "result": res,
            "timestamp": res["timestamp"],
        })
        return res

    def check_health(self, port: int) -> Dict[str, Any]:
        """Performs active TCP HEALTH_CHECK on the service port."""
        self._trigger_dynamic_events()
        call_id = f"call_{uuid.uuid4().hex[:8]}"
        now = time.time()

        if not is_port_listening(port):
            res = {
                "call_id": call_id,
                "port": port,
                "status": "DOWN",
                "healthy": False,
                "error": f"Connection refused: port {port} is not listening",
                "timestamp": now,
            }
        else:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1.5)
            try:
                s.connect(("127.0.0.1", port))
                s.sendall(b"HEALTH_CHECK\n")
                raw_resp = s.recv(1024).decode("utf-8", errors="ignore").strip()
                s.close()
                parsed = json.loads(raw_resp) if raw_resp.startswith("{") else {"raw": raw_resp}
                res = {
                    "call_id": call_id,
                    "port": port,
                    "status": parsed.get("status", "UNKNOWN"),
                    "healthy": parsed.get("status") == "UP",
                    "details": parsed,
                    "timestamp": now,
                }
            except Exception as e:
                s.close()
                res = {
                    "call_id": call_id,
                    "port": port,
                    "status": "ERROR",
                    "healthy": False,
                    "error": str(e),
                    "timestamp": now,
                }

        self.tool_call_history.append({
            "call_id": call_id,
            "step": self.step_count,
            "tool": "check_health",
            "params": {"port": port},
            "exit_code": 0 if res["healthy"] else 1,
            "result": res,
            "timestamp": now,
        })
        return res

    # -------------------------------------------------------------
    # INDEPENDENT VERIFIER
    # -------------------------------------------------------------
    def verify_completion(self) -> Tuple[bool, str]:
        """
        Independent Verifier:
        Confirms:
        1. Process is actively alive.
        2. Config file exists on disk and was read by the process.
        3. Port is listening and responds to HEALTH_CHECK with status == UP.
        4. Config on disk matches the live running parameters.
        Returns: (True, "reason") if verified, (False, "reason") otherwise.
        """
        if not self.daemon_process:
            return False, "Verifier Failure: No active service process registered in environment."

        if self.daemon_process.poll() is not None:
            return False, f"Verifier Failure: Service process exited with code {self.daemon_process.returncode}."

        if not self.deployed_port or not self.deployed_config_path:
            return False, "Verifier Failure: Missing deployed port or config path."

        if not os.path.exists(self.deployed_config_path):
            return False, f"Verifier Failure: Config file does not exist on disk: {self.deployed_config_path}"

        try:
            with open(self.deployed_config_path, "r", encoding="utf-8") as f:
                disk_cfg = json.load(f)
            if disk_cfg.get("port") != self.deployed_port:
                return False, f"Verifier Failure: Disk config port ({disk_cfg.get('port')}) does not match deployed port ({self.deployed_port})."
        except Exception as e:
            return False, f"Verifier Failure: Unable to read/parse disk config: {e}"

        # Connect and check live endpoint
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.5)
        try:
            s.connect(("127.0.0.1", self.deployed_port))
            s.sendall(b"HEALTH_CHECK\n")
            raw_resp = s.recv(1024).decode("utf-8", errors="ignore").strip()
            s.close()
            parsed = json.loads(raw_resp)
            if parsed.get("status") != "UP":
                return False, f"Verifier Failure: Service health status is '{parsed.get('status')}', expected 'UP'."
            if parsed.get("port") != self.deployed_port:
                return False, f"Verifier Failure: Live service reports port {parsed.get('port')}, expected {self.deployed_port}."
            if parsed.get("config_path") != os.path.abspath(self.deployed_config_path):
                return False, f"Verifier Failure: Live service reports config path {parsed.get('config_path')}, expected {self.deployed_config_path}."
        except Exception as e:
            s.close()
            return False, f"Verifier Failure: Failed TCP health handshake on port {self.deployed_port}: {e}"

        return True, f"Verified: telemetry_agent running on port {self.deployed_port} with config {self.deployed_config_path}."

    def teardown(self):
        """Cleans up daemon and all occupier processes."""
        if self.daemon_process:
            try:
                self.daemon_process.terminate()
                self.daemon_process.wait(timeout=1.0)
            except Exception:
                try:
                    self.daemon_process.kill()
                except Exception:
                    pass
            self.daemon_process = None

        for p, proc in list(self.occupier_processes.items()):
            try:
                proc.terminate()
                proc.wait(timeout=1.0)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        self.occupier_processes.clear()
        time.sleep(0.1)


# -------------------------------------------------------------
# DETERMINISTIC OFFLINE SOLVERS
# -------------------------------------------------------------
def solve_instance(env: MultiStepDeploymentEnv, instance_id: str) -> bool:
    """
    Deterministic solver proving each of the 8 instances is solvable.
    Returns True if independent verifier confirms deployment.
    """
    env.setup(instance_id)

    # Step 1: Discover
    disc = env.discover_environment()
    user_conf = "/home/agentuser/service_conf/app.json"

    if instance_id == "inst1_port_conflict_persistent":
        # Port 18080 occupied -> probe 18080 -> choose 18081 -> write config -> start -> health
        p0 = env.probe_port(18080)
        assert p0["is_occupied"] is True
        env.write_config(user_conf, port=18081)
        env.start_service(user_conf)
        env.check_health(18081)

    elif instance_id == "inst2_blockage_cleared":
        # Port 18080 occupied at step 1-2 -> probe at step 2 (occupied) -> step 3 clears -> recheck (free) -> use 18080
        p0 = env.probe_port(18080)
        assert p0["is_occupied"] is True
        env.probe_directory("/home/agentuser/service_conf")  # triggers step 3 dynamic event (blockage cleared)
        p_cleared = env.probe_port(18080)
        assert p_cleared["is_occupied"] is False
        env.write_config(user_conf, port=18080)
        env.start_service(user_conf)
        env.check_health(18080)

    elif instance_id == "inst3_permission_fallback":
        # /etc/service_demo is 0755 non-writable -> probe dir -> write to user_conf -> start on 18080
        p_etc = env.probe_directory("/etc/service_demo")
        assert p_etc["writable_by_user"] is False
        env.write_config(user_conf, port=18080)
        env.start_service(user_conf)
        env.check_health(18080)

    elif instance_id == "inst4_irrelevant_change":
        # Irrelevant audit log updated at step 2 -> nominal deployment on 18080
        env.probe_port(18080)
        env.write_config(user_conf, port=18080)
        env.start_service(user_conf)
        env.check_health(18080)

    elif instance_id == "inst5_stale_observation":
        # 18080 free at step 2 -> step 3 occupied -> agent probes or catches failure, uses 18081
        p_init = env.probe_port(18080)
        assert p_init["is_occupied"] is False
        env.probe_directory("/home/agentuser/service_conf")  # triggers step 3 dynamic event (resource preempted)
        p_recheck = env.probe_port(18080)
        assert p_recheck["is_occupied"] is True
        env.write_config(user_conf, port=18081)
        env.start_service(user_conf)
        env.check_health(18081)

    elif instance_id == "inst6_counterexample_feasibility":
        # Counterexample: 18080 works fine
        env.probe_port(18080)
        env.write_config(user_conf, port=18080)
        env.start_service(user_conf)
        env.check_health(18080)

    elif instance_id == "inst7_midepisode_port_clash":
        # Mid-episode clash at step 3 on 18080, port 18081 reserved -> adapt to 18082
        p_init = env.probe_port(18080)
        assert p_init["is_occupied"] is False
        env.probe_directory("/home/agentuser/service_conf")  # triggers step 3 dynamic event (port clash)
        p_clash = env.probe_port(18080)
        assert p_clash["is_occupied"] is True
        p_reserved = env.probe_port(18081)
        assert p_reserved["is_occupied"] is True
        env.write_config(user_conf, port=18082)
        env.start_service(user_conf)
        env.check_health(18082)

    elif instance_id == "inst8_permission_and_port_composition":
        # /etc/service_demo non-writable AND 18080 occupied -> user_conf + 18081
        p_dir = env.probe_directory("/etc/service_demo")
        p_port = env.probe_port(18080)
        assert p_dir["writable_by_user"] is False
        assert p_port["is_occupied"] is True
        env.write_config(user_conf, port=18081)
        env.start_service(user_conf)
        env.check_health(18081)

    ok, msg = env.verify_completion()
    return ok
