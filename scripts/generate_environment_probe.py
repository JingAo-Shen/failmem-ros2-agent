#!/usr/bin/env python3
"""
Environment Probe Script:
Collects host hardware, CUDA, Python runtime, ROS2 status, Docker,
and Git provenance, outputting to reports/evidence/r0/environment_probe.json.
"""

import os
import sys
import json
import subprocess
import platform
from datetime import datetime, timezone

def run_cmd(cmd):
    try:
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        return res.returncode, res.stdout.strip(), res.stderr.strip()
    except Exception as e:
        return -1, "", str(e)

def main():
    probe = {}
    probe["timestamp_utc"] = datetime.now(timezone.utc).isoformat()
    
    # 1. OS & Kernel
    probe["os"] = {
        "platform": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine()
    }
    _, lsb, _ = run_cmd("cat /etc/os-release")
    probe["os"]["os_release"] = lsb.splitlines()

    # 2. CPU & RAM
    _, cpu_model, _ = run_cmd("lscpu | grep 'Model name:' | head -n 1")
    _, cpu_cores, _ = run_cmd("nproc")
    _, mem_info, _ = run_cmd("free -h")
    probe["cpu_and_memory"] = {
        "cpu_model": cpu_model.replace("Model name:", "").strip(),
        "cpu_threads": int(cpu_cores) if cpu_cores.isdigit() else cpu_cores,
        "memory_summary": mem_info.splitlines()
    }

    # 3. GPU & CUDA
    _, nvidia_smi, _ = run_cmd("nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader")
    _, nvcc_ver, _ = run_cmd("nvcc --version")
    
    torch_cuda = {}
    try:
        import torch
        torch_cuda = {
            "torch_version": torch.__version__,
            "cuda_available": torch.cuda.is_available(),
            "device_count": torch.cuda.device_count() if torch.cuda.is_available() else 0,
            "device_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
            "vram_total_gb": round(torch.cuda.get_device_properties(0).total_memory / 1e9, 2) if torch.cuda.is_available() else None
        }
    except Exception as e:
        torch_cuda["error"] = str(e)
        
    probe["gpu_and_cuda"] = {
        "nvidia_smi_query": nvidia_smi,
        "cuda_toolkit_nvcc": nvcc_ver.splitlines(),
        "python_torch_runtime": torch_cuda
    }

    # 4. Python Environment
    probe["python_environment"] = {
        "python_version": sys.version,
        "python_executable": sys.executable,
        "prefix": sys.prefix
    }

    # 5. ROS2 & Container Probe
    code_ros, which_ros, _ = run_cmd("which ros2")
    opt_ros_exists = os.path.exists("/opt/ros")
    _, dpkg_ros, _ = run_cmd("dpkg -l | grep -E '(ros-humble|ros-iron|ros-rolling|ros2)'")
    _, docker_ver, _ = run_cmd("docker --version")
    _, docker_ps, _ = run_cmd("docker ps -a")
    
    probe["ros2_and_containers"] = {
        "shell_path_ros2": which_ros if code_ros == 0 else "ros2 not found in PATH",
        "opt_ros_directory_exists": opt_ros_exists,
        "dpkg_ros_packages_installed": bool(dpkg_ros),
        "docker_installed": bool(docker_ver),
        "docker_version": docker_ver,
        "docker_ps_output": docker_ps.splitlines() if docker_ps else []
    }

    # 6. Git provenance
    _, git_hash, _ = run_cmd("git rev-parse HEAD")
    _, git_branch, _ = run_cmd("git rev-parse --abbrev-ref HEAD")
    _, git_status, _ = run_cmd("git status --porcelain")
    probe["git"] = {
        "commit": git_hash,
        "branch": git_branch,
        "dirty_files": git_status.splitlines() if git_status else []
    }

    out_file = "reports/evidence/r0/environment_probe.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(probe, f, indent=2, ensure_ascii=False)
        
    print(f"Environment probe saved to {out_file}")

if __name__ == "__main__":
    main()
