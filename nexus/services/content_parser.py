"""Content Parser - Extract text content from various file formats."""

from __future__ import annotations

import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pdfplumber
from docx import Document


@dataclass
class ParsedContent:
    """Result of parsing a file."""
    text: str
    metadata: dict[str, Any]
    chunks: list[str]
    file_type: str


class BaseParser(ABC):
    """Base parser interface."""
    
    @abstractmethod
    def parse(self, content: bytes, filename: str) -> ParsedContent:
        """Parse file content and return extracted text."""
        pass
    
    @abstractmethod
    def supports(self, mime_type: str, filename: str) -> bool:
        """Check if this parser supports the given file type."""
        pass


class TextParser(BaseParser):
    """Parser for plain text files."""

    SUPPORTED_TYPES = {
        "text/plain",
        "text/markdown",
        "text/csv",
        "application/json",
    }
    SUPPORTED_EXTENSIONS = {".txt", ".md", ".csv", ".json", ".yaml", ".yml"}

    def parse(self, content: bytes, filename: str) -> ParsedContent:
        text = content.decode("utf-8", errors="replace")
        return ParsedContent(
            text=text,
            metadata={"filename": filename, "size": len(content)},
            chunks=self._chunk(text),
            file_type="text",
        )

    def supports(self, mime_type: str, filename: str) -> bool:
        ext = Path(filename).suffix.lower()
        return mime_type in self.SUPPORTED_TYPES or ext in self.SUPPORTED_EXTENSIONS

    @staticmethod
    def _chunk(text: str, chunk_size: int = 1000, overlap: int = 100) -> list[str]:
        """Split text into overlapping chunks for vector indexing.

        chunk_size is intentionally smaller than the LLM extraction segment
        (8 000 chars) so that each retrieved snippet is focused and precise.
        One LLM segment ≈ 8 vector chunks, guaranteeing full coverage.
        """
        if len(text) <= chunk_size:
            return [text] if text.strip() else []

        chunks = []
        start = 0
        while start < len(text):
            end = start + chunk_size
            chunk = text[start:end]
            if chunk.strip():
                chunks.append(chunk)
            start += chunk_size - overlap
        return chunks


class PDFParser(BaseParser):
    """Parser for PDF files using pdfplumber."""
    
    SUPPORTED_TYPES = {"application/pdf"}
    SUPPORTED_EXTENSIONS = {".pdf"}
    
    def parse(self, content: bytes, filename: str) -> ParsedContent:
        text_parts = []
        metadata = {"filename": filename, "pages": 0}
        
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp:
            tmp.write(content)
            tmp.flush()
            
            with pdfplumber.open(tmp.name) as pdf:
                metadata["pages"] = len(pdf.pages)
                for i, page in enumerate(pdf.pages):
                    page_text = page.extract_text() or ""
                    if page_text.strip():
                        text_parts.append(f"--- Page {i + 1} ---\n{page_text}")
        
        full_text = "\n\n".join(text_parts)
        return ParsedContent(
            text=full_text,
            metadata=metadata,
            chunks=self._chunk(full_text),
            file_type="pdf",
        )
    
    def supports(self, mime_type: str, filename: str) -> bool:
        ext = Path(filename).suffix.lower()
        return mime_type in self.SUPPORTED_TYPES or ext in self.SUPPORTED_EXTENSIONS
    
    @staticmethod
    def _chunk(text: str, chunk_size: int = 1000, overlap: int = 100) -> list[str]:
        """Split text into overlapping chunks for vector indexing.

        chunk_size is intentionally smaller than the LLM extraction segment
        (8 000 chars) so that each retrieved snippet is focused and precise.
        One LLM segment ≈ 8 vector chunks, guaranteeing full coverage.
        Attempts to break at paragraph boundaries to preserve sentence context.
        """
        if len(text) <= chunk_size:
            return [text] if text.strip() else []

        chunks = []
        start = 0
        while start < len(text):
            end = start + chunk_size
            # Try to break at paragraph boundary
            chunk = text[start:end]
            last_para = chunk.rfind("\n\n")
            if last_para > chunk_size // 2 and end < len(text):
                end = start + last_para + 2
                chunk = text[start:end]

            if chunk.strip():
                chunks.append(chunk)
            start = end
            if start < len(text) and start > 0:
                start = max(0, start - overlap)
                if start in [s for c in chunks for s in [len(c)]]:
                    start = end  # Avoid infinite loop
        return chunks


class DocxParser(BaseParser):
    """Parser for Word documents."""
    
    SUPPORTED_TYPES = {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    }
    SUPPORTED_EXTENSIONS = {".docx"}
    
    def parse(self, content: bytes, filename: str) -> ParsedContent:
        text_parts = []
        metadata = {"filename": filename, "paragraphs": 0}
        
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=True) as tmp:
            tmp.write(content)
            tmp.flush()
            
            doc = Document(tmp.name)
            metadata["paragraphs"] = len(doc.paragraphs)
            
            for para in doc.paragraphs:
                if para.text.strip():
                    text_parts.append(para.text)
        
        full_text = "\n\n".join(text_parts)
        return ParsedContent(
            text=full_text,
            metadata=metadata,
            chunks=TextParser._chunk(full_text),
            file_type="docx",
        )
    
    def supports(self, mime_type: str, filename: str) -> bool:
        ext = Path(filename).suffix.lower()
        return mime_type in self.SUPPORTED_TYPES or ext in self.SUPPORTED_EXTENSIONS


class ContentParserService:
    """Service to parse various file formats."""
    
    def __init__(self) -> None:
        self.parsers: list[BaseParser] = [
            PDFParser(),
            DocxParser(),
            TextParser(),  # Text parser as fallback
        ]
    
    def parse(self, content: bytes, filename: str, mime_type: str = "") -> ParsedContent:
        """Parse file content using appropriate parser."""
        for parser in self.parsers:
            if parser.supports(mime_type, filename):
                return parser.parse(content, filename)
        
        # Fallback to text parser
        return TextParser().parse(content, filename)
    
    def get_supported_types(self) -> dict[str, list[str]]:
        """Return supported MIME types and extensions."""
        return {
            "mime_types": list(PDFParser.SUPPORTED_TYPES | DocxParser.SUPPORTED_TYPES | TextParser.SUPPORTED_TYPES),
            "extensions": list(PDFParser.SUPPORTED_EXTENSIONS | DocxParser.SUPPORTED_EXTENSIONS | TextParser.SUPPORTED_EXTENSIONS),
        }
