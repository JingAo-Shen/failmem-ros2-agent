"""
Standalone CPU Environment Verification for 3 Real Container Failure Mechanisms.
Implements:
1. Port occupancy (real Python socket listener)
2. File permissions (non-root user access permission denied, 0644 vs 0666)
3. Config version mismatch (real local build script assertion)

All operations strictly local to /tmp/constraint_env_test, no external internet, no systemd.
"""
import os
import sys
import time
import socket
import subprocess
from pathlib import Path

ENV_DIR = Path("/tmp/constraint_env_test")
ENV_DIR.mkdir(parents=True, exist_ok=True)
# Ensure directory has rwx permissions for all so nobody can traverse it
os.chmod(ENV_DIR, 0o777)

class PortOccupancyMechanism:
    """Mechanism 1: Real background socket listener occupying a local port."""
    def __init__(self, port: int = 18080):
        self.port = port
        self.listener_process = None

    def setup_state_a(self):
        """State A: Real process listening on port."""
        self.teardown()
        cmd = [sys.executable, "-c", f"""
import socket, time
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(('127.0.0.1', {self.port}))
s.listen(5)
while True:
    time.sleep(1)
"""]
        self.listener_process = subprocess.Popen(cmd)
        time.sleep(0.3)

    def setup_state_b(self):
        """State B: Port freed, action feasible."""
        self.teardown()
        time.sleep(0.2)

    def setup_state_c(self):
        """State C: Unrelated attribute changed (different commandline/PID), port still occupied."""
        self.teardown()
        cmd = [sys.executable, "-c", f"""
# Process alias: mock_worker_process
import socket, time
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(('127.0.0.1', {self.port}))
s.listen(1)
while True:
    time.sleep(0.5)
"""]
        self.listener_process = subprocess.Popen(cmd)
        time.sleep(0.3)

    def teardown(self):
        if self.listener_process:
            try:
                self.listener_process.terminate()
                self.listener_process.wait(timeout=1.0)
            except Exception:
                try:
                    self.listener_process.kill()
                except Exception:
                    pass
            self.listener_process = None

    def probe(self) -> dict:
        """Probe environment via standard socket connect test."""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5)
        try:
            res = s.connect_ex(('127.0.0.1', self.port))
            is_occupied = (res == 0)
        finally:
            s.close()
        return {
            "port": self.port,
            "is_occupied": is_occupied,
            "timestamp": time.time()
        }

    def execute_target_action(self) -> dict:
        """Target Action: Bind server to port."""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(('127.0.0.1', self.port))
            s.listen(1)
            s.close()
            return {"success": True, "error_code": 0, "stderr": ""}
        except OSError as e:
            return {"success": False, "error_code": e.errno, "stderr": str(e)}


