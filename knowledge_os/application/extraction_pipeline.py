"""CandidateExtractionPipeline — Phase 2 pipeline.

Downloads a Cloudreve file (or uses pre-supplied bytes), parses it,
classifies it, runs the LLM extractor, and stores the results as a
*candidate* batch (never committed directly to Neo4j).
Pi-Agent then reviews/edits/commits the candidates.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from knowledge_os.application.services import CandidateExtractionService
from knowledge_os.domain.models import CandidateBatch, CandidateExtractionRequest
from knowledge_os.infrastructure.store import KnowledgeOSStore

if TYPE_CHECKING:
    from core.cloudreve.client import CloudreveClient
    from core.services.content_parser import ContentParserService
    from core.services.document_classifier import DocumentClassifier
    from core.services.knowledge_extractor import KnowledgeExtractor
    from core.settings import Settings

logger = logging.getLogger("knowledge_os.extraction_pipeline")


class ExtractionInputError(ValueError):
    """Raised for caller-side input problems (e.g. an unprocessable file).

    Subclasses ``ValueError`` so existing handlers keep working, but lets the
    API layer distinguish genuine 400 input errors from internal failures such
    as ``json.JSONDecodeError`` (also a ``ValueError``), which must surface as
    500.
    """


@dataclass
class ExtractionPipelineResult:
    batch: CandidateBatch
    doc_type: str
    entities_count: int
    relations_count: int
    warnings: list[str] = field(default_factory=list)


class CandidateExtractionPipeline:
    """Option-C pipeline: download → parse → classify → LLM → candidate batch.

    Does NOT write to Neo4j.  Pi-Agent decides what to commit.
    """

    def __init__(
        self,
        cloudreve_client: CloudreveClient,
        content_parser: ContentParserService,
        classifier: DocumentClassifier,
        extractor: KnowledgeExtractor,
        store: KnowledgeOSStore,
    ) -> None:
        self.cloudreve_client = cloudreve_client
        self.content_parser = content_parser
        self.classifier = classifier
        self.extractor = extractor
        self.store = store

    def run(
        self,
        uri: str,
        *,
        content: bytes | None = None,
        filename: str | None = None,
        instructions: str | None = None,
        requested_by: str = "pi-agent",
        parent_batch_id: str | None = None,
        template_ids: list[str] | None = None,
    ) -> ExtractionPipelineResult:
        """Run the extraction pipeline.

        Parameters
        ----------
        uri:
            Source URI used for provenance. For Cloudreve files use
            ``cloudreve://…``. For locally supplied content you may pass any
            stable identifier such as ``local://my-report.md``.
        content:
            Pre-fetched file bytes. When provided the Cloudreve download step
            is skipped entirely, so *uri* does not need to be a reachable
            Cloudreve path. This is the entry point for locally generated
            reports and uploaded files.
        filename:
            Override for the filename used during parsing and gate-checks.
            Defaults to the last path component of *uri*.
        """
        from core.services.file_gate import FileGate

        filename = filename or (uri.split("/")[-1] or "unknown")
        warnings: list[str] = []

        # Gate check — skip binary/media files early
        gate = FileGate().check(filename)
        if not gate.should_process:
            raise ExtractionInputError(f"File skipped by gate: {gate.reason}")

        # Download — skip when the caller already supplied bytes
        if content is None:
            logger.info("Downloading %s", uri)
            content = self.cloudreve_client.get_file_content_sync(uri)
        else:
            logger.info("Using pre-supplied content for %s (%d bytes)", uri, len(content))

        # Parse
        logger.info("Parsing %s", filename)
        parsed = self.content_parser.parse(content, filename)

        # Classify
        classification = self.classifier.classify(
            filename=filename,
            content_preview=parsed.text[:600],
            file_type=parsed.file_type,
        )
        doc_type = classification.doc_type
        strategy = classification.strategy
        logger.info(
            "Classified '%s' → type=%s strategy=%s confidence=%.2f",
            filename, doc_type, strategy, classification.confidence,
        )

        # Build extraction text; prepend instructions as a hint for the LLM
        extraction_text = parsed.text
        if instructions:
            extraction_text = f"[Extraction instructions: {instructions}]\n\n{parsed.text}"

        # LLM extraction
        logger.info("LLM extraction for %s (strategy=%s)", uri, strategy)
        knowledge = self.extractor.extract(extraction_text, doc_type, strategy=strategy)

        if not knowledge.entities and not knowledge.relations:
            warnings.append("LLM returned no entities or relations; batch will be empty.")

        # Convert ExtractedKnowledge → candidate items
        candidate_entities = [_entity_to_candidate(e) for e in knowledge.entities]
        candidate_relations = [_relation_to_candidate(r) for r in knowledge.relations]

        # Store as candidate batch (no Neo4j write)
        service = CandidateExtractionService(self.store)
        batch = service.run(
            CandidateExtractionRequest(
                uri=uri,
                requested_by=requested_by,
                instructions=instructions,
                parent_batch_id=parent_batch_id,
                template_ids=list(template_ids or []),
                candidate_entities=candidate_entities,
                candidate_relations=candidate_relations,
            )
        )

        logger.info(
            "Candidate batch %s created: %d entities, %d relations",
            batch.id, len(candidate_entities), len(candidate_relations),
        )
        return ExtractionPipelineResult(
            batch=batch,
            doc_type=doc_type,
            entities_count=len(candidate_entities),
            relations_count=len(candidate_relations),
            warnings=warnings,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _entity_to_candidate(entity: dict[str, Any]) -> dict[str, Any]:
    label = entity.get("label") or entity.get("name") or "Unknown"
    return {
        "id": entity.get("id") or str(label).strip().lower().replace(" ", "_"),
        "label": str(label),
        "type": entity.get("type") or "Concept",
        "confidence": float(entity.get("confidence", 0.8)),
        "description": entity.get("description") or "",
        "source_span": entity.get("source_span") or {},
    }


def _relation_to_candidate(rel: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": str(rel.get("source") or rel.get("from") or ""),
        "target": str(rel.get("target") or rel.get("to") or ""),
        "relation": str(rel.get("relation") or rel.get("type") or "RELATES_TO"),
        "confidence": float(rel.get("confidence", 0.8)),
        "evidence": rel.get("evidence") or "",
        "source_span": rel.get("source_span") or {},
    }


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def build_candidate_extraction_pipeline(
    settings: Settings,
    store: KnowledgeOSStore,
) -> CandidateExtractionPipeline | None:
    """Build a pipeline from settings.  Returns None if prerequisites are missing."""
    from core.cloudreve.client import CloudreveClient
    from core.cloudreve.oauth import CloudreveOAuthTokenStore
    from core.services.content_parser import ContentParserService
    from core.services.document_classifier import DocumentClassifier
    from core.services.knowledge_extractor import KnowledgeExtractor

    api_key = settings.zhipu_api_key or settings.openai_api_key
    if not api_key:
        logger.warning("No LLM API key configured; CandidateExtractionPipeline unavailable.")
        return None

    tokens = CloudreveOAuthTokenStore(settings.cloudreve_token_store_path).load()
    access_token = tokens.get("access_token") or settings.cloudreve_access_token
    if not access_token:
        logger.warning("No Cloudreve access token; CandidateExtractionPipeline unavailable.")
        return None

    return CandidateExtractionPipeline(
        cloudreve_client=CloudreveClient(token=access_token),
        content_parser=ContentParserService(),
        classifier=DocumentClassifier(),
        extractor=KnowledgeExtractor(
            api_key=api_key,
            model=settings.llm_model,
            base_url=settings.llm_base_url,
            max_workers=settings.llm_max_workers,
        ),
        store=store,
    )
