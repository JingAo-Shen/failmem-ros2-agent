# 失败约束生命周期核心语义规范 (Constraint Semantics Specification)

> **设计定位与规范声明**：
> 本文档正式定义“条件化失败约束记忆”的核心抽象模型。
> 坚决杜绝“把偶发报错当永久规则”、“环境任何细微变化导致全盘失效”、“守旧死锁剥夺探索权”等工程缺陷。
> 严格解耦**规则有效性**、**当前适用性**与**单次动作执行结果**三个对象，通过确定性状态转移表与反例集提供严格的理论与逻辑支撑。

---

## 一、三层核心对象的形式化解耦

在过往的错误实现与朴素反思方案中，往往将“规则是否成立”、“当前是否生效”和“刚才这次尝试是否成功”混为一谈。本方案必须严格解耦以下三个独立对象：

```
┌───────────────────────────────────────────────────────────────────────────────────┐
│ 1. 规则有效性 (Rule Validity)                                                     │
│    命题：“在条件 P 成立的前提下，执行动作 A 会导致失败 E”是否具备经验证据支撑？        │
│    状态空间: {CANDIDATE, SUPPORTED, CONTRADICTED, RETIRED}                        │
└─────────────────────────────────────────┬─────────────────────────────────────────┘
                                          │ 约束库持有
                                          ▼
┌───────────────────────────────────────────────────────────────────────────────────┐
│ 2. 当前适用性 (Current Applicability)                                             │
│    命题：在当前决策时刻 t，环境的实际观测指纹是否满足条件 P？观测是否足够新鲜？        │
│    状态空间: {APPLICABLE, NOT_APPLICABLE, UNKNOWN}                                │
└─────────────────────────────────────────┬─────────────────────────────────────────┘
                                          │ 指导动作门禁
                                          ▼
┌───────────────────────────────────────────────────────────────────────────────────┐
│ 3. 单次动作执行结果 (Action Execution Outcome)                                    │
│    事件：在步骤 t 实际执行了动作 A，观察到环境返回结果 O（SUCCESS 或 FAILED）          │
│    作用：根据此时的 Applicability，作为反馈证据更新 Rule Validity                      │
└───────────────────────────────────────────────────────────────────────────────────┘
```

### 对象 1：规则有效性 (Rule Validity)
- **定义**：一条因果约束命题 $R = \langle \text{ID}, A, P, E \rangle$ 在认知库中的置信状态。
  - $A$: 受约束的动作特征（如 `bind_port(8080)` 或 `open_file('/etc/app.conf', 'w')`）；
  - $P$: 约束生效的必要前置谓词集合（如 `[is_port_occupied(8080) == True]`）；
  - $E$: 预期失败错误特征（如 `EADDRINUSE` 或 `EACCES`）。
- **状态集合**：
  - `CANDIDATE` (候选规则)：从单次偶发失败中初步提炼，尚未达到最小复现支持度或因果置信阈值；
  - `SUPPORTED` (已证实规则)：在测试范围内获得了多次独立且确定性的环境失败证据支持；
  - `CONTRADICTED` (被反驳规则)：在严格确认 $P$ 成立的前提下执行 $A$，动作却成功或返回了与 $E$ 矛盾的结果；
  - `RETIRED` (已退役/归档规则)：累积反驳证据超标、底层运行环境发生不兼容大版本升级、或被更精确的规则兼并。

### 对象 2：当前适用性 (Current Applicability)
- **定义**：在具体任务执行步骤 $t$ 下，根据**最新的有效环境观测**，判定规则的前置谓词集合 $P$ 是否在当前生效。
- **状态集合**：
  - `APPLICABLE` (当前适用)：$P$ 中包含的所有必要谓词，根据在新鲜度窗口 $\Delta t \le \text{TTL}$ 内的明确观测，**全部确认成立**。
    $\implies$ 触发决策通道门禁，禁止执行 $A$ 或触发重规划；
  - `NOT_APPLICABLE` (当前不适用)：$P$ 中至少有一个核心必要谓词，根据在新鲜度窗口内的明确观测，**确认不成立**（例如端口已处于监听关闭状态）。
    $\implies$ 约束门禁释放，允许执行 $A$；
  - `UNKNOWN` (适用性未知)：$P$ 中的谓词从未被探测，或上一次观测的时间已超过生存时间（$\Delta t > \text{TTL}$），无法确定环境是否发生隐式跃迁。
    $\implies$ **严禁当作 APPLICABLE 或 NOT_APPLICABLE**！必须触发观测探针，或在试探模式下按标准探索推进。

