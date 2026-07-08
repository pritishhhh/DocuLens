import argparse
from pathlib import Path
from typing import List
import chromadb
from sentence_transformers import SentenceTransformer
from app.ingestion.chunker import Chunk, chunk_filing
DATA_DIR = Path(__file__).resolve().parents[2] / 'data' / 'filings'
INDEX_DIR = Path(__file__).resolve().parents[2] / 'data' / 'index'
_model = None

def _embedder():
    global _model
    if _model is None:
        _model = SentenceTransformer('all-MiniLM-L6-v2')
    return _model

class ChromaStore:

    def __init__(self, collection_name: str):
        self.client = chromadb.PersistentClient(path=str(INDEX_DIR))
        self.collection = self.client.get_or_create_collection(collection_name)

    def add(self, chunks: List[Chunk]):
        if not chunks:
            return
        embeddings = _embedder().encode([c.content for c in chunks]).tolist()
        self.collection.add(ids=[c.chunk_id for c in chunks], embeddings=embeddings, documents=[c.content for c in chunks], metadatas=[{'kind': c.kind, 'source_file': c.source_file, 'section_hint': c.section_hint} for c in chunks])

    def query(self, text: str, k: int=5, kind: str=None):
        embedding = _embedder().encode([text]).tolist()
        where = {'kind': kind} if kind else None
        results = self.collection.query(query_embeddings=embedding, n_results=k, where=where)
        out = []
        for i in range(len(results['ids'][0])):
            out.append({'id': results['ids'][0][i], 'content': results['documents'][0][i], 'metadata': results['metadatas'][0][i], 'distance': results['distances'][0][i]})
        return out

def build_index(ticker: str):
    store = ChromaStore(collection_name=ticker.upper())
    filing_dir = DATA_DIR / ticker.upper()
    htm_files = list(filing_dir.glob('*.htm'))
    if not htm_files:
        raise FileNotFoundError(f'No filings found in {filing_dir}. Run app.ingestion.edgar first.')
    total = 0
    for f in htm_files:
        chunks = chunk_filing(f)
        store.add(chunks)
        total += len(chunks)
        print(f'indexed {len(chunks)} chunks from {f.name}')
    print(f'done. {total} total chunks indexed for {ticker.upper()}.')
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--build', action='store_true')
    parser.add_argument('--ticker', required=True)
    args = parser.parse_args()
    if args.build:
        build_index(args.ticker)