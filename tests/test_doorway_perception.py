"""Unit tests for doorway spatial perception and costmap verification."""
import math
import pytest
from src.doorway_evaluator import (
    evaluate_doorway_clearance,
    extract_costmap_doorway_subgrid,
    project_laser_scan_rays_tf,
    ray_intersects_box_2d,
)


def test_ray_intersects_box_2d():
    bbox = (-0.20, 0.20, -0.30, 0.30)
    # Origin (-1.0, 0.0) -> Target (1.0, 0.0): traverses through box
    assert ray_intersects_box_2d((-1.0, 0.0), (1.0, 0.0), bbox) is True
    # Origin (-1.0, 1.0) -> Target (1.0, 1.0): misses box
    assert ray_intersects_box_2d((-1.0, 1.0), (1.0, 1.0), bbox) is False
    # Endpoint inside box
    assert ray_intersects_box_2d((-1.0, 0.0), (0.0, 0.0), bbox) is True
    # Start inside box
    assert ray_intersects_box_2d((0.0, 0.0), (2.0, 0.0), bbox) is True


def test_project_laser_scan_rays_tf_with_offset():
    # Robot at (-1.0, 0.0), lidar at (-1.064, 0.0) with yaw 0
    # Range 1.064 straight ahead (0 rad) -> endpoint should be (0.0, 0.0)
    ranges = [1.064]
    rays, meta = project_laser_scan_rays_tf(
        ranges=ranges,
        angle_min=0.0,
        angle_increment=0.0,
        range_min=0.1,
        range_max=10.0,
        tf_translation=[-1.064, 0.0, 0.1],
        tf_yaw=0.0,
    )
    assert meta["valid_count"] == 1
    assert len(rays) == 1
    mx, my, r, th, is_hit = rays[0]
    assert is_hit is True
    assert pytest.approx(mx, abs=1e-3) == 0.0
    assert pytest.approx(my, abs=1e-3) == 0.0
    assert pytest.approx(r, abs=1e-3) == 1.064


def test_extract_costmap_doorway_subgrid_free():
    # 100x100 grid, res 0.05m, origin at (-2.5, -2.5)
    width = 100
    height = 100
    resolution = 0.05
    origin_x = -2.5
    origin_y = -2.5
    bbox = (-0.20, 0.20, -0.30, 0.30)
    # All 0 (free)
    costmap_data = [0] * (width * height)

    res = extract_costmap_doorway_subgrid(
        costmap_data=costmap_data,
        width=width,
        height=height,
        resolution=resolution,
        origin_x=origin_x,
        origin_y=origin_y,
        doorway_bbox=bbox,
        costmap_stamp_sec=10.0,
        current_sim_time=10.2,
    )
    assert res["status"] == "VALID"
    assert res["total_cells"] > 0
    assert res["unknown_cells"] == 0
    assert res["occupied_cells"] == 0
    assert res["costmap_cleared"] is True


def test_extract_costmap_doorway_subgrid_occupied():
    width = 100
    height = 100
    resolution = 0.05
    origin_x = -2.5
    origin_y = -2.5
    bbox = (-0.20, 0.20, -0.30, 0.30)
    costmap_data = [0] * (width * height)
    # Place lethal cost (100) at (0, 0)
    u0 = int((0.0 - origin_x) / resolution)
    v0 = int((0.0 - origin_y) / resolution)
    costmap_data[v0 * width + u0] = 100

    res = extract_costmap_doorway_subgrid(
        costmap_data=costmap_data,
        width=width,
        height=height,
        resolution=resolution,
        origin_x=origin_x,
        origin_y=origin_y,
        doorway_bbox=bbox,
    )
    assert res["status"] == "VALID"
    assert res["occupied_cells"] >= 1
    assert res["costmap_cleared"] is False


def test_extract_costmap_doorway_subgrid_unknown_or_stale():
    width = 100
    height = 100
    resolution = 0.05
    bbox = (-0.20, 0.20, -0.30, 0.30)
    # Unknown cells (-1)
    costmap_data = [-1] * (width * height)
    res = extract_costmap_doorway_subgrid(
        costmap_data=costmap_data,
        width=width,
        height=height,
        resolution=resolution,
        origin_x=-2.5,
        origin_y=-2.5,
        doorway_bbox=bbox,
    )
    assert res["status"] == "VALID"
    assert res["unknown_cells"] > 0
    assert res["costmap_cleared"] is False

    # Stale costmap
    res_stale = extract_costmap_doorway_subgrid(
        costmap_data=[0] * 10000,
        width=100,
        height=100,
        resolution=0.05,
        origin_x=-2.5,
        origin_y=-2.5,
        doorway_bbox=bbox,
        costmap_stamp_sec=10.0,
        current_sim_time=14.0,  # 4.0s staleness > 3.0s limit
    )
    assert res_stale["status"] == "STALE"


