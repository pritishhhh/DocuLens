from app.llm import call_llm
LABELS = ['numeric_lookup', 'trend_analysis', 'qualitative_risk']
ROUTER_PROMPT = 'Classify the following financial-filing question into exactly one label:\n- numeric_lookup: asks for a specific number or figure at one point in time\n- trend_analysis: asks how a metric changed over multiple periods\n- qualitative_risk: asks about risk factors, strategy, or narrative/qualitative content\n\nQuestion: {question}\n\nRespond with only the label, nothing else.'

def route(question: str) -> str:
    resp = call_llm(ROUTER_PROMPT.format(question=question), max_tokens=20)
    label = resp.strip().lower()
    for l in LABELS:
        if l in label:
            return l
    return 'qualitative_risk'