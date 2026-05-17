"""Knowledge Extractor - Extract structured knowledge from text using LLM."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from nexus.settings import Settings

logger = logging.getLogger(__name__)


@dataclass
class ExtractedKnowledge:
    """Result of knowledge extraction."""
    summary: str
    tags: list[str]
    entities: list[dict[str, Any]]
    relations: list[dict[str, Any]]
    key_points: list[dict[str, Any]]
    confidence: float = 0.8
    raw_response: dict[str, Any] = field(default_factory=dict)


# Default ontology for general / unclassified documents
DEFAULT_ONTOLOGY = {
    "concepts": [
        {"type": "Person", "description": "A named individual (e.g. '张伟', 'Alan Turing'). NOT job titles or roles."},
        {"type": "Organization", "description": "A named company, team, or institution (e.g. 'Alibaba', 'MIT'). NOT departments without names."},
        {"type": "Project", "description": "A named project or initiative with a specific purpose."},
        {"type": "Technology", "description": "A named tool, framework, language, or system (e.g. 'Python', 'Kafka')."},
        {"type": "Concept", "description": "A key abstract idea or domain term central to the document."},
        {"type": "Location", "description": "A named geographical place relevant to the content."},
        {"type": "Event", "description": "A named occurrence with a time dimension (e.g. conference, release, incident)."},
        {"type": "Metric", "description": "A measurable indicator with a value (e.g. '99.9% uptime', '2s latency')."},
    ],
    "relations": [
        {"relation": "WORKS_AT", "source": "Person", "target": "Organization", "description": "Person is employed at or affiliated with organization"},
        {"relation": "WORKS_ON", "source": "Person", "target": "Project", "description": "Person contributes to project"},
        {"relation": "USES", "source": "Person", "target": "Technology", "description": "Person or project uses a technology"},
        {"relation": "PART_OF", "source": "Entity", "target": "Entity", "description": "Entity is a sub-component of another"},
        {"relation": "DEPENDS_ON", "source": "Entity", "target": "Entity", "description": "Entity requires another to function"},
        {"relation": "RELATES_TO", "source": "Entity", "target": "Entity", "description": "General semantic association when no specific relation fits"},
        {"relation": "LOCATED_IN", "source": "Entity", "target": "Location", "description": "Entity is physically or legally based in a location"},
        {"relation": "MEASURES", "source": "Metric", "target": "Entity", "description": "Metric quantifies an aspect of an entity"},
    ],
    "instructions": (
        "Extract named, specific entities only. Avoid generic terms. "
        "Prefer concrete nouns over abstract ones. "
        "Use RELATES_TO only as a last resort when no more specific relation applies."
    ),
}

# Document type specific templates
# ---------------------------------------------------------------------------
# Map-Reduce thresholds
# ---------------------------------------------------------------------------
#: Characters fed to the LLM in single-pass mode.
_SINGLE_PASS_LIMIT: int = 12_000
#: Character budget per segment in map-reduce mode.
_SEGMENT_SIZE: int = 8_000
#: Overlap between adjacent segments to preserve context across boundaries.
_SEGMENT_OVERLAP: int = 400
#: Documents longer than this switch from single-pass to map-reduce.
_MAP_REDUCE_THRESHOLD: int = 10_000
#: Minimum entity confidence score; lower entries are dropped during merge.
MIN_ENTITY_CONFIDENCE: float = 0.5

DOCUMENT_TEMPLATES = {
    "academic_paper": {
        "concepts": [
            {"type": "Researcher", "description": "Named author or researcher (e.g. 'Yann LeCun'). NOT institutions or generic roles like 'scientist'."},
            {"type": "Institution", "description": "University, lab, or company affiliation (e.g. 'MIT', 'Google Brain'). NOT persons."},
            {"type": "Method", "description": "Specific algorithm, model, or technique (e.g. 'BERT', 'ResNet-50'). NOT generic terms like 'deep learning'."},
            {"type": "Dataset", "description": "Named dataset for training or evaluation (e.g. 'ImageNet', 'SQuAD', 'COCO')."},
            {"type": "Metric", "description": "Quantitative performance measure WITH its value (e.g. 'accuracy 94.2%', 'BLEU 32.1'). Omit if no value given."},
            {"type": "Concept", "description": "Core research topic being studied (e.g. 'transfer learning'). NOT method names which belong to Method."},
            {"type": "Task", "description": "ML/AI task or problem being solved (e.g. 'sentiment analysis', 'image segmentation')."},
        ],
        "relations": [
            {"relation": "AUTHORED_BY", "source": "Paper", "target": "Researcher", "description": "Paper written by this researcher"},
            {"relation": "AFFILIATED_WITH", "source": "Researcher", "target": "Institution", "description": "Researcher's institutional affiliation"},
            {"relation": "PROPOSES", "source": "Paper", "target": "Method", "description": "Paper introduces or proposes this method as its contribution"},
            {"relation": "EVALUATES_ON", "source": "Method", "target": "Dataset", "description": "Method is tested or benchmarked on this dataset"},
            {"relation": "ACHIEVES", "source": "Method", "target": "Metric", "description": "Method attains this performance metric"},
            {"relation": "BUILDS_ON", "source": "Method", "target": "Method", "description": "Method extends or modifies a prior method"},
            {"relation": "ADDRESSES", "source": "Paper", "target": "Task", "description": "Paper targets this task or problem"},
            {"relation": "CITES", "source": "Paper", "target": "Method", "description": "Paper references an existing method from prior work"},
        ],
        "instructions": (
            "Focus on: Abstract (research question & contribution), Methods section (proposed techniques), "
            "Experiments (datasets, baselines, metrics with numbers), Results (performance), Conclusion (claims). "
            "Do NOT treat section headings or chapter titles as entities. "
            "Do NOT extract 'deep learning', 'neural network' as Concepts unless they ARE the main contribution. "
            "Metrics must include actual numeric values."
        ),
    },
    "technical_doc": {
        "concepts": [
            {"type": "Component", "description": "A distinct named module, service, or subsystem (e.g. 'AuthService', 'DataPipeline'). NOT generic terms."},
            {"type": "API", "description": "A specific endpoint, method, or interface (e.g. 'POST /api/users', 'getUserById()'). Must have a name/path."},
            {"type": "Database", "description": "A named storage system (e.g. 'PostgreSQL', 'Redis', 'Milvus'). NOT abstract 'database'."},
            {"type": "Framework", "description": "A named software framework or library (e.g. 'FastAPI', 'React', 'PyTorch')."},
            {"type": "Config", "description": "A named configuration parameter or setting (e.g. 'MAX_RETRIES=3', 'JWT_SECRET'). Must be a specific name."},
            {"type": "DataModel", "description": "A named data schema, model, or type (e.g. 'UserProfile', 'JobRecord', 'Order')."},
            {"type": "Error", "description": "A specific error code or exception type (e.g. '401 Unauthorized', 'ConnectionTimeout')."},
        ],
        "relations": [
            {"relation": "DEPENDS_ON", "source": "Component", "target": "Component", "description": "Component requires another component to operate"},
            {"relation": "CALLS", "source": "Component", "target": "API", "description": "Component invokes this API endpoint or method"},
            {"relation": "STORES_IN", "source": "Component", "target": "Database", "description": "Component persists data in this database"},
            {"relation": "IMPLEMENTS", "source": "Component", "target": "API", "description": "Component provides the implementation of this API"},
            {"relation": "USES", "source": "Component", "target": "Framework", "description": "Component is built with or depends on this framework"},
            {"relation": "RETURNS", "source": "API", "target": "DataModel", "description": "API returns this data structure"},
            {"relation": "RAISES", "source": "API", "target": "Error", "description": "API can raise or return this error type"},
            {"relation": "CONFIGURES", "source": "Component", "target": "Config", "description": "Component behaviour is controlled by this config"},
        ],
        "instructions": (
            "Extract concrete named items only — generic terms like 'module' or 'service' are NOT entities. "
            "APIs must have specific names or paths. DataModels must appear as named schemas or classes. "
            "Configs must be specific parameter names, not descriptions. "
            "Relations should reflect actual code-level or architectural dependencies."
        ),
    },
    "meeting_minutes": {
        "concepts": [
            {"type": "Person", "description": "Named meeting participant (e.g. '张伟', 'Sarah Chen'). NOT generic roles like 'PM'."},
            {"type": "Task", "description": "A specific action item someone must do (e.g. '完成用户调研报告'). Must be actionable and concrete."},
            {"type": "Decision", "description": "A resolution or agreement reached in the meeting (e.g. '确定使用 PostgreSQL 方案')."},
            {"type": "Project", "description": "A named project or workstream discussed in the meeting."},
            {"type": "Deadline", "description": "A specific date or relative time for a task (e.g. '2024-03-15', '下周五'). Must be concrete."},
            {"type": "Issue", "description": "A named problem, blocker, or risk raised during the meeting."},
        ],
        "relations": [
            {"relation": "ASSIGNED_TO", "source": "Task", "target": "Person", "description": "Task is owned by this person"},
            {"relation": "DECIDED_BY", "source": "Decision", "target": "Person", "description": "Person proposed or approved this decision"},
            {"relation": "DUE_BY", "source": "Task", "target": "Deadline", "description": "Task must be completed by this deadline"},
            {"relation": "RELATES_TO", "source": "Task", "target": "Project", "description": "Task belongs to this project"},
            {"relation": "RAISED_BY", "source": "Issue", "target": "Person", "description": "Person raised this issue"},
            {"relation": "BLOCKS", "source": "Issue", "target": "Task", "description": "Issue is preventing this task from progressing"},
        ],
        "instructions": (
            "Focus exclusively on: WHO is doing WHAT by WHEN (action items), decisions made, and issues raised. "
            "Do NOT extract casual discussion or context as Tasks. "
            "Tasks must have a clear owner (ASSIGNED_TO required). "
            "Decisions should be distinct conclusions, not discussion points. "
            "Only extract Deadlines that are explicitly stated."
        ),
    },
    "report": {
        "concepts": [
            {"type": "Metric", "description": "A KPI or measurable indicator WITH its value and unit (e.g. '月活跃用户 12万', '转化率 3.2%'). No value = no entity."},
            {"type": "Project", "description": "A named project or business initiative being reported on."},
            {"type": "Team", "description": "A named team or department responsible for a project or metric."},
            {"type": "Risk", "description": "A named risk or threat with specific description (e.g. '供应链延迟风险', 'key person dependency')."},
            {"type": "Milestone", "description": "A named project milestone or goal (e.g. 'Q2 Beta Launch', '10万日活目标')."},
            {"type": "Achievement", "description": "A completed goal or positive outcome explicitly stated (e.g. '提前完成 MVP')."},
            {"type": "Recommendation", "description": "An explicit actionable suggestion in the report (e.g. '建议扩充客服团队')."},
        ],
        "relations": [
            {"relation": "OWNED_BY", "source": "Project", "target": "Team", "description": "Project is under this team's responsibility"},
            {"relation": "MEASURED_BY", "source": "Project", "target": "Metric", "description": "Project performance tracked by this metric"},
            {"relation": "HAS_RISK", "source": "Project", "target": "Risk", "description": "Project faces this risk"},
            {"relation": "TARGETS", "source": "Project", "target": "Milestone", "description": "Project is working toward this milestone"},
            {"relation": "ACHIEVED", "source": "Project", "target": "Achievement", "description": "Project completed this goal"},
            {"relation": "RECOMMENDS", "source": "Report", "target": "Recommendation", "description": "Report explicitly recommends this action"},
        ],
        "instructions": (
            "Prioritize concrete numbers — Metrics without values should not be extracted. "
            "Risks must have specific descriptions, not generic 'schedule risk'. "
            "Distinguish between current Achievements (done) and future Milestones (planned). "
            "Recommendations must be explicitly stated in the report, not inferred."
        ),
    },
    "contract": {
        "concepts": [
            {"type": "Party", "description": "A named contracting party with full name (e.g. '甲方：北京科技有限公司', 'Acme Corp (Party A)'). NOT generic 'buyer/seller'."},
            {"type": "Obligation", "description": "A specific duty one party MUST perform (indicated by 'shall', 'must', '应当', '须'). Paraphrase concisely."},
            {"type": "Right", "description": "A specific entitlement one party MAY exercise (indicated by 'may', 'is entitled to', '有权'). Paraphrase concisely."},
            {"type": "Penalty", "description": "A consequence for breach with amount if stated (e.g. '违约金10万元', 'liquidated damages of $5,000')."},
            {"type": "Jurisdiction", "description": "Governing law or dispute resolution venue (e.g. '中国法律管辖', 'arbitration in Hong Kong')."},
            {"type": "KeyDate", "description": "A critical date: effective date, expiry, payment due (e.g. '合同有效期2年', '2024-06-01生效')."},
            {"type": "Subject", "description": "The main item, service, or intellectual property the contract covers."},
        ],
        "relations": [
            {"relation": "PARTY_TO", "source": "Party", "target": "Contract", "description": "Party is a signatory to the contract"},
            {"relation": "OBLIGATED_BY", "source": "Party", "target": "Obligation", "description": "Party must fulfill this obligation"},
            {"relation": "ENTITLED_TO", "source": "Party", "target": "Right", "description": "Party holds this right"},
            {"relation": "PENALIZED_BY", "source": "Party", "target": "Penalty", "description": "Party faces this penalty for breach"},
            {"relation": "GOVERNED_BY", "source": "Contract", "target": "Jurisdiction", "description": "Contract is subject to this jurisdiction"},
            {"relation": "EFFECTIVE_ON", "source": "Contract", "target": "KeyDate", "description": "Contract milestone date"},
            {"relation": "COVERS", "source": "Contract", "target": "Subject", "description": "Contract governs this subject matter"},
        ],
        "instructions": (
            "Extract both parties with their full legal names. "
            "Identify obligations (shall/must/应当) separately from rights (may/有权). "
            "Include specific penalty amounts when stated. "
            "Capture all key dates. Do NOT extract boilerplate legal language as entities."
        ),
    },
    "email": {
        "concepts": [
            {"type": "Person", "description": "Named sender or recipient (e.g. '张总', 'john@acme.com → John'). NOT generic 'team' or 'all'."},
            {"type": "Organization", "description": "Named company or team mentioned in the email body."},
            {"type": "Topic", "description": "The main subject matter of the email thread (derived from Subject line or opening)."},
            {"type": "Action", "description": "A specific request or follow-up item (e.g. '请在周五前确认方案', 'please review the attached'). Must be concrete."},
            {"type": "KeyDate", "description": "A deadline or meeting time mentioned (e.g. '3月15日前', 'by EOD Friday')."},
            {"type": "Attachment", "description": "A referenced document or file (e.g. '附件：Q1报告.pdf')."},
        ],
        "relations": [
            {"relation": "SENT_BY", "source": "Email", "target": "Person", "description": "Email sender"},
            {"relation": "SENT_TO", "source": "Email", "target": "Person", "description": "Email recipient (To/CC)"},
            {"relation": "REQUESTS", "source": "Person", "target": "Action", "description": "Person is asking for this action"},
            {"relation": "ACTION_BY", "source": "Action", "target": "KeyDate", "description": "Action should be completed by this date"},
            {"relation": "REFERENCES", "source": "Email", "target": "Topic", "description": "Email is about this topic"},
            {"relation": "ATTACHES", "source": "Email", "target": "Attachment", "description": "Email includes this attachment"},
        ],
        "instructions": (
            "Identify who is asking whom to do what by when. "
            "Actions must be concrete requests, NOT casual remarks or pleasantries. "
            "Extract the Topic from the Subject line first, then the opening sentence. "
            "Only extract Attachments that are explicitly named."
        ),
    },
    "tabular_data": {
        "concepts": [
            {"type": "Dataset", "description": "The overall workbook or file (one entity per file)."},
            {"type": "Sheet", "description": "A named worksheet within the workbook."},
            {"type": "Field", "description": "A column header / field name (one entity per column)."},
            {"type": "DataType", "description": "An inferred data type for a field (e.g. 'Date', 'Currency', 'Boolean'). Only when clearly determinable."},
        ],
        "relations": [
            {"relation": "HAS_SHEET", "source": "Dataset", "target": "Sheet", "description": "Workbook contains this sheet"},
            {"relation": "HAS_FIELD", "source": "Sheet", "target": "Field", "description": "Sheet contains this column/field"},
            {"relation": "HAS_TYPE", "source": "Field", "target": "DataType", "description": "Field stores values of this data type"},
        ],
        "instructions": (
            "Create ONE Dataset entity for the whole file. "
            "Create ONE Field entity per column — do not merge or skip columns. "
            "Only add DataType entities when the type is clearly determinable from column name or sample values. "
            "Do not enumerate or describe individual row values."
        ),
    },
}


class KnowledgeExtractor:
    """Extract structured knowledge from text using GLM-compatible chat completions."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        http_client: Any | None = None,
        timeout: float = 180.0,
    ) -> None:
        settings = Settings.from_env()
        self.api_key = api_key or settings.zhipu_api_key or settings.openai_api_key
        self.model = model or settings.llm_model
        self.base_url = base_url or settings.llm_base_url
        self.http_client = http_client or httpx.Client(timeout=timeout)
        self.timeout = timeout
    
    def extract(
        self,
        text: str,
        doc_type: str = "general",
        ontology: dict | None = None,
        strategy: str = "llm_extract",
    ) -> ExtractedKnowledge:
        """Extract knowledge from text, routing by *strategy*.

        * ``"structural_summary"`` — lightweight schema extraction for tabular
          data (Excel / large CSV).  Sends the compact sheet/column summary to
          the LLM; never triggers map-reduce.
        * ``"llm_extract"`` (default) — full extraction, single-pass or
          map-reduce based on document length.

        Args:
            text:     The text content to extract knowledge from.
            doc_type: Category label (academic_paper, tabular_data, …).
            ontology: Custom ontology (uses default if not provided).
            strategy: Extraction strategy hint from the DocumentClassifier.

        Returns:
            ExtractedKnowledge with entities, relations, and summary.
        """
        if not self.api_key:
            return self._mock_extraction(text, doc_type)

        if ontology is None:
            ontology = self._get_ontology(doc_type)

        # ── Tabular / structural path ──────────────────────────────────────────
        if strategy == "structural_summary" or doc_type == "tabular_data":
            logger.info("Tabular extraction (structural summary), doc_type=%s", doc_type)
            return self._extract_tabular(text, ontology)

        # ── Standard LLM path ─────────────────────────────────────────────────
        if len(text) <= _MAP_REDUCE_THRESHOLD:
            # Single-pass: original behaviour, cap at _SINGLE_PASS_LIMIT
            prompt = self._build_extraction_prompt(text[:_SINGLE_PASS_LIMIT], ontology, doc_type)
            result = self._call_chat_completion(prompt)
            return self._normalize_result(result, doc_type)

        # Map-Reduce: long document
        logger.info(
            "Map-reduce extraction: %d chars, doc_type=%s", len(text), doc_type
        )
        return self._extract_mapreduce(text, doc_type, ontology)

    def _extract_tabular(self, structural_text: str, ontology: dict) -> ExtractedKnowledge:
        """Lightweight extraction for tabular data (Excel / large CSV).

        The input is a structural summary produced by ExcelParser, not raw
        cell values.  We ask the LLM to identify the dataset, its sheets,
        columns, and inferred domain — a single short LLM call suffices.
        """
        prompt = f"""You are analyzing the *schema* of a tabular dataset, NOT raw data.
The text below is a structural summary (sheet names, column headers, row counts, sample values).

Your task: extract high-level metadata entities — do NOT enumerate individual rows.

## Output Format (JSON)
{{
  "summary": "<1–2 sentence dataset description: name, domain, size>",
  "tags": ["<domain tag>", ...],
  "entities": [
    {{"id": "<type_label>", "label": "<name>", "type": "Dataset|Field|Sheet|DataType",
      "description": "<brief description>", "confidence": 0.9}}
  ],
  "relations": [
    {{"source": "<entity_id>", "target": "<entity_id>", "relation": "HAS_FIELD|BELONGS_TO_SHEET|HAS_TYPE",
      "confidence": 0.9}}
  ],
  "key_points": [
    {{"content": "<insight about the dataset>", "type": "fact"}}
  ]
}}

Rules:
- Create ONE Dataset entity for the whole workbook / file.
- Create ONE Sheet entity per worksheet (if multiple sheets).
- Create ONE Field entity per column.
- Add DataType entities only for clearly inferred types (e.g. "Date", "Currency", "Boolean").
- Keep relations: Dataset HAS_FIELD Field, Field BELONGS_TO_SHEET Sheet.
- Do not hallucinate columns that are not listed.

## Structural Summary
{structural_text[:6000]}
"""
        try:
            raw = self._call_chat_completion(prompt)
            return self._normalize_result(raw, "tabular_data")
        except Exception as exc:
            logger.warning("Tabular extraction failed: %s", exc)
            return ExtractedKnowledge(
                summary=structural_text[:300],
                tags=["tabular_data"],
                entities=[],
                relations=[],
                key_points=[],
                raw_response={"error": str(exc)},
            )

    def _call_chat_completion(self, prompt: str) -> dict[str, Any]:
        response = self.http_client.post(
            self.base_url,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": self._get_system_prompt()},
                    {"role": "user", "content": prompt},
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0.2,
                "max_tokens": 4096,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        content = payload["choices"][0]["message"]["content"]
        return json.loads(content)

    # ------------------------------------------------------------------
    # Map-Reduce helpers
    # ------------------------------------------------------------------

    def _split_text(self, text: str) -> list[str]:
        """Split *text* into overlapping segments for map-reduce extraction."""
        segments: list[str] = []
        start = 0
        while start < len(text):
            end = min(start + _SEGMENT_SIZE, len(text))
            segments.append(text[start:end])
            if end >= len(text):
                break
            start = end - _SEGMENT_OVERLAP
        return segments

    def _extract_mapreduce(
        self, text: str, doc_type: str, ontology: dict
    ) -> ExtractedKnowledge:
        """Extract knowledge from a long document via map-reduce."""
        segments = self._split_text(text)
        logger.info(
            "Map-reduce: %d segments × ~%d chars each",
            len(segments),
            _SEGMENT_SIZE,
        )

        partials: list[ExtractedKnowledge] = []
        for i, segment in enumerate(segments):
            try:
                prompt = self._build_extraction_prompt(segment, ontology, doc_type)
                raw = self._call_chat_completion(prompt)
                partial = self._normalize_result(raw, doc_type)
                partials.append(partial)
                logger.debug(
                    "Segment %d/%d: %d entities, %d relations",
                    i + 1, len(segments),
                    len(partial.entities), len(partial.relations),
                )
            except Exception as exc:
                logger.warning("Segment %d/%d failed: %s", i + 1, len(segments), exc)

        if not partials:
            # All segments failed — fall back to single-pass on the first window
            logger.warning("All segments failed; falling back to single-pass")
            prompt = self._build_extraction_prompt(text[:_SINGLE_PASS_LIMIT], ontology, doc_type)
            raw = self._call_chat_completion(prompt)
            return self._normalize_result(raw, doc_type)

        return self._merge_extractions(partials)

    def _merge_extractions(
        self, results: list[ExtractedKnowledge]
    ) -> ExtractedKnowledge:
        """Merge partial extractions: deduplicate entities and relations."""
        # Entities — deduplicate by ID (stable: type_label), first occurrence wins
        seen_ids: dict[str, dict] = {}
        for r in results:
            for entity in r.entities:
                eid = entity.get("id", "")
                if eid and eid not in seen_ids:
                    seen_ids[eid] = entity
        merged_entities = list(seen_ids.values())

        # Relations — deduplicate by (source, target, relation) tuple
        seen_rel_keys: set[tuple[str, str, str]] = set()
        merged_relations: list[dict] = []
        for r in results:
            for rel in r.relations:
                key = (
                    rel.get("source", ""),
                    rel.get("target", ""),
                    rel.get("relation", ""),
                )
                if key not in seen_rel_keys:
                    seen_rel_keys.add(key)
                    merged_relations.append(rel)

        # Tags — ordered union, max 20
        seen_tags: set[str] = set()
        merged_tags: list[str] = []
        for r in results:
            for tag in r.tags:
                if tag.lower() not in seen_tags:
                    seen_tags.add(tag.lower())
                    merged_tags.append(tag)
                    if len(merged_tags) >= 20:
                        break

        # Key points — all, capped at 10
        merged_kp = [kp for r in results for kp in r.key_points][:10]

        # Summary — synthesise or take first
        summaries = [r.summary for r in results if r.summary.strip()]
        final_summary = (
            self._synthesize_summary(summaries) if len(summaries) > 1
            else (summaries[0] if summaries else "")
        )

        return ExtractedKnowledge(
            summary=final_summary,
            tags=merged_tags,
            entities=merged_entities,
            relations=merged_relations,
            key_points=merged_kp,
            confidence=min(r.confidence for r in results),
        )

    def _synthesize_summary(self, summaries: list[str]) -> str:
        """Ask the LLM to unify segment summaries into one coherent paragraph."""
        combined = "\n\n".join(
            f"[Part {i + 1}] {s}" for i, s in enumerate(summaries)
        )
        prompt = (
            "The following are summaries of consecutive sections of a single document.\n"
            "Write ONE concise summary (2-3 sentences) capturing the main topic and key conclusions.\n\n"
            f"{combined}\n\n"
            'Return JSON: {"summary": "unified summary here"}'
        )
        try:
            result = self._call_chat_completion(prompt)
            return result.get("summary", summaries[0])
        except Exception:
            return summaries[0]

    def _get_ontology(self, doc_type: str) -> dict:
        """Return the pre-defined rich ontology for *doc_type*.

        Each entry in DOCUMENT_TEMPLATES contains:
        - ``concepts``: list of {type, description} — precise type boundaries
        - ``relations``: list of {relation, source, target, description} — constrained edges
        - ``instructions``: extraction guidance injected into the prompt

        Falls back to DEFAULT_ONTOLOGY for unknown / 'general' types.
        """
        if doc_type in DOCUMENT_TEMPLATES:
            return DOCUMENT_TEMPLATES[doc_type]
        return DEFAULT_ONTOLOGY
    
    def _get_system_prompt(self) -> str:
        """Get system prompt for extraction."""
        return """You are a knowledge extraction expert. Your task is to analyze documents and extract structured knowledge in JSON format.

You must identify:
1. **Summary**: A concise summary of the document (2-3 sentences)
2. **Tags**: 5-10 relevant keywords or tags
3. **Entities**: Important entities mentioned (people, organizations, projects, technologies, concepts, etc.)
4. **Relations**: Relationships between entities
5. **Key Points**: Important facts, conclusions, or insights

Always respond with valid JSON following the specified schema."""
    
    def _build_extraction_prompt(self, text: str, ontology: dict, doc_type: str) -> str:
        """Build an extraction prompt that includes per-type entity descriptions,
        relation source→target constraints, and document-specific instructions."""

        # ── Entity types section ──────────────────────────────────────────────
        concept_lines = []
        for c in ontology.get("concepts", []):
            desc = c.get("description", "")
            concept_lines.append(f"- **{c['type']}**: {desc}")
        concepts_block = "\n".join(concept_lines) if concept_lines else "- Entity: any named item"

        # ── Relation types section (with source → target) ─────────────────────
        relation_lines = []
        for r in ontology.get("relations", []):
            src = r.get("source", "Entity")
            tgt = r.get("target", "Entity")
            desc = r.get("description", "")
            relation_lines.append(f"- **{r['relation']}**: {src} → {tgt}  _{desc}_")
        relations_block = "\n".join(relation_lines) if relation_lines else "- RELATES_TO: Entity → Entity"

        # ── Per-type extraction instructions ─────────────────────────────────
        instructions = ontology.get("instructions", "Extract named, specific entities only.")

        return f"""Analyze the following document and extract structured knowledge.

## Document Type: {doc_type}

## Entity Types  ← use ONLY these; use "Concept" for anything that doesn't fit
{concepts_block}

## Relation Types  ← use ONLY these; respect the source → target direction
{relations_block}

## Extraction Instructions
{instructions}

## Output Format (respond with valid JSON only)
{{
  "summary": "2–3 sentence summary of the document",
  "tags": ["tag1", "tag2"],
  "entities": [
    {{
      "id": "<type_lower>_<label_snake_case>",
      "label": "Display Name",
      "type": "EntityType",
      "description": "One sentence description",
      "confidence": 0.9
    }}
  ],
  "relations": [
    {{
      "source": "<entity_id>",
      "target": "<entity_id>",
      "relation": "RELATION_TYPE",
      "evidence": "brief quote or paraphrase from text"
    }}
  ],
  "key_points": [
    {{
      "content": "Key insight or fact",
      "type": "conclusion|recommendation|fact",
      "confidence": 0.9
    }}
  ]
}}

## Rules
1. Use ONLY the entity types listed above. Unknown types → use "Concept".
2. Use ONLY the relation types listed above; respect the source → target direction.
3. IDs must be stable: lowercase(type) + "_" + lowercase(label with spaces→underscores).
4. Only create relations whose endpoints both exist in the entities list.
5. Only assert relations clearly stated or strongly implied — no hallucination.
6. Set confidence < 0.8 when uncertain; entities below 0.5 will be discarded.

## Document Content
{text}
"""
    
    def _normalize_result(self, result: dict, doc_type: str) -> ExtractedKnowledge:
        """Normalize, validate, and quality-filter the raw LLM extraction result."""
        entities = result.get("entities", [])
        relations = result.get("relations", [])

        # Ensure every entity has a stable ID
        for entity in entities:
            if "id" not in entity or not entity["id"]:
                label = entity.get("label", "unknown")
                etype = entity.get("type", "Concept")
                entity["id"] = f"{etype.lower()}_{label.lower().replace(' ', '_')}"

        # ⑤ Quality filter: drop entities below confidence threshold
        entities = [
            e for e in entities
            if float(e.get("confidence", 1.0)) >= MIN_ENTITY_CONFIDENCE
        ]

        # ⑤ Quality filter: drop relations whose endpoints were removed
        entity_ids = {e["id"] for e in entities}
        valid_relations = [
            rel for rel in relations
            if rel.get("source", "") in entity_ids and rel.get("target", "") in entity_ids
        ]

        return ExtractedKnowledge(
            summary=result.get("summary", ""),
            tags=result.get("tags", []),
            entities=entities,
            relations=valid_relations,
            key_points=result.get("key_points", []),
            confidence=result.get("confidence", 0.8),
            raw_response=result,
        )
    
    def _mock_extraction(self, text: str, doc_type: str) -> ExtractedKnowledge:
        """Return mock extraction when no LLM available."""
        # Simple rule-based extraction
        words = text.lower().split()
        word_freq = {}
        for word in words:
            if len(word) > 4:
                word_freq[word] = word_freq.get(word, 0) + 1
        
        tags = sorted(word_freq.keys(), key=lambda w: word_freq[w], reverse=True)[:8]
        
        return ExtractedKnowledge(
            summary=text[:200] + "..." if len(text) > 200 else text,
            tags=tags,
            entities=[],
            relations=[],
            key_points=[],
            confidence=0.5,
            raw_response={"mock": True},
        )
    
    def get_document_type_suggestions(self, filename: str, text_preview: str) -> str:
        """Suggest document type based on filename and content."""
        filename_lower = filename.lower()
        
        if any(kw in filename_lower for kw in ["paper", "论文", "research", "study"]):
            return "academic_paper"
        if any(kw in filename_lower for kw in ["api", "技术", "tech", "doc", "readme"]):
            return "technical_doc"
        if any(kw in filename_lower for kw in ["meeting", "会议", "minutes"]):
            return "meeting_minutes"
        if any(kw in filename_lower for kw in ["report", "报告", "月报", "周报"]):
            return "report"
        
        return "general"
