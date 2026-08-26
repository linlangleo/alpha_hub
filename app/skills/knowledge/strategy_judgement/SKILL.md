# strategy_judgement

任务：判断文档或 Chunk 是否属于输入中的正式 Strategy。

- `strategy_code` 只能从输入的 active Strategy 列表选择，不匹配时返回 `null`。
- 明确发现新策略时只能返回 `strategy_candidate`，不得创建正式 Strategy。
- 文档 Strategy 是 Chunk 默认值；Chunk 仅在明确属于其他策略、通用知识或新候选时覆盖。
- 通用仓位、风险、宏观等知识允许不属于任何 Strategy。
- 案例偶然出现策略名称不等于整篇资料属于该策略。

