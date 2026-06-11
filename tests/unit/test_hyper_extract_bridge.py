from pathlib import Path
from types import SimpleNamespace
import sys

from core.services.hyper_extract_bridge import HyperExtractRuntimeBridge
from core.services.hyper_extract_bridge import make_template_factory_runner


def _template(template_id="general/base_graph", template_type="graph"):
    return {
        "template_id": template_id,
        "type": template_type,
        "template_hash": "a" * 64,
        "graph_compatible": template_type == "graph",
    }


def test_bridge_is_disabled_by_default_and_does_not_call_runner():
    calls = []

    def runner(template, text):
        calls.append((template, text))
        return {}

    bridge = HyperExtractRuntimeBridge(enabled=False, runner=runner)

    result = bridge.extract_candidates(
        text="AuthService stores data in PostgreSQL.",
        selected_templates=[_template()],
    )

    assert result == []
    assert calls == []


def test_bridge_normalizes_graph_runtime_output_to_kgraph_candidates():
    def runner(template, text):
        assert template["template_id"] == "general/base_graph"
        assert "AuthService" in text
        return {
            "nodes": [
                {"name": "AuthService", "type": "service"},
                {"name": "PostgreSQL", "type": "database"},
            ],
            "edges": [
                {"source": "AuthService", "target": "PostgreSQL", "type": "stores_in"},
            ],
        }

    bridge = HyperExtractRuntimeBridge(enabled=True, runner=runner, max_templates=1)

    result = bridge.extract_candidates(
        text="AuthService stores data in PostgreSQL.",
        selected_templates=[_template()],
    )

    assert len(result) == 1
    candidate = result[0]
    assert candidate["status"] == "success"
    assert candidate["template_id"] == "general/base_graph"
    assert candidate["candidate_entities"] == [
        {"name": "AuthService", "type": "service"},
        {"name": "PostgreSQL", "type": "database"},
    ]
    assert candidate["candidate_relations"] == [
        {"source": "AuthService", "target": "PostgreSQL", "type": "stores_in"},
    ]


def test_bridge_records_runtime_errors_without_raising():
    def runner(template, text):
        raise RuntimeError("runtime unavailable")

    bridge = HyperExtractRuntimeBridge(enabled=True, runner=runner, max_templates=1)

    result = bridge.extract_candidates(
        text="contract text",
        selected_templates=[_template("legal/contract_obligation", "hypergraph")],
    )

    assert result[0]["status"] == "error"
    assert result[0]["template_id"] == "legal/contract_obligation"
    assert "runtime unavailable" in result[0]["error"]


def test_template_factory_runner_uses_selected_template_file(monkeypatch, tmp_path):
    calls = []

    class FakeTemplate:
        def parse(self, text):
            calls.append({"parse_text": text})
            return {"nodes": [{"name": "AuthService"}], "edges": []}

    class FakeTemplateFactory:
        @staticmethod
        def create(source, language, llm_client, embedder, **kwargs):
            calls.append(
                {
                    "source": source,
                    "language": language,
                    "llm_client": llm_client,
                    "embedder": embedder,
                    "kwargs": kwargs,
                }
            )
            return FakeTemplate()

    monkeypatch.setitem(
        sys.modules,
        "hyperextract.utils.template_engine",
        SimpleNamespace(TemplateFactory=FakeTemplateFactory),
    )

    runner = make_template_factory_runner(
        llm_client="llm",
        embedder="embedder",
        template_root=tmp_path,
        language="zh",
        observation_time="2026-06-09",
    )

    output = runner(
        {"relative_path": "general/base_graph.yaml"},
        "AuthService stores data in PostgreSQL.",
    )

    assert output == {"nodes": [{"name": "AuthService"}], "edges": []}
    assert Path(calls[0]["source"]) == tmp_path / "general/base_graph.yaml"
    assert calls[0]["language"] == "zh"
    assert calls[0]["llm_client"] == "llm"
    assert calls[0]["embedder"] == "embedder"
    assert calls[0]["kwargs"] == {"observation_time": "2026-06-09"}
