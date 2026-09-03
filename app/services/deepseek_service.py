import base64
import json
import logging
from time import perf_counter
from typing import Any

from openai import OpenAI

from app.services.skill_service import knowledge_skill_service


logger = logging.getLogger(__name__)
RESPONSE_PREVIEW_CHARS = 1000
REASONING_PREVIEW_CHARS = 2000
RAW_RESPONSE_PREVIEW_CHARS = 10000


class DeepSeekStructuredOutputError(RuntimeError):
    """Carries safe diagnostics for a failed DeepSeek structured response."""

    def __init__(
        self,
        message: str,
        *,
        error_type: str,
        operation: str,
        model: str,
        attempt: int,
        response_id: str | None = None,
        finish_reason: str | None = None,
        response_chars: int = 0,
        reasoning_chars: int = 0,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        total_tokens: int | None = None,
        json_error: str | None = None,
        json_line: int | None = None,
        json_column: int | None = None,
        exception_type: str | None = None,
        technical_message: str | None = None,
    ) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.operation = operation
        self.model = model
        self.attempt = attempt
        self.response_id = response_id
        self.finish_reason = finish_reason
        self.response_chars = response_chars
        self.reasoning_chars = reasoning_chars
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = total_tokens
        self.json_error = json_error
        self.json_line = json_line
        self.json_column = json_column
        self.exception_type = exception_type
        self.technical_message = technical_message

    def as_detail(self) -> dict[str, Any]:
        return {
            "error_type": self.error_type,
            "operation": self.operation,
            "model": self.model,
            "attempt": self.attempt,
            "response_id": self.response_id,
            "finish_reason": self.finish_reason,
            "response_chars": self.response_chars,
            "reasoning_chars": self.reasoning_chars,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "json_error": self.json_error,
            "json_line": self.json_line,
            "json_column": self.json_column,
            "exception_type": self.exception_type,
            "technical_message": self.technical_message,
        }


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

    def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str | None = None,
        operation: str = "chat",
    ) -> str:
        self._require_enabled()
        bounded_prompt = self._validate_input(user_prompt)
        selected_model = model or self.model
        started_at = perf_counter()
        logger.info(
            "DeepSeek request started operation=%s model=%s input_chars=%s",
            operation,
            selected_model,
            len(bounded_prompt),
        )
        response = self.client.chat.completions.create(
            model=selected_model,
            messages=[{"role": "system", "content": system_prompt},
                      {"role": "user", "content": bounded_prompt}],
            max_tokens=self.max_output_tokens,
        )
        choice = response.choices[0]
        content = choice.message.content or ""
        logger.info(
            "DeepSeek request succeeded operation=%s model=%s response_id=%s "
            "finish_reason=%s response_chars=%s attempt=1 duration_ms=%s",
            operation,
            selected_model,
            str(getattr(response, "id", "") or "") or None,
            str(getattr(choice, "finish_reason", "") or "") or None,
            len(content),
            round((perf_counter() - started_at) * 1000),
        )
        return content

    def structured_chat(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str | None = None,
        operation: str = "structured_chat",
    ) -> dict[str, Any]:
        self._require_enabled()
        bounded_prompt = self._validate_input(user_prompt)
        selected_model = model or self.model
        return self._structured_request(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": bounded_prompt},
            ],
            model=selected_model,
            operation=operation,
            input_chars=len(bounded_prompt),
        )

    def _structured_request(
        self,
        messages: list[dict[str, Any]],
        model: str,
        operation: str,
        input_chars: int,
    ) -> dict[str, Any]:
        started_at = perf_counter()
        logger.info(
            "DeepSeek request started operation=%s model=%s input_chars=%s "
            "max_attempts=%s",
            operation,
            model,
            input_chars,
            self.retry,
        )
        last_error: DeepSeekStructuredOutputError | None = None
        last_cause: Exception | None = None
        for attempt in range(1, self.retry + 1):
            try:
                response = self.client.chat.completions.create(
                    model=model,
                    messages=messages,
                    response_format={"type": "json_object"},
                    max_tokens=self.max_output_tokens,
                )
            except Exception as exc:
                raise DeepSeekStructuredOutputError(
                    "DeepSeek API 调用失败",
                    error_type="API_REQUEST_FAILED",
                    operation=operation,
                    model=model,
                    attempt=attempt,
                    exception_type=type(exc).__name__,
                    technical_message=str(exc)[:1000],
                ) from exc

            choice = response.choices[0]
            content = choice.message.content or ""
            reasoning_content = str(
                getattr(choice.message, "reasoning_content", "") or ""
            )
            usage = self._object_dict(getattr(response, "usage", None))
            prompt_tokens = self._optional_int(usage.get("prompt_tokens"))
            completion_tokens = self._optional_int(usage.get("completion_tokens"))
            total_tokens = self._optional_int(usage.get("total_tokens"))
            response_id = str(getattr(response, "id", "") or "") or None
            finish_reason = str(getattr(choice, "finish_reason", "") or "") or None
            if finish_reason == "length":
                last_error = DeepSeekStructuredOutputError(
                    "DeepSeek 返回内容被截断",
                    error_type="OUTPUT_TRUNCATED",
                    operation=operation,
                    model=model,
                    attempt=attempt,
                    response_id=response_id,
                    finish_reason=finish_reason,
                    response_chars=len(content),
                    reasoning_chars=len(reasoning_content),
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                )
                last_cause = None
            elif not content.strip():
                last_error = DeepSeekStructuredOutputError(
                    "DeepSeek 返回空内容",
                    error_type="EMPTY_RESPONSE",
                    operation=operation,
                    model=model,
                    attempt=attempt,
                    response_id=response_id,
                    finish_reason=finish_reason,
                    response_chars=len(content),
                    reasoning_chars=len(reasoning_content),
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                )
                last_cause = None
            else:
                try:
                    result = json.loads(content)
                except json.JSONDecodeError as exc:
                    last_error = DeepSeekStructuredOutputError(
                        "DeepSeek 返回内容不是合法 JSON",
                        error_type="INVALID_JSON",
                        operation=operation,
                        model=model,
                        attempt=attempt,
                        response_id=response_id,
                        finish_reason=finish_reason,
                        response_chars=len(content),
                        reasoning_chars=len(reasoning_content),
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        total_tokens=total_tokens,
                        json_error=exc.msg,
                        json_line=exc.lineno,
                        json_column=exc.colno,
                    )
                    last_cause = exc
                else:
                    if isinstance(result, dict):
                        logger.info(
                            "DeepSeek request succeeded operation=%s model=%s "
                            "response_id=%s finish_reason=%s response_chars=%s "
                            "attempt=%s duration_ms=%s",
                            operation,
                            model,
                            response_id,
                            finish_reason,
                            len(content),
                            attempt,
                            round((perf_counter() - started_at) * 1000),
                        )
                        return result
                    last_error = DeepSeekStructuredOutputError(
                        "DeepSeek 返回 JSON 的顶层不是对象",
                        error_type="INVALID_JSON_ROOT",
                        operation=operation,
                        model=model,
                        attempt=attempt,
                        response_id=response_id,
                        finish_reason=finish_reason,
                        response_chars=len(content),
                        reasoning_chars=len(reasoning_content),
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        total_tokens=total_tokens,
                    )
                    last_cause = None

            logger.warning(
                "DeepSeek structured output failed operation=%s model=%s "
                "attempt=%s/%s error_type=%s response_id=%s finish_reason=%s "
                "response_chars=%s json_error=%s response_preview=%r",
                operation,
                model,
                attempt,
                self.retry,
                last_error.error_type,
                response_id,
                finish_reason,
                len(content),
                last_error.json_error,
                content[:RESPONSE_PREVIEW_CHARS],
            )
            logger.warning(
                "DeepSeek failed response usage operation=%s attempt=%s usage=%s",
                operation,
                attempt,
                json.dumps(usage, ensure_ascii=False, default=str),
            )
            logger.warning(
                "DeepSeek failed response reasoning operation=%s attempt=%s "
                "reasoning_chars=%s reasoning_preview=%r",
                operation,
                attempt,
                len(reasoning_content),
                reasoning_content[:REASONING_PREVIEW_CHARS],
            )
            logger.warning(
                "DeepSeek failed raw response operation=%s attempt=%s raw_response=%s",
                operation,
                attempt,
                self._raw_response(response)[:RAW_RESPONSE_PREVIEW_CHARS],
            )

        if last_error is None:
            raise RuntimeError("DeepSeek Structured Output 处理失败")
        if last_cause is not None:
            raise last_error from last_cause
        raise last_error

    def analyze_document(
        self,
        document: dict[str, Any],
        blocks: list[dict[str, Any]],
        strategies: list[dict[str, Any]],
        model: str | None = None,
    ) -> dict[str, Any]:
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
        return self.structured_chat(
            f"{rules}\n\n{schema}",
            json.dumps(payload, ensure_ascii=False),
            model=model,
            operation="document_analysis",
        )

    def analyze_chunk_batch(self, document_context: dict[str, Any],
                            document_strategy_code: str | None,
                            chunks: list[dict[str, Any]], strategies: list[dict[str, Any]],
                            existing_tags: list[str],
                            model: str | None = None) -> dict[str, Any]:
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
        return self.structured_chat(
            f"{rules}\n\n{schema}",
            json.dumps(payload, ensure_ascii=False),
            model=model,
            operation="chunk_analysis",
        )

    def regenerate_context(self, document_context: dict[str, Any],
                           strategy_code: str | None, content: str,
                           previous_context: str | None = None,
                           compress: bool = False,
                           model: str | None = None) -> str:
        rules = knowledge_skill_service.combine("chunk_context")
        instruction = ("现有 context 超过限制。请在不新增信息的前提下重新压缩到 100 个中文字符以内。"
                       if compress else "请生成新的 context。")
        result = self.structured_chat(
            f'{rules}\n\n只返回 JSON：{{"context":"string"}}',
            json.dumps({"instruction": instruction, "document_context": document_context,
                        "strategy_code": strategy_code, "content": content,
                        "previous_context": previous_context}, ensure_ascii=False),
            model=model,
            operation="context_regeneration",
        )
        return str(result.get("context") or "").strip()

    def analyze_image(
        self,
        image: bytes,
        content_type: str,
        filename: str,
        model: str,
    ) -> dict[str, Any]:
        self._require_enabled()
        rules = knowledge_skill_service.combine("image_analysis")
        schema = (
            '只返回 JSON：{"title":"string","transcription":"string",'
            '"description":"string"}'
        )
        image_url = (
            f"data:{content_type};base64,"
            f"{base64.b64encode(image).decode('ascii')}"
        )
        return self._structured_request(
            messages=[
                {"role": "system", "content": f"{rules}\n\n{schema}"},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": f"提取并描述知识图片：{filename}",
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": image_url,
                                "detail": "original",
                            },
                        },
                    ],
                },
            ],
            model=model,
            operation="image_analysis",
            input_chars=len(image_url),
        )

    def answer_knowledge(self, question: str, contexts: list[dict[str, Any]]) -> str:
        rules = knowledge_skill_service.combine("rag_answer")
        return self.chat(rules, json.dumps(
            {"question": question, "knowledge_contexts": contexts}, ensure_ascii=False
        ), operation="knowledge_answer")

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

    @staticmethod
    def _object_dict(value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        if hasattr(value, "model_dump"):
            dumped = value.model_dump()
            return dumped if isinstance(dumped, dict) else {"value": dumped}
        if hasattr(value, "dict"):
            dumped = value.dict()
            return dumped if isinstance(dumped, dict) else {"value": dumped}
        attributes = getattr(value, "__dict__", None)
        return dict(attributes) if isinstance(attributes, dict) else {"value": str(value)}

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @classmethod
    def _raw_response(cls, response: Any) -> str:
        if hasattr(response, "model_dump_json"):
            return str(response.model_dump_json())
        return json.dumps(cls._object_dict(response), ensure_ascii=False, default=str)

    def _require_enabled(self) -> None:
        if not self.enabled:
            raise RuntimeError("DeepSeek API Key 未配置，请设置 DEEPSEEK_API_KEY")
