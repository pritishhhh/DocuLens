import json
import time
from contextlib import contextmanager
from pathlib import Path
LOG_PATH = Path(__file__).resolve().parents[1] / 'data' / 'traces.jsonl'

@contextmanager
def trace_step(name: str, metadata: dict | None=None):
    start = time.time()
    error = None
    try:
        yield
    except Exception as e:
        error = str(e)
        raise
    finally:
        duration_ms = round((time.time() - start) * 1000, 2)
        record = {'step': name, 'duration_ms': duration_ms, 'metadata': metadata or {}, 'error': error, 'ts': time.time()}
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, 'a') as f:
            f.write(json.dumps(record) + '\n')