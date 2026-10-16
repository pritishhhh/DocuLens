import json

import pytest

from app.ingestion.vectorstore import _read_index


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCULENS_INDEX_DIR", str(tmp_path))
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.delenv("DOCULENS_API_TOKEN", raising=False)
    monkeypatch.delenv("VERCEL", raising=False)
    _read_index.cache_clear()


@pytest.fixture
def corpus(tmp_path):
    chunks = [
        {"chunk_id": "annual-table", "kind": "table",
         "content": "USD in millions\nFiscal year | 2024 | 2023\nRevenue | 120 | 100\nGross margin | 50% | 40%",
         "source_file": "annual.htm", "section_hint": "Income statement",
         "source_url": "https://www.sec.gov/Archives/example-annual.htm",
         "form": "10-K", "filing_date": "2025-02-01", "report_date": "2024-12-31", "accession": "annual"},
        {"chunk_id": "annual-risk", "kind": "text",
         "content": "We rely on a single supplier for components. A disruption may delay production.",
         "source_file": "annual.htm", "section_hint": "Risk factors",
         "source_url": "https://www.sec.gov/Archives/example-annual.htm",
         "form": "10-K", "filing_date": "2025-02-01", "report_date": "2024-12-31", "accession": "annual"},
        {"chunk_id": "quarter-table", "kind": "table",
         "content": "USD in millions\nQuarter ended March 31, 2025\nRevenue | 35\nGross margin | 48%",
         "source_file": "quarter.htm", "section_hint": "Income statement",
         "source_url": "https://www.sec.gov/Archives/example-quarter.htm",
         "form": "10-Q", "filing_date": "2025-05-01", "report_date": "2025-03-31", "accession": "quarter"}
    ]
    data = {"schema_version": 1, "ticker": "EXM", "built_at": "2025-05-02T00:00:00+00:00",
            "embedding_model": None, "dimensions": 0, "chunks": chunks}
    (tmp_path / "EXM.json").write_text(json.dumps(data), encoding="utf-8")
    return data
