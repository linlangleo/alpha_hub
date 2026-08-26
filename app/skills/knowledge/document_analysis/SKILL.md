# document_analysis

任务：理解整篇投资资料，输出 `document_summary`、`document_context` 和 `category`。

规则：

- 忠于原文，不补充原文不存在的数字、条件、结论或金融常识。
- 不把案例扩展成通用投资规则，不改变原文确定性程度。
- `document_summary` 用于快速阅读整篇资料。
- `document_context` 用于后续 Chunk 分析，应包含 `topic`、`core_scope`、`key_terms`、
  `important_background`、`strategy_code`。
- 特殊术语及其原文定义尽量写入 `key_terms`。
- 不得创建正式 Strategy。