### 对象 3：单次动作执行结果 (Action Execution Outcome)
- **定义**：步骤 $t$ 上执行动作 $A$ 后物理环境返回的确定性信号 $O_t \in \{\text{SUCCESS}, \text{FAILED}(e)\}$。
- **证据效力**：执行结果 $O_t$ 对规则有效性 $R$ 的反向修正作用，**严格受制于执行发生时的当前适用性状态**（详见下节转移表）。

---

## 二、状态转移表与因果判定矩阵

### 表 1：环境观测新鲜度与适用性求值表 (Applicability Evaluation)

| 必要谓词观测状态 ($P$) | 观测时间差 $\Delta t$ 与 TTL 关系 | 当前适用性判定 (Applicability) | 动作调度与决策通道行为 |
| :--- | :--- | :---: | :--- |
| 全部谓词明确满足 (True) | $\Delta t \le \text{TTL}$ (新鲜) | **`APPLICABLE`** | **本地拦截门禁激活**：驳回动作提议，提示规划器选择替代路径。 |
| 至少一个必要谓词被明确否定 (False) | $\Delta t \le \text{TTL}$ (新鲜) | **`NOT_APPLICABLE`** | **门禁放行**：前置阻碍已解除，允许规划器正常执行该动作。 |
| 任一必要谓词未曾观测 (None) | 任意 | **`UNKNOWN`** | **触发探针优先**：要求智能体先行执行只读探测命令确认状态。 |
| 谓词曾满足，但观测已过期 | $\Delta t > \text{TTL}$ (陈旧) | **`UNKNOWN`** | **触发探测或保护性试探**：不允许直接硬阻断。 |

---

### 表 2：动作执行反馈与规则有效性状态转移矩阵 (Validity State Transitions)

当智能体在步骤 $t$ 实际执行了动作 $A$（可能由试探探索、探针尝试或门禁放行触发），观察到真实结果 $O_t$：

| 当前规则有效性 | 执行前适用性判定 | 实际执行结果 ($O_t$) | 下一规则有效性 | 证据判定理由与科研逻辑 |
| :--- | :---: | :---: | :---: | :--- |
| **`CANDIDATE`** | `APPLICABLE` | 失败且特征符合 $E$ | $\to$ **`SUPPORTED`** | **因果复现确立**：在确认前置条件成立下复现了失败，提炼为受支持规则。 |
| **`CANDIDATE`** | `APPLICABLE` | 成功 (SUCCESS) | $\to$ **`RETIRED`** | **候选假说排除**：原以为不可行，但确认前置条件成立下动作成功，规则纯属假象。 |
| **`CANDIDATE`** | `UNKNOWN` | 失败 (偶发/超时) | 维持 **`CANDIDATE`** | **证据依然不足**：环境前置未锁死，不能过早上升为正式规则，仅记录观测。 |
| **`SUPPORTED`** | `APPLICABLE` | 失败且特征符合 $E$ | 维持 **`SUPPORTED`** | **规则持续稳固**：加深证据权重，更新时间戳。 |
| **`SUPPORTED`** | `APPLICABLE` | **成功 (SUCCESS)** | $\to$ **`CONTRADICTED`** | **出现直接反证**：在环境满足阻碍前提下居然成功了，规则被证伪/存在未发现的变量。 |
| **`SUPPORTED`** | **`NOT_APPLICABLE`** | **成功 (SUCCESS)** | 维持 **`SUPPORTED`** | **逻辑正常推论（非反证！）**：前置阻碍本就不成立，动作成功理所应当，规则依旧有效！ |
| **`SUPPORTED`** | `NOT_APPLICABLE` | 失败且特征不符合 $E$ | 维持 **`SUPPORTED`** | **独立新故障**：在其他条件下遇到其他错误，与本条规则无关，创建新 Candidate。 |
| **`CONTRADICTED`**| `APPLICABLE` | 再次成功 (SUCCESS) | $\to$ **`RETIRED`** | **反证确认超标**：规则彻底退役并归档，解除对系统的后续干扰。 |
| **`CONTRADICTED`**| `APPLICABLE` | 失败且特征符合 $E$ | 维持 **`CONTRADICTED`** | 存在高阶不确定性，标记为不稳定规则，降级为试探监控。 |

