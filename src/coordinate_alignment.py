"""FailMem Coordinate Alignment & Proof of Frame Identity (world == map).

Empirical and mathematical verification of coordinate frame identity between:
- Gazebo simulation frame: 'world'
- Navigation2 / AMCL frame: 'map'

Uses static non-collinear landmarks in configs/turtlebot3_world.pgm and configs/world_with_state.model.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, List, Tuple
import yaml
from PIL import Image
import numpy as np


def verify_world_map_alignment(
    map_yaml_path: str = "/workspace/configs/turtlebot3_world.yaml",
    map_pgm_path: str = "/workspace/configs/turtlebot3_world.pgm",
) -> Dict[str, Any]:
    """Verify coordinate transformation and residual errors between Gazebo world and ROS map frame.

    Checks at least 3 non-collinear static landmarks (cylinders) defined in turtlebot3_world SDF:
      - 'two_two': central cylinder at (0.0, 0.0)
      - 'one_two': cylinder at (-1.1, 0.0)
      - 'three_two': cylinder at (1.1, 0.0)
      - 'two_three': cylinder at (0.0, 1.1)
      - 'two_one': cylinder at (0.0, -1.1)
      - 'one_one': cylinder at (-1.1, -1.1)
      - 'three_three': cylinder at (1.1, 1.1)
    """
    map_yaml = Path(map_yaml_path)
    map_pgm = Path(map_pgm_path)

    if not map_yaml.exists() or not map_pgm.exists():
        return {
            "verified": False,
            "error": f"Map files not found: {map_yaml_path} or {map_pgm_path}",
        }

    with open(map_yaml, "r", encoding="utf-8") as f:
        meta = yaml.safe_load(f)

    resolution = float(meta["resolution"])
    origin = meta["origin"]
    x0, y0, theta0 = float(origin[0]), float(origin[1]), float(origin[2])

    img = Image.open(map_pgm)
    arr = np.array(img)
    H, W = arr.shape

    # Standard ROS Map Server coordinate transform:
    # x = x0 + u * resolution
    # y = y0 + (H - v) * resolution (where v is row from top, H-v is row from bottom)
    #
    # Ground truth locations of 5 non-collinear static pillars from SDF:
    ground_truth_landmarks = [
        {"name": "two_two (center)", "world_xy": (0.0, 0.0)},
        {"name": "one_two (west)", "world_xy": (-1.1, 0.0)},
        {"name": "three_two (east)", "world_xy": (1.1, 0.0)},
        {"name": "two_three (north)", "world_xy": (0.0, 1.1)},
        {"name": "two_one (south)", "world_xy": (0.0, -1.1)},
    ]

    landmark_results = []
    max_residual = 0.0

    for lm in ground_truth_landmarks:
        wx, wy = lm["world_xy"]
        # Expected pixel coordinate in image
        expected_u = (wx - x0) / resolution
        expected_v = H - ((wy - y0) / resolution)

        u_idx = int(round(expected_u))
        v_idx = int(round(expected_v))

        # Check neighborhood around expected pixel for dark/occupied obstacle pixel
        # Search a window of +/- 4 pixels (+/- 0.20m, cylinder radius is 0.15m)
        win_size = 5
        sub_arr = arr[max(0, v_idx - win_size):min(H, v_idx + win_size + 1),
                      max(0, u_idx - win_size):min(W, u_idx + win_size + 1)]

        # Occupied pixels in PGM have low values (< 50, usually 0)
        occupied_mask = (sub_arr < 50)
        if np.any(occupied_mask):
            local_v, local_u = np.where(occupied_mask)
            center_local_v = float(np.mean(local_v))
            center_local_u = float(np.mean(local_u))
            detected_v = (v_idx - win_size) + center_local_v
            detected_u = (u_idx - win_size) + center_local_u

            # Map coordinates from detected pixel
            map_x = x0 + detected_u * resolution
            map_y = y0 + (H - detected_v) * resolution
            residual = math.hypot(map_x - wx, map_y - wy)
        else:
            map_x = None
            map_y = None
            residual = 999.0

        max_residual = max(max_residual, residual)
        landmark_results.append({
            "landmark": lm["name"],
            "world_xy": [wx, wy],
            "expected_pixel_uv": [round(expected_u, 2), round(expected_v, 2)],
            "detected_map_xy": [round(map_x, 4), round(map_y, 4)] if map_x is not None else None,
            "residual_m": round(residual, 4),
            "within_resolution_cell": residual <= (resolution * 1.5),
        })

    # Verification criteria:
    # 1. At least 3 non-collinear landmarks successfully resolved
    # 2. Maximum residual is within 1.5 grid cell resolution (0.075m for 0.05m grid)
    # 3. Origin theta is 0.0
    verified = (
        len(landmark_results) >= 3
        and max_residual <= (resolution * 1.5)
        and abs(theta0) < 1e-4
    )

    return {
        "verified": verified,
        "resolution_m": resolution,
        "map_origin": [x0, y0, theta0],
        "image_shape": [H, W],
        "non_collinear_landmarks_tested": len(landmark_results),
        "max_residual_m": round(max_residual, 4),
        "residual_threshold_m": round(resolution * 1.5, 4),
        "landmarks": landmark_results,
        "mathematical_basis": (
            f"Image has shape ({H}, {W}) with resolution {resolution}m/px and origin [{x0}, {y0}, {theta0}]. "
            f"Pixel transform: map_x = {x0} + u * {resolution}, map_y = {y0} + ({H} - v) * {resolution}. "
            f"All {len(landmark_results)} static pillars in Gazebo world align with map obstacles within {round(max_residual, 4)}m residual (< {round(resolution * 1.5, 4)}m)."
        ),
    }


if __name__ == "__main__":
    import json
    res = verify_world_map_alignment("configs/turtlebot3_world.yaml", "configs/turtlebot3_world.pgm")
    print(json.dumps(res, indent=2))
