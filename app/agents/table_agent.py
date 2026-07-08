from app.ingestion.vectorstore import ChromaStore
from app.llm import call_llm
from app.tracing import trace_step
TABLE_PROMPT = "You are analyzing a financial table extracted from an SEC filing.\nAnswer the question using ONLY the data in the table below. If the answer isn't in\nthe table, say so explicitly rather than guessing.\n\nTable:\n{table}\n\nQuestion: {question}\n\nAnswer concisely, citing the specific row/column values you used."

def answer_from_tables(ticker: str, question: str, k: int=3):
    store = ChromaStore(collection_name=ticker.upper())
    with trace_step('table_retrieve', {'ticker': ticker}):
        tables = store.query(question, k=k, kind='table')
    if not tables:
        return {'answer': None, 'tables_used': [], 'note': 'no matching tables found'}
    combined = '\n\n---\n\n'.join((t['content'] for t in tables))
    with trace_step('table_reasoning', {'num_tables': len(tables)}):
        answer = call_llm(TABLE_PROMPT.format(table=combined, question=question))
    return {'answer': answer, 'tables_used': [t['metadata']['source_file'] for t in tables]}