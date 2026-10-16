"""A retrieval hint; every route still retrieves both text and tables."""
import re

LABELS = ("numeric_lookup", "trend_analysis", "qualitative_risk")


def route(question: str) -> str:
    if re.search(r"\b(trend|change|grew|growth|compare|comparison|year.over.year|yoy|over time)\b", question, re.I):
        return "trend_analysis"
    if re.search(r"\b(how much|how many|what was|what were|revenue|margin|income|cash|percentage|total)\b", question, re.I):
        return "numeric_lookup"
    return "qualitative_risk"
