# Literature Reading Notes (Literature Verification Audit)

- **Audit Date**: 2026-09-27
- **Reviewer**: Research Execution Engineer
- **Status**: Verified against arXiv versions and official code/project repositories

---

## 1. Reflexion: Language Agents with Verbal Reinforcement Learning
- **arXiv ID**: [2303.11366](https://arxiv.org/abs/2303.11366) (Version read: v4, Oct 2023)
- **Authors**: Noah Shinn, Federico Cassano, Edward Berman, Ashwin Gopinath, Karthik Narasimhan, Shunyu Yao
- **Code Repository**: https://github.com/noahshinn/reflexion (License: MIT)
- **Inspected Sections**:
  - Section 2 (Reflexion Architecture, pp. 2-4): Defines the triad of Actor ($M_a$), Evaluator ($M_e$), and Self-Reflection model ($M_{sr}$). Equation 1-3 formalize the short-term memory buffer $\Omega_t$ and the reflective memory buffer $M_t$.
  - Section 3 (Empirical Evaluation, pp. 4-8): Benchmarks on HumanEval (Python coding), HotpotQA (multi-hop QA), and ALFWorld (text-based embodied interactive environment).
  - Section 4 (Analysis): Discussion on trial budget $k \in [1, 5]$.
- **Key Evidence on Scope & Limitations**:
  - *Within-episode Trial Scope*: "At each trial $t$, the Actor receives a reflective memory $mem_{t-1}$ summarizing previous trial failures of the same problem... Once the problem is solved or budget $k$ is exhausted, memory is reset." (Sec. 2.1, p. 3).
  - *No spatial/physical precondition validation*: In ALFWorld, state feedback is discrete text (e.g. "You are in the middle of a room. On the desk, you see a pen."). No sensor verifier or dynamic costmap invalidation is evaluated.
- **FailMem Differentiation**:
  - Reflexion reflects within repeated trials of the same episode.
  - In inspected text, no persistent cross-episode experience retrieval or spatial costmap invalidation mechanism was identified.

---

## 2. REFLECT: Summarizing Robot Experiences for Failure Explanation and Correction
- **arXiv ID**: [2306.15724](https://arxiv.org/abs/2306.15724) (Version read: v4, Oct 2023)
- **Authors**: Zeyi Liu, Arpit Bahety, Shuran Song
- **Conference**: Conference on Robot Learning (CoRL) 2023
- **Official Project**: https://robot-reflect.github.io/
- **Code Repository**: https://github.com/columbia-ai-robotics/reflect (License: MIT)
- **Inspected Sections**:
  - Section 3.1 (Hierarchical Robot Summary, pp. 3-4): Details sensory-input summary (task-informed 3D scene graphs from RGB-D, audio classification via AST) and event/subgoal-based summaries.
  - Section 3.2-3.3 (Progressive Failure Explanation & Correction Planner, pp. 4-5): Two-stage prompting for failure localization and generation of correction subgoals.
  - Section 4 (The RoboFail Dataset, pp. 5-6): Describes 100 simulation failure demonstrations in AI2-THOR and 30 real-world demonstrations collected via human teleoperation on a UR5e robot arm in a toy kitchen.
  - Section 5 & Tables 1-2 (Evaluation, pp. 6-8): Models evaluated are GPT-4 (`gpt-4-0314`) and GPT-3.5 (`text-davinci-003`).
- **Key Evidence on Scope & Limitations**:
  - *Perception & Models*: REFLECT does not use GPT-4V. Instead, it converts multisensory signals (visual scene graph + audio labels) into structured text before prompting text LLMs (GPT-4/GPT-3.5) (Sec. 3.1.1, p. 3).
  - *Embodiment*: Embodiments evaluated are AI2-THOR virtual agent and a tabletop UR5e robotic arm (Sec. 4, p. 5), not mobile dual-arm robots.
  - *Single-episode correction*: REFLECT produces a one-off correction plan for the immediate failed trajectory. In inspected sections (Sec. 3-5), it does not maintain a persistent long-term database indexing recovery actions across new task episodes, nor does it define invalidation rules for changing physical layouts.

---

## 3. Inner Monologue: Embodied Reasoning through Planning with Language Models
- **arXiv ID**: [2207.05608](https://arxiv.org/abs/2207.05608) (Version read: v2, Oct 2022)
- **Authors**: Wenlong Huang, Fei Xia, Ted Xiao, Harris Chan, Jacky Liang, Pete Florence, Andy Zeng, Jonathan Tompson, Igor Mordatch, Yevgen Chebotar, Pierre Sermanet, Noah Brown, Tomas Jackson, Linda Luu, Sergey Levine, Karol Hausman, Brian Ichter
- **Conference**: Conference on Robot Learning (CoRL) 2022
- **Official Project**: https://innermonologue.github.io
- **Code Repository**: https://github.com/google-research/google-research (Apache-2.0)
- **Inspected Sections**:
  - Section 3 (Inner Monologue Formulation, pp. 3-5): Closes the loop with perception models: Success Detector (is the subtask completed?), Passive Scene Describer (what objects are in the scene?), and Human Feedback.
  - Section 4 (Experiments): Evaluates mobile manipulation tasks with Everyday Robots.
- **Key Evidence on Scope & Limitations**:
  - *Dialog Context History*: Feedback is appended directly into the active prompt context of the ongoing episode (Sec. 3.2, p. 4).
  - In inspected text, no persistent failure memory database across distinct episodes or explicit expiration rules for changing maps was found.

---

## 4. SayPlan: Grounding Large Language Models using 3D Scene Graphs for Scalable Robot Task Planning
- **arXiv ID**: [2307.06135](https://arxiv.org/abs/2307.06135) (Version read: v2, Oct 2023)
- **Authors**: Krishan Rana, Jesse Haviland, Sourav Garg, Jad Abou-Chakra, Ian Reid, Niko Suenderhauf
- **Conference**: Conference on Robot Learning (CoRL) 2023 (Oral)
- **Official Project**: https://sayplan.github.io
- **Code Repository**: UNKNOWN (Code link on project page lacks an active URL; no verified public repo found)
- **Inspected Sections**:
  - Section 3 (Method, pp. 3-6): Semantic search over collapsed 3D scene graphs (`expand`, `contract`) and iterative replanning with a 3DSG execution verifier.
  - Section 4 (Experimental Results, pp. 6-9): 3-floor building environments with 36 rooms and 140 objects.
- **Key Evidence on Scope & Limitations**:
  - SayPlan grounds LLM plans into large topological graphs and replans when subtasks fail during execution.
  - In inspected sections (Sec. 3-4), it maintains environment state in the 3DSG but does not store an indexed library of past failure-recovery lessons for reuse across subsequent tasks.

---

## 5. Recover, Discover, Plan: Learning Skills and Concepts from Robot Failures (ReSYNC)
- **arXiv ID**: [2606.18328](https://arxiv.org/abs/2606.18328) (Version read: v1, Jun 2026)
- **Authors**: Bowen Li, Mayank Mishra, Y. Isabel Liu, Stone Tao, Nishanth Kumar, Alexander G. Gray, Ruwan Wickramarachchi, Jonathan Francis, Sebastian Scherer, Tom Silver
- **Official Project**: https://jaraxxus-me.github.io/ReSYNC/
- **Code Repository**: UNKNOWN (Project page does not link a public repository as of v1)
- **Inspected Sections**:
  - Section 3 (Overview & Problem Formulation, pp. 2-4): Dual-learning process combining reinforcement learning for recovery skill acquisition with symbolic concept discovery (predicate induction).
  - Section 4 (Skill & Concept Discovery, pp. 4-6): Learning low-level PPO policies from failed states and discovering relational predicates to update a symbolic STRIPS planning domain.
  - Section 5 (Experiments, pp. 6-9): 4 simulated robotic manipulation domains (e.g. Non-prehensile block pushing/insertion) and real-world Franka/UR manipulation.
- **Key Evidence on Scope & Limitations**:
  - ReSYNC bridges reinforcement learning and symbolic classical planning for manipulation.
  - In inspected text, it does not use LLM planners for mobile robot navigation, nor does it address costmap dynamic layer expiration.

---

## 6. LifeMem: Enabling Lifelong Experience Reuse for LLM Agents
- **arXiv ID**: [2609.12655](https://arxiv.org/abs/2609.12655) (Version read: v1, Sep 2026; Accepted to EMNLP 2026 Main)
- **Authors**: Yuli Qiu, Yutong Li, Wei Su, Zeming Liu, Wanxiang Che, Heyan Huang, Haifeng Wang, Yuang Guo
- **Code Repository**: https://github.com/BITHLP/LifeMem (License: UNKNOWN, Repo Public)
- **Inspected Sections**:
  - Section 3 (LifeMem Framework, pp. 3-5): Trajectory clustering based on workflow representations to extract reusable skill patterns; memory consolidation and retrieval at inference.
  - Section 4 & Appendix A (Experiments & Datasets, pp. 5-8, 12-14): 10 environments covering Embodied Action (ALFWorld, VirtualHome), Tool Utilization (ToolBench), Web Search, Data Analysis, and Web Browser (Mind2Web, WebArena).
- **Key Evidence on Scope & Limitations**:
  - Evaluated on software agents, web interaction, and high-level symbolic embodied benchmarks.
  - In inspected text, LifeMem does not address physical robotics navigation, spatial costmap updates, or physical obstacle persistence.

---

## 7. RoboOS-NeXT: A Unified Memory-based Framework for Lifelong, Scalable, and Robust Multi-Robot Collaboration
- **arXiv ID**: [2510.26536](https://arxiv.org/abs/2510.26536) (Version read: v1, Oct 2025)
- **Authors**: Huajie Tan, Cheng Chi, Xiansheng Chen, Yuheng Ji, Zhongxia Zhao, Xiaoshuai Hao, Yaoxu Lyu, Mingyu Cao, Junkai Zhao, Huaihai Lyu, Enshen Zhou, Ning Chen, Yankai Fu, Cheng Peng, Wei Guo, Dong Liang, Zhuo Chen, Mengsi Lyu, Chenrui He, Yulong Ao, Yonghua Lin, Pengwei Wang, Zhongyuan Wang, Shanghang Zhang
- **Official Project**: https://flagopen.github.io/RoboOS/
- **Code Repository**: https://github.com/FlagOpen/RoboOS (License: Apache-2.0)
- **Inspected Sections**:
  - Section 3 (System Architecture, pp. 3-5): Spatio-Temporal-Embodiment Memory (STEM) integrating spatial geometry, temporal event history, and embodiment profiles; brain-cerebellum framework.
  - Section 4 (Dynamic Task Allocation & Failure Recovery, pp. 5-7): Failure detection and task re-allocation across heterogeneous multi-robot teams.
  - Section 5 (Experiments, pp. 7-10): Collaborative tasks in restaurants, supermarkets, and households.
- **Key Evidence on Scope & Limitations**:
  - Focuses on multi-robot collaborative scheduling, team task re-allocation, and shared embodiment profiles.
  - In inspected text, it does not isolate single-robot failure memory validity boundaries under costmap invalidation rules.

---

## 8. RoboMemory: A Brain-inspired Multi-memory Agentic Framework for Interactive Environmental Learning in Physical Embodied Systems
- **arXiv ID**: [2508.01415](https://arxiv.org/abs/2508.01415) (Version read: v1, Aug 2025)
- **Authors**: Mingcong Lei, Honghao Cai, Yuyuan Yang, Yimou Wu, Jinke Ren, Zezhou Cui, Liangchen Tan, Junkun Hong, Gehan Hu, Shuangyu Zhu, Shaohan Jiang, Ge Wang, Junyuan Tan, Zhenglin Wan, Zheng Li, Zhen Li, Shuguang Cui, Yiming Zhao, Yatong Han
- **Code Repository**: UNKNOWN (Paper does not provide a public code link as of v1; paper license: CC-BY-NC-SA-4.0)
- **Inspected Sections**:
  - Section 3 (RoboMemory Framework, pp. 3-6): Multi-memory architecture comprising Working Memory, Spatial Memory (topological graphs), Procedural Memory, Episodic Memory, and Semantic Memory.
  - Section 4.1.2 (Settings & Baselines, pp. 6-7): Compares against closed-source VLMs (GPT-4o, Claude3.5-Sonnet, Gemini-2.0-flash), open-source VLMs (LLaMA-3.2-90B-Vision, InternVL-3-72B), and agent frameworks (Reflexion, Voyager, Cradle). Evaluated using Qwen2.5-VL-72b-Ins backbone.
  - Section 4.1.1 & 4.5 (Benchmarks & Real-world, pp. 6, 9-10): EmbodiedBench (EB-ALFRED, EB-Habitat) and real-world indoor mobile manipulation.
- **Key Evidence on Scope & Limitations**:
  - Explores comprehensive brain-inspired multi-memory frameworks for lifelong embodied learning.
  - In inspected text (Sec. 3-4), explicit postcondition verifier isolation and costmap-grounded expiration rules under dynamic layout shifts were not investigated.
