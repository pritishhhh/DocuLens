"""Retrieve original tables, without laundering an LLM answer into evidence."""


def answer_from_tables(store, question: str, k: int = 4, **filters):
    return store.query(question, k=k, kind="table", **filters)
