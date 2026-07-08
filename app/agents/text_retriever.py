from app.ingestion.vectorstore import ChromaStore
from app.tracing import trace_step

def retrieve_text(ticker: str, question: str, k: int=5):
    store = ChromaStore(collection_name=ticker.upper())
    with trace_step('text_retrieve', {'ticker': ticker, 'k': k}):
        return store.query(question, k=k, kind='text')