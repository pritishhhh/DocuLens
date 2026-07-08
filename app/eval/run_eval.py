import json
import sys
from pathlib import Path
from app.graph import ask
GOLDEN_PATH = Path(__file__).resolve().parents[2] / 'data' / 'golden' / 'golden_set.jsonl'
AGGREGATE_FAITHFULNESS_THRESHOLD = 0.7

def load_golden_set():
    with open(GOLDEN_PATH) as f:
        return [json.loads(line) for line in f if line.strip()]

def run():
    rows = load_golden_set()
    results = []
    for row in rows:
        print(f'--- {row['ticker']}: {row['question']}')
        out = ask(row['ticker'], row['question'])
        results.append({'question': row['question'], 'type': row['type'], 'route_matched_expected': out['route'] == row['type'], 'faithfulness': out['critique']['faithfulness'], 'answer_relevancy': out['critique']['answer_relevancy'], 'passed': out['critique']['passed'], 'retries': out['retries']})
        print(json.dumps(results[-1], indent=2))
    avg_faithfulness = sum((r['faithfulness'] for r in results)) / len(results)
    avg_relevancy = sum((r['answer_relevancy'] for r in results)) / len(results)
    pass_rate = sum((r['passed'] for r in results)) / len(results)
    summary = {'n_questions': len(results), 'avg_faithfulness': round(avg_faithfulness, 3), 'avg_answer_relevancy': round(avg_relevancy, 3), 'pass_rate': round(pass_rate, 3), 'route_accuracy': round(sum((r['route_matched_expected'] for r in results)) / len(results), 3)}
    print('\n=== EVAL SUMMARY ===')
    print(json.dumps(summary, indent=2))
    if avg_faithfulness < AGGREGATE_FAITHFULNESS_THRESHOLD:
        print(f'FAILED: avg faithfulness {avg_faithfulness} below threshold {AGGREGATE_FAITHFULNESS_THRESHOLD}')
        sys.exit(1)
if __name__ == '__main__':
    run()