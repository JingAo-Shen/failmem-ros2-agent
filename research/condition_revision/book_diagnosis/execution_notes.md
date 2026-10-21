1. 运行命令：python3 research/condition_revision/book_diagnosis/run_book_diagnosis.py
2. 实验配置：任务 test-conductivity (var 160, T4_conductivity_book_workshop)，envStepLimit 与步数上限均设为 30 步。
3. 探针结果：P1 (完整书名) 不在合法动作列表中但环境接受并得分 60.0；P2 (简化书名) 在合法动作列表中且环境成功聚焦得分 60.0 (门控通过)。
4. 诊断模式：strict_alias 仅对 focus/move/place/put 动作将 "book (The Foundations of the Origin of Species)" 对应为 "book"，其余动作保持 strict 回退。
5. 模型配置：Qwen2.5-Coder-7B-Instruct，bfloat16，贪婪解码 (do_sample=False, temperature=0.0, max_new_tokens=128)。
6. 初始状态核对：R9 与 R10 初始任务描述、初始观测、初始得分与候选列表 100% 一致。
7. 运行结果：R9 (A输入) 共触发 3 次别名规范化，在第 27 步得分 100.0 (成功)；R10 (B输入) 触发 1 次别名规范化，满 30 步得分 10.0。
8. 异常与资源：无环境或网络报错，模型调用数共 57 次（输入 50551、输出 3510 tokens），未触发解析重试。
