# FailMem: Failure-Aware Memory for ROS2 Agents

> Research on episodic failure memory, execution verification, recovery, and reusable skill formation in long-horizon ROS2 agents.

## Research Goal

Can a ROS2 agent convert execution failures into reusable episodic memory and skills, reducing repeated failures and hallucinated success in future tasks?

## First Paper Target

**FailMem: Failure-Aware Episodic Memory for Long-Horizon ROS2 Agent Planning**

## Repository Status

This repository is currently in the **research incubation** stage. The immediate goal is to turn the idea into a reproducible research question, benchmark, baseline suite, and first paper submission.

## Planned Structure

- `docs/research-plan.md` — research questions, hypotheses, novelty, risks
- `docs/roadmap.md` — staged implementation plan
- `experiments/experiment-matrix.md` — baselines, ablations, metrics
- `papers/` — manuscript notes, figures, tables, drafts
- `src/` — implementation
- `data/` — dataset scripts/configs; do not commit large datasets

## Hardware Assumption

Primary local environment: NVIDIA RTX 2080 Ti, 22 GB VRAM. Larger models or large-scale runs may use rented cloud GPUs when necessary.

## Current Principle

Prefer research problems where **memory, verification, generalization, orchestration, or evaluation design** are the main contribution, rather than simply scaling model size.
