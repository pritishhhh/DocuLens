import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from app.config import ROOT
from app.ingestion.edgar import filing_url, list_filings
from app.ingestion.vectorstore import HybridStore, build_index
from app.llm import ProviderError


def test_archive_submissions_are_followed_when_needed():
    recent = {"form": ["8-K"], "primaryDocument": ["current.htm"], "filingDate": ["2025-01-01"],
              "accessionNumber": ["0000000001-25-000001"]}
    older = {"form": ["10-K"], "primaryDocument": ["annual.htm"], "filingDate": ["2024-01-01"],
             "reportDate": ["2023-12-31"], "accessionNumber": ["0000000001-24-000001"]}
    responses = [Mock(json=lambda: {"filings": {"recent": recent, "files": [
        {"name": "CIK0000000001-submissions-001.json"}]}}), Mock(json=lambda: older)]
    with patch("app.ingestion.edgar._get", side_effect=responses) as get:
        filings = list_filings("0000000001", count=1)
    assert filings[0]["reportDate"] == "2023-12-31"
    assert get.call_count == 2


@pytest.mark.parametrize("document", ["../secret", "/tmp/file", "file.htm?key=value"])
def test_sec_document_paths_cannot_escape_archive(document):
    with pytest.raises(ValueError):
        filing_url("1", {"primaryDocument": document, "accessionNumber": "0000000001-24-000001"})


def test_rebuild_replaces_previous_snapshot_without_duplicates(tmp_path, monkeypatch):
    root = tmp_path / "project"
    folder = root / "data" / "filings" / "EXM"
    folder.mkdir(parents=True)
    filing = {"local_file": "annual.htm", "source_url": "https://www.sec.gov/annual.htm",
              "form": "10-K", "filingDate": "2025-02-01", "reportDate": "2024-12-31",
              "accessionNumber": "0000000001-25-000001"}
    (folder / "manifest.json").write_text(json.dumps([filing]), encoding="utf-8")
    (folder / "annual.htm").write_text("<h2>Revenue</h2><p>Revenue was USD 120 million.</p>")
    monkeypatch.setattr("app.ingestion.vectorstore.ROOT", root)
    build_index("EXM", lexical_only=True)
    first = HybridStore("EXM").data["chunks"]
    build_index("EXM", lexical_only=True)
    assert HybridStore("EXM").data["chunks"] == first
    (folder / "annual.htm").write_text("<h2>Income</h2><p>Net income was USD 40 million.</p>")
    build_index("EXM", lexical_only=True)
    assert not HybridStore("EXM").query("revenue")
    assert HybridStore("EXM").query("income")


def test_semantic_query_uses_recorded_embedding_model(corpus, tmp_path, monkeypatch):
    corpus.update(embedding_model="recorded-model", dimensions=2)
    for index, chunk in enumerate(corpus["chunks"]):
        chunk["embedding"] = [1.0, 0.0] if index == 1 else [0.0, 1.0]
    (tmp_path / "EXM.json").write_text(json.dumps(corpus), encoding="utf-8")
    monkeypatch.setenv("GEMINI_EMBEDDING_MODEL", "different-model")
    with patch("app.ingestion.vectorstore.embed", return_value=[[1.0, 0.0]]) as embed:
        results = HybridStore("EXM").query("manufacturing dependence")
    assert results[0]["id"] == "annual-risk"
    assert embed.call_args.args[1:] == ("RETRIEVAL_QUERY", "recorded-model", 2)


def test_deployment_dependency_definitions_agree():
    import tomllib
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
    assert set(config["project"]["dependencies"]) == set(requirements)
    assert Path(ROOT / ".python-version").read_text().strip() == "3.12"


def test_example_environment_contains_no_real_credentials():
    from dotenv import dotenv_values
    values = dotenv_values(ROOT / ".env.example")
    assert not values.get("GEMINI_API_KEY")
    assert not values.get("DOCULENS_API_TOKEN")
    assert values["EDGAR_USER_AGENT"] == "Your name your-email@example.com"


def test_embedding_build_resumes_cached_batches_and_handles_quota(tmp_path, monkeypatch):
    root = tmp_path / "project"
    folder = root / "data" / "filings" / "EXM"
    folder.mkdir(parents=True)
    filing = {"local_file": "annual.htm", "source_url": "https://www.sec.gov/annual.htm",
              "form": "10-K", "filingDate": "2025-02-01", "reportDate": "2024-12-31",
              "accessionNumber": "0000000001-25-000001"}
    (folder / "manifest.json").write_text(json.dumps([filing]), encoding="utf-8")
    (folder / "annual.htm").write_text("<p>Revenue was USD 120 million.</p>")
    monkeypatch.setattr("app.ingestion.vectorstore.ROOT", root)
    vector = [1.0] + [0.0] * 767
    with patch("app.ingestion.vectorstore.embed", side_effect=[ProviderError("quota", 429), [vector]]) as embed, \
            patch("app.ingestion.vectorstore.time.sleep") as sleep:
        build_index("EXM")
    assert embed.call_count == 2
    sleep.assert_called_once_with(60)
    with patch("app.ingestion.vectorstore.embed") as embed:
        build_index("EXM")
    embed.assert_not_called()
    assert HybridStore("EXM").data["chunks"][0]["embedding"] == vector


def test_pinned_evaluation_does_not_change_serving_index_directory(monkeypatch, tmp_path):
    from app.eval.run_eval import run
    monkeypatch.setenv("DOCULENS_INDEX_DIR", str(tmp_path))
    assert run()
    import os
    assert os.environ["DOCULENS_INDEX_DIR"] == str(tmp_path)
