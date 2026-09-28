#!/bin/bash
set -e

# Source ROS2 environment
source /opt/ros/humble/setup.bash

# Ensure TB3 and domain settings
export TURTLEBOT3_MODEL=${TURTLEBOT3_MODEL:-waffle}
export GAZEBO_MODEL_DATABASE_URI=""
export GAZEBO_MODEL_PATH=/usr/share/gazebo-11/models:/opt/ros/humble/share/turtlebot3_gazebo/models:${GAZEBO_MODEL_PATH}
export ROS_DOMAIN_ID=42
export ROS_LOCALHOST_ONLY=1

if [ "$1" = "smoke" ]; then
    echo "Running P1a headless navigation smoke test..."
    exec python3 /workspace/scripts/run_p1a_nav.py
elif [ "$1" = "v2" ] || [ "$1" = "p1a_v2" ]; then
    echo "Running P1a-v2 isolated episodes runner..."
    exec python3 /workspace/scripts/run_p1a_v2.py
elif [ "$1" = "v3" ] || [ "$1" = "p1a_v3" ]; then
    echo "Running P1a-v3 isolated episodes runner with passive halt & scoring evaluator..."
    exec python3 /workspace/scripts/run_p1a_v3.py
else
    exec "$@"
fi