---

## 三、六大核心语义不变量与反例剖析 (Core Invariants & Counterexamples)

为彻底解决 Agent 记忆系统中常见的逻辑混乱，本规范确立以下 6 项不可动摇的因果语义约束：

### 不变量 1：前提不成立时执行成功，绝不能作为规则被反驳的证据
- **逻辑原理**：命题 $P \implies \text{Fail}$ 在 $\neg P$ 时（前提为假），无论结论为真或假，原命题均为真（vacuous truth）。
- **具体场景**：
  - 规则 $R$: “当端口 8080 被占用 ($P$) 时，绑定端口 8080 ($A$) 会失败 ($E$)”。
  - 演进：前序动作杀死了占用 8080 的进程，探针观测到 `is_port_occupied(8080) == False`（即 $P$ 不成立，当前适用性为 `NOT_APPLICABLE`）。
  - 动作：智能体执行 `bind_port(8080)`，操作返回 `SUCCESS`。
- **错误做法**：将这次 `SUCCESS` 记录为规则 $R$ 的反证，导致规则 $R$ 状态变为 `CONTRADICTED` 并退役。后续一旦新进程再次占用 8080，智能体再次踩坑！
- **正确语义**：适用性为 `NOT_APPLICABLE` 时的成功，是**因果链条的必然预期**。规则 $R$ 的有效性必须保持 `SUPPORTED`，唯独当前适用性在阻碍消除期间为 `NOT_APPLICABLE`。

---

### 不变量 2：环境指纹的无关属性变化，绝不使规则失效（相关谓词解耦）
- **逻辑原理**：约束的匹配必须且仅必须针对与失败有因果关系的**核心谓词子集**，严禁使用全环境快照哈希。
- **具体场景**：
  - 规则 $R$ 的核心前置谓词是 `[port_8080_occupied == True]`。
  - 初始失败时，占用 8080 端口的进程名是 `nginx`，PID 是 1024。
  - 稍后系统重启，占用 8080 端口的变成了一个内部测试脚本 `python server.py`，PID 是 2048。
- **错误做法**：采用全环境哈希或全量键值比对。发现 `process_name != nginx` 或 `pid != 1024`，判定环境指纹失配，规则自动失效，直接调用 `bind_port(8080)` 触发崩溃。
- **正确语义**：规则前置条件仅绑定 `port_8080_occupied == True`。进程名与 PID 属于无关属性（Irrelevant Attributes），不参与适用性判定。当前适用性依然为 `APPLICABLE`。

---

### 不变量 3：单次偶发超时或非确定性故障，严禁固化为永久禁止规则
- **逻辑原理**：缺少确定性错误签名与状态特征的失败，无法确立因果闭环。
- **具体场景**：
  - 智能体执行 `curl http://api.internal/health`，由于瞬时负载波动或网络抖动，命令在 5 秒时超时（Timeout）。
- **错误做法**：立即生成一条强约束 `[curl http://api.internal/health is forbidden forever]`，在后续步骤中彻底封死健康检查接口。
- **正确语义**：
  1. 偶发超时、SIGKILL 或退出码非因果确定性的事件，直接被**拒识门禁 (Abstention Gate)** 拦截；
  2. 哪怕进入记忆，状态仅为 `CANDIDATE` 且置信度极低，单次超时**绝对不能跃迁为 `SUPPORTED`**；
  3. 后续重规划允许重试，只有连续 $M$ 次且伴随确定性状态时才允许深入诊断。

---

### 不变量 4：适用性“UNKNOWN”既不能当作满足，也不能当作违反
- **逻辑原理**：未知状态代表信息熵未消除，非黑即白判定必然导致假阳性或假阴性。
- **具体场景**：
  - 智能体需要修改 `/var/log/app.log`，存在历史约束：`[file_is_readonly == True -> write fails]`。
  - 当前由于已经执行了 10 步其他操作，距离上次 `ls -l` 检查已过去 5 分钟，观测缓存已过 TTL；或当前根本没有该文件的权限元数据。
