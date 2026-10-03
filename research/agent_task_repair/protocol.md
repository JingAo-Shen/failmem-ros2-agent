# Protocol: Explicit Subgoal-Scoped Memory vs Phase Heuristic Filtering (FailMem Stage 2)

**Document Type**: Pre-Execution Research Protocol & Validity Specification  
**Version**: 1.3 (Revised: 4-Group Paired Diagnosis under S1 Task Skeleton & 8 Diagnostic Scenarios)  
**Branch**: `research/agent-task-repair-pilot`  
**Base Commit**: `13a4d83`  
**Date**: 2026-10-03  

---

## 1. Research Question & Hypotheses

### 1.1 Core Research Question
In long-horizon robotic delivery tasks subject to dynamic, non-stationary environmental constraints (temporary door obstacles, shifting access credentials, multi-target delivery obligations), **does Explicit Subgoal-Scoped Memory ($S_1\_G$) provide independent value beyond simple Phase Heuristic Filtering ($S_1\_H$) in reducing precondition violations, preventing premature task abandonment, and improving execution efficiency?**

### 1.2 Experimental Design (4-Group Paired Matrix under S1 Task Skeleton)
All conditions operate under the **Public Task Skeleton ($S_1$)**, isolating the memory injection and filtering mechanism:
- **Group A ($S_1\_M_0$, Baseline)**: No Cross-Task Memory. Operates purely on task skeleton, public state, and within-task step history.
- **Group B ($S_1\_M_1$, Global Memory)**: Global Memory Injection. All active failure memories matching candidate entities are injected into the prompt as a global warning block.
- **Group C ($S_1\_H$, Phase Heuristic Filtering)**: Coarse phase-based heuristic filtering. Suppresses navigation warnings if local pickable items are present at origin, but lacks explicit subgoal-target binding.
- **Group D ($S_1\_G$, Explicit Subgoal Scoping)**: Structured Subgoal Memory Filter. Dynamically derives an explicit active subgoal ($s = \langle \text{id}, \text{type}, \text{target}, \text{pkg\_id}, \text{preconditions}, \text{completion} \rangle$) and scopes memory strictly to the active subgoal and its required topological transitions or credential requirements.

**Evaluation Scale**: 8 Diagnostic Scenarios $\times$ 4 Groups $\times$ 3 Runs = **96 Continuation Units** executed deterministically on GPU (`Qwen/Qwen2.5-Coder-7B-Instruct`).

---

## 2. System Boundary & Grounding Rules

1. **Environment State vs. Public Agent Observation**:
   - The simulator maintains true ground-truth state $\mathcal{S}_{\text{true}}$ (door blockages, recipient status, battery level, package locations).
   - Ground truth is **strictly hidden** from the Agent.
   - Task instructions contain ONLY public delivery requests without hidden state hints.
   - The Agent interacts **solely** via structured tool calls returning discrete `ActionResult` dictionaries.
2. **Authentic Tool-Generated Historical Checkpoints**:
   - All Task 1 seed histories MUST be generated via actual tool execution on `DeliveryTaskEnv` (e.g. `env.step("navigate", ...)`).
   - Pre-acquired observations (e.g. observing door cleared) MUST enter the shared `known_state` for all methods equally.
   - Fixed pre-run checkpoint costs and continuation run costs MUST be reported separately.
3. **Execution Guardrails**:
   - Max Tool Calls per Continuation Task: $25$.
   - Max LLM Invocations per Continuation Task: $20$.
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

## 3. Explicit Subgoal Memory Retrieval Interface

Every memory retrieval call MUST log a structured audit entry containing:
- `step_index`: Current decision step.
- `active_subgoal`: Explicit structured subgoal object ($s$).
- `candidate_entities`: List of candidate zones, packages, and recipients.
- `evaluated_records`: List of memory items evaluated with 3-valued match result.
- `injected_records`: Memories injected with explicit reason (e.g., `G: Relevant to active navigation subgoal [Office_B]`).
- `excluded_records`: Memories excluded with explicit reason (e.g., `G: Active subgoal is PICKUP(pkg_docs); memory for navigate(Corridor_North) is excluded`).

---

## 4. Evaluation Metrics

### 4.1 Primary Metrics
1. **Task Success Rate ($SR_{\text{task}}$)**: Fraction of tasks where all target packages are successfully delivered without constraint violations.
2. **Task Dependency Errors ($N_{\text{dep\_err}}$)**: Violations of *known* preconditions (e.g., attempting delivery without holding package, attempting pickup when inventory is known full, attempting recharge when not at charger). Distinct from first-time discoveries of unknown environment obstacles.
3. **Repeated Failure Count ($N_{\text{rep}}$)**: Frequency of re-attempting identical failing actions under unchanged conditions.
4. **Unwarranted Detour Count ($N_{\text{detour}}$)**: Number of detour traversals through `Corridor_South` when `door_north` was physically clear and the destination was in the northern wing.

### 4.2 Efficiency Accounting Rules
5. **Cost Accounting on Mutual Successes**: Paired cost differences ($\Delta \text{Battery}, \Delta \text{Steps}$) are computed **strictly on instances where both compared methods succeeded**. Early termination due to failure is NEVER reported as efficiency savings.
6. **Separation of Pre-Run and Continuation Costs**: Fixed seed costs (Task 1) and continuation costs (Task 2) are reported independently.

---

## 5. The 8 Diagnostic Scenarios

1. `scen_1_persist_door_north` (Detour & Persistence): Door North is persistently blocked. Task: Deliver `pkg_docs` from Lobby to Alice in `Office_A`. Detour via `Corridor_South` is required.
2. `scen_2_cleared_door_north_unobs` (Stale Memory & Blind Detour): Door North was blocked in Task 1, but is cleared in Task 2. Robot has not observed it. Tests whether stale memory induces unwarranted detour.
3. `scen_3_cleared_door_north_obs` (Active Invalidation): Door North was blocked in Task 1, but observed FREE in shared state before Task 2. Tests whether dynamic invalidation allows direct transit.
4. `scen_4_lab_badge_required` (Credential Precondition Scoping): `door_lab` requires a security badge. Badge is at Lobby. Task: Deliver `pkg_hardware` from Lobby to Bob in `Lab_Secure`.
5. `scen_5_capacity_constraint` (Capacity Precondition & Multi-Trip): 3 packages at Lobby, maximum capacity is 2. Requires multi-trip sequencing.
6. `scen_6_multi_target_interleave` (Subgoal Disambiguation): Robot starts holding `pkg_1` (destined for `Office_A`) while `pkg_2` (destined for `Office_B`) is on the floor at Lobby. Tests whether explicit subgoal tracking correctly sequences delivery of held package before diverting.
7. `scen_7_mandatory_battery_charging` (Physical Feasibility): Robot starts at Lobby with 10% battery. Nominal path cost to `Office_B` is 17% ($10\% < 17\%$). Recharging at Lobby is physically mandatory to prevent battery exhaustion.
8. `scen_8_irrelevant_memory_distraction` (Distraction Immunity): Seed history contains a past failure in an unrelated wing (`Storage_Archive`). Task: Deliver `pkg_mail` from Lobby to Alice in `Office_A`. Tests whether irrelevant memory is filtered out without distracting the agent.
