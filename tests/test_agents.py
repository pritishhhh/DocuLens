import json
from unittest.mock import patch

import pytest

from app.agents.critic import critique
from app.agents.router import route
from app.agents.synthesis import synthesize
from app.graph import ask
from app.ingestion.chunker import chunk_filing
from app.ingestion.vectorstore import HybridStore
from app.llm import InvalidModelOutput


def test_chunker_preserves_tables_short_text_and_provenance(tmp_path):
    path = tmp_path / "sample.htm"
    path.write_text("""<html><body><h2>Risk Factors</h2><p>Supply chain risk.</p>
        <div hidden>SECRET HIDDEN XBRL</div><script>bad script</script>
        <h2>Financial Data</h2><p>USD in millions</p><table>
        <tr><th>Quarter</th><th>Revenue</th></tr><tr><td>Q1</td><td>100</td></tr>
        <tr><td>Q2</td><td>120</td></tr></table></body></html>""", encoding="utf-8")
    chunks = chunk_filing(path, metadata={"source_url": "https://www.sec.gov/filing", "report_date": "2024-12-31"})
    assert {c.kind for c in chunks} == {"table", "text"}
    tables = "\n".join(c.content for c in chunks if c.kind == "table")
    assert all(word in tables for word in ("Quarter", "Revenue", "100", "120", "millions"))
    assert any("Supply chain risk." in c.content for c in chunks)
    assert all("SECRET" not in c.content and "bad script" not in c.content for c in chunks)
    assert all(c.report_date == "2024-12-31" and c.source_file == "sample.htm" for c in chunks)


def test_oversized_paragraphs_are_bounded_and_nonempty(tmp_path):
    path = tmp_path / "long.htm"
    path.write_text("<p>" + "Financial revenue growth. " * 500 + "</p>", encoding="utf-8")
    chunks = chunk_filing(path, max_chars=500)
    assert len(chunks) > 5
    assert all(0 < len(c.content) <= 500 for c in chunks)


def test_repeated_table_headers_and_units(tmp_path):
    path = tmp_path / "table.htm"
    rows = "".join(f"<tr><td>Metric {i}</td><td>{i + 1200}</td></tr>" for i in range(80))
    path.write_text('<h2>Income statement</h2><p>USD in millions</p><table><tr><th>Metric</th>'
                    '<th>2024</th></tr>' + rows + '</table>', encoding="utf-8")
    chunks = [c for c in chunk_filing(path, max_chars=500) if c.kind == "table"]
    assert len(chunks) > 1
    assert all(len(c.content) <= 500 and "2024" in c.content and "millions" in c.content for c in chunks)
    assert "Metric 79" in "\n".join(c.content for c in chunks)


def test_layout_table_narrative_is_not_dropped(tmp_path):
    path = tmp_path / "layout.htm"
    path.write_text("<table><tr><td><p>Our material risk is supplier concentration.</p></td></tr></table>")
    assert "supplier concentration" in " ".join(c.content for c in chunk_filing(path))


def test_mixed_content_and_standalone_spans_survive(tmp_path):
    path = tmp_path / "mixed.htm"
    path.write_text("<body><!-- omit this comment -->Direct body text<div>Before<p>Nested paragraph</p>After</div>"
                    "<span>Standalone span</span></body>")
    content = " ".join(c.content for c in chunk_filing(path))
    for value in ("Direct body text", "Before", "Nested paragraph", "After", "Standalone span"):
        assert value in content
    assert "omit this comment" not in content


@pytest.mark.parametrize("question,label", [
    ("What was total revenue last quarter?", "numeric_lookup"),
    ("How did revenue change year over year?", "trend_analysis"),
    ("What supply chain risks were identified?", "qualitative_risk")])
def test_router(question, label):
    assert route(question) == label


