# DocuLens

**Evidence-grounded answers from SEC filings.**

DocuLens helps readers explore financial statements with questions in plain language. It retrieves relevant narrative and table excerpts, generates cited claims, and checks those claims against the original evidence before returning an answer.

A browser interface makes the supporting excerpts, reporting periods, and SEC source links available alongside each answer.

## Features

- **Hybrid retrieval:** BM25 keyword search and Gemini embeddings combined through reciprocal rank fusion. A BM25-only mode works without an embedding API.
- **Financial context:** table row groups retain headers, units, section context, filing dates, and reporting dates.
- **Traceable answers:** each claim includes a citation and a verbatim supporting quote.
- **Conservative verification:** invalid citations, incomplete model responses, or failed grounding checks result in abstention.
- **Explicit coverage:** filter by company, form, and filing date; inspect the indexed snapshot before interpreting an answer.
- **Serverless deployment:** FastAPI runs on Vercel without a local model download, writable database, or separate database service.

## Quick start

Requires Python 3.12 or newer.

```bash
git clone https://github.com/pritishhhh/DocuLens.git
cd DocuLens
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

On Windows, activate with `.venv\Scripts\Activate.ps1` and copy the environment file with `Copy-Item .env.example .env`.

Create a key in [Google AI Studio](https://aistudio.google.com/apikey) and set `GEMINI_API_KEY` in `.env`. Then start the app:

```bash
uvicorn app.main:app --reload
```

Open [localhost:8000](http://localhost:8000). Interactive API documentation is at [/docs](http://localhost:8000/docs).

The deployment corpus includes NVIDIA's fiscal 2026 10-K and three 10-Q filings, covering reports filed from November 2025 through August 2026. Filing coverage and reporting periods are visible in the interface. This is an indexed snapshot, not a live market-data feed.

## Add filings

Set `EDGAR_USER_AGENT="Your name your-email@example.com"` in `.env`. SEC requires an identifying user agent for automated requests.

```bash
python -m app.ingestion.edgar --ticker NVDA --forms 10-K 10-Q --count 4
python -m app.ingestion.vectorstore --build --ticker NVDA
```

The first command downloads filings and their provenance. The second builds a hybrid index with Gemini embeddings. To use keyword retrieval without embedding calls:

```bash
python -m app.ingestion.vectorstore --build --ticker NVDA --lexical-only
```

Indexes are rebuilt atomically from the download manifest. They live in `data/corpus/`; downloaded HTML stays in the ignored `data/filings/` directory. Build indexes locally, then include the desired corpus files in your deployment. Rebuilding NVDA replaces its serving snapshot. Completed embedding batches are cached locally, so an interrupted build can resume without embedding the same content again.

## Deploy on Vercel

1. Merge [PR #1](https://github.com/pritishhhh/DocuLens/pull/1), or deploy its `codex/rag-vercel-review` branch. Import the repository into Vercel and select the **FastAPI** framework preset. Keep the repository root as the project root.
2. Set `GEMINI_API_KEY` in the Vercel environment variables.
3. Set `DOCULENS_API_TOKEN` to restrict answer requests. For an intentionally public demo, set `DOCULENS_PUBLIC_DEMO=true` instead.
4. Leave Build Command and Output Directory at their framework defaults and deploy. The configured build check validates the frontend and filing index without API calls. The checked-in corpus works immediately; include additional generated `data/corpus/*.json` files when deploying a larger corpus.

The API key stays on the server. An access token, if configured, is entered in the interface or supplied as a bearer token. A public demo shares the owner's API quota; use Vercel Firewall rate limits for public traffic.

See the [deployment guide](docs/deployment.md) for configuration, corpus refreshes, and troubleshooting.

## API

```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"ticker":"NVDA","question":"What was revenue in fiscal year 2026?","form":"10-K","filing_date":"2026-02-25"}'
```

Add `-H "Authorization: Bearer YOUR_ACCESS_TOKEN"` for a protected deployment.

| Endpoint | Purpose |
| --- | --- |
| `GET /` | Research interface |
| `GET /corpus` | Indexed companies, filing coverage, and configuration status |
| `POST /query` | Answer, cited excerpts, grounding assessment, and snapshot metadata |
| `GET /health` | Process liveness |

Answers return `status: "answered"` or `"insufficient_evidence"`. Unknown companies return 404; missing configuration returns 503; provider quota exhaustion returns 429.

## Models and cost

The defaults are `gemini-3.5-flash-lite` for generation and verification, and `gemini-embedding-001` for text embeddings. Both have a free tier in the [Gemini API pricing documentation](https://ai.google.dev/gemini-api/docs/pricing). Availability and quotas depend on the project and region.

Set `GEMINI_MODEL` or `GEMINI_EMBEDDING_MODEL` to change models. Changing the embedding model requires rebuilding the index; query embeddings always use the model recorded in that index.

A typical answer makes two generation calls and, for hybrid indexes, one query-embedding call. One expanded retrieval attempt is allowed. BM25-only indexes skip embedding calls. Gemini's free-tier data-use terms apply to submitted questions and excerpts; use public, non-sensitive material.

## Validation

```bash
pip install -r requirements-dev.txt
python -m ruff check app tests
python -m pytest -q
python -m app.eval.run_eval
# Optional: calls Gemini and checks answers against pinned references.
python -m app.eval.run_eval --live
```

CI runs offline tests and retrieval reference checks on pushes and pull requests. Live evaluation is an explicit workflow action requiring a `GEMINI_API_KEY` repository secret.

The pinned reference excerpts in `data/reference/` are separate from the serving corpus, so refreshing filings does not silently change evaluation questions. The reference set is a small smoke test, not a benchmark of financial-answer accuracy. Runtime LLM grounding scores are heuristics, not RAGAS metrics or proof of correctness.

## Scope

DocuLens handles text-based HTML 10-K and 10-Q filings. It does not perform OCR, retrieve page images, or interpret charts. Large corpora should move to a managed retrieval service; the bundled index is intended for a small research collection.

"Latest" refers to the indexed snapshot. Annual and quarterly figures, fiscal periods, and units still need careful review. Automated verification can miss mistakes, particularly in complex tables and calculations; inspect the cited filing before relying on an answer.
