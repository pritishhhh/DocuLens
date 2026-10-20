"""Bounded retrieval -> synthesis -> verification workflow.

One retrieval expansion is allowed. Rejected answers are never returned.
"""
import re

from app.agents.critic import critique
from app.agents.router import route
from app.agents.synthesis import synthesize
from app.agents.table_agent import answer_from_tables
from app.agents.text_retriever import retrieve_text
from app.config import ticker_symbol
from app.ingestion.vectorstore import HybridStore
from app.llm import InvalidModelOutput, request_budget
from app.tracing import trace_step

MAX_RETRIES = 1
ABSTENTION = ("I couldn't verify a complete answer from the indexed filings. "
              "Try specifying a reporting period or adding the relevant filings.")


def _period_filters(store, question, form, filing_date):
    # Honor explicit filters. Resolve relative periods only within the snapshot.
    if form is None:
        if re.search(r"(latest|most recent|last)\s+(fiscal\s+)?(year|annual)", question, re.I):
            form = "10-K"
        elif re.search(r"(latest|most recent|last)\s+(fiscal\s+)?quarter", question, re.I):
            form = "10-Q"
    if filing_date is None and re.search(
            r"\b(latest|most recent)\s+(?:(?:fiscal|reported)\s+)?(?:year|annual|quarter|filing)\b",
            question, re.I):
        matching = [c for c in store.data["chunks"] if form is None or c.get("form") == form]
        if matching:
            # Report period determines recency; filing date breaks ties.
            latest = max(matching, key=lambda c: (c.get("report_date", ""), c.get("filing_date", "")))
            filing_date = latest.get("filing_date") or None
    return {"form": form, "filing_date": filing_date}


def ask(ticker: str, question: str, form: str | None = None, filing_date: str | None = None) -> dict:
    ticker = ticker_symbol(ticker)
    store = HybridStore(ticker)
    label = route(question)
    filters = _period_filters(store, question, form, filing_date)
    snapshot = {"ticker": ticker, "built_at": store.data["built_at"],
                "coverage": store.data.get("coverage", "full indexed filings"),
                "latest_filing_date": max(c.get("filing_date", "") for c in store.data["chunks"]),
                "retrieval": "hybrid" if store.data.get("embedding_model") else "bm25",
                "filters": filters, "scope": "indexed filings only"}
    last_critique = {"passed": False, "method": "not_evaluated"}
    with request_budget():
        for attempt in range(MAX_RETRIES + 1):
            with trace_step("retrieve", {"ticker": ticker, "attempt": attempt}):
                k = 5 + attempt * 4
                texts = retrieve_text(store, question, k=k, **filters)
                tables = answer_from_tables(store, question, k=k, **filters)
                ordered = (tables + texts if label != "qualitative_risk" else texts + tables)
                selected, seen, chars = [], set(), 0
                for result in ordered:
                    if result["id"] in seen or chars + len(result["content"]) > 26000:
                        continue
                    selected.append(result)
                    seen.add(result["id"])
                    chars += len(result["content"])
            if not selected:
                break
            try:
                draft = synthesize(question, selected, snapshot)
                if draft["insufficient_context"]:
                    continue
                last_critique = critique(question, draft["answer"], draft["context_used"])
            except InvalidModelOutput:
                last_critique = {"passed": False, "method": "validation", "reason": "invalid_model_output"}
                continue
            if last_critique["passed"]:
                return {"status": "answered", "answer": draft["answer"], "sources": draft["sources"],
                        "claims": draft["claims"], "route": label, "critique": last_critique,
                        "retries": attempt, "snapshot": snapshot}
    return {"status": "insufficient_evidence", "answer": ABSTENTION, "sources": [],
            "claims": [], "route": label, "critique": last_critique,
            "retries": attempt, "snapshot": snapshot}
