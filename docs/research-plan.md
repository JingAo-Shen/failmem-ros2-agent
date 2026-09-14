# Research Plan

## Core Question

Can a ROS2 agent convert execution failures into reusable episodic memory and skills, reducing repeated failures and hallucinated success in future tasks?

## Candidate Contributions

1. Define a precise research problem with measurable failure modes.
2. Build a reproducible benchmark or task suite.
3. Propose a method that is lightweight enough to run mostly on a 22 GB GPU.
4. Compare against strong, simple baselines rather than only weak handcrafted baselines.
5. Report quality, cost, latency, memory use, and failure cases.

## Research Hypotheses

- **H1:** A structured method tailored to the target failure mode can outperform naive context expansion or naive retrieval.
- **H2:** The method can improve task success without requiring a larger backbone model.
- **H3:** Benefits remain under model/domain/task transfer instead of appearing only in a single in-domain setup.
- **H4:** The contribution remains useful after controlling for additional tokens, retrieval calls, or compute budget.

## Methodology Rules

- Separate training, validation, and final evaluation scenarios.
- Log every experiment with seed, model version, prompt/config hash, GPU, runtime, and cost.
- Always include simple baselines.
- Prefer at least 3 random seeds for smaller experiments.
- Perform ablations on every proposed component.
- Add qualitative failure analysis, not only aggregate accuracy.

## Paper Skeleton

1. Introduction
2. Related Work
3. Problem Formulation
4. Proposed Method
5. Benchmark / Experimental Setup
6. Main Results
7. Ablation Study
8. Failure Analysis
9. Limitations
10. Conclusion

## Direction-Specific Memory Types

- Semantic Memory: stable environment facts
- Spatial Memory: locations and relations
- Episodic Memory: prior task episodes
- Failure Memory: causes, symptoms, recovery actions
- Skill Memory: reusable successful procedures

### Core Loop
Plan -> Execute -> Observe -> Verify -> Success / Diagnose Failure -> Replan -> Store Episode -> Abstract Skill

### Failure Scenarios
- Route blockage
- Target not found / moved
- Localization error
- Tool/action failure
- Timeout
- Dynamic environment change
- False success judgment

### Candidate Metrics
- Task Success Rate
- Recovery Rate
- Repeated Failure Rate
- Hallucinated Success Rate
- Planning Steps
- Recovery Latency
- LLM Calls / token cost

