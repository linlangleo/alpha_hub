# chunk_planning

任务：根据全文 Blocks 和文档理解输出 `start_block`、`end_block` 语义边界。

规则：

- 优先保证完整规则、案例或论述的语义完整性，不按固定字符数机械切分。
- 不把多个独立主题强行合并；图片、表格保持与上下文的位置关系。
- 持久化 Chunk 不做 overlap，每个 Block 只能属于一个 Chunk。
- 边界必须覆盖全部 Blocks，按顺序连续、无遗漏、无交叉、无重复。
- LLM 只返回边界，不生成或改写正文；程序根据边界重建 `content`。
- 所有 Chunk 按 `chunk_index` 排序后应能重构解析内容。

