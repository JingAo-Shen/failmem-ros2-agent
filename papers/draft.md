# Verified Failure Memory for Cross-Episode Robot Recovery

> **[R0 AUDIT RETRACTION NOTICE / 真实性审计撤回声明]**  
> **状态**: **DRAFT RETRACTED / PENDING REAL EXPERIMENT (初稿结论已撤回，待真实实验)**  
> **审计依据**: 参见 [`reports/R0-evidence-audit.md`](../reports/R0-evidence-audit.md) 与 [`reports/R0-review.md`](../reports/R0-review.md)。  
> **撤回原因**:
> 1. 本文所有实验数据源于 60 行轻量 NumPy 2D 坐标 mock 状态机，未真正接入 ROS2/Gazebo/Nav2 物理仿真环境，亦未调用任何 LLM 规划模型。
> 2. 摘要中声称的 “86.7% 恢复成功率”、“相对基线提高 53.4 个百分点”、“重复失败率从 18.2% 降到 0.0%” 纯属虚构，在已有实验日志中无任何原始数据支撑（详见审计报告 C1-C3 项）。
> 3. 表 1 中的四象限结果均为 83.3%，系因验证器未接入逻辑、单步后故障自动消失导致盲重试全部假通过，且指标混淆了总任务通过率与恢复率。
> 4. 原文保留用于历史科研审计对照，文中所有数值已置为待证实占位符 `[TO_BE_VERIFIED]`。

**Anonymous Authors**

---

## Abstract
Mobile robots deployed in dynamic indoor environments frequently encounter unforeseen execution failures such as temporary path obstructions, moving human obstacles, and localization action timeouts. Traditional verbal self-reflection mechanisms iterate naively within a single episode, often repeating invalid actions and lacking systematic cross-episode persistence. In this work, we propose **FailMem (Verified Failure Memory)**, a structured failure indexing and recovery framework for mobile robots. FailMem formalizes failure episodes into verifiable tuples comprising symptom signatures, causal hypotheses, physical recovery actions, and costmap-grounded expiration rules. Evaluated across 180 fault-injected navigation episodes across six unseen spatial layouts over three random seeds *(Note: currently synthetic 2D mock coordinates; physical simulation pending P1)*, FailMem targets improving fault recovery success rate and reducing repeat failure rate. *(Historical ungrounded claim retracted: ~~achieves an 86.7% fault recovery success rate, outperforming the memory-less baseline by +53.4 percentage points while reducing repeat failure rate from 18.2% to 0.0%~~; current status: `[UNVERIFIED - RETRACTED UNDER R0]`).*

---

## 1. Introduction & Methodology
Embodied robots operating with ROS2 / Nav2 encounter physical failures requiring structured recovery actions (e.g., clearing costmaps, dynamic rerouting). FailMem introduces:
1. *Verifiable Recovery Actions*: Only physical actions verified via sensor postconditions are committed to memory.
2. *Spatial-Temporal Expiry Rules*: Invalidation hooks trigger when the navigation costmap is updated, preventing the reuse of obsolete obstacle assumptions.

*(System implementation note: true ROS2/Nav2 node integration and verifiable postcondition execution are scheduled for P1).*

---

## 2. Experimental Results (Historical Mock Run — Invalid Evaluation)
Table 1: Four-Quadrant Evaluation on 180 Fault Episodes Across 3 Seeds *(Retracted Mock Artifact)*:

| Method Configuration | Memory | Verifier | Recovery Rate (%) | Repeat Failure Rate (%) |
| :--- | :--- | :--- | :--- | :--- |
| **MemOFF + VerOFF** | $\times$ | $\times$ | *[83.3% - Mock artifact]* | *[0.0% - Mock artifact]* |
| **MemOFF + VerON** | $\times$ | $\checkmark$ | *[83.3% - Mock artifact]* | *[0.0% - Mock artifact]* |
| **MemON + VerOFF** | $\checkmark$ | $\times$ | *[83.3% - Mock artifact]* | *[0.0% - Mock artifact]* |
| **FailMem (Full)** | $\checkmark$ | $\checkmark$ | *[83.3% - Mock artifact]* | *[0.0% - Mock artifact]* |

*Audit Finding on Table 1: In the mock environment, all four configurations achieved identical 83.3% pass rates because use_verifier was a no-op parameter, the fault automatically vanished on the next step allowing blind retries to succeed, and all 30 failures were solely caused by distance to goal exceeding the arbitrary 6-step limit. True evaluation will be conducted under frozen protocol P3.*

---

## 3. Conclusion & Next Steps
FailMem provides a structured conceptual formulation for failure memory and expiration in autonomous mobile robot task recovery. Formal validation in realistic ROS2/Nav2 simulation environments with real LLM planners will be executed in phases P0-P4.
