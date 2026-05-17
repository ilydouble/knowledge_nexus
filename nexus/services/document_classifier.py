"""Document Classifier — multi-signal content-aware document type detection.

Classification uses three independent signal groups, applied in priority order:

1. **Extension signals** — definitive for tabular formats (.xlsx / .csv row-count)
2. **Filename keyword signals** — strong hints (论文, report, meeting …)
3. **Content preview signals** — body-level keywords from the first 600 chars

Each category is paired with an extraction *strategy*:

* ``"llm_extract"``        — full LLM extraction (single-pass or map-reduce)
* ``"structural_summary"`` — skip LLM content analysis; only schema + row stats
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Pre-defined categories and their extraction strategies
# ---------------------------------------------------------------------------

CATEGORIES: dict[str, dict] = {
    "academic_paper": {
        "strategy": "llm_extract",
        "description": "Research papers, theses, journal articles",
        "filename_keywords": ["paper", "论文", "research", "study", "thesis", "preprint", "journal"],
        "content_keywords": ["abstract", "introduction", "methodology", "experiment", "conclusion",
                             "references", "doi:", "keywords:", "摘要", "方法论"],
    },
    "technical_doc": {
        "strategy": "llm_extract",
        "description": "API docs, READMEs, architecture documents",
        "filename_keywords": ["api", "readme", "tech", "architecture", "spec", "design",
                              "技术", "架构", "接口", "规范"],
        "content_keywords": ["endpoint", "request", "response", "schema", "install",
                             "configuration", "class ", "def ", "function", "module"],
    },
    "meeting_minutes": {
        "strategy": "llm_extract",
        "description": "Meeting notes, agendas, action items",
        "filename_keywords": ["meeting", "minutes", "会议", "纪要", "agenda", "action"],
        "content_keywords": ["attendees", "action item", "决议", "与会", "action:", "todo:",
                             "next steps", "owner:", "due date"],
    },
    "report": {
        "strategy": "llm_extract",
        "description": "Status reports, business reports, summaries",
        "filename_keywords": ["report", "报告", "月报", "周报", "summary", "review", "analysis"],
        "content_keywords": ["executive summary", "key findings", "recommendation", "kpi",
                             "同比", "环比", "增长", "风险", "milestone", "progress"],
    },
    "contract": {
        "strategy": "llm_extract",
        "description": "Contracts, agreements, NDAs",
        "filename_keywords": ["contract", "agreement", "合同", "协议", "nda", "terms", "license"],
        "content_keywords": ["party", "whereas", "hereby", "clause", "term and condition",
                             "甲方", "乙方", "第一条", "违约", "本协议"],
    },
    "email": {
        "strategy": "llm_extract",
        "description": "Email threads and correspondence",
        "filename_keywords": ["email", "mail", "邮件", "correspondence"],
        "content_keywords": ["from:", "to:", "subject:", "cc:", "dear ", "regards,",
                             "发件人:", "收件人:", "主题:"],
    },
    "tabular_data": {
        "strategy": "structural_summary",
        "description": "Spreadsheets and large CSV datasets",
        "filename_keywords": [],      # handled by extension signal
        "content_keywords": [],
    },
    "general": {
        "strategy": "llm_extract",
        "description": "Fallback for unrecognised document types",
        "filename_keywords": [],
        "content_keywords": [],
    },
}

# Extensions that are always tabular regardless of filename
_TABULAR_EXTENSIONS: frozenset[str] = frozenset({".xlsx", ".xls", ".xlsm", ".ods"})
# CSV/TSV only flagged as tabular when they look row-heavy (handled after parsing)
_CSV_EXTENSIONS: frozenset[str] = frozenset({".csv", ".tsv"})


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class ClassificationResult:
    doc_type: str
    strategy: str            # "llm_extract" | "structural_summary"
    confidence: float        # 0.0 – 1.0 (informational)
    signals: list[str] = field(default_factory=list)   # debug trail


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------

class DocumentClassifier:
    """Classify a document into a pre-defined category using multiple signals."""

    def classify(
        self,
        filename: str,
        content_preview: str = "",
        file_type: str = "",      # already-parsed file_type from parser (e.g. "tabular_data")
        row_count: int = 0,       # only relevant for CSV
    ) -> ClassificationResult:
        """Return :class:`ClassificationResult` for the given document.

        Args:
            filename:        Original filename (used for extension + keyword signals).
            content_preview: First ~600 chars of extracted text (used for body signals).
            file_type:       ``ParsedContent.file_type`` from the parser, if available.
            row_count:       Number of data rows (for CSVs — triggers tabular mode when large).
        """
        ext = Path(filename).suffix.lower()
        name_lower = filename.lower()
        preview_lower = content_preview.lower()
        signals: list[str] = []

        # ── Signal 1: file_type set by parser (highest priority) ──────────────
        if file_type == "tabular_data":
            signals.append("parser:file_type=tabular_data")
            return ClassificationResult("tabular_data", "structural_summary", 1.0, signals)

        # ── Signal 2: extension is definitively tabular ────────────────────────
        if ext in _TABULAR_EXTENSIONS:
            signals.append(f"extension:{ext}=tabular")
            return ClassificationResult("tabular_data", "structural_summary", 1.0, signals)

        # CSV/TSV are tabular only if they look large (many rows)
        if ext in _CSV_EXTENSIONS and row_count > 200:
            signals.append(f"csv_rows:{row_count}>200")
            return ClassificationResult("tabular_data", "structural_summary", 0.9, signals)

        # ── Signal 3 + 4: filename keywords and content keywords ───────────────
        scores: dict[str, float] = {cat: 0.0 for cat in CATEGORIES if cat != "general"}

        for cat, meta in CATEGORIES.items():
            if cat in ("general", "tabular_data"):
                continue

            for kw in meta["filename_keywords"]:
                if kw in name_lower:
                    scores[cat] += 2.0
                    signals.append(f"filename:{kw}→{cat}")

            for kw in meta["content_keywords"]:
                if kw in preview_lower:
                    scores[cat] += 1.0
                    signals.append(f"content:{kw}→{cat}")

        best_cat = max(scores, key=lambda c: scores[c]) if scores else "general"
        best_score = scores.get(best_cat, 0.0)

        if best_score == 0.0:
            signals.append("no signals matched → general")
            return ClassificationResult("general", "llm_extract", 0.3, signals)

        confidence = min(1.0, best_score / 6.0)   # normalise roughly to [0, 1]
        strategy = CATEGORIES[best_cat]["strategy"]
        return ClassificationResult(best_cat, strategy, confidence, signals)
