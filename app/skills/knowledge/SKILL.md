# AlphaHub 知识 LLM 规则总纲

本目录只约束 LLM 的理解、判断、归纳和生成行为。PostgreSQL CRUD、MinIO、Qdrant、Embedding、
边界重建、状态更新等确定性流程由程序负责，不属于 Skill。

规则模块：

1. `document_analysis`：理解整篇资料。
2. `chunk_planning`：判断无重叠语义 Chunk 边界。
3. `chunk_context`：补充 Chunk 脱离全文后的必要检索背景。
4. `chunk_metadata`：生成 title、summary、chunk_type。
5. `strategy_judgement`：从正式 Strategy 中选择或提出候选。
6. `tag_generation`：复用或生成知识标签。
7. `rag_answer`：严格依据召回知识回答并提供来源。

Skill 文件数量只代表规则模块数量，不代表 LLM 调用次数。同一次 LLM 调用可以同时应用多个 Skill。

