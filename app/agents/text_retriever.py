def retrieve_text(store, question: str, k: int = 5, **filters):
    return store.query(question, k=k, kind="text", **filters)
