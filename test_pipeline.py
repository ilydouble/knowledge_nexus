#!/usr/bin/env python3
"""Test script for semantic processing pipeline."""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from nexus.services.content_parser import ContentParserService
from nexus.services.knowledge_extractor import KnowledgeExtractor
from nexus.services.pipeline import SemanticPipeline
from nexus.settings import Settings


def test_content_parser():
    """Test content parsing."""
    print("\n=== Testing Content Parser ===")
    
    parser = ContentParserService()
    
    # Test text parsing
    text_content = b"Hello, this is a test document.\n\nIt has multiple paragraphs."
    result = parser.parse(text_content, "test.txt", "text/plain")
    print(f"Text parsing: {result.file_type}, chunks: {len(result.chunks)}")
    
    # Test supported types
    supported = parser.get_supported_types()
    print(f"Supported MIME types: {supported['mime_types'][:5]}...")
    print(f"Supported extensions: {supported['extensions']}")


def test_knowledge_extractor():
    """Test knowledge extraction."""
    print("\n=== Testing Knowledge Extractor ===")
    
    settings = Settings.from_env()
    extractor = KnowledgeExtractor(api_key=settings.openai_api_key)
    
    # Test with sample text
    sample_text = """
    Project Alpha is a machine learning project led by John Smith at TechCorp.
    The project uses TensorFlow and PyTorch frameworks.
    Key achievements include 95% accuracy on the test dataset.
    The team consists of 5 engineers working remotely.
    """
    
    print("Extracting knowledge from sample text...")
    result = extractor.extract(sample_text, doc_type="general")
    
    print(f"Summary: {result.summary[:100]}...")
    print(f"Tags: {result.tags}")
    print(f"Entities: {len(result.entities)}")
    for entity in result.entities[:5]:
        print(f"  - {entity.get('label')} ({entity.get('type')})")
    print(f"Relations: {len(result.relations)}")
    for rel in result.relations[:3]:
        print(f"  - {rel.get('source')} --{rel.get('relation')}--> {rel.get('target')}")


def test_pipeline():
    """Test full pipeline with mock data."""
    print("\n=== Testing Pipeline ===")
    
    settings = Settings.from_env()
    
    if not settings.cloudreve_token:
        print("Skipping pipeline test: CLOUDREVE_TOKEN not set")
        return
    
    if not settings.openai_api_key:
        print("Warning: OPENAI_API_KEY not set, will use mock extraction")
    
    print(f"Cloudreve URL: {settings.cloudreve_base_url}")
    print(f"Neo4j URI: {settings.neo4j_uri}")
    print(f"Milvus: {settings.milvus_host}:{settings.milvus_port}")
    
    # Note: Full pipeline test requires a real file in Cloudreve
    print("\nTo test full pipeline, run:")
    print("  python -m nexus.worker")
    print("Then upload a file to Cloudreve")


def test_ontology_builder():
    """Test knowledge-graph skill ontology builder."""
    print("\n=== Testing Ontology Builder ===")
    
    skill_path = Path(__file__).parent / "knowledge-graph" / "scripts" / "ontology_builder.py"
    
    if not skill_path.exists():
        print(f"Ontology builder not found at {skill_path}")
        return
    
    import subprocess
    import json
    
    result = subprocess.run(
        ["python", str(skill_path), "--action", "suggest", "--domain", "computer science"],
        capture_output=True, text=True
    )
    
    if result.returncode == 0:
        ontology = json.loads(result.stdout)
        print(f"Domain: {ontology.get('domain')}")
        print(f"Suggested concepts: {[c['type'] for c in ontology.get('suggested_concepts', [])]}")
    else:
        print(f"Error: {result.stderr}")


def main():
    """Run all tests."""
    print("Knowledge Nexus - Semantic Processing Pipeline Tests")
    print("=" * 50)
    
    test_content_parser()
    test_knowledge_extractor()
    test_ontology_builder()
    test_pipeline()
    
    print("\n" + "=" * 50)
    print("Tests completed!")


if __name__ == "__main__":
    main()
