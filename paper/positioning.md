# Paper Positioning & Scope Definition: FailMem

**Document Type**: Internal Research Strategy & Manuscript Positioning  
**Target Length**: Within 2 pages (~1,200 words)  
**Date**: 2026-10-02  
**Baseline Commit**: `04631bd`  

---

## 1. Executive Summary

This document formalizes the scientific positioning and contribution boundaries for the FailMem manuscript. To ensure scientific rigor and prevent overclaiming during peer review, the manuscript's findings are explicitly grounded in the concrete evidence collected. Methodological and engineering audit depth is recognized as experimental rigor, not as conceptual algorithmic novelty. The primary positioning of this work is an **auditable exploratory comparative study** (可审计的探索性比较). We do not claim to have established universal operational boundaries or proved that any specific memory mechanism is indispensable.

---

## 2. Firmly Supported Contributions

The empirical evidence from the 30-run exploratory benchmark ($n=3$ per condition under sequential fixed seeds) and the 4-run feasibility check firmly supports the following:

1. **Traceable Failure Memory Lifecycle for ROS 2 / Nav2**:
   - Implemented an event-driven lifecycle binding execution aborts to immutable observation bundles (raw LiDAR scans, TF transforms, costmap ROIs) within a single runner session across sequential phases.
   - Implemented perception-driven dynamic invalidation that unsuppresses paths upon verified environmental clearance.
2. **Deterministically Re-Auditable Evaluation Pipeline**:
   - Developed an independent cryptographic replay auditor (`replay_and_score_p2c.py`) that recomputes physical halt stability ($|v_{\text{lin}}| \le 0.05\,\text{m/s}, |v_{\text{ang}}| \le 0.08\,\text{rad/s}$) and sensory outcomes directly from raw serialized logs against SHA256 manifests.
3. **Exploratory Dual-Path Comparative Benchmark ($n=3$)**:
   - *Dead-End Elimination*: In Scenario D1, historical information in FailMem ($F$) eliminates redundant corridor entry ($0.0$ vs. $1.0$ dead ends) relative to an unguided reactive retry baseline ($R$), saving $-18.5\%$ distance ($14.03\,\text{m}$ vs. $17.22\,\text{m}$) and $-22.3\%$ simulation duration ($109.5\,\text{s}$ vs. $141.0\,\text{s}$).
   - *D2 Performance Under Obstacle Removal*: In Scenario D2, FailMem ($F$) reduces travel distance by $\approx 11.0\%$ relative to permanent suppression ($M1$) ($16.25\,\text{m}$ vs. $18.25\,\text{m}$), while average total simulation duration increases by $\approx 1.5\%$ ($151.1\,\text{s}$ vs. $148.8\,\text{s}$). No duration benefit was observed in this experiment, and the underlying cause remains unverified.
4. **Empirical Boundary Finding (Exploratory Data)**:
   - In the evaluated static 2D geometry, FailMem ($F$) and spatial costmap caching ($O$) selected identical topological routes, exhibiting $<1\%$ difference in reported total travel distance and total simulation time. **在本布局和当前运行样本中，未观察到 F 相对 O 的额外收益；不能据此推出普遍无效或统计等价** (In this layout and current run sample, no additional benefit of $F$ over $O$ was observed; this does not imply general lack of benefit across arbitrary domains or statistical equivalence).

---

## 3. Firmly Unsupported / Disclaimed Claims

The following claims are **not supported** by the current evidence and must be explicitly disclaimed:

1. **Algorithmic Superiority**: We do **not** claim FailMem is universally superior to existing baselines. In the tested static 2D geometry, current exploratory data does not show an additional benefit of $F$ over spatial caching $O$. (Note: Lack of demonstrated benefit in this layout does not constitute a proof of zero advantage across all possible robotic tasks).
2. **Mechanism Indispensability & Exclusivity**: We do **not** claim that episodic failure memory is uniquely indispensable or that dynamic recovery is exclusive to FailMem. The $F$ vs. $M1$ comparison confirms that dynamic unsuppression avoids the persistent detour penalty of static suppression under the tested conditions. However, spatial observation caching ($O$) likewise updates its internal state upon acquiring new sensory observations and recovers optimal paths without explicit failure logs.
3. **Formal Statistical Equivalence**: We do **not** claim formal statistical equivalence between $F$ and $O$; $n=3$ per condition is an exploratory sample size and lacks statistical power for Two One-Sided Tests (TOST) or asymptotic equivalence bounds.
4. **Generalization Across Platforms & Lifetimes**: There is **no evidence** for persistent multi-task memory across separate OS daemon lifetimes, multi-robot transfer, real-world hardware robustness, or efficacy in complex 3D / dynamic obstacle fields. Evaluation was confined to cross-phase memory within a single continuous runner execution.
5. **Action-Conditioned Failure Semantics**: The independent value of action-conditioned failure memory is **unproven**. Candidate configurations in the $H_1$ feasibility check did not establish executability divergence (4/4 Nav2 `SUCCEEDED`).

---

## 4. Evaluation of Three Candidate Positionings

| Candidate Positioning | Core Argument | Strengths | Vulnerabilities & Review Risks | Selected? |
| :--- | :--- | :--- | :--- | :---: |
| **A. Reproducible System & Evaluation Tool** | An open-source, causally bound failure memory and replay auditing framework for ROS 2. | Solid engineering; high re-auditability; cryptographic manifests and strict data contracts. | Reviewers expect multi-benchmark evaluations, long-term deployments, or broad ecosystem integration. Engineering test count $\ne$ scientific novelty. | Supporting |
| **B. Auditable Exploratory Comparison & Negative Finding** | An exploratory comparative study examining whether explicit episodic failure memory provides routing benefits over spatial caching in 2D geometry, reporting identical route selection and dynamic invalidation effects. | Completely faithful to data; prevents community from assuming episodic memory is necessary where standard costmaps suffice; high scientific transparency. | Requires venues or reviewers that value rigorous negative findings, empirical comparisons, and boundary characterization over headline performance claims. | **PRIMARY** |
| **C. Novel Memory Algorithm** | FailMem as a novel superior memory architecture for mobile robots. | Traditional conference narrative. | **Fatal flaw**: Empirical data shows no additional routing benefit over baseline $O$. Claiming algorithmic superiority or novelty will lead to immediate rejection during peer review. | **REJECTED** |

### Selected Strategy: Positioning B (Auditable Exploratory Comparison)

The paper is framed strictly as an **auditable exploratory comparative study** (可审计的探索性比较):
- It investigates: *In a canonical dual-path chokepoint navigation task, how does event-driven failure memory compare with spatial costmap caching, reactive retry, and permanent suppression?*
- It demonstrates that in static 2D geometry, spatial observation caching is already sufficient to achieve efficient routing, yielding identical route selection with $<1\%$ metric divergence.
- It highlights that dynamic state updates (applicable to both FailMem and spatial caching) prevent the permanent detour penalty of static suppression upon environmental clearance ($-11.0\%$ distance in D2, though average simulation duration increased by $\approx 1.5\%$), noting that no duration benefit was observed and the cause remains unverified.
- It transparently reports that candidate action configurations in $H_1$ did not establish executability divergence, providing empirical stopping rationale for this exploratory branch.
- Venue selection must be guided by contribution fit and evidentiary strength, rather than journal prestige or APC cost.
