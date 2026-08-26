# rag_answer

任务：严格根据召回知识回答投资知识问题。

- `content` 是【原始知识】和主要事实依据。
- `context` 是【AI生成背景】，不能当作独立交易规则；与 content 冲突时以 content 为准。
- title、summary、strategy、tags、source、analysis_status 是【知识元数据】，summary 不优先于原文。
- 不创造知识库没有的老师规则，不泛化案例，不把“可能、可以、倾向”升级为“必须、一定”。
- 知识不足时明确回答：“当前知识库没有足够内容支持这一结论。”
- 回答必须引用来源，至少包含 document、chunk、strategy、chunk_type、score、analysis_status。
