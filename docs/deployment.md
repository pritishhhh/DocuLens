# Deploying DocuLens

## Runtime

Vercel detects `app/main.py` and its exported `app` FastAPI instance. `pyproject.toml` also identifies that entrypoint. `vercel.json` sets a 120-second function limit and includes `data/corpus/` in the function bundle. The application uses a 100-second provider-call budget.

The server reads the corpus and serves the interface. It never downloads filings, builds embeddings, writes trace files, or updates the index during a query. Structured traces go to stdout through Python logging.

The deployment uses Python 3.12 or newer. There is no Node build, model checkpoint, GPU requirement, or external vector database.

The build hook runs `python scripts/check_deployment.py`. It checks that the frontend files and serving indexes exist, chunk identities are unique, and semantic vectors have the correct dimensions and normalization. It does not require API credentials, contact SEC, or spend Gemini quota. An incomplete bundle fails the build with an actionable message.

## Environment variables

| Variable | Purpose |
| --- | --- |
| `GEMINI_API_KEY` | Required to generate answers and build semantic indexes |
| `GEMINI_MODEL` | Generation and grounding-check model; defaults to `gemini-3.5-flash-lite` |
| `GEMINI_EMBEDDING_MODEL` | Index-building model; defaults to `gemini-embedding-001` |
| `DOCULENS_EMBEDDING_TPM` | Offline embedding pace, estimated tokens/minute; defaults to 24000 |
| `DOCULENS_API_TOKEN` | Optional locally; recommended on Vercel |
| `DOCULENS_PUBLIC_DEMO` | Set exactly `true` to allow public answers when no access token is configured |
| `DOCULENS_INDEX_DIR` | Optional corpus directory override; defaults to the bundled `data/corpus/` |
| `EDGAR_USER_AGENT` | Needed only by offline ingestion; include your real name and contact email |

`GOOGLE_API_KEY` remains a compatibility alias for `GEMINI_API_KEY`. The old OpenAI and Anthropic variables are unused.

Use Vercel's environment-variable controls for secrets. Never put credentials in source files, a public URL, or browser JavaScript.

## Deploy with Git

1. Merge [PR #1](https://github.com/pritishhhh/DocuLens/pull/1) into `master`, or explicitly select `codex/rag-vercel-review` as the deployment branch. The fixes are on that branch until the PR is merged.
2. Import the repository into Vercel.
3. Select the FastAPI framework preset and repository root. Leave Build Command and Output Directory at their defaults so Vercel uses the configured Python build hook.
4. Add `GEMINI_API_KEY` for the deployment environment. For a public demo, add `DOCULENS_PUBLIC_DEMO=true`. For restricted access, set `DOCULENS_API_TOKEN` instead. Index-building variables and `EDGAR_USER_AGENT` are not needed for deployment.
5. Deploy and verify `/health`, `/corpus`, and a question supported by the corpus.

The bundled NVDA corpus contains four filings: the fiscal 2026 10-K and the 10-Q filings for periods ended October 26, 2025, April 26, 2026, and July 26, 2026. The latest included filing was submitted August 26, 2026. The interface shows the exact coverage. Frozen fiscal 2025 summary excerpts in `data/reference/` are used only for repeatable evaluation.

To demonstrate the bundled data, ask: **What was NVIDIA's revenue in fiscal year 2026, in billions of dollars?**

Before importing, you can run `python scripts/check_deployment.py` locally. A successful `/health` response confirms process liveness; check `/corpus` and a supported question to verify the configured deployment. Keep `.env` local and enter secrets through Vercel's environment-variable settings.

## Refresh the corpus

Run ingestion and indexing locally:

```bash
python -m app.ingestion.edgar --ticker NVDA --forms 10-K 10-Q --count 4
python -m app.ingestion.vectorstore --build --ticker NVDA
```

Review and deploy the generated `data/corpus/NVDA.json`. It contains public filing excerpts and vectors, without API keys. Git deployments require this generated file to be committed; local ignored files are not available to a remote build.

The built index records its embedding model and dimensions. Query embeddings use those same settings, even if the deployment's index-building environment variable changes. Rebuild the entire index to switch embedding models. Completed batches are cached under ignored `data/index/embedding-cache.json`; rerunning after a quota interruption resumes from completed content. The pace uses a conservative character estimate and can be lowered with `DOCULENS_EMBEDDING_TPM` for a smaller project quota.

Ingestion follows SEC fair-access guidance, identifies its client, spaces requests, follows older submissions files when needed, and retains accession numbers, reporting dates, and SEC document URLs. Hosting networks may still be blocked by SEC. Run ingestion locally in that case.

## Access and quotas

With `DOCULENS_API_TOKEN`, answer requests require `Authorization: Bearer <token>`. The interface accepts the token in a password field, uses it for one request, and clears it. Company coverage and process liveness remain public.

With `DOCULENS_PUBLIC_DEMO=true`, visitors share the owner's provider quota. Configure Vercel Firewall rate limiting for `POST /query` before sharing a public deployment widely. In-memory limits are deliberately avoided because serverless instances do not share memory.

Do not enable paid Gemini billing merely to bypass free quotas unless you intend to pay for usage. There is no automatic paid-provider fallback.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| No companies shown | Check that `data/corpus/*.json` exists in the deployed Git revision |
| 404 on a company | Build and deploy that company's index |
| 401 on a question | Supply the configured deployment access token |
| 503 on Vercel | Set the Gemini key and choose protected access or an explicit public demo |
| 429 | Check project-specific Gemini quotas in AI Studio; retry later |
| Answer withheld | Inspect coverage and filters; add the filing or ask a narrower question |
| Wrong model or embedding dimensions | Rebuild the corpus with a supported model and redeploy |

## Platform references

- [Vercel FastAPI deployment](https://vercel.com/docs/frameworks/backend/fastapi)
- [Vercel function limits](https://vercel.com/docs/functions/limitations)
- [Gemini pricing and free tiers](https://ai.google.dev/gemini-api/docs/pricing)
- [Gemini embedding task types](https://ai.google.dev/gemini-api/docs/embeddings)
- [SEC automated access guidance](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data)
