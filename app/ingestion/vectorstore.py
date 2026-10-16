"""Read-only hybrid retrieval over a small, deployment-bundled corpus.

BM25 + normalized cosine ranks are combined with reciprocal rank fusion.
No database writes or transformer weights are needed by the serving process.
"""
import argparse
import hashlib
import json
import math
import os
import re
import tempfile
import time
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from app.config import ROOT, index_dir, ticker_symbol
from app.ingestion.chunker import chunk_filing
from app.llm import ProviderError, embed

SCHEMA_VERSION = 1
STOPWORDS = set("a an the and or of to in for on is was were what how did does at by with as it its from".split())


class MissingIndexError(FileNotFoundError):
    pass


def terms(text):
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in STOPWORDS]


@lru_cache(maxsize=8)
def _read_index(path: str, mtime: int):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported index version; rebuild the corpus")
    if not data.get("chunks"):
        raise ValueError("Index contains no chunks")
    return data


class HybridStore:
    def __init__(self, collection_name: str):
        self.ticker = ticker_symbol(collection_name)
        path = index_dir() / f"{self.ticker}.json"
        if not path.is_file():
            raise MissingIndexError(f"No corpus is available for {self.ticker}. Build its index before querying.")
        self.data = _read_index(str(path.resolve()), path.stat().st_mtime_ns)
        if self.data["ticker"] != self.ticker:
            raise ValueError("Index ticker does not match its filename")
        self._query_vectors = {}

    def query(self, text: str, k: int = 5, kind: str | None = None,
              form: str | None = None, filing_date: str | None = None):
        docs = [c for c in self.data["chunks"]
                if (kind is None or c["kind"] == kind)
                and (form is None or c.get("form") == form)
                and (filing_date is None or c.get("filing_date") == filing_date)]
        if not docs:
            return []
        query_terms = set(terms(text))
        tokens = [Counter(terms(c.get("section_hint", "") + " " + c["content"])) for c in docs]
        lengths = [sum(t.values()) for t in tokens]
        avg_len = sum(lengths) / len(lengths) or 1
        scores = [0.0] * len(docs)
        for term in query_terms:
            df = sum(term in t for t in tokens)
            idf = math.log(1 + (len(docs) - df + 0.5) / (df + 0.5))
            for i, counts in enumerate(tokens):
                tf = counts.get(term, 0)
                scores[i] += idf * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * lengths[i] / avg_len))
        lexical = sorted((i for i, score in enumerate(scores) if score > 0), key=lambda i: -scores[i])
        ranks = {}
        for rank, i in enumerate(lexical[:50], 1):
            ranks[i] = 1 / (60 + rank)
        model = self.data.get("embedding_model")
        if model:
            if text not in self._query_vectors:
                self._query_vectors[text] = embed([text], "RETRIEVAL_QUERY", model,
                                                  self.data["dimensions"])[0]
            vector = self._query_vectors[text]
            semantic = []
            for i, doc in enumerate(docs):
                stored = doc["embedding"]
                if len(stored) != len(vector):
                    raise ValueError("Index embedding dimensions are inconsistent; rebuild it")
                similarity = sum(a * b for a, b in zip(vector, stored))
                if similarity >= 0.25:
                    semantic.append((similarity, i))
            for rank, (_, i) in enumerate(sorted(semantic, reverse=True)[:50], 1):
                ranks[i] = ranks.get(i, 0) + 1 / (60 + rank)
        selected = sorted(ranks, key=lambda i: (-ranks[i], docs[i]["chunk_id"]))[:k]
        return [{"id": docs[i]["chunk_id"], "content": docs[i]["content"],
                 "metadata": {key: value for key, value in docs[i].items()
                              if key not in ("embedding", "content", "chunk_id")},
                 "score": round(ranks[i], 6)} for i in selected]


def build_index(ticker: str, lexical_only: bool = False, output: Path | None = None):
    ticker = ticker_symbol(ticker)
    filing_dir = ROOT / "data" / "filings" / ticker
    manifest_path = filing_dir / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError("Ingest filings first: no filing manifest was found")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    chunks = []
    for filing in manifest:
        path = filing_dir / Path(filing["local_file"]).name
        metadata = {"source_url": filing["source_url"], "form": filing["form"],
                    "filing_date": filing["filingDate"], "report_date": filing.get("reportDate", ""),
                    "accession": filing["accessionNumber"]}
        chunks.extend(asdict(c) for c in chunk_filing(path, metadata=metadata))
    if not chunks:
        raise ValueError("No extractable filing content was found")
    model = None if lexical_only else os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001")
    dimensions = 768 if model else 0
    if model:
        texts = [c["section_hint"] + "\n" + c["content"] for c in chunks]
        keys = [hashlib.sha256(f"{model}|{dimensions}|{text}".encode()).hexdigest() for text in texts]
        cache_path = ROOT / "data" / "index" / "embedding-cache.json"
        cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
        pending = [i for i, key in enumerate(keys) if key not in cache]
        # Conservative character estimate, configurable to the project's quota.
        tokens_per_minute = max(1000, int(os.getenv("DOCULENS_EMBEDDING_TPM", "24000")))
        for start in range(0, len(pending), 16):
            batch = pending[start:start + 16]
            began = time.monotonic()
            for quota_attempt in range(3):
                try:
                    vectors = embed([texts[i] for i in batch], "RETRIEVAL_DOCUMENT", model, dimensions)
                    break
                except ProviderError as exc:
                    if exc.status_code not in (429, 502, 504) or quota_attempt == 2:
                        raise
                    pause = 60 if exc.status_code == 429 else 2 ** quota_attempt
                    print(f"Embedding provider unavailable; pausing {pause} seconds. Completed batches are saved.",
                          flush=True)
                    time.sleep(pause)
            for i, vector in zip(batch, vectors):
                cache[keys[i]] = [round(v, 7) for v in vector]
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_tmp = cache_path.with_suffix(".tmp")
            cache_tmp.write_text(json.dumps(cache, separators=(",", ":")), encoding="utf-8")
            cache_tmp.replace(cache_path)
            print(f"Embedded {min(start + 16, len(pending))}/{len(pending)} new chunks", flush=True)
            if start + 16 < len(pending):
                interval = sum(len(texts[i]) for i in batch) / 3 / tokens_per_minute * 60
                time.sleep(max(1, interval - (time.monotonic() - began)))
        for chunk, key in zip(chunks, keys):
            chunk["embedding"] = cache[key]
    data = {"schema_version": SCHEMA_VERSION, "ticker": ticker,
            "built_at": datetime.now(timezone.utc).isoformat(),
            "embedding_model": model, "dimensions": dimensions, "chunks": chunks}
    target = output or index_dir()
    target.mkdir(parents=True, exist_ok=True)
    # An interrupted rebuild must not leave a partially written serving index.
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target, suffix=".tmp", delete=False) as handle:
        json.dump(data, handle, separators=(",", ":"), ensure_ascii=False)
        temporary = Path(handle.name)
    temporary.replace(target / f"{ticker}.json")
    print(f"Indexed {len(chunks)} chunks for {ticker} ({'hybrid' if model else 'BM25'}).", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", action="store_true", required=True)
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--lexical-only", action="store_true", help="Build BM25 retrieval without embedding API calls")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    build_index(args.ticker, args.lexical_only, args.output)
