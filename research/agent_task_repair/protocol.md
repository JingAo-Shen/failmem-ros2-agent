# Protocol: Condition-Aware Failure Memory for Long-Horizon Robotic Task Repair (FailMem Stage 2)

**Document Type**: Pre-Execution Research Protocol & Boundary Specification  
**Version**: 1.0 (Frozen before pilot evaluation)  
**Branch**: `research/agent-task-repair-pilot`  
**Base Commit**: `7a64c50d92354f6605e73f0eba4be8eb68ec0f80`  
**Date**: 2026-10-02  

---

## 1. Research Question & Hypotheses

### 1.1 Core Research Question
In long-horizon robotic delivery tasks subject to non-stationary environments (e.g., temporary obstacles, shifting access permissions, varying recipient availability), **does condition-aware failure memory with perception-driven invalidation enable an LLM planning agent to reduce repeated failure attempts without suffering from unwarranted avoidance (错误回避) or permanent detour traps, compared to unconditioned or decay-based memory baselines?**

### 1.2 Research Hypotheses (Exploratory)
- **Hypothesis $H_{\text{valid}}$ (Error Reduction)**: When failure-inducing conditions persist (Scenario Cat 1), structured memory prevents redundant retries, reducing action steps and energy consumption relative to memoryless baseline ($B0$).
- **Hypothesis $H_{\text{stale}}$ (Unwarranted Avoidance Mitigation)**: When environmental conditions recover (e.g., obstacle cleared, permission granted, recipient available in Scenario Cat 2), evidence-driven dynamic invalidation enables the agent to recover nominal paths, achieving higher success and lower detour cost than static memory ($B2$) or naive text memory ($B1$).
- **Hypothesis $H_{\text{scope}}$ (Discrimination / Applicability)**: In tasks with superficial semantic similarity but distinct preconditions (Scenario Cat 3), condition checking prevents false-positive memory transfer, outperforming unconditioned text retrieval ($B1$).
- **Hypothesis $H_{\text{ablation}}$ (Condition vs. Decay)**: Dynamic perceptual invalidation ($F$) outperforms heuristic time-to-live decay ($B3$) by explicitly coupling memory expiration to verified sensor evidence rather than arbitrary time constants.

---

## 2. Related Work & Mechanism Comparison

We review 8 primary foundational and contemporary works across robotics, agent memory, and plan repair:

| Reference & Venue | Core Paradigm | Memory Representation | Invalidation / Expiration Mechanism | Task Domain | Key Baselines | Distinctive Boundary of FailMem Stage 2 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **REFLECT** (Liu et al., CoRL 2023) \cite{liu2023reflect} | Hierarchical LLM summarization | Natural language text summaries of multimodal sensor logs | End-of-episode batch reset; no physical precondition invalidation | VirtualHome manipulation | SayCan, Inner Monologue | FailMem operates in low-level discrete-event robotics with explicit condition matching and active sensor invalidation during execution. |
| **Inner Monologue** (Huang et al., CoRL 2022) \cite{huang2023inner} | Closed-loop language planning | Text prompt context with success detectors | Re-prompted every step; memory vanishes across tasks | Tabletop manipulation | Open-loop LLM, SayCan | Inner Monologue lacks cross-task episodic memory; FailMem focuses specifically on cross-task transfer and stale memory recovery. |
| **SayCan** (Ahn et al., RSS 2022) \cite{ahn2022can} | Affordance-grounded planning | Value function $V(s, a)$ over primitives | Real-time state evaluation; no explicit failure episodic store | Mobile manipulation | Standard LLM prompting | SayCan models immediate affordances but does not maintain a structured history of past failures and their invalidation triggers. |
| **Reflexion** (Shinn et al., NeurIPS 2023) \cite{shinn2023reflexion} | Verbal reinforcement learning | Natural language episodic reflections in prompt buffer | Manual context buffer eviction; no physical state verification | AlfWorld, WebShop | Chain-of-Thought, ReAct | Reflexion stores free-form text reflections susceptible to hallucinated causes; FailMem strictly separates tool-verified `FACT` from `CONJECTURE`. |
| **Generative Agents** (Park et al., UIST 2023) | Associative memory stream | Natural language memory statements with recency/importance weights | Continuous decay exponential weight; no discrete verification | Sandbox social simulation | Static prompt context | Heuristic decay suffers in robotics where obstacles can clear immediately or persist indefinitely; FailMem invalidates on physical observation. |
| **Deliberation Survey** (Ingrand & Ghallab, AIJ 2017) \cite{ingrand2017deliberation} | Classical execution monitoring & repair | Symbolic plan trees and causal link chronicles | Plan repair on goal failure; state tracker | Classical robotics | PRS, IXTET, T-REX | FailMem combines classical precondition/postcondition monitoring with LLM semantic reasoning and tool dispatch. |
| **GRASP / CDCL** (Marques-Silva & Sakallah, IEEE TC 1999) \cite{marquessilva1999grasp} | Conflict-driven clause learning | Boolean conflict clauses ("no-goods") | Backtracking resolution; static during search | SAT solving | DPLL | FailMem adapts the "no-good" constraint learning concept to dynamic robotics environments where constraints are time-varying. |
| **Layered Costmaps** (Lu et al., IROS 2014) \cite{lu2014layered} | Spatial geometric mapping | 2D occupancy grid cells | Sensor raycasting ray traversal | 2D mobile navigation | Static occupancy grid | Costmaps handle 2D spatial occupancy; FailMem Phase 2 extends this to symbolic, relational constraints (permissions, schedules, recipients). |

