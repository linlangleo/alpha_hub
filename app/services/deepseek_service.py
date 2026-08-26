import json
from typing import Any

from openai import OpenAI

from app.services.skill_service import knowledge_skill_service


class DeepSeekService:
    """Single boundary for all DeepSeek calls and Skill composition."""

    def __init__(self, api_key: str, base_url: str, model: str, timeout: float,
                 retry: int, max_input_chars: int, max_output_tokens: int) -> None:
        self.enabled = bool(api_key)
        self.model = model
        self.retry = max(1, retry)
        self.max_input_chars = max_input_chars
        self.max_output_tokens = max_output_tokens
        self.client = OpenAI(api_key=api_key or "not-configured", base_url=base_url,
                             timeout=timeout, max_retries=retry)

    def chat(self, system_prompt: str, user_prompt: str) -> str:
        self._require_enabled()
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": system_prompt},
                      {"role": "user", "content": self._validate_input(user_prompt)}],
            max_tokens=self.max_output_tokens,
        )
        return response.choices[0].message.content or ""

    def structured_chat(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        self._require_enabled()
        bounded_prompt = self._validate_input(user_prompt)
        last_error: Exception | None = None
        for _ in range(self.retry):
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": system_prompt},
                          {"role": "user", "content": bounded_prompt}],
                response_format={"type": "json_object"},
                max_tokens=self.max_output_tokens,
            )
            content = response.choices[0].message.content or ""
            try:
                result = json.loads(content)
            except json.JSONDecodeError as exc:
                last_error = exc
                continue
            if isinstance(result, dict):
                return result
            last_error = RuntimeError("DeepSeek Structured Output 顶层必须是 JSON Object")
        raise RuntimeError("DeepSeek 连续返回空内容或无法解析的 JSON") from last_error

    def analyze_document(self, document: dict[str, Any], blocks: list[dict[str, Any]],
                         strategies: list[dict[str, Any]]) -> dict[str, Any]:
        rules = knowledge_skill_service.combine(
            "document_analysis", "chunk_planning", "strategy_judgement"
        )
        schema = '''只返回 JSON：
{"document_summary":"string","document_context":{"topic":"string",
"strategy_code":"string|null","core_scope":"string","key_terms":[{"term":"string",
"definition":"string"}],"important_background":["string"]},"category":"string",
"strategy_code":"string|null","strategy_candidate":{"name":"string","confidence":0.0}|null,
"chunks":[{"start_block":0,"end_block":1}]}
chunks 必须覆盖全部 block，连续、按升序、无交叉、无重复。'''
        payload = {"document": document, "blocks": blocks,
                   "formal_strategies": self._strategies(strategies)}
        return self.structured_chat(f"{rules}\n\n{schema}",
                                    json.dumps(payload, ensure_ascii=False))

    def analyze_chunk_batch(self, document_context: dict[str, Any],
                            document_strategy_code: str | None,
                            chunks: list[dict[str, Any]], strategies: list[dict[str, Any]],
                            existing_tags: list[str]) -> dict[str, Any]:
        rules = knowledge_skill_service.combine(
            "chunk_context", "chunk_metadata", "strategy_judgement", "tag_generation"
        )
        schema = '''只返回 JSON：
{"chunks":[{"chunk_index":0,"title":"string","context":"string","summary":"string",
"chunk_type":"other","strategy_code":"string|null","strategy_candidate":
{"name":"string","confidence":0.0}|null,"existing_tags":["string"],"new_tags":["string"]}]}
必须为输入中的每个 chunk_index 恰好返回一项，不得返回或改写 content。'''
        payload = {"document_context": document_context,
                   "document_strategy_code": document_strategy_code, "chunks": chunks,
                   "formal_strategies": self._strategies(strategies),
                   "existing_tags": existing_tags}
        return self.structured_chat(f"{rules}\n\n{schema}",
                                    json.dumps(payload, ensure_ascii=False))

    def regenerate_context(self, document_context: dict[str, Any],
                           strategy_code: str | None, content: str,
                           previous_context: str | None = None,
                           compress: bool = False) -> str:
        rules = knowledge_skill_service.combine("chunk_context")
        instruction = ("现有 context 超过限制。请在不新增信息的前提下重新压缩到 100 个中文字符以内。"
                       if compress else "请生成新的 context。")
        result = self.structured_chat(
            f'{rules}\n\n只返回 JSON：{{"context":"string"}}',
            json.dumps({"instruction": instruction, "document_context": document_context,
                        "strategy_code": strategy_code, "content": content,
                        "previous_context": previous_context}, ensure_ascii=False),
        )
        return str(result.get("context") or "").strip()

    def answer_knowledge(self, question: str, contexts: list[dict[str, Any]]) -> str:
        rules = knowledge_skill_service.combine("rag_answer")
        return self.chat(rules, json.dumps(
            {"question": question, "knowledge_contexts": contexts}, ensure_ascii=False
        ))

    @staticmethod
    def _strategies(strategies: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{"id": str(item["id"]), "code": item["code"], "name": item["name"],
                 "description": item.get("description")} for item in strategies
                if item.get("status") == "active"]

    def _validate_input(self, user_prompt: str) -> str:
        if len(user_prompt) > self.max_input_chars:
            raise ValueError(
                f"DeepSeek 输入超过配置上限 {self.max_input_chars} 字符，拒绝截断以避免边界丢失"
            )
        return user_prompt

    def _require_enabled(self) -> None:
        if not self.enabled:
            raise RuntimeError("DeepSeek API Key 未配置，请设置 DEEPSEEK_API_KEY")
