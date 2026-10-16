"""Offline SEC ingestion with fair-access headers, bounded requests, and provenance."""
import argparse
import json
import os
import re
import time
from pathlib import Path

import requests

from app.config import ROOT, ticker_symbol

DATA_DIR = ROOT / "data" / "filings"
TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
_last_request = 0.0


def _headers():
    ua = os.getenv("EDGAR_USER_AGENT", "")
    if not re.search(r"[^\s@]+@[^\s@]+\.[^\s@]+", ua):
        raise RuntimeError('Set EDGAR_USER_AGENT="Your name your-email@example.com" as required by SEC fair access.')
    return {"User-Agent": ua, "Accept-Encoding": "gzip, deflate"}


def _get(url):
    global _last_request
    for attempt in range(3):
        time.sleep(max(0, 0.25 - (time.monotonic() - _last_request)))
        _last_request = time.monotonic()
        response = requests.get(url, headers=_headers(), timeout=(5, 45))
        if response.status_code in (429, 500, 502, 503) and attempt < 2:
            time.sleep(2 ** attempt)
            continue
        if response.status_code == 403:
            raise RuntimeError("SEC blocked this request. Verify your EDGAR_USER_AGENT and retry later.")
        response.raise_for_status()
        return response
    raise RuntimeError("SEC is unavailable")


def ticker_to_cik(ticker: str) -> str:
    ticker = ticker_symbol(ticker)
    for entry in _get(TICKER_MAP_URL).json().values():
        if entry["ticker"].upper() == ticker:
            return str(entry["cik_str"]).zfill(10)
    raise ValueError(f"Ticker {ticker} was not found in the SEC ticker table")


def list_filings(cik: str, forms=("10-K", "10-Q"), count: int = 4):
    if not 1 <= count <= 40 or not set(forms) <= {"10-K", "10-Q"}:
        raise ValueError("Use 1-40 filings and forms 10-K / 10-Q")
    data = _get(SUBMISSIONS_URL.format(cik=cik)).json()
    groups = [data["filings"]["recent"]]
    out = []

    def collect(group):
        for i, form in enumerate(group["form"]):
            if form in forms and group["primaryDocument"][i]:
                out.append({"form": form, "filingDate": group["filingDate"][i],
                            "reportDate": group.get("reportDate", [""] * len(group["form"]))[i],
                            "accessionNumber": group["accessionNumber"][i],
                            "primaryDocument": group["primaryDocument"][i]})

    collect(groups[0])
    # Older filings may be in the submissions archive rather than 'recent'.
    for older in data["filings"].get("files", []):
        if len(out) >= count:
            break
        name = older["name"]
        if not re.fullmatch(r"CIK\d+-submissions-\d+\.json", name):
            raise ValueError("Unexpected SEC submissions archive name")
        collect(_get("https://data.sec.gov/submissions/" + name).json())
    return sorted({f["accessionNumber"]: f for f in out}.values(),
                  key=lambda f: (f["filingDate"], f["accessionNumber"]), reverse=True)[:count]


def filing_url(cik, filing):
    document = filing["primaryDocument"]
    accession = filing["accessionNumber"]
    if not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession) or not re.fullmatch(r"[\w.-]+", document):
        raise ValueError("Unexpected SEC filing path")
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/{document}"


def download_filing(cik: str, filing: dict, out_dir: Path) -> Path:
    url = filing_url(cik, filing)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{filing['accessionNumber']}_{filing['primaryDocument']}"
    content = _get(url).content
    if b"<html" not in content[:20000].lower():
        raise ValueError("SEC did not return an HTML filing")
    path.write_bytes(content)
    filing.update(source_url=url, local_file=path.name)
    return path


def ingest(ticker: str, forms, count: int):
    ticker = ticker_symbol(ticker)
    cik = ticker_to_cik(ticker)
    filings = list_filings(cik, forms, count)
    if not filings:
        raise ValueError("No matching filings were found")
    out_dir = DATA_DIR / ticker
    saved = []
    for filing in filings:
        path = download_filing(cik, filing, out_dir)
        saved.append(str(path))
        print(f"Saved {filing['form']} ({filing['filingDate']})")
    (out_dir / "manifest.json").write_text(json.dumps(filings, indent=2), encoding="utf-8")
    return saved


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--forms", nargs="+", choices=["10-K", "10-Q"], default=["10-K", "10-Q"])
    parser.add_argument("--count", type=int, default=4)
    args = parser.parse_args()
    ingest(args.ticker, args.forms, args.count)
