from io import BytesIO
from typing import Any

from PIL import Image, UnidentifiedImageError

from app.services.docx_parser import DocumentBlock, ParsedDocument


SUPPORTED_IMAGE_FORMATS = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "GIF": "image/gif",
    "WEBP": "image/webp",
}


class ImageParser:
    """Validate a standalone image and build its text-backed parsed form."""

    def validate(self, content: bytes) -> str:
        try:
            with Image.open(BytesIO(content)) as image:
                image_format = str(image.format or "").upper()
                image.verify()
        except (UnidentifiedImageError, OSError) as exc:
            raise RuntimeError("图片文件损坏或格式不受支持") from exc
        content_type = SUPPORTED_IMAGE_FORMATS.get(image_format)
        if content_type is None:
            raise RuntimeError("图片仅支持 JPEG、PNG、GIF、WebP")
        return content_type

    @staticmethod
    def from_analysis(
        object_key: str,
        analysis: dict[str, Any],
    ) -> ParsedDocument:
        title = str(analysis.get("title") or "").strip()
        transcription = str(analysis.get("transcription") or "").strip()
        description = str(analysis.get("description") or "").strip()
        sections = []
        if title:
            sections.append(f"标题：{title}")
        if transcription:
            sections.append(f"可见文字：\n{transcription}")
        if description:
            sections.append(f"视觉内容说明：\n{description}")
        if not sections:
            raise RuntimeError("视觉模型没有提取出可用的图片内容")
        return ParsedDocument(
            blocks=[
                DocumentBlock(
                    type="image",
                    index=0,
                    text="\n\n".join(sections),
                    image_id="image_001",
                    object_key=object_key,
                )
            ],
            images=[],
        )