def test_evaluate_doorway_all_nan_scan():
    # 360 rays of NaN
    ranges = [float('nan')] * 360
    res = evaluate_doorway_clearance(
        ranges=ranges,
        angle_min=-math.pi,
        angle_increment=2 * math.pi / 360,
        range_min=0.1,
        range_max=10.0,
        tf_translation=[-1.0, 0.0, 0.1],
        tf_yaw=0.0,
        tf_stamp_sec=10.0,
        scan_stamp_sec=10.0,
        current_sim_time=10.0,
    )
    assert res["doorway_state"] == "UNKNOWN"
    assert "ZERO_VALID_LASER_RAYS" in res["error"] or "NAN" in res["reason"]


def test_evaluate_doorway_tf_missing_or_stale():
    ranges = [2.0] * 360
    # Missing TF
    res1 = evaluate_doorway_clearance(
        ranges=ranges,
        angle_min=-math.pi,
        angle_increment=2 * math.pi / 360,
        range_min=0.1,
        range_max=10.0,
        tf_translation=None,
        tf_yaw=None,
        tf_stamp_sec=None,
        scan_stamp_sec=10.0,
        current_sim_time=10.0,
    )
    assert res1["doorway_state"] == "UNKNOWN"
    assert "TF_UNAVAILABLE" in res1["reason"]

    # TF - Scan time mismatch
    res2 = evaluate_doorway_clearance(
        ranges=ranges,
        angle_min=-math.pi,
        angle_increment=2 * math.pi / 360,
        range_min=0.1,
        range_max=10.0,
        tf_translation=[-1.0, 0.0, 0.1],
        tf_yaw=0.0,
        tf_stamp_sec=10.0,
        scan_stamp_sec=11.0,  # 1.0s mismatch > 0.8s limit
        current_sim_time=11.0,
    )
    assert res2["doorway_state"] == "UNKNOWN"
    assert "MISMATCH" in res2["reason"]

    # TF Staleness
    res3 = evaluate_doorway_clearance(
        ranges=ranges,
        angle_min=-math.pi,
        angle_increment=2 * math.pi / 360,
        range_min=0.1,
        range_max=10.0,
        tf_translation=[-1.0, 0.0, 0.1],
        tf_yaw=0.0,
        tf_stamp_sec=10.0,
        scan_stamp_sec=10.0,
        current_sim_time=11.5,  # 1.5s staleness > 1.0s limit
    )
    assert res3["doorway_state"] == "UNKNOWN"
    assert "TF_STALE" in res3["reason"]


def test_evaluate_doorway_out_of_fov():
    # Robot facing backwards away from doorway at (-1.0, 0.0), yaw = pi
    # FOV is [-0.1, 0.1] relative to heading -> rays point towards x = -3.0
    ranges = [2.0] * 20
    res = evaluate_doorway_clearance(
        ranges=ranges,
        angle_min=-0.1,
        angle_increment=0.01,
        range_min=0.1,
        range_max=10.0,
        tf_translation=[-1.0, 0.0, 0.1],
        tf_yaw=math.pi,  # Facing away
        tf_stamp_sec=10.0,
        scan_stamp_sec=10.0,
        current_sim_time=10.0,
    )
    assert res["doorway_state"] == "UNKNOWN"
    assert "FOV" in res["reason"] or "ZERO_RAYS" in res["error"]


def test_evaluate_doorway_occupied():
    # Robot at (-1.0, 0.0), facing doorway (yaw 0).
    # Rays hit obstacle at (0.0, 0.0) -> distance 1.0m
    # 20 rays with range 1.0m
    ranges = [1.0] * 20
    costmap_summary = {
        "status": "VALID",
        "total_cells": 64,
        "unknown_cells": 0,
        "occupied_cells": 10,
        "costmap_cleared": False,
    }
    res = evaluate_doorway_clearance(
        ranges=ranges,
        angle_min=-0.1,
        angle_increment=0.01,
        range_min=0.1,
        range_max=10.0,
        tf_translation=[-1.0, 0.0, 0.1],
        tf_yaw=0.0,
        tf_stamp_sec=10.0,
        scan_stamp_sec=10.0,
        current_sim_time=10.0,
        costmap_data_summary=costmap_summary,
    )
    assert res["doorway_state"] == "OCCUPIED"
    assert res["hits_inside_count"] >= 5


def test_evaluate_doorway_free():
    # Robot at (-1.0, 0.0), facing doorway (yaw 0).
    # Clear path: rays reach Room 2 far wall at x = 2.0m -> distance 3.0m
    ranges = [3.0] * 20
    costmap_summary = {
        "status": "VALID",
        "total_cells": 64,
        "unknown_cells": 0,
        "occupied_cells": 0,
        "costmap_cleared": True,
    }
    res = evaluate_doorway_clearance(
        ranges=ranges,
        angle_min=-0.1,
        angle_increment=0.01,
        range_min=0.1,
        range_max=10.0,
        tf_translation=[-1.0, 0.0, 0.1],
        tf_yaw=0.0,
        tf_stamp_sec=10.0,
        scan_stamp_sec=10.0,
        current_sim_time=10.0,
        costmap_data_summary=costmap_summary,
    )
    assert res["doorway_state"] == "FREE"
    assert res["hits_inside_count"] == 0
    assert res["pass_through_count"] >= 8
