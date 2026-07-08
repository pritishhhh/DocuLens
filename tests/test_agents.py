from unittest.mock import patch
from app.ingestion.chunker import chunk_filing
import tempfile
from pathlib import Path
SAMPLE_HTML = '\n<html><body>\n<h2>Risk Factors</h2>\n<p>Our business depends on the continued success of our supply chain partners\nand any disruption could materially affect our results of operations and\noverall financial condition going forward into future fiscal periods.</p>\n<h2>Financial Data</h2>\n<table>\n<tr><th>Quarter</th><th>Revenue</th></tr>\n<tr><td>Q1</td><td>100</td></tr>\n<tr><td>Q2</td><td>120</td></tr>\n</table>\n</body></html>\n'

def test_chunker_splits_text_and_tables():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / 'sample.htm'
        path.write_text(SAMPLE_HTML)
        chunks = chunk_filing(path)
        kinds = {c.kind for c in chunks}
        assert 'table' in kinds
        assert 'text' in kinds
        table_chunk = next((c for c in chunks if c.kind == 'table'))
        assert 'Revenue' in table_chunk.content

@patch('app.agents.router.call_llm', return_value='numeric_lookup')
def test_router_classifies_numeric(mock_llm):
    from app.agents.router import route
    assert route('What was total revenue last quarter?') == 'numeric_lookup'

@patch('app.agents.router.call_llm', return_value='garbage_unparseable_label')
def test_router_falls_back_safely(mock_llm):
    from app.agents.router import route
    assert route('some ambiguous question') == 'qualitative_risk'