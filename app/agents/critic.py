"""
Critic agent.

Before an answer is returned to the user, score it for faithfulness (is every
claim actually supported by the retrieved context?) and answer relevancy (does
it actually address the question?) using a direct LLM-as-judge prompt rather
than the RAGAS library, to avoid RAGAS's LangChain-community dependency chain.
If it fails the threshold, the graph re-retrieves with a broadened query.
"""
import json
import re

from app.llm import call_llm
from app.tracing import trace_step

FAITHFULNESS_THRESHOLD = 0.7
RELEVANCY_THRESHOLD = 0.6

JUDGE_PROMPT = """You are grading an AI-generated answer for quality. Score it on two dimensions, each from 0.0 to 1.0:

- faithfulness: does every claim in the answer come directly from the provided context, with no invented/hallucinated facts?
- answer_relevancy: does the answer actually address the question asked?

Context:
{context}

Question: {question}

Answer to grade:
{answer}

Respond with ONLY valid JSON in this exact format, nothing else:
{{"faithfulness": 0.0, "answer_relevancy": 0.0}}"""


def critique(question: str, answer: str, context_used: str) -> dict:
    with trace_step("critic_eval", {}):
        raw = call_llm(
            JUDGE_PROMPT.format(
                context=context_used,
                question=question,
                answer=answer,
            ),
            max_tokens=1024,
            json_mode=True,
        )

        raw = raw.strip()

        try:
            scores = json.loads(raw)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if not match:
                raise RuntimeError(f"Gemini didn't return JSON.\n\n{raw}")

            scores = json.loads(match.group(0))

    f_score = float(scores["faithfulness"])
    r_score = float(scores["answer_relevancy"])
    passed = f_score >= FAITHFULNESS_THRESHOLD and r_score >= RELEVANCY_THRESHOLD

    return {
        "passed": passed,
        "faithfulness": f_score,
        "answer_relevancy": r_score,
        "thresholds": {"faithfulness": FAITHFULNESS_THRESHOLD, "answer_relevancy": RELEVANCY_THRESHOLD},
    }