- **错误做法 A (冒进)**：将 `UNKNOWN` 当作 `NOT_APPLICABLE`，盲目执行写操作，导致权限被拒与试错成本激增。
- **错误做法 B (保守)**：将 `UNKNOWN` 当作 `APPLICABLE`，永久禁止碰这个文件，即便 root 早已修复了权限，智能体依然死锁。
- **正确语义**：
  1. 当前适用性标记为 `UNKNOWN`；
  2. 决策层将 `UNKNOWN` 路由至**只读探针机制**（主动生成 `stat /var/log/app.log` 命令消除未知）；
  3. 若探针成本过高，则在允许的试探限额内执行单次安全尝试以刷新状态。

---

### 不变量 5：严格限制被约束动作，不能永远剥夺获取反证的机会（防饥饿与探测机制）
- **逻辑原理**：若一条规则一旦进入 `SUPPORTED`，系统就 100% 永久拦截该动作且不再关注，当外部环境发生静默修复时，系统将永远无法得知规则已被颠覆，陷入**“自证预言式守旧死锁”**。
- **解决机制**：
  1. **主动探针刷新 (Active Invalidation Probe)**：当底层环境发生明确的跃迁事件（例如检测到用户执行了 `chmod`、安装了补丁包、或者经过了 $N$ 步任务调度），智能体对活跃约束的前置谓词进行轻量级主动探针检测；
  2. **试探期宽限 (Probationary Trial)**：当探针发现谓词变化时，规则适用性从 `APPLICABLE` 转为 `NOT_APPLICABLE`，释放动作拦截；
  3. **反证捕获**：此时动作若成功，原约束平滑失效；此时动作若失败，则加深该约束在当前状态下的边界描述。

---

### 不变量 6：结构化证据指纹与局部绑定
- **结构模板**：
  ```json
  {
    "rule_id": "rule_port_8080_bind_fail",
    "action_signature": {
      "command": "python -m http.server 8080",
      "target_resource": "port:8080"
    },
    "precondition_predicates": [
      {
        "probe_command": "ss -lnt 'sport = :8080'",
        "match_pattern": "LISTEN",
        "expected_value": true,
        "is_essential": true
      }
    ],
    "failure_evidence": {
      "error_code": 98,
      "stderr_signature": "Address already in use"
    },
    "validity_state": "SUPPORTED",
    "ttl_seconds": 30.0,
    "last_supported_timestamp": 1728560000.0,
    "support_count": 3,
    "contradict_count": 0
  }
  ```

---

## 四、语义规范执行伪代码逻辑 (Decoupled Evaluation Logic)

```python
class ConstraintLifecycleManager:
    def evaluate_applicability(self, rule: Rule, current_env_obs: dict, current_time: float) -> str:
        """评估规则在当前决策时刻的适用性状态"""
        if rule.validity_state in ["CONTRADICTED", "RETIRED"]:
            return "NOT_APPLICABLE"
            
        all_predicates_matched = True
        has_unknown = False
        
        for pred in rule.precondition_predicates:
            obs_entry = current_env_obs.get(pred.key)
            if obs_entry is None or (current_time - obs_entry.timestamp > rule.ttl_seconds):
                has_unknown = True
                break
            if obs_entry.value != pred.expected_value:
                all_predicates_matched = False
                break
                
        if has_unknown:
            return "UNKNOWN"
        elif all_predicates_matched:
            return "APPLICABLE"
        else:
            return "NOT_APPLICABLE"

    def record_action_outcome(self, rule: Rule, prior_applicability: str, success: bool, error_info: dict):
        """根据先验适用性与实际动作结果更新有效性"""
        if prior_applicability == "APPLICABLE":
            if success:
                # 在确认阻碍存在时执行成功 -> 核心反证！
                rule.contradict_count += 1
                if rule.contradict_count >= 2:
                    rule.validity_state = "RETIRED"
                else:
                    rule.validity_state = "CONTRADICTED"
            else:
                # 阻碍存在时失败且特征符合 -> 证据加固
                if error_info.get("signature") == rule.failure_evidence.get("stderr_signature"):
                    rule.support_count += 1
                    if rule.validity_state == "CANDIDATE" and rule.support_count >= 2:
                        rule.validity_state = "SUPPORTED"
                        
        elif prior_applicability == "NOT_APPLICABLE":
            if success:
                # 前提不成立时成功 -> 完全符合因果预期，绝对不是反证！
                pass
            else:
                # 前提不成立时遇到了其他失败 -> 独立事件，不影响本规则
                pass
```

---
*本规范严格界定因果约束的判定底线，杜绝任何概念混淆。*
