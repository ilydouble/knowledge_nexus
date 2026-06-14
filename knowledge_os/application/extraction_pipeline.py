"""CandidateExtractionPipeline — Phase 2 pipeline.

Reads a file (local path, uploaded bytes, or Cloudreve URI), parses it,
classifies it, runs the LLM extractor, persists file-level semantic metadata
to the relational store, and saves the results as a *candidate* batch (never
committed directly to Neo4j).
Pi-Agent then reviews/edits/commits the candidates.
"""

from __future__ import annotations

import hashlib
import logging
import mimetypes
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from knowledge_os.application.services import CandidateExtractionService
from knowledge_os.domain.models import CandidateBatch, CandidateExtractionRequest
from knowledge_os.infrastructure.store import KnowledgeOSStore

if TYPE_CHECKING:
    from core.cloudreve.client import CloudreveClient
    from core.repositories.base import NexusRepository
    from core.services.content_parser import ContentParserService
    from core.services.document_classifier import DocumentClassifier
    from core.services.knowledge_extractor import KnowledgeExtractor
    from core.settings import Settings
    from core.storage.artifact_store import ArtifactStore
    from core.vector.milvus_store import MilvusVectorStore

logger = logging.getLogger("knowledge_os.extraction_pipeline")

# Maximum characters stored in semantic_chunks.text (display preview only).
# Full parsed text is NOT persisted in Postgres; callers re-read from the
# source file referenced by semantic_documents.parsed_text_key.
_CHUNK_PREVIEW_MAX: int = 400


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
    """Option-C pipeline: read → parse → classify → LLM → candidate batch.

    File source priority:
    1. *content* bytes passed directly by the caller (uploaded file, pre-read).
    2. local:// / file:// URI → read from local filesystem.
    3. cloudreve:// URI → download via CloudreveClient (optional).

    Does NOT write to Neo4j.  Pi-Agent decides what to commit.
    Immediately writes file-level semantic metadata to *repository*
    (semantic_documents + semantic_chunks) so the relational store is
    populated right after extraction, regardless of commit status.
    """

    def __init__(
        self,
        content_parser: ContentParserService,
        classifier: DocumentClassifier,
        extractor: KnowledgeExtractor,
        store: KnowledgeOSStore,
        repository: NexusRepository,
        cloudreve_client: CloudreveClient | None = None,
        artifact_store: ArtifactStore | None = None,
        embedding_service: Any | None = None,
        milvus_store: MilvusVectorStore | None = None,
    ) -> None:
        self.cloudreve_client = cloudreve_client
        self.content_parser = content_parser
        self.classifier = classifier
        self.extractor = extractor
        self.store = store
        self.repository = repository
        self.artifact_store = artifact_store
        self.embedding_service = embedding_service
        self.milvus_store = milvus_store

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
            Source URI used for provenance.
            - ``cloudreve://…`` → download from Cloudreve (token required).
            - ``local:///abs/path`` or ``file:///abs/path`` → read from disk.
            - Any other scheme → must supply *content* directly.
        content:
            Pre-fetched file bytes. When provided the fetch step is skipped.
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

        # ── Resolve content bytes ──────────────────────────────────────────────
        if content is None:
            if uri.startswith("local://") or uri.startswith("file://"):
                content, filename = self._read_local(uri, filename)
            elif uri.startswith("cloudreve://"):
                if self.cloudreve_client is None:
                    raise ExtractionInputError(
                        "Cloudreve URI requested but no Cloudreve token is configured. "
                        "Use a local:// URI or supply file content directly."
                    )
                logger.info("Downloading %s from Cloudreve", uri)
                content = self.cloudreve_client.get_file_content_sync(uri)
            else:
                raise ExtractionInputError(
                    f"Cannot fetch content for URI '{uri}'. "
                    "Supply content directly or use a local:// / cloudreve:// URI."
                )
        else:
            logger.info("Using pre-supplied content for %s (%d bytes)", uri, len(content))

        # ── Parse ─────────────────────────────────────────────────────────────
        logger.info("Parsing %s", filename)
        parsed = self.content_parser.parse(content, filename)

        # ── Classify ──────────────────────────────────────────────────────────
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

        # ── Write full parsed text to object storage ──────────────────────────
        # parsed_text_key will be updated to s3:// if MinIO is available,
        # otherwise it stays as the source URI (set later in upsert_document).
        parsed_text_key: str | None = None
        if self.artifact_store is not None:
            content_hash_hex = hashlib.sha256(content).hexdigest()
            try:
                s3_uri = self.artifact_store.write(content_hash_hex, filename, parsed.text)
                if s3_uri:  # NullArtifactStore returns ""
                    parsed_text_key = s3_uri
                    logger.info("Full parsed text stored at %s", s3_uri)
            except Exception as exc:
                warnings.append(f"Artifact store write failed (non-fatal): {exc}")
                logger.warning("Artifact store write failed for %s: %s", uri, exc)

        # Build extraction text; prepend instructions as a hint for the LLM
        extraction_text = parsed.text
        if instructions:
            extraction_text = f"[Extraction instructions: {instructions}]\n\n{parsed.text}"

        # ── LLM extraction ────────────────────────────────────────────────────
        logger.info("LLM extraction for %s (strategy=%s)", uri, strategy)
        knowledge = self.extractor.extract(extraction_text, doc_type, strategy=strategy)

        if not knowledge.entities and not knowledge.relations:
            warnings.append("LLM returned no entities or relations; batch will be empty.")

        # ── Persist semantic archive (relational store) ───────────────────────
        source_type = "cloudreve" if uri.startswith("cloudreve://") else "local"
        mime_type, _ = mimetypes.guess_type(filename)
        content_hash = hashlib.sha256(content).hexdigest()
        chunk_count = len(knowledge.segment_results)

        try:
            self.repository.upsert_document({
                "uri": uri,
                "summary": knowledge.summary,
                "tags": knowledge.tags,
                "entities": knowledge.entities,
                "requested_by": requested_by,
                "status": "active",
                "content_hash": content_hash,
                "filename": filename,
                "source_type": source_type,
                "mime_type": mime_type,
                "size_bytes": len(content),
                "doc_type": doc_type,
                "chunk_count": chunk_count,
                # s3:// URI when MinIO is available; local:// when the
                # LocalArtifactStore fallback was used; source URI only as a
                # last resort (e.g. if both writes failed due to disk issues).
                "parsed_text_key": parsed_text_key or uri,
            })

            if knowledge.segment_results:
                chunk_ids = [str(uuid.uuid4()) for _ in knowledge.segment_results]
                chunks = [
                    {
                        "id": chunk_ids[i],
                        "chunk_index": seg.chunk_index,
                        # Store only a short preview — full text is at parsed_text_key.
                        "text": seg.text[:_CHUNK_PREVIEW_MAX],
                        "summary": seg.summary,
                        "tags": seg.tags,
                        "entities": seg.entities,
                        "char_start": seg.char_start,
                        "char_end": seg.char_end,
                    }
                    for i, seg in enumerate(knowledge.segment_results)
                ]
                self.repository.replace_chunks(uri, chunks)

            logger.info(
                "Semantic archive persisted for %s: %d chunk(s)", uri, chunk_count
            )
        except Exception as exc:
            warnings.append(f"Semantic archive write failed (non-fatal): {exc}")
            logger.warning("Semantic archive write failed for %s: %s", uri, exc)

        # ── Embed chunks and upsert to Milvus (non-fatal) ────────────────────
        if (
            self.embedding_service is not None
            and self.milvus_store is not None
            and knowledge.segment_results
        ):
            try:
                from core.vector.milvus_store import MilvusChunk
                # Use full segment text for embeddings (not the 400-char preview).
                # Milvus VARCHAR field allows up to 2048 chars.
                _MILVUS_TEXT_MAX = 2048
                seg_texts = [seg.text[:_MILVUS_TEXT_MAX] for seg in knowledge.segment_results]
                vectors = self.embedding_service.embed_batch(seg_texts)
                milvus_chunks = [
                    MilvusChunk(
                        chunk_id=str(uuid.uuid4()),
                        uri=uri,
                        text=seg_texts[i],
                        created_by=requested_by,
                        visibility="team",
                        vector=vectors[i],
                    )
                    for i in range(len(knowledge.segment_results))
                ]
                # Clear all previous vectors for this URI before inserting new
                # ones so re-extraction never leaves stale chunks in Milvus.
                self.milvus_store.delete_chunks_by_uri(uri)
                self.milvus_store.upsert_chunks(milvus_chunks)
                logger.info("Milvus upsert: %d chunks for %s", len(milvus_chunks), uri)
            except Exception as exc:
                warnings.append(f"Milvus upsert failed (non-fatal): {exc}")
                logger.warning("Milvus upsert failed for %s: %s", uri, exc)

        # ── Convert ExtractedKnowledge → candidate items ──────────────────────
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

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _read_local(uri: str, fallback_filename: str) -> tuple[bytes, str]:
        """Read a ``local://`` or ``file://`` URI from the local filesystem.

        URI formats accepted:
        - ``local:///absolute/path/to/file.pdf``
        - ``local://relative/path/to/file.pdf``  (relative to cwd)
        - ``file:///absolute/path/to/file.pdf``
        """
        # Strip scheme prefix
        if uri.startswith("local://"):
            raw_path = uri[len("local://"):]
        elif uri.startswith("file://"):
            raw_path = uri[len("file://"):]
        else:
            raw_path = uri

        path = Path(raw_path)
        if not path.is_absolute():
            path = Path.cwd() / path
        if not path.exists():
            raise ExtractionInputError(f"Local file not found: {path}")
        if not path.is_file():
            raise ExtractionInputError(f"Path is not a file: {path}")

        logger.info("Reading local file %s", path)
        content = path.read_bytes()
        filename = path.name or fallback_filename
        return content, filename


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
    repository: Any | None = None,
    artifact_store: Any | None = None,
    embedding_service: Any | None = None,
    milvus_store: Any | None = None,
) -> CandidateExtractionPipeline | None:
    """Build a pipeline from settings.  Returns None if LLM API key is missing.

    Cloudreve is optional: the pipeline is built regardless of whether a
    Cloudreve token is present.  Cloudreve downloads are only attempted when
    a ``cloudreve://`` URI is requested at runtime.

    Parameters
    ----------
    artifact_store:
        Optional ``ArtifactStore`` for persisting full parsed text to object
        storage (MinIO).  When *None* or a ``NullArtifactStore``, the full
        text is not persisted and ``parsed_text_key`` falls back to the source
        URI.
    embedding_service:
        Optional embedding service (``BigModelEmbeddingService``).  When
        provided, chunk texts are embedded and upserted into Milvus, and the
        ``KnowledgeExtractor`` uses semantic template matching + dedup.
    milvus_store:
        Optional ``MilvusVectorStore``.  Chunks are upserted here after each
        extraction run if *embedding_service* is also provided.
    """
    from core.cloudreve.client import CloudreveClient
    from core.cloudreve.oauth import CloudreveOAuthTokenStore
    from core.repositories.memory import InMemoryRepository
    from core.services.content_parser import ContentParserService
    from core.services.document_classifier import DocumentClassifier
    from core.services.knowledge_extractor import KnowledgeExtractor

    api_key = settings.zhipu_api_key or settings.openai_api_key
    if not api_key:
        logger.warning("No LLM API key configured; CandidateExtractionPipeline unavailable.")
        return None

    # Cloudreve is optional — only wire it in when a token is available
    cloudreve_client: CloudreveClient | None = None
    try:
        tokens = CloudreveOAuthTokenStore(settings.cloudreve_token_store_path).load()
        access_token = tokens.get("access_token") or settings.cloudreve_access_token
        if access_token:
            cloudreve_client = CloudreveClient(token=access_token)
        else:
            logger.info(
                "No Cloudreve access token configured; Cloudreve downloads disabled. "
                "Local file analysis remains fully available."
            )
    except Exception as exc:
        logger.warning("Could not load Cloudreve token store: %s", exc)

    # Fall back to an in-memory no-op repository when none is provided
    repo = repository if repository is not None else InMemoryRepository()

    # Semantic template matching and two-stage extraction are gated behind
    # HYPER_EXTRACT_RUNTIME_ENABLED.  The embedding_service is ALSO passed to
    # the pipeline itself (unconditionally) for Milvus chunk upsert — those
    # are separate concerns.
    hyper_enabled = settings.hyper_extract_runtime_enabled

    return CandidateExtractionPipeline(
        content_parser=ContentParserService(),
        classifier=DocumentClassifier(),
        extractor=KnowledgeExtractor(
            api_key=api_key,
            model=settings.llm_model,
            base_url=settings.llm_base_url,
            max_workers=settings.llm_max_workers,
            two_stage_extraction=hyper_enabled,
            # Semantic template matching requires embedding service AND the
            # hyper-extract flag; never enabled just because embeddings exist.
            embedding_service=embedding_service if hyper_enabled else None,
            template_top_k=settings.hyper_extract_runtime_max_templates,
        ),
        store=store,
        repository=repo,
        cloudreve_client=cloudreve_client,
        artifact_store=artifact_store,
        # Always pass embedding_service to the pipeline so Milvus upsert works
        # regardless of whether Hyper-Extract is turned on.
        embedding_service=embedding_service,
        milvus_store=milvus_store,
    )
