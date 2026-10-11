"""
Deterministic Real System Task Environments for Conditional Failure Constraint Memory.
Implements:
1. PortTaskEnvironment: Real socket listeners on 18080/18081, passive /proc/net/tcp probe, independent socket verifier.
2. FilePermissionTaskEnvironment: Non-root 'agentuser' context, /etc/service_demo/app.conf (0644) vs user override, independent config verifier.
3. ConfigVersionMismatchSyntheticEnvironment: Explicitly marked SYNTHETIC protocol version check.

Includes readiness checks and 100-probe jitter-free stability testing.
"""

import os
import sys
import time
import socket
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional, Tuple


ENV_DIR = Path("/tmp/constraint_env_test")
ENV_DIR.mkdir(parents=True, exist_ok=True)
os.chmod(ENV_DIR, 0o777)

SYS_CONF_DIR = Path("/etc/service_demo")
SYS_CONF_DIR.mkdir(parents=True, exist_ok=True)
SYS_CONF_FILE = SYS_CONF_DIR / "app.conf"
USER_OVERRIDE_FILE = Path("/home/agentuser/user_override.conf")


def is_port_listening(port: int) -> bool:
    """Passively checks if a TCP port is in LISTEN state using /proc/net/tcp and /proc/net/tcp6."""
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


class PortTaskEnvironment:
    """
    Real Port Environment:
    - Primary port: 18080
    - Alternative legal port: 18081
    - Background occupier runs in State A, C, D
    - Independent verifier performs real TCP handshake to confirm service readiness.
    """
    def __init__(self, primary_port: int = 18080, alt_port: int = 18081):
        self.primary_port = primary_port
        self.alt_port = alt_port
        self.occupier_process: Optional[subprocess.Popen] = None
        self.service_processes: Dict[int, subprocess.Popen] = {}
        self.current_state: Optional[str] = None

    def setup(self, state: str):
        """Sets up environment for State A, B, C, or D."""
        self.teardown()
        self.current_state = state.upper()

        if self.current_state in ("A", "C", "D"):
            # Start background socket listener on primary_port
            cmd_comment = "mock_occupier" if self.current_state != "C" else "worker_daemon_v2"
            script = f"""
import socket, time
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(('127.0.0.1', {self.primary_port}))
s.listen(5)
# {cmd_comment}
while True:
    try:
        conn, _ = s.accept()
        conn.sendall(b'OCCUPIED_BANNER\\n')
        conn.close()
    except Exception:
        time.sleep(0.5)
"""
            self.occupier_process = subprocess.Popen([sys.executable, "-c", script])
            # Wait for readiness
            t0 = time.time()
            while time.time() - t0 < 3.0:
                if is_port_listening(self.primary_port):
                    break
                time.sleep(0.05)
        elif self.current_state == "B":
            # Primary port is completely free
            pass
        else:
            raise ValueError(f"Unknown state: {state}")

    def readiness_check(self) -> bool:
        """Verifies environment readiness."""
        if self.current_state in ("A", "C", "D"):
            return is_port_listening(self.primary_port) and not is_port_listening(self.alt_port)
        elif self.current_state == "B":
            return not is_port_listening(self.primary_port) and not is_port_listening(self.alt_port)
        return False

    def probe(self, port: int) -> Dict[str, Any]:
        """Independent probe tool: checks if port is occupied."""
        occupied = is_port_listening(port)
        return {
            "port": port,
            "status": "OCCUPIED" if occupied else "FREE",
            "is_occupied": occupied,
            "timestamp": time.time(),
        }

    def execute_start_service(self, port: int) -> Dict[str, Any]:
        """
        Target Action: start service on given port.
        Attempts real socket bind.
        """
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(('127.0.0.1', port))
            s.close()
        except OSError as e:
            s.close()
            return {
                "success": False,
                "error_code": e.errno,
                "error_type": "AddressAlreadyInUse" if e.errno == 98 else "OSError",
                "stderr": f"OSError: [Errno {e.errno}] {e.strerror} (Port {port})",
                "stdout": "",
            }

        # If bind succeeded, start the actual service echo responder
        service_script = f"""
import socket, time
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(('127.0.0.1', {port}))
s.listen(5)
while True:
    try:
        conn, _ = s.accept()
        data = conn.recv(1024)
        if b'PING' in data:
            conn.sendall(b'PONG\\n')
        else:
            conn.sendall(b'SERVICE_ACTIVE\\n')
        conn.close()
    except Exception:
        time.sleep(0.5)
"""
        proc = subprocess.Popen([sys.executable, "-c", service_script])
        self.service_processes[port] = proc
        # Wait until listening
        t0 = time.time()
        while time.time() - t0 < 2.0:
            if is_port_listening(port):
                break
            time.sleep(0.05)

        return {
            "success": True,
            "error_code": 0,
            "error_type": None,
            "stderr": "",
            "stdout": f"Service successfully started and listening on 127.0.0.1:{port}",
        }

    def verify_completion(self) -> bool:
        """
        Independent Verifier:
        Connects via TCP and exchanges PING/PONG with the agent's service.
        In State A, C, D: requires service on alt_port 18081.
        In State B: service on primary_port 18080 (or alt_port 18081) succeeds.
        """
        ports_to_check = [self.alt_port, self.primary_port]
        for p in ports_to_check:
            if p in self.service_processes and is_port_listening(p):
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(1.0)
                try:
                    s.connect(('127.0.0.1', p))
                    s.sendall(b'PING\n')
                    resp = s.recv(1024)
                    s.close()
                    if b'PONG' in resp:
                        return True
                except Exception:
                    s.close()
        return False

    def teardown(self):
        """Cleans up occupier and service processes."""
        if self.occupier_process:
            try:
                self.occupier_process.terminate()
                self.occupier_process.wait(timeout=1.0)
            except Exception:
                try:
                    self.occupier_process.kill()
                except Exception:
                    pass
            self.occupier_process = None

        for p, proc in list(self.service_processes.items()):
            try:
                proc.terminate()
                proc.wait(timeout=1.0)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        self.service_processes.clear()
        time.sleep(0.1)


