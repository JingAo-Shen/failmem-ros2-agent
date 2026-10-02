#!/usr/bin/env python3
"""Plot representative robot trajectories on the dual-path simulation environment map.

Generates:
- paper/figures/trajectories_map.png
- paper/figures/trajectories_map.pdf
"""

import json
from pathlib import Path
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BASE_EVIDENCE_DIR = REPO_ROOT / "reports" / "evidence" / "p2c_pilot" / "p2c_pilot_20261001_022711_0d3c35"
OUTPUT_DIR = REPO_ROOT / "paper" / "figures"


def load_trajectory(ep_name: str):
    traj_file = BASE_EVIDENCE_DIR / ep_name / "trajectory.json"
    if not traj_file.exists():
        raise FileNotFoundError(f"Missing {traj_file}")
    with open(traj_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    samples = data.get("odom_trajectory", [])
    xs = [s["x"] for s in samples]
    ys = [s["y"] for s in samples]
    return xs, ys


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Set publication style
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.size": 10,
        "axes.labelsize": 11,
        "axes.titlesize": 12,
        "legend.fontsize": 9,
        "xtick.labelsize": 9,
        "ytick.labelsize": 9,
        "figure.dpi": 300,
    })

    fig, axes = plt.subplots(2, 2, figsize=(11, 7.5), sharex=True, sharey=True)

    episodes = [
        ("D1_F_ep1", "Scenario D1: FailMem ($F$)", "#d97706", axes[0, 0], "Avoids dead end;\ndirects via South Path B ($13.84\\,\\text{m}$)"),
        ("D1_R_ep1", "Scenario D1: Reactive ($R$)", "#dc2626", axes[0, 1], "Uninformed retry to gate;\nretreats, takes Path B ($17.50\\,\\text{m}$)"),
        ("D2_F_ep1", "Scenario D2: FailMem ($F$)", "#16a34a", axes[1, 0], "Dynamic invalidation on FREE;\ndirects via North Path A ($16.23\\,\\text{m}$)"),
        ("D2_M1_ep1", "Scenario D2: Persistent ($M1$)", "#9333ea", axes[1, 1], "Permanent suppression;\ndetour via South Path B ($18.34\\,\\text{m}$)"),
    ]

    for ep_id, title, color, ax, subtitle in episodes:
        # 1. Environment Walls & Geometry
        # Outer boundary
        ax.plot([-3.5, 3.5], [2.2, 2.2], 'k-', lw=2.5)   # North outer
        ax.plot([-3.5, 3.5], [-3.2, -3.2], 'k-', lw=2.5) # South outer
        ax.plot([-3.5, -3.5], [-3.2, 2.2], 'k-', lw=2.5) # West outer
        ax.plot([3.5, 3.5], [-3.2, 2.2], 'k-', lw=2.5)   # East outer

        # Interior dividing wall between North and South corridors (with central block / chokepoint)
        ax.plot([-3.5, -0.2], [0.6, 0.6], 'k-', lw=2.0)  # North corridor bottom wall west
        ax.plot([0.2, 3.5], [0.6, 0.6], 'k-', lw=2.0)   # North corridor bottom wall east

        ax.plot([-3.5, 3.5], [-0.8, -0.8], 'k-', lw=2.0) # South corridor top wall

        # North chokepoint doorway walls (doorway at x=0.0, y=1.2, width 0.8)
        ax.plot([0.0, 0.0], [1.6, 2.2], 'k-', lw=2.5)   # Door top wall
        ax.plot([0.0, 0.0], [0.6, 0.8], 'k-', lw=2.5)   # Door bottom wall

        # Blockage box in D1
        if "D1" in ep_id:
            rect_block = patches.Rectangle((-0.15, 0.95), 0.30, 0.50, linewidth=1.5, edgecolor='#b91c1c', facecolor='#fca5a5', alpha=0.9, zorder=5)
            ax.add_patch(rect_block)
            ax.text(0.0, 1.20, "Obstacle", color='#7f1d1d', fontsize=7.5, weight='bold', ha='center', va='center', zorder=6)
        else:
            # Doorway open
            rect_open = patches.Rectangle((-0.20, 0.85), 0.40, 0.70, linewidth=1, edgecolor='#16a34a', facecolor='#dcfce7', linestyle='--', alpha=0.5, zorder=4)
            ax.add_patch(rect_open)
            ax.text(0.0, 1.20, "Doorway\n(Clear)", color='#15803d', fontsize=7, ha='center', va='center', zorder=5)

        # 2. Key POIs
        # J0 Decision Junction
        ax.plot(-2.50, 0.00, marker='s', markersize=7, color='#2563eb', zorder=7)
        ax.text(-2.50, -0.35, r"$J_0\ [-2.5, 0.0]$", color='#1d4ed8', fontsize=8, weight='bold', ha='center', zorder=8)

        # Goal
        ax.plot(2.50, 0.00, marker='*', markersize=10, color='#b91c1c', zorder=7)
        ax.text(2.50, -0.35, r"$\mathrm{Goal}\ [2.5, 0.0]$", color='#991b1b', fontsize=8, weight='bold', ha='center', zorder=8)

        # Vantage Observation point
        ax.plot(-1.50, 1.20, marker='^', markersize=6, color='#6b21a8', zorder=7)
        ax.text(-1.50, 1.45, r"$\mathrm{Vantage}\ [-1.5, 1.2]$", color='#6b21a8', fontsize=7.5, ha='center', zorder=8)

        # 3. Trajectory Plot
        xs, ys = load_trajectory(ep_id)
        ax.plot(xs, ys, color=color, lw=2.0, alpha=0.85, label=f"Odometry Trajectory ({ep_id})", zorder=6)

        # Subtitle / Header
        ax.set_title(f"{title}\n{subtitle}", pad=8)
        ax.set_xlim([-3.8, 3.8])
        ax.set_ylim([-3.5, 2.5])
        ax.set_aspect('equal', adjustable='box')
        ax.grid(True, linestyle=':', alpha=0.5)

    # Set overall labels
    for ax in axes[1, :]:
        ax.set_xlabel("X (meters)")
    for ax in axes[:, 0]:
        ax.set_ylabel("Y (meters)")

    fig.suptitle("Representative Physical Trajectories Across Evaluated Conditions", fontsize=13, weight='bold', y=0.99)
    plt.tight_layout()

    png_path = OUTPUT_DIR / "trajectories_map.png"
    pdf_path = OUTPUT_DIR / "trajectories_map.pdf"
    plt.savefig(png_path, dpi=300, bbox_inches='tight')
    plt.savefig(pdf_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"Generated {png_path} and {pdf_path}")


if __name__ == "__main__":
    main()