def test_filters_do_not_mix_quarterly_and_annual_revenue(corpus):
    store = HybridStore("exm")
    results = store.query("total revenue", form="10-K")
    assert results
    assert all(r["metadata"]["form"] == "10-K" for r in results)
    assert store.query("revenue", filing_date="2000-01-01") == []
    assert store.query("zxqvunknown") == []


def draft_json(source_id="S1", quote="Revenue | 120 | 100"):
    return json.dumps({"insufficient_context": False, "claims": [
        {"text": "Revenue was USD 120 million in 2024.",
         "evidence": [{"source_id": source_id, "quote": quote}]}]})


def test_citations_reference_original_excerpts(corpus):
    results = HybridStore("EXM").query("revenue", kind="table", form="10-K")
    with patch("app.agents.synthesis.call_llm", return_value=draft_json()):
        out = synthesize("Revenue?", results, {})
    assert "[S1]" in out["answer"]
    assert out["sources"][0]["excerpt"] == results[0]["content"]


@pytest.mark.parametrize("source_id,quote", [("S99", "Revenue | 120 | 100"), ("S1", "Revenue | 999 | 888")])
def test_invented_citations_and_quotes_are_rejected(corpus, source_id, quote):
    results = HybridStore("EXM").query("revenue", kind="table", form="10-K")
    with patch("app.agents.synthesis.call_llm", return_value=draft_json(source_id, quote)):
        with pytest.raises(InvalidModelOutput):
            synthesize("Revenue?", results, {})


@pytest.mark.parametrize("raw", [
    '{"faithfulness": 2, "answer_relevancy": 1, "all_claims_supported": true}',
    '{"faithfulness": "1", "answer_relevancy": 1, "all_claims_supported": true}',
    '{"faithfulness": NaN, "answer_relevancy": 1, "all_claims_supported": true}',
    '{"faithfulness": 1, "answer_relevancy": 1, "all_claims_supported": "false"}',
    '{}', 'not json'
])
def test_malformed_judge_scores_fail_closed(raw):
    with patch("app.agents.critic.call_llm", return_value=raw):
        with pytest.raises(InvalidModelOutput):
            critique("question", "answer", "[]")


def test_any_unsupported_claim_fails_judge():
    with patch("app.agents.critic.call_llm", return_value=json.dumps(
            {"faithfulness": 1.0, "answer_relevancy": 1.0, "all_claims_supported": False})):
        assert not critique("question", "answer", "[]")["passed"]


def test_failed_judgment_never_returns_answer(corpus):
    draft = {"answer": "UNSUPPORTED SECRET DRAFT", "context_used": "[]", "insufficient_context": False}
    with patch("app.graph.synthesize", return_value=draft) as synthesis, patch(
            "app.graph.critique", return_value={"passed": False}):
        out = ask("EXM", "What was revenue?")
    assert out["status"] == "insufficient_evidence"
    assert "UNSUPPORTED" not in out["answer"]
    assert out["sources"] == []
    assert synthesis.call_count == 2
    assert out["retries"] == 1


def test_latest_annual_selects_annual_not_newer_quarter(corpus):
    with patch("app.graph.synthesize", return_value={"insufficient_context": True}) as synthesis:
        out = ask("EXM", "What was total revenue in the most recent fiscal year?")
    assert out["snapshot"]["filters"] == {"form": "10-K", "filing_date": "2025-02-01"}
    assert all(r["metadata"]["form"] == "10-K" for r in synthesis.call_args.args[1])


def test_empty_retrieval_does_not_call_generation(corpus):
    with patch("app.graph.synthesize") as synthesis:
        out = ask("EXM", "zxqvunknown")
    synthesis.assert_not_called()
    assert out["status"] == "insufficient_evidence"


def test_retry_preserves_original_question(corpus):
    with patch("app.graph.synthesize", return_value={"insufficient_context": True}) as synthesis:
        ask("EXM", "What was revenue?")
    assert [call.args[0] for call in synthesis.call_args_list] == ["What was revenue?"] * 2
