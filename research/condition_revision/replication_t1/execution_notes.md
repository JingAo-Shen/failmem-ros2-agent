1. 运行命令：python3 research/condition_revision/replication_t1/run_replication.py
2. 实验配置：任务 test-conductivity (var 460, T1_conductivity_paper_clip_workshop)，步数上限 10 步/episode。
3. 模型配置：Qwen2.5-Coder-7B-Instruct (/models/Qwen2.5-Coder-7B-Instruct)，bfloat16，贪婪解码 (do_sample=False, temperature=0.0, max_new_tokens=128)。
4. 代码基线版本：b67a8b1。
5. 输入说明：A 输入 extra_context 为空；B 输入从 attribution_results.json 原样读取 T1-B 的 extra_context。
6. 适配器模式：R1/R2 使用 current 适配器；R3/R4 使用 strict 严格适配器（仅允许大小写/首尾空格及同义 place/put...in... 转换，其余均回退 look around）。
7. 初始状态校验：R1~R4 的 task_desc、initial observation 及初始 25 个候选动作列表 100% 一致 (initial_state_consistent: True)。
8. 异常情况：无环境或网络报错，无模型解析异常；程序正常退出并保存全量数据（环境 close 时标准 BrokenPipe 仅为 Java 进程退出信号）。
