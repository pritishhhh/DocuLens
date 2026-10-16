# RAG and deployment review

Review baseline: Git commit `8a4d6d7`.

## Critical findings

| Finding | Effect | Resolution |
| --- | --- | --- |
| `google-generativeai` installed, `google.genai` imported | Clean installations cannot initialize the provider | Use one small Gemini REST client with server-side keys |
| Same-quote nested f-strings used with Python 3.11 Docker/CI | Several modules fail to parse on the documented runtime | Use Python 3.12+ and syntax checks; rewrite affected modules |
| Critic failure returned the rejected answer after retries | Unsupported financial claims escape the quality gate | Return a clear abstention with no rejected answer or sources |
| Generated table answers added to the judge's context | A hallucination can become its own supporting evidence | Retrieve raw tables and judge against original excerpts only |
| Writable Chroma directory and file-based tracing in the deployment | Serverless persistence/read-only filesystem failures | Bundle a read-only corpus and log structured events to stdout |
| Heavy sentence-transformer/Chroma dependency chain | Large bundles, cold starts, runtime weight downloads | Use hosted embeddings and lightweight local retrieval |
| Evaluation ignores `expected_answer_contains` | No independent check of answer correctness | Pin explicit reference facts, patterns, source chunks, and abstention cases |

## Retrieval and ingestion findings

- Text splitting could emit an empty chunk and leave oversized paragraphs unsplit. The new splitter is bounded, overlaps narrative chunks, and does not discard short labels.
- Every table was removed from narrative, including layout tables and parsing failures. Layout content is now retained; extracted numeric tables are separated.
- Long tables had no row-group splitting or repeated context. Row groups now repeat headers and retain nearby unit/section context.
- Table-to-Markdown required an undeclared `tabulate` dependency. The parser now uses BeautifulSoup without pandas or tabulate.
- Multi-level headers and spans could lose alignment. Row/column spans are expanded, subject to bounds.
- Hidden inline XBRL, scripts, and styles could contaminate the searchable text. These nodes are excluded.
- Numeric routes retrieved only text through the main retriever, while narrative routes could miss tables. Every route now searches both evidence types.
- No retrieval threshold, period filter, or original-source citation IDs existed. The new store filters metadata, combines lexical and semantic ranks, and applies a semantic similarity floor.
- Local paths were exposed as citations. Sources now include a filing URL, accession, form, filing date, reporting date, section, and excerpt.
- Ingestion dropped filing URL/reporting-period provenance and identified downloads only by form/date. Accession-based filenames and manifests now preserve identity.
- Only the SEC 'recent' submissions list was searched. Archived submissions files are followed when needed.
- Invalid ticker/path inputs were not constrained. Tickers and SEC filename components are validated.
- Rebuilding Chroma could duplicate or retain stale chunks; short ticker collection names were also problematic. Atomic per-ticker snapshot replacement avoids both issues.
- Query and document embedding roles were indistinguishable. The new implementation uses `RETRIEVAL_DOCUMENT` and `RETRIEVAL_QUERY`, normalizes vectors, and records the model/dimensions.
- The retry query appended generic text to the user's question. Retries now expand the evidence count without changing the question.
- 'Most recent' had no period policy. Singular latest annual/quarterly requests are resolved within the indexed snapshot, with the applied filters returned.

## Reliability and security findings

- Provider retries covered configuration and parsing failures indiscriminately. Permanent provider errors and quota failures now return controlled responses without repeated calls; transient server errors receive one retry.
- Model responses could be empty, blocked, truncated, malformed, or contain invalid score ranges. These conditions now fail closed.
- Generation and judge prompts interpolated untrusted text without an instruction boundary. System instructions now treat input excerpts as data; output schemas and exact-quote checks add independent validation.
- The old router spent an API call on every query. A deterministic hint now chooses evidence ordering; it cannot exclude a source modality.
- Unbounded questions and missing symbols were not handled. API validation limits questions and rejects invalid forms, dates, symbols, and unexpected fields.
- No distinction existed between missing corpus, missing provider configuration, quota exhaustion, and internal failures. These now have actionable HTTP responses.
- The public API could silently consume the owner's key. Vercel requires a deployment token or explicit public-demo configuration.
- Tracing wrote to disk on every LLM call, potentially masking the original error. It now logs durations and exception types without prompts, credentials, or raw provider errors.
- Docker Compose passed an OpenAI key; CI passed an Anthropic key. Both now use the same Gemini configuration.
- CI lacked pytest and expected an ignored, nonexistent index. Offline checks now use a bundled corpus and isolated fixtures; live evaluation is manual.
- The frontend renders model and filing content with text nodes, validates SEC links, and uses a restrictive content security policy.

## Documentation corrections

The original README claimed multimodal/ColPali retrieval, TAPEX-style table reasoning, RAGAS scores, 20 hand-verified references, context precision, reranking, and CI quality gates that were absent or stubbed. It also documented the wrong provider and included interview instructions.

The replacement describes the implemented text/table pipeline, dated filing coverage, actual verification method, setup, deployment, and limits. The unused visual stub and unused heavyweight libraries were removed. The LangGraph wrapper was replaced with a small explicit workflow: retrieval, synthesis, verification, and one bounded expansion.

## Remaining limits

- The same model family generates and reviews answers. Exact-quote validation catches invented evidence, but neither it nor an LLM judge proves entailment, arithmetic, or financial correctness.
- Table extraction remains heuristic. Complex nested layouts, missing HTML units, and visually encoded values need manual review or a dedicated layout parser.
- This is an HTML pipeline, without OCR, image retrieval, chart interpretation, XBRL numeric validation, or deterministic accounting calculations.
- The tiny pinned reference set is a smoke test. A broad financial RAG evaluation would need many verified companies, periods, tables, arithmetic questions, and adversarial cases.
- Snapshot retrieval is intended for a small corpus. It scans candidate chunks in memory. Use a managed index for larger corpora, multi-user document isolation, or live ingestion.
- Free provider quotas and regional access vary. Public deployments need external rate limiting; the application does not claim distributed abuse prevention.
- A Git corpus refresh changes generated chunk IDs. Frozen evaluation excerpts are stored separately from the serving corpus; update custom evaluation references deliberately when regenerating their source chunks.

These limits are documented rather than disguised as completed features.
