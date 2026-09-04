import logging
from io import BytesIO
from typing import Any

import pymupdf
from PIL import Image

from app.services.docx_parser import DocumentBlock, ExtractedImage, ParsedDocument


logger = logging.getLogger(__name__)

PDF_IMAGE_JPEG_QUALITY = 95
_PIL_ROTATABLE_FORMATS = {"JPEG", "PNG", "GIF", "WEBP"}

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
                rotation = int(page.rotation) % 360
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
                                data=self._align_image_to_page(
                                    bytes(raw_block["image"]),
                                    rotation,
                                    extension,
                                ),
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

    @staticmethod
    def _align_image_to_page(data: bytes, rotation: int, extension: str) -> bytes:
        """Rotate an embedded image so stored bytes match the on-screen page.

        ``Page.get_text("dict")`` image blocks expose the raw XObject pixels, which do
        not include the page ``/Rotate`` compensation that PDF viewers apply. Scanned
        pages can therefore come out sideways or upside down while sibling pages with
        ``rotation == 0`` look normal. Rotate the pixels clockwise by ``rotation``
        degrees so stored preview/OCR inputs equal what the PDF actually displays.

        ``rotation == 0`` returns the original bytes untouched, so ordinary PDFs keep
        byte-identical output.
        """
        rotation = int(rotation) % 360
        if rotation == 0:
            return data
        try:
            with Image.open(BytesIO(data)) as source:
                if getattr(source, "is_animated", False):
                    return data
                source_format = str(source.format or "").upper()
                if source_format not in _PIL_ROTATABLE_FORMATS:
                    return data
                # PIL rotate() turns counter-clockwise; (360 - rotation) % 360 is the
                # clockwise equivalent of the page rotation applied by viewers.
                rotated = source.rotate((360 - rotation) % 360, expand=True)
                buffer = BytesIO()
                if source_format == "JPEG":
                    if rotated.mode not in ("RGB", "L"):
                        rotated = rotated.convert("RGB")
                    rotated.save(buffer, format="JPEG", quality=PDF_IMAGE_JPEG_QUALITY)
                else:
                    rotated.save(buffer, format=source_format)
                return buffer.getvalue()
        except Exception as exc:
            logger.warning(
                "PDF 内嵌图片方向校正失败，按原图保存（rotation=%s, ext=%s）: %s",
                rotation,
                extension,
                exc,
            )
            return data
