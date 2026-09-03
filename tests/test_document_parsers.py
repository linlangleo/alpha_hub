import logging
from io import BytesIO
from types import SimpleNamespace

import pymupdf
import pytest
from PIL import Image

from app.core.config import SETTINGS
from app.services.image_parser import ImageParser
from app.services.deepseek_service import (
    DeepSeekService,
    DeepSeekStructuredOutputError,
)
from app.services.pdf_parser import PdfParser
from app.services.text_parser import TextParser
from app.workflows.knowledge_ingestion import KnowledgeIngestionWorkflow


def test_text_parser_supports_utf8_and_gb18030() -> None:
    utf8 = TextParser().parse("第一段\n第二段".encode("utf-8"))
    gb18030 = TextParser().parse("中文知识".encode("gb18030"))

    assert utf8.blocks[0].content() == "第一段\n第二段"
    assert gb18030.blocks[0].content() == "中文知识"


def test_pdf_parser_extracts_text() -> None:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "AlphaHub PDF knowledge")
    content = document.tobytes()
    document.close()

    parsed = PdfParser().parse(content)

    assert "AlphaHub PDF knowledge" in "\n".join(
        block.content() for block in parsed.blocks
    )


def test_image_parser_preserves_reference_and_vision_text() -> None:
    stream = BytesIO()
    Image.new("RGB", (32, 32), color="white").save(stream, format="PNG")
    content = stream.getvalue()

    assert ImageParser().validate(content) == "image/png"
    parsed = ImageParser.from_analysis(
        "raw/image/1/example.png",
        {
            "title": "示例图",
            "transcription": "N字战法",
            "description": "一张带有走势标记的图",
        },
    )

    block = parsed.blocks[0]
    assert block.object_key == "raw/image/1/example.png"
    assert block.content().startswith("[[IMAGE:image_001]]")
    assert "N字战法" in block.content()
    assert "走势标记" in block.content()


def test_analysis_model_is_selected_by_file_type() -> None:
    workflow = KnowledgeIngestionWorkflow()

    assert workflow._select_model("docx", "") == SETTINGS.deepseek_model
    assert workflow._select_model("pdf", "deepseek-v4-pro") == "deepseek-v4-pro"
    assert workflow._select_model("image", "") == SETTINGS.deepseek_vision_model

    with pytest.raises(ValueError, match="Vision"):
        workflow._select_model("image", "deepseek-v4-pro")
    with pytest.raises(ValueError, match="文本模型"):
        workflow._select_model("text", SETTINGS.deepseek_vision_model)


def test_deepseek_call_uses_selected_model_and_vision_content(caplog) -> None:
    caplog.set_level(logging.INFO, logger="app.services.deepseek_service")
    calls = []

    class Completions:
        @staticmethod
        def create(**kwargs):
            calls.append(kwargs)
            message = SimpleNamespace(
                content='{"title":"图","transcription":"文字","description":"说明"}'
            )
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    service = DeepSeekService(
        api_key="test",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        timeout=1,
        retry=1,
        max_input_chars=1000,
        max_output_tokens=100,
    )
    service.client = SimpleNamespace(
        chat=SimpleNamespace(completions=Completions())
    )

    service.structured_chat("system", "{}", model="deepseek-v4-pro")
    service.analyze_image(
        b"image",
        "image/png",
        "example.png",
        "deepseek-v4-flash-vision-exp",
    )

    assert calls[0]["model"] == "deepseek-v4-pro"
    assert calls[1]["model"] == "deepseek-v4-flash-vision-exp"
    user_content = calls[1]["messages"][1]["content"]
    assert user_content[1]["type"] == "image_url"
    assert user_content[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert "DeepSeek request started operation=structured_chat" in caplog.text
    assert "DeepSeek request succeeded operation=structured_chat" in caplog.text
    assert "DeepSeek request succeeded operation=image_analysis" in caplog.text


def test_deepseek_invalid_json_exposes_structured_diagnostics(caplog) -> None:
    class Completions:
        @staticmethod
        def create(**kwargs):
            message = SimpleNamespace(content='{"chunks": [}')
            choice = SimpleNamespace(message=message, finish_reason="stop")
            return SimpleNamespace(id="response-1", choices=[choice])

    service = DeepSeekService(
        api_key="test",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        timeout=1,
        retry=1,
        max_input_chars=1000,
        max_output_tokens=100,
    )
    service.client = SimpleNamespace(
        chat=SimpleNamespace(completions=Completions())
    )

    with pytest.raises(DeepSeekStructuredOutputError) as raised:
        service.structured_chat("system", "{}", operation="chunk_analysis")

    detail = raised.value.as_detail()
    assert str(raised.value) == "DeepSeek 返回内容不是合法 JSON"
    assert detail["error_type"] == "INVALID_JSON"
    assert detail["operation"] == "chunk_analysis"
    assert detail["response_id"] == "response-1"
    assert detail["finish_reason"] == "stop"
    assert detail["json_line"] == 1
    assert detail["json_column"] == 13
    assert "response_preview" in caplog.text


def test_deepseek_length_finish_reason_is_reported_as_truncated() -> None:
    class Completions:
        @staticmethod
        def create(**kwargs):
            message = SimpleNamespace(
                content="",
                reasoning_content="正在推理但尚未生成最终 JSON",
            )
            choice = SimpleNamespace(message=message, finish_reason="length")
            usage = SimpleNamespace(
                prompt_tokens=2500,
                completion_tokens=8192,
                total_tokens=10692,
            )
            return SimpleNamespace(id="response-2", choices=[choice], usage=usage)

    service = DeepSeekService(
        api_key="test",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        timeout=1,
        retry=1,
        max_input_chars=1000,
        max_output_tokens=100,
    )
    service.client = SimpleNamespace(
        chat=SimpleNamespace(completions=Completions())
    )

    with pytest.raises(DeepSeekStructuredOutputError) as raised:
        service.structured_chat("system", "{}", operation="chunk_analysis")

    assert raised.value.error_type == "OUTPUT_TRUNCATED"
    assert str(raised.value) == "DeepSeek 返回内容被截断"
    assert raised.value.reasoning_chars == 16
    assert raised.value.prompt_tokens == 2500
    assert raised.value.completion_tokens == 8192
    assert raised.value.total_tokens == 10692