class FilePermissionTaskEnvironment:
    """
    Real File Permission Environment:
    - Primary config: /etc/service_demo/app.conf (root:root, mode 0644 in State A, C, D; mode 0666 in State B)
    - Non-root user: 'agentuser' (UID 1001)
    - Alternative legal path: /home/agentuser/user_override.conf
    - Independent verifier checks effective configuration without leaking.
    """
    def __init__(self, non_root_user: str = "agentuser"):
        self.non_root_user = non_root_user
        self.sys_file = SYS_CONF_FILE
        self.user_file = USER_OVERRIDE_FILE
        self.current_state: Optional[str] = None

    def setup(self, state: str):
        """Sets up filesystem permissions according to state."""
        self.teardown()
        self.current_state = state.upper()

        SYS_CONF_DIR.mkdir(parents=True, exist_ok=True)
        os.chmod(SYS_CONF_DIR, 0o755)

        if self.current_state == "A":
            self.sys_file.write_text("BASE_CONFIG=DEFAULT\n", encoding="utf-8")
            os.chmod(self.sys_file, 0o644)
        elif self.current_state == "B":
            self.sys_file.write_text("BASE_CONFIG=DEFAULT\n", encoding="utf-8")
            os.chmod(self.sys_file, 0o666)
        elif self.current_state == "C":
            # Irrelevant attribute: updated mtime and comments, still 0644
            self.sys_file.write_text("# Updated header timestamp\nBASE_CONFIG=DEFAULT\n", encoding="utf-8")
            os.chmod(self.sys_file, 0o644)
            os.utime(self.sys_file, None)
        elif self.current_state == "D":
            # 0644, requires active probe to discover
            self.sys_file.write_text("BASE_CONFIG=DEFAULT\n", encoding="utf-8")
            os.chmod(self.sys_file, 0o644)
        else:
            raise ValueError(f"Unknown state: {state}")

    def readiness_check(self) -> bool:
        """Verifies environment readiness."""
        if not self.sys_file.exists():
            return False
        st = os.stat(self.sys_file)
        is_world_writable = bool(st.st_mode & 0o002)
        if self.current_state in ("A", "C", "D"):
            return not is_world_writable and not self.user_file.exists()
        elif self.current_state == "B":
            return is_world_writable and not self.user_file.exists()
        return False

    def probe(self, filepath: str) -> Dict[str, Any]:
        """Independent probe tool: checks file existence and non-root write access."""
        p = Path(filepath)
        if not p.exists():
            return {
                "filepath": str(p),
                "exists": False,
                "writable_by_agentuser": False,
                "mode": "none",
                "timestamp": time.time(),
            }
        st = os.stat(p)
        is_writable = False
        if st.st_uid == 1001:
            is_writable = bool(st.st_mode & 0o200)
        elif st.st_gid == 1001:
            is_writable = bool(st.st_mode & 0o020)
        else:
            is_writable = bool(st.st_mode & 0o002)

        return {
            "filepath": str(p),
            "exists": True,
            "writable_by_agentuser": is_writable,
            "mode": oct(st.st_mode)[-4:],
            "timestamp": time.time(),
        }

    def execute_write_config(self, filepath: str, key: str, value: str) -> Dict[str, Any]:
        """
        Target Action: writes config entry as non-root user 'agentuser'.
        """
        cmd_str = f"echo '{key}={value}' >> '{filepath}'"
        res = subprocess.run(
            ["su", "-s", "/bin/bash", self.non_root_user, "-c", cmd_str],
            capture_output=True,
            text=True,
        )
        if res.returncode == 0:
            return {
                "success": True,
                "error_code": 0,
                "error_type": None,
                "stderr": "",
                "stdout": f"Configuration successfully written to {filepath}",
            }
        else:
            return {
                "success": False,
                "error_code": res.returncode,
                "error_type": "PermissionDenied",
                "stderr": res.stderr.strip() or f"Permission denied writing to {filepath}",
                "stdout": "",
            }

    def verify_completion(self, expected_key: str = "ENABLE_TELEMETRY", expected_val: str = "true") -> bool:
        """
        Independent Verifier:
        Checks effective configuration in either user override or system config.
        """
        expected_line = f"{expected_key}={expected_val}"
        if self.user_file.exists():
            content = self.user_file.read_text(encoding="utf-8")
            if expected_line in content:
                return True
        if self.sys_file.exists():
            content = self.sys_file.read_text(encoding="utf-8")
            if expected_line in content:
                return True
        return False

    def teardown(self):
        """Cleans up created configuration files."""
        if self.user_file.exists():
            try:
                self.user_file.unlink()
            except Exception:
                pass
        if self.sys_file.exists():
            try:
                os.chmod(self.sys_file, 0o666)
                self.sys_file.unlink()
            except Exception:
                pass


