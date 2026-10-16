"""FastAPI entrypoint used by Vercel, uvicorn, and the CLI."""
import argparse
import json
import logging
import os
import secrets
from datetime import date

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.config import ConfigurationError, ROOT, api_key, index_dir, ticker_symbol
from app.graph import ask
from app.ingestion.vectorstore import HybridStore, MissingIndexError
from app.llm import ProviderError

logging.basicConfig(level=logging.INFO)
app = FastAPI(title="DocuLens", version="1.0.0", description="Cited answers from indexed SEC filings.")
api = app  # Preserve existing uvicorn app.main:api commands.


class QueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    ticker: str
    question: str = Field(min_length=5, max_length=2000)
    form: str | None = Field(default=None, pattern=r"^10-(K|Q)$")
    filing_date: date | None = None

    @field_validator("ticker")
    @classmethod
    def validate_ticker(cls, value):
        return ticker_symbol(value)


def authorize(authorization: str | None = Header(default=None)):
    token = os.getenv("DOCULENS_API_TOKEN")
    # A public deployment must explicitly opt into spending its shared free quota.
    if os.getenv("VERCEL") and not token and os.getenv("DOCULENS_PUBLIC_DEMO") != "true":
        raise HTTPException(503, "Configure DOCULENS_API_TOKEN or explicitly enable DOCULENS_PUBLIC_DEMO.")
    if token and not secrets.compare_digest((authorization or "").encode(), ("Bearer " + token).encode()):
        raise HTTPException(401, "Enter the deployment access token to ask a question.",
                            headers={"WWW-Authenticate": "Bearer"})


@app.post("/query", dependencies=[Depends(authorize)])
def query(req: QueryRequest):
    try:
        return ask(req.ticker, req.question, req.form,
                   req.filing_date.isoformat() if req.filing_date else None)
    except MissingIndexError as exc:
        raise HTTPException(404, str(exc)) from None
    except ConfigurationError as exc:
        raise HTTPException(503, str(exc)) from None
    except ProviderError as exc:
        raise HTTPException(exc.status_code, str(exc),
                            headers={"Retry-After": str(exc.retry_after)} if exc.status_code == 429 else None) from None
    except (ValueError, KeyError, OSError):
        logging.getLogger("doculens").error("Corpus could not be read; rebuild the deployed index")
        raise HTTPException(503, "The filing corpus is unavailable. Rebuild the deployment index.") from None


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/corpus")
def corpus():
    entries = []
    for path in sorted(index_dir().glob("*.json")):
        try:
            store = HybridStore(path.stem)
            filings = {c.get("accession", c["source_file"]): {
                "form": c.get("form", ""), "filing_date": c.get("filing_date", ""),
                "report_date": c.get("report_date", ""), "source_url": c.get("source_url", "")}
                for c in store.data["chunks"]}
            entries.append({"ticker": path.stem, "built_at": store.data["built_at"],
                            "coverage": store.data.get("coverage", "full indexed filings"),
                            "retrieval": "hybrid" if store.data.get("embedding_model") else "bm25",
                            "filings": sorted(filings.values(), key=lambda f: f["filing_date"], reverse=True)})
        except (OSError, ValueError, KeyError):
            continue
    try:
        api_key()
        configured = True
    except ConfigurationError:
        configured = False
    return {"tickers": entries, "answering_configured": configured,
            "requires_token": bool(os.getenv("DOCULENS_API_TOKEN"))}


@app.get("/", include_in_schema=False)
def home():
    return FileResponse(ROOT / "app" / "static" / "index.html")


app.mount("/assets", StaticFiles(directory=ROOT / "app" / "static"), name="assets")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--form", choices=["10-K", "10-Q"])
    parser.add_argument("--filing-date", type=date.fromisoformat)
    args = parser.parse_args()
    print(json.dumps(ask(args.ticker, args.query, args.form,
                         args.filing_date.isoformat() if args.filing_date else None), indent=2))
