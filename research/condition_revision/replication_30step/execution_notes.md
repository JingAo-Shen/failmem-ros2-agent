1. 运行命令：python3 research/condition_revision/replication_30step/run_replication_30step.py
2. 实验配置：统一使用 strict 适配器，envStepLimit 与步数上限均设为 30 步；成功或 env done 时立即结束。
3. 任务与输入：R5 (曲别针 var 460 + 空 A), R6 (曲别针 var 460 + T1-B 上下文), R7 (书本 var 160 + 空 A), R8 (书本 var 160 + T4-B 上下文)。
4. 模型配置：Qwen2.5-Coder-7B-Instruct (/models/Qwen2.5-Coder-7B-Instruct)，bfloat16，贪婪解码 (do_sample=False, temperature=0.0, max_new_tokens=128)。
5. 初始状态一致性：书本任务 (R7 vs R8) 与曲别针任务 (R5 vs R6) 初始描述、观测、候选动作 100% 一致。
6. 前10步复现核对：R5 与 R3 前 10 步建议动作、执行动作与得分 100% 一致；R6 与 R4 前 10 步亦 100% 一致。
7. 运行结果：R5 在第 10 步得分 100.0 (成功)；R6 在第 22 步得分 100.0 (成功)；R7 满 30 步得分 14.0；R8 满 30 步得分 10.0。
8. 异常与资源：无环境或网络报错，模型调用数按前后差值统计共 92 次（消耗输入 88036、输出 5785 tokens），未触发解析重试。
