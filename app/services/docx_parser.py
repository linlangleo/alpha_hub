from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath
from typing import Any

from docx import Document
from docx.document import Document as DocumentType
from docx.oxml.ns import qn
from docx.table import Table


@dataclass
class DocumentBlock:
    type: str
    index: int
    text: str = ""
    image_id: str | None = None
    object_key: str | None = None

    def content(self) -> str:
        if self.type == "image" and self.image_id:
            return f"[[IMAGE:{self.image_id}]]"
        return self.text

    def analysis_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {"type": self.type, "index": self.index}
        if self.type == "image":
            value["image_id"] = self.image_id
        else:
            value["text"] = self.text
        return value


@dataclass(frozen=True)
class ExtractedImage:
    image_id: str
    filename: str
    content_type: str
    data: bytes


@dataclass
class ParsedDocx:
    blocks: list[DocumentBlock]
    images: list[ExtractedImage]


class DocxParser:
    """Parse DOCX body blocks while retaining paragraph/table/image order."""

    def parse(self, content: bytes) -> ParsedDocx:
        document = Document(BytesIO(content))
        blocks: list[DocumentBlock] = []
        images: list[ExtractedImage] = []

        for child in document.element.body.iterchildren():
            if child.tag == qn("w:p"):
                self._append_paragraph(child, document, blocks, images)
            elif child.tag == qn("w:tbl"):
                markdown = self._table_to_markdown(Table(child, document))
                if markdown:
                    blocks.append(DocumentBlock(type="table", index=len(blocks), text=markdown))

        if not blocks:
            raise RuntimeError("DOCX 没有可解析的文字、图片或表格")
        return ParsedDocx(blocks=blocks, images=images)

    def _append_paragraph(
        self,
        element: Any,
        document: DocumentType,
        blocks: list[DocumentBlock],
        images: list[ExtractedImage],
    ) -> None:
        text_buffer: list[str] = []

        def flush_text() -> None:
            text = "".join(text_buffer).strip()
            text_buffer.clear()
            if text:
                blocks.append(DocumentBlock(type="paragraph", index=len(blocks), text=text))

        for node in element.iter():
            if node.tag == qn("w:t") and node.text:
                text_buffer.append(node.text)
            elif node.tag == qn("w:tab"):
                text_buffer.append("\t")
            elif node.tag in {qn("w:br"), qn("w:cr")}:
                text_buffer.append("\n")
            elif node.tag == qn("a:blip"):
                relation_id = node.get(qn("r:embed"))
                if not relation_id:
                    continue
                image_part = document.part.related_parts.get(relation_id)
                if image_part is None or not hasattr(image_part, "blob"):
                    continue
                flush_text()
                image_id = f"image_{len(images) + 1:03d}"
                suffix = PurePosixPath(str(image_part.partname)).suffix or ".bin"
                images.append(
                    ExtractedImage(
                        image_id=image_id,
                        filename=f"{image_id}{suffix.lower()}",
                        content_type=str(getattr(image_part, "content_type", "application/octet-stream")),
                        data=image_part.blob,
                    )
                )
                blocks.append(
                    DocumentBlock(type="image", index=len(blocks), image_id=image_id)
                )
        flush_text()

    @staticmethod
    def _table_to_markdown(table: Table) -> str:
        rows: list[list[str]] = []
        for row in table.rows:
            values = [
                cell.text.replace("|", "\\|").replace("\r", " ").replace("\n", "<br>").strip()
                for cell in row.cells
            ]
            if any(values):
                rows.append(values)
        if not rows:
            return ""
        width = max(len(row) for row in rows)
        normalized = [row + [""] * (width - len(row)) for row in rows]
        header = "| " + " | ".join(normalized[0]) + " |"
        separator = "| " + " | ".join(["---"] * width) + " |"
        body = ["| " + " | ".join(row) + " |" for row in normalized[1:]]
        return "\n".join([header, separator, *body])
