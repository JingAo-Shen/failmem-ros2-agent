# Protocol: Condition-Aware Failure Memory for Long-Horizon Robotic Task Repair (FailMem Stage 2)

**Document Type**: Pre-Execution Research Protocol & Validity Specification  
**Version**: 1.2 (Revised: 2x3 Matrix Factor Decomposition & Subgoal Memory Interface)  
**Branch**: `research/agent-task-repair-pilot`  
**Base Commit**: `2a5ba61`  
**Date**: 2026-10-03  

---

## 1. Research Question & Hypotheses

### 1.1 Core Research Question
In long-horizon robotic delivery tasks subject to dynamic, non-stationary environmental constraints (temporary door obstacles, shifting access credentials, varying recipient availability), **does scoping failure memory to the active subgoal (按当前子目标使用记忆) better preserve task dependency relationships (e.g. picking up packages before attempting obstacle avoidance) and improve overall task execution compared to global warning injection (全局注入历史警告)?**

### 1.2 Factor Decomposition (2x3 Controlled Matrix)
To isolate the source of execution improvements, the evaluation explicitly separates two independent factors:
- **Factor 1: Planning Architecture ($S$)**
  * $S_0$ (Flat Single-Step Planning): Standard ReAct prompt with immediate state description and tool catalogue.
  * $S_1$ (Public Task Skeleton Planning): Explicit public state tracker maintaining pending delivery obligations, unsatisfied preconditions, and candidate subgoals.
- **Factor 2: Memory Injection Scope ($M$)**
  * $M_0$ (No Cross-Task Memory): Memory store disabled; decisions rely solely on current public observation and within-task step history.
  * $M_1$ (Global Memory Injection): All active failure memories matching candidate entities are injected into the prompt as a global warning block.
  * $M_2$ (Subgoal-Aware Memory Injection): Failure memories are strictly scoped by the active candidate subgoal domain (navigation memories scoped to path choices, access/recipient memories scoped to delivery/protected room actions).

This defines 6 paired evaluation conditions:
1. `S0_M0`: Flat Plan + No Memory
2. `S0_M1`: Flat Plan + Global Memory
3. `S0_M2`: Flat Plan + Subgoal-Aware Memory
4. `S1_M0`: Skeleton Plan + No Memory
5. `S1_M1`: Skeleton Plan + Global Memory
6. `S1_M2`: Skeleton Plan + Subgoal-Aware Memory

---

## 2. System Boundary & Information Access Rules

1. **Environment State vs. Agent Observation**:
   - The simulator maintains true ground-truth state $\mathcal{S}_{\text{true}}$ (door blockages, recipient status, battery level, package locations).
   - Ground truth is **strictly hidden** from the Agent.
   - Task instructions contain ONLY public delivery requests without hidden state hints.
   - The Agent interacts **solely** via structured tool calls returning discrete `ActionResult` dictionaries.
2. **Authentic Tool-Generated Historical Checkpoints**:
   - All Task 1 seed histories MUST be generated via actual tool execution on `DeliveryTaskEnv` (e.g. `env.step("navigate", ...)`).
   - Pre-acquired observations (e.g. observing door cleared) MUST enter the shared `known_state` for all methods equally.
   - Fixed pre-run checkpoint costs and continuation run costs MUST be reported separately.
3. **Execution Guardrails**:
   - Max Tool Calls per Continuation Task: $15$.
   - Max LLM Invocations per Continuation Task: $15$.
   - Max Simulation Time per Task: $300.0\,\text{s}$.
   - Consecutive No-Progress Limit: $3$ identical failed action attempts triggers `DEAD_LOOP_ABORT`.
4. **Epistemic Classification & Condition Matching**:
   - `FACT`: Directly verified by an environment tool return.
   - `CONJECTURE`: Speculated without tool confirmation.
   - **3-Valued Condition Logic**:
     * `MATCH`: All required preconditions confirmed in known state.
     * `MISMATCH`: Preconditions contradict known state (inapplicable, filtered out).
     * `UNKNOWN`: Preconditions cannot be verified from known state (requires cautious exploration, never assumed permanently infeasible).

---

## 3. Subgoal Memory Retrieval Interface

Every memory retrieval call MUST log a structured audit entry containing:
- `step_index`: Current decision step.
- `current_subgoal` / `subgoal_domain`: e.g., `pickup` (at origin), `navigate` (to zone), `deliver` (to recipient).
- `candidate_entities`: List of candidate zones, packages, and recipients.
- `evaluated_records`: List of memory items evaluated with 3-valued match result.
- `injected_records`: Memories injected with explicit reason (e.g., `M2: Relevant to candidate navigation transition`).
- `excluded_records`: Memories excluded with explicit reason (e.g., `M2: Local pickup pending; navigation obstacle scoped out to prevent preemption`).

---

## 4. Evaluation Metrics

### 4.1 Primary Metrics
1. **Task Success Rate ($SR_{\text{task}}$)**: Fraction of tasks where all target packages are successfully delivered without constraint violations.
2. **Task Dependency Errors ($N_{\text{dep\_err}}$)**: Number of illegal action attempts violating task dependencies (e.g. attempting delivery without holding package, attempting pickup when inventory is full).
3. **Repeated Failure Count ($N_{\text{rep}}$)**: Frequency of re-attempting identical failing actions under unchanged conditions.
4. **Unwarranted Detour Count ($N_{\text{detour}}$)**: Number of detour traversals through `Corridor_South` when `door_north` was physically clear and the destination was in the northern wing.

### 4.2 Secondary Metrics
5. **Observation Tool Calls ($N_{\text{obs}}$)**: Number of explicit `observe` or `query_status` actions executed.
6. **Execution Efficiency**: Average action steps, simulation time, and battery consumed (reported separately from pre-run seed cost).
7. **Computational Overhead**: Total LLM invocations, prompt tokens, generated tokens, and inference latency.
8. **Behavioral Divergence Point**: Exact step and action where methods diverge from the memoryless baseline.

---

## 5. Development Scenarios (6 Diagnostic Scenarios)

1. `scen_1_persist_door_north` (Cat 1): Persisting obstacle at `door_north`. Deliver package from Lobby to `Office_B`. (Detour required).
2. `scen_2_cleared_door_north_unobs` (Cat 2): Obstacle cleared, unobserved at start. Deliver package from Lobby to `Office_A`. (Nominal route open).
3. `scen_3_cleared_door_north_obs` (Cat 2): Obstacle cleared, confirmed FREE via shared tool observation before Task 2. Deliver package to `Office_B`.
4. `scen_4_inapp_lab_badge` (Cat 3): Historical failure requires `security_badge` for `Lab_Secure`. Current task delivers to `Office_A` (no badge required).
5. `scen_5_capacity_constraint`: 3 packages at Lobby, maximum capacity is strictly 2. Cannot pick up all packages at once; requires multi-trip planning.
6. `scen_6_battery_recharge`: Low initial battery (35%) requiring a planned recharge at Lobby charging station to prevent battery depletion during delivery.
