import argparse
import json
import os
import time
from pathlib import Path
import requests
DATA_DIR = Path(__file__).resolve().parents[2] / 'data' / 'filings'
TICKER_MAP_URL = 'https://www.sec.gov/files/company_tickers.json'
SUBMISSIONS_URL = 'https://data.sec.gov/submissions/CIK{cik}.json'

def _headers():
    ua = os.environ.get('EDGAR_USER_AGENT')
    if not ua:
        raise RuntimeError('Set EDGAR_USER_AGENT env var, e.g. \'export EDGAR_USER_AGENT="Jane Doe jane@example.com"\' — SEC requires this on every request.')
    return {'User-Agent': ua}

def ticker_to_cik(ticker: str) -> str:
    resp = requests.get(TICKER_MAP_URL, headers=_headers(), timeout=30)
    resp.raise_for_status()
    table = resp.json()
    ticker = ticker.upper()
    for entry in table.values():
        if entry['ticker'] == ticker:
            return str(entry['cik_str']).zfill(10)
    raise ValueError(f'Ticker {ticker} not found in SEC ticker table')

def list_filings(cik: str, forms=('10-K', '10-Q'), count: int=4):
    resp = requests.get(SUBMISSIONS_URL.format(cik=cik), headers=_headers(), timeout=30)
    resp.raise_for_status()
    recent = resp.json()['filings']['recent']
    out = []
    for i, form in enumerate(recent['form']):
        if form in forms:
            out.append({'form': form, 'filingDate': recent['filingDate'][i], 'accessionNumber': recent['accessionNumber'][i], 'primaryDocument': recent['primaryDocument'][i]})
        if len(out) >= count:
            break
    return out

def download_filing(cik: str, filing: dict, out_dir: Path) -> Path:
    acc_no_nodash = filing['accessionNumber'].replace('-', '')
    url = f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_no_nodash}/{filing['primaryDocument']}'
    resp = requests.get(url, headers=_headers(), timeout=60)
    resp.raise_for_status()
    out_dir.mkdir(parents=True, exist_ok=True)
    fname = f'{filing['form']}_{filing['filingDate']}.htm'
    path = out_dir / fname
    path.write_bytes(resp.content)
    return path

def ingest(ticker: str, forms, count: int):
    cik = ticker_to_cik(ticker)
    filings = list_filings(cik, forms=forms, count=count)
    out_dir = DATA_DIR / ticker.upper()
    saved = []
    for f in filings:
        time.sleep(0.2)
        path = download_filing(cik, f, out_dir)
        saved.append(str(path))
        print(f'saved {f['form']} ({f['filingDate']}) -> {path}')
    manifest = out_dir / 'manifest.json'
    manifest.write_text(json.dumps(filings, indent=2))
    return saved
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--ticker', required=True)
    parser.add_argument('--forms', nargs='+', default=['10-K', '10-Q'])
    parser.add_argument('--count', type=int, default=4)
    args = parser.parse_args()
    ingest(args.ticker, args.forms, args.count)