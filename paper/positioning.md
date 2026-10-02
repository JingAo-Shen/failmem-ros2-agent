# Paper Positioning & Scope Definition: FailMem

**Document Type**: Internal Research Strategy & Manuscript Positioning  
**Target Length**: Within 2 pages (~1,200 words)  
**Date**: 2026-10-02  
**Baseline Commit**: `e3cce9d`  

---

## 1. Executive Summary

This document formalizes the scientific positioning, contribution boundaries, and venue strategy for the FailMem manuscript. To ensure rigorous scientific honesty and prevent overclaiming during peer review, the manuscript's claims are explicitly separated into verified findings versus unsupported hypotheses. Engineering verification depth is recognized as methodological rigor, not as conceptual algorithmic novelty.

---

## 2. Firmly Supported Contributions

The empirical evidence from the 30-run exploratory benchmark ($n=3$ per condition) and 4-run feasibility check firmly supports the following contributions:

1. **Traceable Failure Memory Architecture for ROS 2 / Nav2**:
   - Implemented an event-driven lifecycle binding execution aborts to immutable observation bundles (raw LiDAR range arrays, TF transforms, costmap ROIs).
   - Designed sensor-driven dynamic invalidation that unsuppresses paths upon verified environmental clearance.
2. **Deterministically Re-Auditable Evaluation Pipeline**:
   - Built an independent cryptographic replay auditor (`replay_and_score_p2c.py`) that recomputes halt stability ($|v_{\text{lin}}| \le 0.05\,\text{m/s}, |v_{\text{ang}}| \le 0.08\,\text{rad/s}$) and sensory outcomes directly from raw logs against SHA256 manifests.
3. **Exploratory Dual-Path Comparative Benchmark ($n=3$)**:
   - *Dead-End Elimination*: In Scenario D1, FailMem ($F$) eliminates redundant corridor entry ($0.0$ vs. $1.0$ dead ends) relative to a reactive retry baseline ($R$), saving $-18.5\%$ distance ($14.03\,\text{m}$ vs. $17.22\,\text{m}$) and $-22.3\%$ duration ($109.5\,\text{s}$ vs. $141.0\,\text{s}$).
   - *Detour Avoidance*: In Scenario D2, dynamic invalidation saves $-11.0\%$ distance relative to permanent suppression ($M1$) ($16.25\,\text{m}$ vs. $18.25\,\text{m}$).
4. **Empirical Boundary Finding (Negative/Neutral Result)**:
   - In static 2D geometry, FailMem ($F$) and spatial costmap caching ($O$) chose identical topological routes, exhibiting $<1\%$ difference in reported total travel distance and execution time. The current exploratory evidence demonstrates **no additional routing benefit** of explicit episodic failure memory over standard spatial observation caching in static 2D layouts.

---

## 3. Firmly Unsupported / Bounded Claims

The following claims are **not supported** by the current evidence and must be strictly disclaimed:

1. **Algorithmic Superiority**: FailMem is **not** universally superior to existing baselines. In static geometry, it provides zero performance advantage over simple spatial caching ($O$).
2. **Statistical Equivalence**: We do **not** claim formal statistical equivalence between $F$ and $O$; $n=3$ per condition is an exploratory sample size and lacks statistical power for Two One-Sided Tests (TOST) or equivalence bounds.
3. **Generalization Across Platforms & Environments**: There is **no evidence** for cross-task memory persistence, multi-robot transfer, real-world hardware robustness, or efficacy in complex 3D / dynamic clutter.
4. **Action-Conditioned Failure Semantics**: The independent value of action-conditioned failure memory is **unproven**. The $H_1$ feasibility check demonstrated that Nav2's local planner negotiated narrow inflation boundaries without abortion (4/4 Nav2 `SUCCEEDED`), failing to establish executability divergence in the candidate setup.

---

## 4. Evaluation of Three Candidate Positionings

| Candidate Positioning | Core Argument | Strengths | Vulnerabilities & Review Risks | Selected? |
| :--- | :--- | :--- | :--- | :---: |
| **A. Reproducible System & Evaluation Tool** | An open-source, causally bound failure memory and replay auditing framework for ROS 2. | Solid engineering; high re-auditability; cryptographic manifests and strict data contracts. | Reviewers expect multi-benchmark evaluations, long-term deployments, or broad ecosystem integration. Engineering test count $\ne$ scientific novelty. | Secondary |
| **B. Exploratory Comparison & Negative Result** | An empirical study demonstrating that explicit failure memory offers no routing advantage over spatial caching in static 2D geometry, while establishing dynamic recovery boundaries. | 100% faithful to data; prevents community from reinventing redundant episodic mechanisms where costmaps suffice; high scientific integrity. | Requires venues or tracks that explicitly value negative results, boundary studies, and rigorous empirical characterization. | **PRIMARY** |
| **C. Novel Memory Algorithm** | FailMem as a novel superior memory architecture for mobile robots. | Traditional conference narrative. | **Fatal flaw**: Empirical data directly refutes superiority over baseline $O$. Claiming algorithmic novelty would lead to immediate rejection during peer review. | **REJECTED** |

### Selected Strategy: Positioning B (with System Traceability as Supporting Pillar)

The paper must be framed as an **empirical boundary analysis and exploratory study** of failure-aware memory in mobile robot navigation:
- It asks: *When does an autonomous mobile robot actually need episodic failure memory over existing spatial costmap caching?*
- It demonstrates that in static 2D geometry, spatial observation caching is already sufficient, yielding identical route selection with $<1\%$ divergence.
- It identifies where failure memory is required: preventing permanent detour traps via dynamic sensor-driven invalidation upon recovery, while providing an auditable, causally bound evaluation architecture.
- It documents the negative outcome of candidate action-conditioned scenarios ($H_1$), providing a concrete methodological guide for future research.

