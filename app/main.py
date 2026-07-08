import argparse
import json
from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel
from app.graph import ask
load_dotenv()
api = FastAPI(title='DocuLens')

class QueryRequest(BaseModel):
    ticker: str
    question: str

@api.post('/query')
def query(req: QueryRequest):
    return ask(req.ticker, req.question)

@api.get('/health')
def health():
    return {'status': 'ok'}
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--ticker', required=True)
    parser.add_argument('--query', required=True)
    args = parser.parse_args()
    result = ask(args.ticker, args.query)
    print(json.dumps(result, indent=2))