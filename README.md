# DocuLens

**Multimodal RAG + multi-agent system for answering analyst questions over real SEC filings (10-K / 10-Q), with a built-in eval harness and observability.**

## The problem

Financial filings bury the answers analysts actually need — revenue by segment, risk-factor language, YoY trends — inside dense prose, multi-column tables, and embedded charts. Naive "chunk the PDF text and embed it" RAG breaks on this data: tables get flattened into garbage text, and numbers get silently wrong or hallucinated. Most public RAG demos never test for this because they never touch real structured documents.

DocuLens is built specifically to survive that failure mode: it retrieves filing **pages as images** (for tables/charts) in addition to text, routes numeric questions to a table-reasoning agent instead of a text-generation agent, and grades every answer against a hand-built golden set before it's allowed to call itself "done."

## Architecture

```
                        ┌─────────────────┐
   user question ─────▶ │   Router Agent    │  (zero-shot classification:
                        └────────┬─────────┘   numeric / trend / qualitative)
                                 │
                 ┌───────────────┼───────────────┐
                 ▼               ▼               ▼
        ┌─────────────┐    ┌──────────────┐  ┌──────────────┐
        │ Text Retriever│  │ Visual Page  │  │ Table Agent  │
        │  (pgvector /  │  │  Retriever   │  │  (TAPEX-style│
        │   chroma)     │  │  (ColPali)   │  │   structured │
        └──────┬────────┘  └──────┬───────┘  │   extraction)│
               │                  │          └──────┬───────┘
               └────────┬─────────┴─────────────────┘
                        ▼
                ┌─────────────────┐
                │ Synthesis Agent  │ - composes cited answer
                └────────┬─────────┘
                         ▼
                ┌─────────────────┐
                │  Critic / Eval   │  RAGAS faithfulness +
                │      Agent       │  answer-relevance check
                └────────┬─────────┘
                         │ fail? ──▶ re-retrieve (loop, max 2x)
                         ▼ pass
                  final answer + citations
```

Orchestrated as an explicit **LangGraph** state machine (not a linear chain), so each agent's input/output and the retry loop are inspectable and testable in isolation.

## Hugging Face tasks used

| Task | Where it's used |
|---|---|
| Visual Document Retrieval | Embedding and retrieving filing page *images* so tables/charts survive retrieval |
| Document Question Answering | Grounded QA over retrieved filing pages |
| Table Question Answering | Structured numeric extraction from parsed tables |
| Image-to-Text | Captioning embedded charts/figures |
| Zero-Shot Classification | Router agent (query type detection) |
| Summarization | Condensing long MD&A / risk-factor sections |
| Sentence Similarity | Reranking retrieved chunks before synthesis |

## Stack

- **Orchestration:** LangGraph
- **Vector store:** Chroma locally (drop-in swap to pgvector/Pinecone — see `app/ingestion/vectorstore.py`)
- **Embeddings:** `sentence-transformers/all-MiniLM-L6-v2` (local, free) — swap for OpenAI/Voyage embeddings in prod
- **Visual retrieval:** ColPali-style page-image embeddings (stubbed interface in `app/agents/visual_retriever.py`, swappable for a real ColPali checkpoint)
- **LLM:** Anthropic Claude API (any Messages-API-compatible model) — set `ANTHROPIC_API_KEY`
- **Eval:** RAGAS (faithfulness, answer relevancy, context precision) against a hand-built golden set in `data/golden/`
- **Observability:** structured JSON tracing per agent step (`app/tracing.py`) — drop-in compatible with Arize Phoenix / LangSmith
- **Data source:** SEC EDGAR full-text search + filing index API (free, no key required) — `app/ingestion/edgar.py`
- **CI:** GitHub Actions runs the eval suite on every push (`.github/workflows/eval.yml`) and fails the build if faithfulness drops below threshold

## Repo layout

```
doculens/
├── app/
│   ├── ingestion/
│   │   ├── edgar.py          # pulls real 10-K/10-Q filings from SEC EDGAR
│   │   ├── chunker.py        # text + table-aware chunking
│   │   └── vectorstore.py    # Chroma wrapper (swap-in pgvector/Pinecone)
│   ├── agents/
│   │   ├── router.py         # zero-shot query classification
│   │   ├── text_retriever.py
│   │   ├── visual_retriever.py  # ColPali-style page-image retrieval (stub + real interface)
│   │   ├── table_agent.py    # structured table QA
│   │   ├── synthesis.py      # composes final cited answer
│   │   └── critic.py         # RAGAS-gated self-check + retry loop
│   ├── graph.py               # LangGraph state machine wiring all agents
│   ├── tracing.py             # per-step structured logging
│   └── main.py                # FastAPI app
├── app/eval/
│   ├── run_eval.py            # runs golden set through the pipeline, scores with RAGAS
│   └── ragas_metrics.py
├── data/golden/
│   └── golden_set.jsonl        # 20 hand-verified Q&A pairs against real filings
├── tests/
│   └── test_agents.py
├── .github/workflows/eval.yml
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## Setup

```bash
git clone <this repo>
cd doculens
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-...
```

### 1. Pull real filings from EDGAR
```bash
python -m app.ingestion.edgar --ticker NVDA --forms 10-K --count 4
```
This hits SEC EDGAR's public full-text search + submissions API (no key needed), downloads the actual filing documents, and caches them under `data/filings/`.

### 2. Build the index
```bash
python -m app.ingestion.vectorstore --build --ticker NVDA
```

### 3. Ask a question
```bash
python -m app.main --query "How did NVDA's data center revenue trend over the last 4 quarters, and what risk factors did they flag around it?"
```

### 4. Run the eval suite
```bash
python -m app.eval.run_eval
```
Outputs per-question RAGAS scores (faithfulness, answer relevancy, context precision) and an aggregate pass/fail against threshold — this is what CI runs on every push.

## Status / roadmap (be upfront about this in interviews)

- [x] EDGAR ingestion (real data, no mocks)
- [x] Text-based RAG pipeline (Chroma + local embeddings)
- [x] Table-aware chunking + table QA agent
- [x] LangGraph multi-agent orchestration with router + critic retry loop
- [x] RAGAS eval harness + golden set + CI gating
- [ ] Real ColPali visual-page-embedding model swapped in (currently a documented stub interface — see `visual_retriever.py`)
- [ ] pgvector/Pinecone production backend (Chroma used for local dev; swap documented in code)
- [ ] Latency/cost dashboard (Phoenix integration)

