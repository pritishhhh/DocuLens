from pathlib import Path

def retrieve_visual_pages(ticker: str, question: str, k: int=3):
    return [{'page_ref': f'{ticker.upper()}_10-K_page_STUB', 'note': 'Visual retrieval not yet wired to a real ColPali checkpoint — see module docstring for the swap-in implementation.', 'score': None} for _ in range(0)]