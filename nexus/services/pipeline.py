"""Pipeline - Complete semantic processing pipeline."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from nexus.cloudreve.client import CloudreveClient
from nexus.graph.neo4j_store import Neo4jGraphStore
from nexus.models import GraphEdge, GraphNode, KnowledgeLayer, SemanticDocument, TextChunk
from nexus.repositories.base import NexusRepository
from nexus.services.content_parser import ContentParserService, ParsedContent
from nexus.services.embedding import BigModelEmbeddingService, DeterministicEmbeddingService
from nexus.services.document_classifier import DocumentClassifier
from nexus.services.file_gate import FileGate
from nexus.services.kgraph_context import KGraphContextBuilder
from nexus.services.hyper_extract_bridge import HyperExtractRuntimeBridge
from nexus.services.knowledge_extractor import ExtractedKnowledge, KnowledgeExtractor
from nexus.settings import Settings
from nexus.vector.milvus_store import MilvusChunk, MilvusVectorStore


logger = logging.getLogger("nexus.pipeline")


@dataclass
class ProcessingResult:
    """Result of processing a file."""
    uri: str
    filename: str
    success: bool
    summary: str = ""
    tags: list[str] = field(default_factory=list)
    entities_count: int = 0
    relations_count: int = 0
    chunks_count: int = 0
    stage: str = "queued"
    error_code: str | None = None
    error: str | None = None
    processing_time_ms: int = 0
    skipped: bool = False
    skip_reason: str | None = None
    kgraph_context: dict[str, Any] = field(default_factory=dict)


class SemanticPipeline:
    """Complete semantic processing pipeline.
    
    Flow:
    1. Download file from Cloudreve
    2. Parse content (PDF/Word/Text)
    3. Extract knowledge (LLM + knowledge-graph skill)
    4. Store in Neo4j (graph) + Milvus (vectors)
    """
    
    def __init__(
        self,
        cloudreve_token: str | None,
        settings: Settings | None = None,
        repository: NexusRepository | None = None,
        enable_neo4j: bool = True,
        enable_milvus: bool = True,
    ) -> None:
        self.settings = settings or Settings.from_env()
        self.cloudreve_client = CloudreveClient(token=cloudreve_token)
        self.file_gate = FileGate()

        # Build classifier agent when an API key is available (graceful degradation)
        _classifier_agent = None
        _llm_api_key = self.settings.zhipu_api_key or self.settings.openai_api_key
        if _llm_api_key:
            try:
                from nexus.agents.classifier_agent import create_classifier_agent  # lazy
                _classifier_agent = create_classifier_agent(self.settings)
                logger.info("Classifier agent (Agent1) initialised")
            except Exception as _exc:
                logger.warning("Could not initialise classifier agent: %s", _exc)

        self.document_classifier = DocumentClassifier(agent=_classifier_agent)
        self.kgraph_context_builder = KGraphContextBuilder()
        self.hyper_extract_bridge = HyperExtractRuntimeBridge(
            enabled=self.settings.hyper_extract_runtime_enabled,
            max_templates=self.settings.hyper_extract_runtime_max_templates,
        )
        self.content_parser = ContentParserService()
        self.knowledge_extractor = KnowledgeExtractor(
            api_key=self.settings.zhipu_api_key or self.settings.openai_api_key,
            model=self.settings.llm_model,
            base_url=self.settings.llm_base_url,
        )
        self.repository = repository

        # Embedding service — prefer real BigModel embeddings when API key is present
        embedding_api_key = self.settings.zhipu_api_key or self.settings.openai_api_key
        if embedding_api_key:
            self.embedding_service: BigModelEmbeddingService | DeterministicEmbeddingService = BigModelEmbeddingService(
                api_key=embedding_api_key,
                model=self.settings.embedding_model,
                dimensions=self.settings.embedding_dimensions,
                base_url=self.settings.embedding_base_url,
            )
            logger.info(
                "Embedding: BigModel %s (%d-dim)", self.settings.embedding_model, self.settings.embedding_dimensions
            )
        else:
            self.embedding_service = DeterministicEmbeddingService(dimensions=64)
            logger.info("Embedding: deterministic fallback (64-dim, no API key)")

        # Storage backends
        self.neo4j_store: Neo4jGraphStore | None = None
        self.milvus_store: MilvusVectorStore | None = None

        if enable_neo4j and self.settings.neo4j_uri:
            try:
                self.neo4j_store = Neo4jGraphStore(
                    uri=self.settings.neo4j_uri,
                    user=self.settings.neo4j_user,
                    password=self.settings.neo4j_password,
                )
                logger.info("Neo4j connection established")
            except Exception as e:
                logger.warning(f"Failed to connect to Neo4j: {e}")

        # Milvus is opt-in: requires both enable_milvus=True AND VECTOR_BACKEND=milvus
        vector_backend = self.settings.vector_backend.lower()
        if enable_milvus and vector_backend == "milvus" and self.settings.milvus_host:
            try:
                self.milvus_store = MilvusVectorStore(
                    host=self.settings.milvus_host,
                    port=self.settings.milvus_port,
                    dimensions=self.embedding_service.dimensions,
                )
                self.milvus_store.ensure_collection()
                logger.info("Milvus connection established (dim=%d)", self.embedding_service.dimensions)
            except Exception as e:
                logger.warning(f"Failed to connect to Milvus: {e}")
        elif vector_backend != "milvus":
            logger.info("Vector store disabled (VECTOR_BACKEND=%s); skipping embedding", vector_backend)
    
    def process_file(
        self,
        uri: str,
        requested_by: str = "system",
        doc_type: str | None = None,
    ) -> ProcessingResult:
        """Process a single file through the complete pipeline."""
        start_time = datetime.now(UTC)
        stage = "download"
        
        try:
            # Step 0: Gate check — decide before downloading anything
            filename = uri.split("/")[-1] or "unknown"
            gate = self.file_gate.check(filename)
            if not gate.should_process:
                logger.info("Gate skipped %s: %s", uri, gate.reason)
                return ProcessingResult(
                    uri=uri,
                    filename=filename,
                    success=True,
                    stage="gate",
                    skipped=True,
                    skip_reason=gate.reason,
                )

            # Step 1: Download file from Cloudreve
            logger.info(f"Downloading file: {uri}")
            content = self._download_file(uri)
            
            # Step 2: Parse content
            stage = "parse"
            logger.info(f"Parsing content: {filename}")
            parsed = self._parse_content(content, filename)
            
            # Auto-classify document type and extraction strategy
            classification = self.document_classifier.classify(
                filename=filename,
                content_preview=parsed.text[:600],
                file_type=parsed.file_type,
            )
            if doc_type is None:
                doc_type = classification.doc_type
                effective_classification = classification
            else:
                effective_classification = replace(
                    classification,
                    doc_type=doc_type,
                    signals=[*classification.signals, f"override:doc_type={doc_type}"],
                )
            strategy = classification.strategy
            logger.info(
                "Classified '%s' → type=%s strategy=%s confidence=%.2f signals=%s",
                filename, doc_type, strategy, classification.confidence,
                classification.signals[:3],
            )

            kgraph_context = self.kgraph_context_builder.build(
                uri=uri,
                parsed=parsed,
                classification=effective_classification,
            )
            extraction_text = self.kgraph_context_builder.render_for_extraction(kgraph_context)
            if not extraction_text.strip():
                extraction_text = parsed.text
            kgraph_context["candidate_extractions"] = self.hyper_extract_bridge.extract_candidates(
                text=extraction_text,
                selected_templates=kgraph_context.get("classification", {}).get("selected_templates", []),
            )

            # Step 3: Extract knowledge
            stage = "semantic_extract"
            logger.info(f"Extracting knowledge (type: {doc_type}, strategy: {strategy})")
            knowledge = self._extract_knowledge(extraction_text, doc_type, strategy)
            
            # Step 4: Store in databases
            stage = "persist"
            logger.info("Storing knowledge")
            self._store_knowledge(uri, knowledge, parsed, requested_by)
            
            processing_time = int((datetime.now(UTC) - start_time).total_seconds() * 1000)
            
            return ProcessingResult(
                uri=uri,
                filename=filename,
                success=True,
                summary=knowledge.summary,
                tags=knowledge.tags,
                entities_count=len(knowledge.entities),
                relations_count=len(knowledge.relations),
                chunks_count=len(parsed.chunks),
                stage="persist",
                processing_time_ms=processing_time,
                kgraph_context=kgraph_context,
            )
        
        except Exception as e:
            logger.error(f"Failed to process {uri}: {e}")
            return ProcessingResult(
                uri=uri,
                filename=uri.split("/")[-1] or "unknown",
                success=False,
                stage=stage,
                error_code=f"{stage}_failed",
                error=str(e),
            )
    
    def _download_file(self, uri: str) -> bytes:
        """Download file content from Cloudreve."""
        return self.cloudreve_client.get_file_content_sync(uri)
    
    def _parse_content(self, content: bytes, filename: str) -> ParsedContent:
        """Parse file content."""
        return self.content_parser.parse(content, filename)
    
    def _extract_knowledge(self, text: str, doc_type: str, strategy: str = "llm_extract") -> ExtractedKnowledge:
        """Extract structured knowledge from text."""
        return self.knowledge_extractor.extract(text, doc_type, strategy=strategy)
    
    def _store_knowledge(
        self,
        uri: str,
        knowledge: ExtractedKnowledge,
        parsed: ParsedContent,
        requested_by: str,
    ) -> None:
        """Store extracted knowledge in Neo4j and Milvus."""
        
        # Store file node in Neo4j
        if self.repository:
            document = SemanticDocument(
                uri=uri,
                summary=knowledge.summary,
                tags=knowledge.tags,
                entities=[entity.get("label", "") for entity in knowledge.entities if entity.get("label")],
                chunks=[
                    TextChunk(id=f"{uri}#chunk-{index}", text=chunk_text, index=index)
                    for index, chunk_text in enumerate(parsed.chunks, start=1)
                    if chunk_text.strip()
                ],
                requested_by=requested_by,
            )
            self.repository.add_document(document)

        # Store file node in Neo4j
        if self.neo4j_store:
            file_node = GraphNode(
                id=f"file:{uri}",
                uri=uri,
                label=uri.split("/")[-1],
                summary=knowledge.summary,
                layer=KnowledgeLayer.L2,  # Default to team knowledge
                accessible=True,
                properties={
                    "tags": knowledge.tags,
                    "doc_type": parsed.file_type,
                    "pages": parsed.metadata.get("pages", 0),
                    "processed_at": datetime.now(UTC).isoformat(),
                },
            )
            self.neo4j_store.upsert_file_node(file_node)
            
            # Store entities and relations
            entity_uri_map: dict[str, str] = {}
            
            for entity in knowledge.entities:
                entity_id = entity.get("id", str(uuid4()))
                entity_uri = f"entity://{entity_id}"
                entity_uri_map[entity_id] = entity_uri
                
                entity_node = GraphNode(
                    id=entity_id,
                    uri=entity_uri,
                    label=entity.get("label", "Unknown"),
                    summary=entity.get("description", ""),
                    layer=KnowledgeLayer.L2,
                    accessible=True,
                    properties={
                        "type": entity.get("type", "Concept"),
                        "confidence": entity.get("confidence", 0.8),
                    },
                )
                self.neo4j_store.upsert_file_node(entity_node)
                
                # Create relation: file MENTIONS entity
                mention_edge = GraphEdge(
                    id=f"edge:{uri}:{entity_id}",
                    source=f"file:{uri}",
                    target=entity_id,
                    relation="MENTIONS",
                    layer=KnowledgeLayer.L2,
                    owner_scope=requested_by,
                    source_file_uri=uri,
                    visibility="team",
                )
                self.neo4j_store.upsert_edge(mention_edge, uri, entity_uri)
            
            # Store entity-entity relations
            for rel in knowledge.relations:
                source_id = rel.get("source", "")
                target_id = rel.get("target", "")
                
                if source_id in entity_uri_map and target_id in entity_uri_map:
                    edge = GraphEdge(
                        id=f"edge:{source_id}:{target_id}:{rel.get('relation', 'RELATES_TO')}",
                        source=source_id,
                        target=target_id,
                        relation=rel.get("relation", "RELATES_TO"),
                        layer=KnowledgeLayer.L2,
                        owner_scope=requested_by,
                        source_file_uri=uri,
                        visibility="team",
                        properties={"evidence": rel.get("evidence", "")},
                    )
                    self.neo4j_store.upsert_edge(
                        edge,
                        entity_uri_map[source_id],
                        entity_uri_map[target_id],
                    )
        
        # Store chunks in Milvus — batch-embed all chunks in one API call
        if self.milvus_store:
            # Filter empty chunks first to avoid wasting embed quota
            valid_chunks = [
                (i, t) for i, t in enumerate(parsed.chunks) if t.strip()
            ]
            if valid_chunks:
                texts = [t for _, t in valid_chunks]
                # embed_batch splits internally at MAX_BATCH_SIZE (64); one call per ≤64 texts
                vectors = self.embedding_service.embed_batch(texts)
                chunks_to_store = [
                    MilvusChunk(
                        chunk_id=f"{uri}#chunk-{i}",
                        uri=uri,
                        text=t[:2000],  # Milvus text field limit (chunks are ~1000 chars)
                        created_by=requested_by,
                        visibility="team",
                        vector=v,
                    )
                    for (i, t), v in zip(valid_chunks, vectors)
                ]
                self.milvus_store.upsert_chunks(chunks_to_store)
                logger.debug(
                    "Embedded %d chunks for %s (%d API calls)",
                    len(chunks_to_store), uri,
                    -(-len(texts) // 64),  # ceil(n/64)
                )
    
    def close(self) -> None:
        """Close connections."""
        if self.neo4j_store:
            self.neo4j_store.close()
