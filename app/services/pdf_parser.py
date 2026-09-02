from typing import Any

import pymupdf

from app.services.docx_parser import DocumentBlock, ExtractedImage, ParsedDocument


IMAGE_MIME_TYPES = {
    "jpeg": "image/jpeg",
    "jpg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "webp": "image/webp",
}


class PdfParser:
    """Extract PDF text and embedded images in page reading order."""

    def parse(self, content: bytes) -> ParsedDocument:
        try:
            document = pymupdf.open(stream=content, filetype="pdf")
        except Exception as exc:
            raise RuntimeError("PDF 文件损坏或格式不正确") from exc

        blocks: list[DocumentBlock] = []
        images: list[ExtractedImage] = []
        try:
            for page in document:
                page_blocks = page.get_text("dict").get("blocks", [])
                for raw_block in sorted(page_blocks, key=self._position):
                    if raw_block.get("type") == 0:
                        text = self._text(raw_block)
                        if text:
                            blocks.append(
                                DocumentBlock(
                                    type="paragraph",
                                    index=len(blocks),
                                    text=text,
                                )
                            )
                    elif raw_block.get("type") == 1 and raw_block.get("image"):
                        extension = str(raw_block.get("ext") or "png").lower()
                        image_id = f"image_{len(images) + 1:03d}"
                        images.append(
                            ExtractedImage(
                                image_id=image_id,
                                filename=f"{image_id}.{extension}",
                                content_type=IMAGE_MIME_TYPES.get(
                                    extension,
                                    "application/octet-stream",
                                ),
                                data=bytes(raw_block["image"]),
                            )
                        )
                        blocks.append(
                            DocumentBlock(
                                type="image",
                                index=len(blocks),
                                image_id=image_id,
                            )
                        )
        finally:
            document.close()

        if not blocks:
            raise RuntimeError("PDF 没有可解析的文字或图片")
        return ParsedDocument(blocks=blocks, images=images)

    @staticmethod
    def _position(block: dict[str, Any]) -> tuple[float, float]:
        bbox = block.get("bbox") or (0, 0, 0, 0)
        return float(bbox[1]), float(bbox[0])

    @staticmethod
    def _text(block: dict[str, Any]) -> str:
        lines = []
        for line in block.get("lines", []):
            value = "".join(str(span.get("text") or "") for span in line.get("spans", []))
            if value.strip():
                lines.append(value.rstrip())
        return "\n".join(lines).strip()
