"""Validate bundled assets before Vercel builds the function; never call an API."""
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check_deployment(root: Path = ROOT) -> dict:
    for name in ("index.html", "app.js", "styles.css"):
        if not (root / "app" / "static" / name).is_file():
            raise ValueError(f"Missing frontend asset: app/static/{name}")
    indexes = sorted((root / "data" / "corpus").glob("*.json"))
    if not indexes:
        raise ValueError("No filing indexes found. Include data/corpus/*.json in the deployed revision.")
    total = 0
    for path in indexes:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema_version") != 1 or data.get("ticker") != path.stem:
            raise ValueError(f"Invalid index version or ticker: {path.name}")
        if not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", path.stem):
            raise ValueError(f"Invalid ticker filename: {path.name}")
        chunks = data.get("chunks")
        if not isinstance(chunks, list) or not chunks:
            raise ValueError(f"Index has no chunks: {path.name}")
        seen = set()
        for chunk in chunks:
            chunk_id = chunk.get("chunk_id")
            if not chunk_id or chunk_id in seen or not chunk.get("content"):
                raise ValueError(f"Missing or duplicate chunk identity/content: {path.name}")
            seen.add(chunk_id)
            if data.get("embedding_model"):
                vector = chunk.get("embedding", [])
                if not vector or len(vector) != data.get("dimensions"):
                    raise ValueError(f"Embedding dimensions do not match: {path.name}")
                if not all(isinstance(v, (float, int)) and not isinstance(v, bool)
                           and math.isfinite(v) for v in vector):
                    raise ValueError(f"Invalid embedding values: {path.name}")
                if abs(sum(v * v for v in vector) - 1) > 0.0001:
                    raise ValueError(f"Embedding is not normalized: {path.name}")
        total += len(chunks)
    return {"companies": len(indexes), "chunks": total}


if __name__ == "__main__":
    try:
        result = check_deployment()
    except (ValueError, OSError, KeyError, TypeError, AttributeError) as exc:
        raise SystemExit(f"Deployment preflight failed: {exc}") from None
    print(f"Deployment assets validated: {result['companies']} companies, {result['chunks']} chunks.")