class FilePermissionMechanism:
    """Mechanism 2: Real filesystem permission denied for non-root execution context."""
    def __init__(self, filepath: Path = ENV_DIR / "protected_app.conf", non_root_user: str = "nobody"):
        self.filepath = filepath
        self.non_root_user = non_root_user

    def setup_state_a(self):
        """State A: File is owned by root and mode 0644 (non-root cannot write)."""
        self.filepath.write_text("INITIAL_READONLY_CONFIG=true\n", encoding="utf-8")
        os.chmod(self.filepath, 0o644)

    def setup_state_b(self):
        """State B: File permission updated to world-writable 0666 (non-root can write)."""
        if not self.filepath.exists():
            self.filepath.write_text("CONFIG=true\n", encoding="utf-8")
        os.chmod(self.filepath, 0o666)

    def setup_state_c(self):
        """State C: Unrelated attribute changed (touch access/mtime, comment added), still 0644."""
        os.chmod(self.filepath, 0o666)
        self.filepath.write_text("CONFIG=true\n# Unrelated comment line\n", encoding="utf-8")
        os.chmod(self.filepath, 0o644)
        os.utime(self.filepath, None)

    def teardown(self):
        if self.filepath.exists():
            try:
                os.chmod(self.filepath, 0o666)
                self.filepath.unlink()
            except Exception:
                pass

    def probe(self) -> dict:
        """Probe environment via stat checking write permission for non-root context."""
        if not self.filepath.exists():
            return {"exists": False, "writable_by_non_root": False, "timestamp": time.time()}
        st = os.stat(self.filepath)
        # Check if world-writable (since non_root_user is not owner and not in root group)
        writable = bool(st.st_mode & 0o002)
        return {
            "exists": True,
            "mode_octal": oct(st.st_mode)[-3:],
            "writable_by_non_root": writable,
            "timestamp": time.time()
        }

    def execute_target_action(self) -> dict:
        """Target Action: Non-root user attempts to write to file."""
        cmd = ["su", "-s", "/bin/bash", self.non_root_user, "-c", f"echo 'APPENDED_PARAM=value' >> {self.filepath}"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        return {
            "success": (res.returncode == 0),
            "error_code": res.returncode,
            "stderr": res.stderr.strip()
        }


class ConfigVersionMismatchMechanism:
    """Mechanism 3: Local build/run tool checking protocol version compatibility."""
    def __init__(self, workdir: Path = ENV_DIR / "build_project"):
        self.workdir = workdir
        self.cfg_file = self.workdir / "project.ini"
        self.build_script = self.workdir / "run_build.py"
        self.workdir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.workdir, 0o777)
        self._init_build_tool()

    def _init_build_tool(self):
        code = """import sys, configparser
from pathlib import Path
cfg = configparser.ConfigParser()
cfg_path = Path(__file__).parent / 'project.ini'
if not cfg_path.exists():
    sys.stderr.write("ERROR: Missing project.ini\\n")
    sys.exit(1)
cfg.read(cfg_path)
ver = cfg.get('protocol', 'version', fallback='unknown')
if ver != '2.0':
    sys.stderr.write(f"BUILD_ERROR: Incompatible protocol version '{ver}'. Minimum required: 2.0\\n")
    sys.exit(2)
sys.stdout.write("BUILD_SUCCESS: Built artifacts with protocol 2.0\\n")
sys.exit(0)
"""
        self.build_script.write_text(code, encoding="utf-8")

    def setup_state_a(self):
        """State A: Protocol version is 1.0 (incompatible)."""
        self.cfg_file.write_text("[protocol]\nversion = 1.0\n[build]\nopt = false\n", encoding="utf-8")

    def setup_state_b(self):
        """State B: Protocol version is 2.0 (compatible)."""
        self.cfg_file.write_text("[protocol]\nversion = 2.0\n[build]\nopt = false\n", encoding="utf-8")

    def setup_state_c(self):
        """State C: Unrelated attribute changed (log_level=debug added), version still 1.0."""
        self.cfg_file.write_text("[protocol]\nversion = 1.0\n[build]\nopt = false\nlog_level = debug\n# Author comment\n", encoding="utf-8")

    def teardown(self):
        if self.cfg_file.exists():
            self.cfg_file.unlink()

    def probe(self) -> dict:
        """Probe config file version."""
        if not self.cfg_file.exists():
            return {"exists": False, "version": None, "timestamp": time.time()}
        lines = self.cfg_file.read_text(encoding="utf-8").splitlines()
        ver = None
        for l in lines:
            if l.strip().startswith("version"):
                ver = l.split("=")[-1].strip()
        return {
            "exists": True,
            "version": ver,
            "is_compatible": (ver == "2.0"),
            "timestamp": time.time()
        }

    def execute_target_action(self) -> dict:
        """Target Action: Execute local build script."""
        res = subprocess.run([sys.executable, str(self.build_script)], capture_output=True, text=True)
        return {
            "success": (res.returncode == 0),
            "error_code": res.returncode,
            "stderr": res.stderr.strip(),
            "stdout": res.stdout.strip()
        }
