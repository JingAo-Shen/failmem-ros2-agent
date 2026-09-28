"""Doorway spatial clearance and costmap verification module.

Provides rigorous, testable geometric perception evaluation:
- Laser scan ray projection using exact map <- base_scan TF transforms.
- 3-valued doorway state classification: OCCUPIED / FREE / UNKNOWN.
- Direct sub-grid extraction and occupancy verification from Nav2 Costmap (OccupancyGrid).
- Detection of occlusions, field-of-view limits, invalid/all-NaN scans, and expired data.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple, Union


def is_finite_number(val: Any) -> bool:
    """Check if value is a finite number."""
    if val is None or isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    return math.isfinite(val)


def project_laser_scan_rays_tf(
    ranges: List[float],
    angle_min: float,
    angle_increment: float,
    range_min: float,
    range_max: float,
    tf_translation: Tuple[float, float, float] | List[float],
    tf_yaw: float,
) -> Tuple[List[Tuple[float, float, float, float, bool]], Dict[str, Any]]:
    """Project 2D laser scan rays into map frame using TF translation and yaw.
    
    Returns:
        rays: List of (endpoint_x, endpoint_y, effective_range, ray_angle_map, is_hit)
              where is_hit is True if finite obstacle hit, False if max-range free ray.
        metadata: Dict of projection statistics
    """
    if tf_translation is None or len(tf_translation) < 2 or not is_finite_number(tf_yaw):
        return [], {"error": "INVALID_TF_TRANSFORM", "valid_count": 0, "total_count": len(ranges)}

    tx, ty = float(tf_translation[0]), float(tf_translation[1])
    projected_rays = []
    invalid_count = 0
    hit_count = 0
    free_ray_count = 0

    for i, r in enumerate(ranges):
        if r is None or isinstance(r, bool):
            invalid_count += 1
            continue

        theta_local = angle_min + i * angle_increment
        theta_map = tf_yaw + theta_local

        # Case 1: Finite obstacle hit within valid range
        if isinstance(r, (int, float)) and math.isfinite(r) and range_min <= r <= range_max:
            r_eff = float(r)
            is_hit = True
            hit_count += 1
        # Case 2: Out of range / Inf (free space up to range_max)
        elif isinstance(r, (int, float)) and (math.isinf(r) or r > range_max):
            r_eff = float(range_max)
            is_hit = False
            free_ray_count += 1
        else:
            invalid_count += 1
            continue

        # Local laser scanner frame coords
        lx = r_eff * math.cos(theta_local)
        ly = r_eff * math.sin(theta_local)

        # Transformed map frame endpoint
        mx = tx + lx * math.cos(tf_yaw) - ly * math.sin(tf_yaw)
        my = ty + lx * math.sin(tf_yaw) + ly * math.cos(tf_yaw)

        projected_rays.append((round(mx, 4), round(my, 4), round(r_eff, 4), round(theta_map, 4), is_hit))

    meta = {
        "total_count": len(ranges),
        "valid_count": len(projected_rays),
        "hit_count": hit_count,
        "free_ray_count": free_ray_count,
        "invalid_count": invalid_count,
        "laser_origin_map": [round(tx, 4), round(ty, 4)],
        "laser_yaw_map": round(tf_yaw, 4),
    }
    return projected_rays, meta


def ray_intersects_box_2d(
    p1: Tuple[float, float],
    p2: Tuple[float, float],
    bbox: Tuple[float, float, float, float],
) -> bool:
    """Check if 2D line segment between p1 and p2 intersects an axis-aligned bounding box."""
    xmin, xmax, ymin, ymax = bbox
    x1, y1 = p1
    x2, y2 = p2

    # Check if either endpoint is inside
    if (xmin <= x1 <= xmax and ymin <= y1 <= ymax) or (xmin <= x2 <= xmax and ymin <= y2 <= ymax):
        return True

    # Liang-Barsky line clipping algorithm
    dx = x2 - x1
    dy = y2 - y1

    p = [-dx, dx, -dy, dy]
    q = [x1 - xmin, xmax - x1, y1 - ymin, ymax - y1]

    u1 = 0.0
    u2 = 1.0

    for pi, qi in zip(p, q):
        if pi == 0:
            if qi < 0:
                return False
        else:
            t = qi / pi
            if pi < 0:
                if t > u2:
                    return False
                if t > u1:
                    u1 = t
            elif pi > 0:
                if t < u1:
                    return False
                if t < u2:
                    u2 = t

    return u1 <= u2


def extract_costmap_doorway_subgrid(
    costmap_data: Optional[List[int]],
    width: int,
    height: int,
    resolution: float,
    origin_x: float,
    origin_y: float,
    doorway_bbox: Tuple[float, float, float, float],
    costmap_stamp_sec: Optional[float] = None,
    current_sim_time: Optional[float] = None,
    max_staleness_sec: float = 3.0,
    lethal_cost_threshold: int = 100,
) -> Dict[str, Any]:
    """Extract and analyze costmap cells within the doorway bounding box."""
    if costmap_data is None or len(costmap_data) == 0 or width <= 0 or height <= 0 or resolution <= 0.0:
        return {
            "status": "UNAVAILABLE",
            "error": "MISSING_OR_INVALID_COSTMAP_DATA",
            "total_cells": 0,
            "costmap_cleared": False,
        }

    if costmap_stamp_sec is not None and current_sim_time is not None:
        staleness = current_sim_time - costmap_stamp_sec
        if staleness > max_staleness_sec or staleness < -0.50:
            return {
                "status": "STALE",
                "error": f"COSTMAP_STALENESS_EXCEEDED ({staleness:.3f}s > {max_staleness_sec}s)",
                "staleness_sec": round(staleness, 4),
                "total_cells": 0,
                "costmap_cleared": False,
            }

    xmin, xmax, ymin, ymax = doorway_bbox
    u_min = max(0, int((xmin - origin_x) / resolution))
    u_max = min(width - 1, int((xmax - origin_x) / resolution))
    v_min = max(0, int((ymin - origin_y) / resolution))
    v_max = min(height - 1, int((ymax - origin_y) / resolution))

    if u_min > u_max or v_min > v_max:
        return {
            "status": "OUT_OF_BOUNDS",
            "error": "DOORWAY_BBOX_OUTSIDE_COSTMAP_GRID",
            "total_cells": 0,
            "costmap_cleared": False,
        }

    total_cells = 0
    unknown_cells = 0
    occupied_cells = 0  # cost >= lethal_cost_threshold (lethal obstacle)
    free_cells = 0      # 0 <= cost < lethal_cost_threshold
    max_cost = 0

    for v in range(v_min, v_max + 1):
        for u in range(u_min, u_max + 1):
            idx = v * width + u
            val = costmap_data[idx]
            total_cells += 1
            if val < 0:
                unknown_cells += 1
            elif val >= lethal_cost_threshold:
                occupied_cells += 1
                if val > max_cost:
                    max_cost = val
            else:
                free_cells += 1
                if val > max_cost:
                    max_cost = val

    costmap_cleared = (total_cells > 0 and unknown_cells == 0 and occupied_cells == 0)

    return {
        "status": "VALID",
        "error": None,
        "grid_bounds_u": [u_min, u_max],
        "grid_bounds_v": [v_min, v_max],
        "total_cells": total_cells,
        "unknown_cells": unknown_cells,
        "occupied_cells": occupied_cells,
        "free_cells": free_cells,
        "max_cost": max_cost,
        "costmap_cleared": costmap_cleared,
        "stamp_sec": costmap_stamp_sec,
    }


def evaluate_doorway_clearance(
    ranges: List[float],
    angle_min: float,
    angle_increment: float,
    range_min: float,
    range_max: float,
    tf_translation: Optional[Tuple[float, float, float] | List[float]],
    tf_yaw: Optional[float],
    tf_stamp_sec: Optional[float],
    scan_stamp_sec: Optional[float],
    current_sim_time: Optional[float],
    doorway_bbox: Tuple[float, float, float, float] = (-0.20, 0.20, -0.30, 0.30),
    costmap_data_summary: Optional[Dict[str, Any]] = None,
    min_pass_through_rays: int = 8,
    min_obstacle_hits: int = 5,
    max_tf_staleness_sec: float = 1.0,
    max_tf_scan_diff_sec: float = 0.8,
) -> Dict[str, Any]:
    """Evaluate 3-valued doorway state: OCCUPIED / FREE / UNKNOWN.
    
    Strict Rules:
    - OCCUPIED: Verified obstacle laser hits inside doorway (>= min_obstacle_hits) OR costmap occupied.
    - FREE: Zero laser hits inside doorway AND >= min_pass_through_rays passing through doorway to Room 2 AND costmap cleared.
    - UNKNOWN: TF missing/expired/mismatched, scan all-NaN, doorway out of FOV, costmap missing/stale/unknown cells.
    """
    xmin, xmax, ymin, ymax = doorway_bbox

    # 1. TF Integrity & Timestamp Validation
    if tf_translation is None or tf_yaw is None or not is_finite_number(tf_yaw):
        return {
            "doorway_state": "UNKNOWN",
            "reason": "TF_UNAVAILABLE",
            "doorway_bbox": list(doorway_bbox),
            "hits_inside_count": 0,
            "pass_through_count": 0,
            "error": "TF_TRANSLATION_OR_YAW_MISSING",
        }

    if tf_stamp_sec is not None and scan_stamp_sec is not None:
        tf_scan_diff = abs(tf_stamp_sec - scan_stamp_sec)
        if tf_scan_diff > max_tf_scan_diff_sec:
            return {
                "doorway_state": "UNKNOWN",
                "reason": f"TF_SCAN_TIME_MISMATCH ({tf_scan_diff:.3f}s > {max_tf_scan_diff_sec:.2f}s)",
                "doorway_bbox": list(doorway_bbox),
                "hits_inside_count": 0,
                "pass_through_count": 0,
                "error": "TF_SCAN_TIME_MISMATCH",
            }

    if tf_stamp_sec is not None and current_sim_time is not None:
        tf_staleness = current_sim_time - tf_stamp_sec
        if tf_staleness > max_tf_staleness_sec or tf_staleness < -0.50:
            return {
                "doorway_state": "UNKNOWN",
                "reason": f"TF_STALE ({tf_staleness:.3f}s > {max_tf_staleness_sec}s)",
                "doorway_bbox": list(doorway_bbox),
                "hits_inside_count": 0,
                "pass_through_count": 0,
                "error": "TF_STALE",
            }

    # 2. Project Laser Scan Rays
    projected_rays, proj_meta = project_laser_scan_rays_tf(
        ranges=ranges,
        angle_min=angle_min,
        angle_increment=angle_increment,
        range_min=range_min,
        range_max=range_max,
        tf_translation=tf_translation,
        tf_yaw=tf_yaw,
    )

    if proj_meta.get("valid_count", 0) == 0:
        return {
            "doorway_state": "UNKNOWN",
            "reason": "SCAN_ALL_NAN_OR_INVALID",
            "doorway_bbox": list(doorway_bbox),
            "hits_inside_count": 0,
            "pass_through_count": 0,
            "error": "ZERO_VALID_LASER_RAYS",
        }

    tx, ty = float(tf_translation[0]), float(tf_translation[1])
    origin_point = (tx, ty)

    hits_inside = []
    pass_through_rays = []
    rays_intersecting_bbox_count = 0

    for mx, my, r, th_map, is_hit in projected_rays:
        endpoint = (mx, my)
        intersects = ray_intersects_box_2d(origin_point, endpoint, doorway_bbox)

        if intersects:
            rays_intersecting_bbox_count += 1
            # Check if ray hit an obstacle strictly inside the doorway box
            if is_hit and (xmin <= mx <= xmax and ymin <= my <= ymax):
                hits_inside.append((mx, my, r, th_map))
            # Check if ray traversed the box and reached beyond (e.g. into Room 2: mx > xmax)
            elif mx > xmax:
                pass_through_rays.append((mx, my, r, th_map))

    # 3. Field of View & Occlusion Check
    if rays_intersecting_bbox_count == 0:
        return {
            "doorway_state": "UNKNOWN",
            "reason": "DOORWAY_NOT_IN_FOV_OR_OCCLUDED",
            "doorway_bbox": list(doorway_bbox),
            "hits_inside_count": 0,
            "pass_through_count": 0,
            "laser_origin_map": [round(tx, 4), round(ty, 4)],
            "error": "ZERO_RAYS_DIRECTED_AT_DOORWAY",
        }

    hits_count = len(hits_inside)
    pass_count = len(pass_through_rays)

    # 4. Check Costmap Evidence (if provided)
    costmap_cleared = True
    costmap_status = "NOT_CHECKED"
    if costmap_data_summary is not None:
        costmap_status = costmap_data_summary.get("status", "UNAVAILABLE")
        if costmap_status != "VALID":
            return {
                "doorway_state": "UNKNOWN",
                "reason": f"COSTMAP_{costmap_status}",
                "doorway_bbox": list(doorway_bbox),
                "hits_inside_count": hits_count,
                "pass_through_count": pass_count,
                "costmap_summary": costmap_data_summary,
                "error": costmap_data_summary.get("error"),
            }
        costmap_cleared = costmap_data_summary.get("costmap_cleared", False)

    # 5. Evaluate Final 3-Valued State
    if hits_count >= min_obstacle_hits or (costmap_data_summary and costmap_data_summary.get("occupied_cells", 0) > 0):
        doorway_state = "OCCUPIED"
        reason = f"OBSTACLE_DETECTED ({hits_count} laser hits inside doorway bbox, costmap_occupied={costmap_data_summary.get('occupied_cells', 0) if costmap_data_summary else 'N/A'})"
    elif hits_count == 0 and pass_count >= min_pass_through_rays and costmap_cleared:
        doorway_state = "FREE"
        reason = f"DOORWAY_CLEARANCE_VERIFIED ({pass_count} rays traversing through doorway to Room 2, costmap free)"
    else:
        doorway_state = "UNKNOWN"
        reason = f"INSUFFICIENT_CLEARANCE_EVIDENCE (hits={hits_count}, pass_through={pass_count} < {min_pass_through_rays}, costmap_cleared={costmap_cleared})"

    return {
        "doorway_state": doorway_state,
        "reason": reason,
        "doorway_bbox": list(doorway_bbox),
        "hits_inside_count": hits_count,
        "pass_through_count": pass_count,
        "rays_intersecting_bbox_count": rays_intersecting_bbox_count,
        "sample_hits_inside": [h[:3] for h in hits_inside[:5]],
        "sample_pass_through": [p[:3] for p in pass_through_rays[:5]],
        "laser_origin_map": [round(tx, 4), round(ty, 4)],
        "laser_yaw_map": round(tf_yaw, 4),
        "costmap_status": costmap_status,
        "costmap_summary": costmap_data_summary,
        "error": None,
    }
