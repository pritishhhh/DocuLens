"""Bounded text chunks and row-grouped tables with filing provenance."""
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from bs4 import BeautifulSoup
from bs4.element import NavigableString, Tag


@dataclass
class Chunk:
    chunk_id: str
    kind: str
    content: str
    source_file: str
    section_hint: str = ""
    source_url: str = ""
    form: str = ""
    filing_date: str = ""
    report_date: str = ""
    accession: str = ""


def split_text(text: str, limit: int, overlap: int = 180) -> list[str]:
    text = re.sub(r"[ \t]+", " ", text).strip()
    chunks = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break
        end = text.rfind(" ", limit // 2, limit)
        if end < 0:
            end = limit
        chunks.append(text[:end].strip())
        start = max(1, end - min(overlap, limit // 4))
        text = text[start:].lstrip()
    return [c for c in chunks if c]


def _section(tag) -> str:
    for prev in tag.find_all_previous(["h1", "h2", "h3", "h4", "b", "strong"], limit=12):
        value = prev.get_text(" ", strip=True)
        if 3 < len(value) < 180:
            return value
    return ""


def _table_rows(table) -> list[list[str]]:
    # Expand row/column spans, preserving alignment with multi-level year headers.
    grid = {}
    rows = table.find_all("tr")
    for r, row in enumerate(rows):
        if row.find_parent("table") is not table:
            continue
        col = 0
        for cell in row.find_all(["td", "th"], recursive=False):
            while (r, col) in grid:
                col += 1
            value = re.sub(r"\s+", " ", cell.get_text(" ", strip=True)).replace("|", "/")
            try:
                rs = min(100, max(1, int(cell.get("rowspan", 1))))
                cs = min(100, max(1, int(cell.get("colspan", 1))))
            except ValueError:
                rs, cs = 1, 1
            for dr in range(rs):
                for dc in range(cs):
                    grid[r + dr, col + dc] = value
            col += cs
    if not grid:
        return []
    width = min(150, max(c for _, c in grid) + 1)
    return [[grid.get((r, c), "") for c in range(width)]
            for r in range(max(r for r, _ in grid) + 1)]


def chunk_filing(html_path: Path, max_chars: int = 2800, metadata: dict | None = None) -> list[Chunk]:
    if max_chars < 400:
        raise ValueError("max_chars must be at least 400")
    metadata = metadata or {}
    soup = BeautifulSoup(html_path.read_text(encoding="utf-8", errors="replace"), "html.parser")
    for tag in list(soup.find_all(["script", "style", "noscript", "head"])):
        tag.decompose()
    for tag in list(soup.find_all()):
        if tag.attrs is None:
            continue
        style = re.sub(r"\s", "", tag.get("style", "").lower())
        if tag.name in ("ix:hidden", "ix:header") or tag.has_attr("hidden") or "display:none" in style:
            tag.decompose()
    chunks = []
    identity = metadata.get("accession", html_path.stem)

    def add(kind, content, section):
        digest = hashlib.sha256(f"{identity}|{kind}|{len(chunks)}|{content}".encode()).hexdigest()[:24]
        chunks.append(Chunk(chunk_id=digest, kind=kind, content=content,
                            source_file=html_path.name, section_hint=section,
                            **{k: metadata.get(k, "") for k in
                               ("source_url", "form", "filing_date", "report_date", "accession")}))

    # Inner numeric tables are extracted first; layout tables remain as narrative.
    for table in reversed(list(soup.find_all("table"))):
        if table.attrs is None or table.find("table"):
            continue
        rows = _table_rows(table)
        if len(rows) < 2 or max((len(r) for r in rows), default=0) < 2:
            continue
        if not any(re.search(r"\d", cell) for row in rows[1:] for cell in row):
            continue
        section = _section(table)
        caption = table.find("caption")
        nearby = [s.get_text(" ", strip=True) for s in table.previous_siblings
                  if getattr(s, "get_text", None)][:3]
        prefix = "\n".join(filter(None, [section, caption.get_text(" ", strip=True) if caption else "",
                                          " ".join(reversed(nearby))[-500:]]))[:700]
        # SEC tables often use several header rows (units, fiscal years, currency).
        header_count = 1
        for row_index, row in enumerate(rows[1:9], 1):
            values = [cell for cell in row[1:] if re.search(r"\d", cell)]
            # Year labels belong to the header; metric values begin the body.
            is_data = row[0].strip() and values and any(
                not re.fullmatch(r"(?:19|20)\d{2}", cell.strip()) for cell in values)
            if is_data:
                header_count = row_index
                break
            header_count = row_index + 1
        header_count = min(header_count, len(rows) - 1)
        header = "\n".join(" | ".join(r) for r in rows[:header_count])
        prefix = (prefix + "\n" + header)[:max_chars // 2]
        buf = prefix
        for row in rows[header_count:]:
            line = " | ".join(row)
            for part in split_text(line, max_chars - len(prefix) - 2, overlap=0):
                if len(buf) + len(part) + 1 > max_chars:
                    add("table", buf, section)
                    buf = prefix
                buf += "\n" + part
        add("table", buf, section)
        # Leave a marker so surrounding narrative still identifies the table.
        table.replace_with(soup.new_string("\n" + section + "\n"))

    # Walk text nodes once. Selecting only leaf paragraphs loses direct text
    # around nested blocks, standalone spans, and mixed-content layout cells.
    section = ""
    blocks = []
    for element in soup.descendants:
        if isinstance(element, Tag) and element.name in ("h1", "h2", "h3", "h4", "p", "div", "b", "strong"):
            title = element.get_text(" ", strip=True)
            is_heading = element.name.startswith("h") or (
                len(title) < 160 and re.match(r"Item\s+\d", title, re.I))
            if is_heading and title != section:
                if blocks:
                    for part in split_text("\n".join(blocks), max_chars):
                        add("text", part, section)
                    blocks = []
                section = title
        elif type(element) is NavigableString:
            value = re.sub(r"\s+", " ", str(element)).strip()
            if value:
                blocks.append(value)
    if not blocks and not chunks:
        blocks = [soup.get_text(" ", strip=True)]
    for part in split_text("\n".join(blocks), max_chars):
        add("text", part, section)
    return chunks
