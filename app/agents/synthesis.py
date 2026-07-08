from app.llm import call_llm
from app.tracing import trace_step
SYNTHESIS_PROMPT = "You are a financial analyst assistant. Answer the user's question\nusing ONLY the context provided below. Every claim must be traceable to the context.\nIf the context is insufficient, say so explicitly rather than filling gaps from\ngeneral knowledge.\n\nContext:\n{context}\n\nQuestion: {question}\n\nGive a concise, well-cited answer. After the answer, list the source documents used."

def synthesize(question: str, text_results: list, table_result: dict | None):
    context_parts = []
    for r in text_results:
        context_parts.append(f'[{r['metadata']['source_file']}]\n{r['content']}')
    if table_result and table_result.get('answer'):
        context_parts.append(f'[table_answer]\n{table_result['answer']}')
    context = '\n\n---\n\n'.join(context_parts) if context_parts else '(no context retrieved)'
    with trace_step('synthesis', {'num_context_chunks': len(context_parts)}):
        answer = call_llm(SYNTHESIS_PROMPT.format(context=context, question=question))
    sources = list({r['metadata']['source_file'] for r in text_results})
    if table_result:
        sources.extend(table_result.get('tables_used', []))
    return {'answer': answer, 'sources': sorted(set(sources)), 'context_used': context}