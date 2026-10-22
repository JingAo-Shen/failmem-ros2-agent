# 强规划器接入与离线准备操作指南 (Offline Backend Preparation Guide)

**基准 Commit**：`e87026d`  
**当前状态**：`OFFLINE_BACKEND_PREPARATION_COMPLETE`  
**核准资源消耗**：**0 环境 Episodes，0 次真实模型推理**  

---

## 1. 概述与准备目标

为解决本地小模型在科学虚拟环境（ScienceWorld）中规划能力不足的问题，本项目完成了一个轻量、解耦、支持 OpenAI 兼容接口的远程强规划器离线接入层。  
该接入层严格遵循以下防御性安全原则：
- **默认网络硬拦截**：默认使用 Mock 传输层，禁止任何未授权的网络请求；
- **配置缺失即刻失败**：配置不完整时直接抛出异常退出，严禁悄默回退到本地模型；
- **零密钥存储**：API Key 仅通过指定的系统环境变量读取，严禁出现在代码、日志、配置文件或提交记录中；
- **真实 Token 记账**：当远程供应商不返回 token 统计字段时，统一记为 `"unknown"`，杜绝假 0 污染。

---

## 2. 已通过离线测试验证的行为清单 (Verified Behaviors)

通过执行 `pytest research/condition_revision/tests`（25/25 测试项全部通过），以下行为已获严格验证：

| 行为类别 | 验证内容 | 对应测试函数 |
| :--- | :--- | :--- |
| **动作模板装配** | `prompt_mode="action_templates"` 正确将 ScienceWorld 27 个原生动作模板无截断地注入用户提示词，带有固定免责声明，且不包含人工候选推荐动作。 | `test_prompt_and_templates_reach_payload` |
| **原生直通动作提取** | 模型返回的 JSON 动作字段被准确提取，仅剥离首尾空白字符，不做同义转换或候选替换。 | `test_native_action_extraction_and_whitespace_trimming` |
| **格式容错与重试** | 模型首次返回非合法 JSON 时，客户端自动重试 1 次并注入纠偏提示词，在元数据中如实记录重试事件。 | `test_invalid_json_retry_and_logging` |
| **彻底失效降级** | 重试后仍无法解析 JSON 时，返回包含 `parse_error: True` 的降级字典并记录原始文本，保障调用链路不崩溃。 | `test_invalid_json_unrecovered_fallback` |
| **超时安全拦截** | 当网络或 Mock 层响应超出指定 `timeout` 阈值时，抛出 `RemotePlannerTimeoutError`。 | `test_timeout_handling` |
| **默认网络阻断** | 当 `allow_live_network=False` 且未提供 Mock 时，拦截一切外网访问并抛出 `NetworkAccessBlockedError`。 | `test_default_network_block` |
| **快错与零本地回退** | 缺失 endpoint、model_id、环境变量名或环境变量为空时，立即抛出 `ConfigurationError`，不引入本地模型。 | `test_incomplete_config_fail_fast_without_local_fallback` |
| **真实 Token 记账** | 供应商返回完整 `usage` 时如实累加；若不返回或为 `None`，标记为 `"unknown"` 而非 0。 | `test_token_usage_accounting` |

---

## 3. 待实机验证项 (Pending Live-Runtime Validations)

在未来获得正式实验授权后，需要首轮实机测试验证的项目：
1. **端点连通性与鉴权**：验证实际远程服务商对 Bearer Token 的鉴权有效性与 HTTP 200 返回；
2. **长上下文遵循率**：验证强规划器在多轮历史（包含观测、任务描述与 27 个动作模板）下的有效 JSON 生成概率；
3. **真实动作语法有效性**：验证强规划器在没有人工候选动作列表提示时，自主组合 `teleport <room>`、`focus on <obj>`、`pick up <obj>` 等合法动作的准确率；
4. **延迟与费用统计核实**：核验实际往返延迟（RTT）与账单 Token 计费。

---

## 4. 实测前必须配置的参数与步骤 (Pre-Execution Requirements)

在开展任何真实网络评测前，操作人员必须显式完成以下三项设置：

### 第一步：设置环境变量（严禁写入文件）
```bash
# 示例：以具体的服务商环境变量为准
export REMOTE_PLANNER_API_KEY="sk-xxxxxxxxxxxxxxxxxxxxxxxx"
```

### 第二步：创建实际配置文件
参考 `research/condition_revision/remote_planner_config.example.json`，创建 `research/condition_revision/remote_planner_config.json`（该文件已在 `.gitignore` 中被忽略）：
```json
{
  "endpoint": "https://api.openai.com/v1/chat/completions",
  "model_id": "gpt-4o",
  "api_key_env_var": "REMOTE_PLANNER_API_KEY",
  "timeout": 60.0,
  "allow_live_network": true,
  "generation_params": {
    "temperature": 0.0,
    "top_p": 1.0,
    "max_tokens": 256
  }
}
```

### 第三步：确认开启显式网络许可
`allow_live_network` 必须显式置为 `true`。

---

## 5. 成本硬上限与准入测试预算红线 (Cost Caps & Hard Limits)

在开启实测时，必须在代码与执行框架中施加以下硬性限制：

1. **准入轮次红线**：
   - 严格限定在 **P1 剩余的 7 个 episode** 预算以内；
   - 准入用例集固定为 6 个基准测试（如导电性与状态变化任务），不得追加多余尝试；
2. **单轮动作步数与调用上限**：
   - 每轮 episode 上限固定为 30 步；
   - 单步推理超时硬上限：60 秒；
   - 单次生成最大 token：256 tokens；
3. **经费硬上限 (Cost Cap)**：
   - 准入测试总模型开销不得超过 **$10.00 USD**；
4. **准入通过门槛 (Admission Threshold)**：
   - 6 项准入测试中至少达成 **4/6 成功**，且**必须成功完成至少 1 项长程物理状态转换任务**（如 melt 或 boil）；
   - 若未通过，立即停止后续所有实验，标记为 `REMOTE_PLANNER_ADMISSION_FAILED`，坚决不启动 P2。