### 2.1 Critical Reflection: Is this merely a trivial combination?
- **Analysis**: "Conditions + Retrieval + TTL" is a standard heuristic in software caching. However, in LLM-driven robotics, applying software cache heuristics naively leads to two failure modes:
  1. *Unwarranted Avoidance (False Negative)*: If memory persists after an obstacle is cleared or permission granted, the agent permanently detours or prematurely declares the task unsolvable.
  2. *Heuristic Expiration Failure*: Time-based TTL either expires too quickly (causing repeated collisions with persisting obstacles) or too slowly (causing long detour delays).
- **Testable Proposition**: Conditioning memory on **observable physical predicates** (e.g., `door_north.obstacle == True`, `recipient.status == in_meeting`, `robot.has_badge == False`) and updating memory **only upon verified tool observation** provides superior Pareto efficiency (Success Rate vs. Action Cost) compared to both static and time-decay baselines.

---

## 3. System Boundary & Information Access Rules

1. **Environment State vs. Agent Observation**:
   - The simulator maintains true ground-truth state $\mathcal{S}_{\text{true}}$ (door blockages, recipient calendar, battery level, package locations).
   - Ground truth is **strictly hidden** from the Agent.
   - The Agent interacts **solely** via structured tool calls returning discrete `ActionResult` dictionaries.
2. **Resource & Time Accounting**:
   - Every action (including `observe` and `query_status`) incurs simulated execution time and battery depletion.
   - Free observations are strictly prohibited.
3. **Execution Guardrails**:
   - Max Tool Calls per Task: $25$.
   - Max LLM Invocations per Task: $20$.
   - Max Simulation Time per Task: $300.0\,\text{s}$.
   - Consecutive No-Progress Limit: $3$ identical failed action attempts triggers abort.
4. **Epistemic Classification**:
   - `FACT`: Directly verified by an environment tool return (e.g., `observe(door_north)` returns `OCCUPIED`).
   - `CONJECTURE`: Generated by the LLM planner without tool confirmation. Conjectures cannot invalidate facts.

---

## 4. Evaluated Baseline Groups

All methods utilize the exact same LLM architecture (`Qwen/Qwen2.5-Coder-7B-Instruct` on local GPU), identical system prompts, identical tool schemas, and identical in-task scratchpad management. They differ strictly in cross-task memory handling:

1. **B0 (No Cross-Task Memory)**: Standard ReAct planning agent. Within-task tool history is maintained; cross-task memory store is disabled.
2. **B1 (Unstructured Natural Language Memory)**: Stores free-text failure descriptions (e.g., `"Failed to deliver package to Office B because door was locked"`). Retrieves top-$k$ entries via string/semantic similarity without condition checking or invalidation.
3. **B2 (Static Condition-Aware Memory)**: Stores structured tuples $\langle \text{action}, \text{target}, \text{conditions}, \text{error} \rangle$. Matches conditions against current known state, but **never updates or invalidates** records once created.
4. **B3 (Decay / Time-To-Live Memory)**: Unstructured memory with an exponential step-decay / TTL expiration (records expire after $T_{\text{decay}} = 2$ task episodes, calibrated on development tasks).
5. **F (Full Condition-Aware Memory + Dynamic Invalidation + Plan Repair)**: Stores structured tuples with epistemic tags (`FACT` vs `CONJECTURE`), actively updates/invalidates records upon contradictory tool observations, and provides verified repair actions to the planner.

---

## 5. Evaluation Metrics

### 5.1 Primary Metrics
1. **Task Success Rate ($SR_{\text{task}}$)**: Fraction of evaluation tasks where all target packages are successfully delivered to correct recipients within constraints ($0.0 \dots 1.0$).
2. **Hard Constraint Violation Rate ($VR_{\text{hard}}$)**: Fraction of tasks where the agent commits a critical violation (battery drained to 0%, unauthorized room breach, delivery to wrong recipient).

### 5.2 Secondary Metrics
3. **Repeated Failure Count ($N_{\text{repeat}}$)**: Number of times an agent re-executes an identical failing action under identical conditions.
4. **Unwarranted Avoidance Rate ($R_{\text{avoid}}$)**: Frequency of refusing to use a viable, clear nominal route/action due to outdated memory.
5. **Total Simulated Time ($T_{\text{sim}}$)**: Cumulative simulated seconds to complete tasks.
6. **Battery Consumption ($\Delta \text{Bat}$)**: Total battery percentage consumed across tasks.
7. **Computational Overhead**: Average LLM calls, total token count (prompt + generation), and wall-clock execution latency per task.

---

## 6. Dataset Splits, Budget & Stopping Rules

- **Development Set (Calibration)**: 3 task sequences used strictly for interface verification, prompt debugging, and tuning TTL for $B3$.
- **Pilot Evaluation Set (Frozen)**:
  - **Category 1 (Valid Experience, 5 paired sequences)**: Failure conditions persist across tasks.
  - **Category 2 (Stale Experience, 5 paired sequences)**: Failure conditions resolve before subsequent tasks.
  - **Category 3 (Inapplicable Experience, 5 paired sequences)**: Surface similarity with distinct requirements.
  - Total Evaluation Units: $15 \text{ sequences} \times 5 \text{ methods} = 75 \text{ evaluation runs}$.
- **Stopping Rule**: If FailMem ($F$) does not achieve measurable improvement over the strongest simple baseline ($B2$ or $B3$) in this pilot batch, or if gains are driven purely by excess token consumption, the project terminates with an empirical No-Go without expanding to large-scale simulation.