class ConfigVersionMismatchSyntheticEnvironment:
    """
    Explicitly marked: [SYNTHETIC]
    Config Version Mismatch controlled synthetic task.
    """
    def __init__(self, workdir: Path = ENV_DIR / "synthetic_build"):
        self.workdir = workdir
        self.cfg_file = self.workdir / "project.ini"
        self.current_state: Optional[str] = None
        self.workdir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.workdir, 0o777)

    def setup(self, state: str):
        self.teardown()
        self.current_state = state.upper()
        if self.current_state in ("A", "C", "D"):
            self.cfg_file.write_text("[protocol]\nversion = 1.0\n", encoding="utf-8")
        elif self.current_state == "B":
            self.cfg_file.write_text("[protocol]\nversion = 2.0\n", encoding="utf-8")

    def readiness_check(self) -> bool:
        return self.cfg_file.exists()

    def probe(self) -> Dict[str, Any]:
        if not self.cfg_file.exists():
            return {"exists": False, "version": None, "timestamp": time.time()}
        lines = self.cfg_file.read_text(encoding="utf-8").splitlines()
        ver = None
        for l in lines:
            if l.strip().startswith("version"):
                ver = l.split("=")[-1].strip()
        return {"exists": True, "version": ver, "is_compatible": (ver == "2.0"), "timestamp": time.time()}

    def execute_build(self) -> Dict[str, Any]:
        probe_res = self.probe()
        if probe_res.get("is_compatible"):
            return {"success": True, "error_code": 0, "error_type": None, "stderr": "", "stdout": "Build succeeded"}
        return {
            "success": False,
            "error_code": 2,
            "error_type": "ConfigVersionMismatch",
            "stderr": f"BUILD_ERROR: Incompatible protocol version '{probe_res.get('version')}'. Minimum required: 2.0",
            "stdout": "",
        }

    def verify_completion(self) -> bool:
        return self.probe().get("is_compatible", False)

    def teardown(self):
        if self.cfg_file.exists():
            self.cfg_file.unlink()


def test_probe_stability_100_runs() -> Dict[str, Any]:
    """
    Continuous 100-run probe stability test with zero jitter.
    Tests PortTaskEnvironment and FilePermissionTaskEnvironment.
    """
    results = {"port_stability_passed": True, "file_stability_passed": True, "details": []}

    # 1. Port probe stability (State A: occupied)
    port_env = PortTaskEnvironment()
    try:
        port_env.setup("A")
        assert port_env.readiness_check(), "Port readiness failed in State A"
        port_readings = []
        for _ in range(100):
            res = port_env.probe(port_env.primary_port)
            port_readings.append(res["is_occupied"])
        if not all(port_readings):
            results["port_stability_passed"] = False
            results["details"].append(f"Port probe jitter: {port_readings.count(True)}/100 true")
        else:
            results["details"].append("Port probe: 100/100 consistent OCCUPIED readings.")
    finally:
        port_env.teardown()

    # 2. File probe stability (State A: 0644 non-writable)
    file_env = FilePermissionTaskEnvironment()
    try:
        file_env.setup("A")
        assert file_env.readiness_check(), "File readiness failed in State A"
        file_readings = []
        for _ in range(100):
            res = file_env.probe(str(file_env.sys_file))
            file_readings.append(res["writable_by_agentuser"])
        if any(file_readings):
            results["file_stability_passed"] = False
            results["details"].append(f"File probe jitter: {file_readings.count(False)}/100 false")
        else:
            results["details"].append("File probe: 100/100 consistent NOT_WRITABLE readings.")
    finally:
        file_env.teardown()

    return results
