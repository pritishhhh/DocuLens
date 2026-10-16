"""Reproducible retrieval checks; optional live answers checked against references."""
import argparse
import json
import os
import re
from pathlib import Path

from app.config import ROOT
from app.graph import ask
from app.ingestion.vectorstore import HybridStore

GOLDEN_PATH = ROOT / "data" / "golden" / "golden_set.jsonl"


def load_golden_set(path: Path = GOLDEN_PATH):
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        raise ValueError("The evaluation set is empty")
    required = {"id", "ticker", "question", "expected_source_ids", "expected_patterns", "expect_abstention"}
    for row in rows:
        if not required <= row.keys():
            raise ValueError("Every evaluation row needs explicit references and expectations")
        if not row["expect_abstention"] and (not row["expected_patterns"] or not row["expected_source_ids"]):
            raise ValueError("Answerable questions need reference patterns and source IDs")
    return rows


def _run(live: bool, path: Path):
    results = []
    for row in load_golden_set(path):
        store = HybridStore(row["ticker"])
        filters = {key: row[key] for key in ("form", "filing_date") if row.get(key)}
        retrieved = store.query(row["question"], k=5, **filters)
        found = {r["id"] for r in retrieved}
        expected = set(row["expected_source_ids"])
        recall = len(found & expected) / len(expected) if expected else None
        result = {"id": row["id"], "retrieval_recall_at_5": recall}
        passed = recall is None or recall >= 1
        if not live and row["expect_abstention"]:
            result.update(passed=None, skipped="Abstention requires a live generation check")
            results.append(result)
            continue
        if live:
            answer = ask(row["ticker"], row["question"], **filters)
            abstained = answer["status"] == "insufficient_evidence"
            pattern_match = all(re.search(p, answer["answer"], re.I) for p in row["expected_patterns"])
            source_match = any(s.get("accession") in
                               {r["metadata"].get("accession") for r in retrieved if r["id"] in expected}
                               for s in answer["sources"]) if expected else True
            result.update(expected_abstention=row["expect_abstention"], abstained=abstained,
                          reference_match=bool(pattern_match), cited_reference_filing=source_match)
            passed = passed and (abstained if row["expect_abstention"]
                                 else not abstained and pattern_match and source_match)
        result["passed"] = bool(passed)
        results.append(result)
    summary = {"mode": "live_reference_checks" if live else "retrieval_only",
               "questions": len(results), "passed": sum(r["passed"] is True for r in results),
               "skipped": sum(r["passed"] is None for r in results),
               "results": results}
    print(json.dumps(summary, indent=2))
    return all(r["passed"] is not False for r in results)


def run(live: bool = False, path: Path = GOLDEN_PATH):
    # Keep pinned smoke references independent of refreshed serving corpora.
    previous = os.environ.get("DOCULENS_INDEX_DIR")
    if path.resolve() == GOLDEN_PATH.resolve():
        os.environ["DOCULENS_INDEX_DIR"] = str(ROOT / "data" / "reference")
    try:
        return _run(live, path)
    finally:
        if previous is None:
            os.environ.pop("DOCULENS_INDEX_DIR", None)
        else:
            os.environ["DOCULENS_INDEX_DIR"] = previous


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Calls Gemini and checks answers against reference patterns")
    parser.add_argument("--golden", type=Path, default=GOLDEN_PATH)
    args = parser.parse_args()
    raise SystemExit(0 if run(args.live, args.golden) else 1)
