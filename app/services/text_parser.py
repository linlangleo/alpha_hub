from app.services.docx_parser import DocumentBlock, ParsedDocument


class TextParser:
    """Decode a plain-text document without adding overlap."""

    def parse(self, content: bytes) -> ParsedDocument:
        text: str | None = None
        for encoding in ("utf-8-sig", "gb18030"):
            try:
                text = content.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            raise RuntimeError("TXT 仅支持 UTF-8 或 GB18030 编码")
        normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not normalized:
            raise RuntimeError("TXT 没有可解析的文字")
        return ParsedDocument(
            blocks=[DocumentBlock(type="paragraph", index=0, text=normalized)],
            images=[],
        )
