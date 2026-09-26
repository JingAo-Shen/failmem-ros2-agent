#!/usr/bin/env bash
# P0 Environment & Container Verification Script

echo "=== System & Kernel ==="
uname -a
lsb_release -d 2>/dev/null || cat /etc/os-release | grep PRETTY_NAME

echo "=== GPU & Driver ==="
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader

echo "=== CUDA Runtime Check ==="
which nvcc 2>&1 || echo "nvcc not in PATH"
nvcc --version 2>&1 | grep "release" || true

echo "=== ROS2 System Status ==="
if command -v ros2 &> /dev/null; then
    echo "ros2 command found: $(which ros2)"
else
    echo "ros2 not found in current shell PATH"
fi
if [ -d "/opt/ros" ]; then
    echo "/opt/ros exists: $(ls /opt/ros)"
else
    echo "/opt/ros does not exist"
fi

echo "=== Container Infrastructure ==="
if command -v docker &> /dev/null; then
    docker --version
    echo "Docker service status:"
    docker info 2>&1 | grep -E "(Server Version|Runtimes|Operating System)" || true
else
    echo "Docker not installed"
fi

echo "=== Local LLM Model Check ==="
MODEL_PATH="/root/.cache/modelscope/models/Qwen--Qwen2.5-Coder-7B-Instruct/snapshots/master"
if [ -d "$MODEL_PATH" ]; then
    echo "Qwen2.5-Coder-7B-Instruct found at: $MODEL_PATH ($(du -sh $MODEL_PATH | cut -f1))"
else
    echo "Model path not found"
fi
