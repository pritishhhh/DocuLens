import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import List
import pandas as pd
from bs4 import BeautifulSoup

@dataclass
class Chunk:
    chunk_id: str
    kind: str
    content: str
    source_file: str
    section_hint: str = ''
    table_df: pd.DataFrame = field(default=None, repr=False)

def _guess_section(tag) -> str:
    for prev in tag.find_all_previous(['h1', 'h2', 'h3', 'b', 'strong'], limit=5):
        text = prev.get_text(strip=True)
        if text and len(text) < 120:
            return text
    return ''

def chunk_filing(html_path: Path, max_chars: int=1500) -> List[Chunk]:
    html = html_path.read_text(errors='ignore')
    soup = BeautifulSoup(html, 'lxml')
    chunks: List[Chunk] = []
    idx = 0
    for table in soup.find_all('table'):
        try:
            dfs = pd.read_html(io.StringIO(str(table)))
        except ValueError:
            continue
        for df in dfs:
            if df.shape[0] < 2 or df.shape[1] < 2:
                continue
            idx += 1
            chunks.append(Chunk(chunk_id=f'{html_path.stem}-table-{idx}', kind='table', content=df.to_markdown(index=False), source_file=str(html_path), section_hint=_guess_section(table), table_df=df))
        table.decompose()
    text = soup.get_text(separator='\n')
    paragraphs = [p.strip() for p in text.split('\n') if p.strip() and len(p.strip()) > 40]
    buf = ''
    for p in paragraphs:
        if len(buf) + len(p) > max_chars:
            idx += 1
            chunks.append(Chunk(chunk_id=f'{html_path.stem}-text-{idx}', kind='text', content=buf, source_file=str(html_path)))
            buf = p
        else:
            buf += '\n' + p
    if buf:
        idx += 1
        chunks.append(Chunk(chunk_id=f'{html_path.stem}-text-{idx}', kind='text', content=buf, source_file=str(html_path)))
    return chunks