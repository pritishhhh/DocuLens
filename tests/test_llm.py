from unittest.mock import Mock, patch

import pytest

from app.llm import InvalidModelOutput, ProviderError, call_llm, embed


def response(status, data):
    return Mock(status_code=status, ok=status < 400, json=Mock(return_value=data))


def test_key_uses_header_not_url():
    data = {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "{}"}]}}]}
    with patch("app.llm.requests.post", return_value=response(200, data)) as post:
        assert call_llm("hello") == "{}"
    assert "test-key" not in post.call_args.args[0]
    assert post.call_args.kwargs["headers"]["x-goog-api-key"] == "test-key"


def test_permanent_key_error_is_not_retried_or_leaked():
    with patch("app.llm.requests.post", return_value=response(403, {"secret": "test-key"})) as post:
        with pytest.raises(ProviderError) as error:
            call_llm("hello")
    assert post.call_count == 1
    assert "test-key" not in str(error.value)


def test_free_quota_error_does_not_retry():
    with patch("app.llm.requests.post", return_value=response(429, {})) as post:
        with pytest.raises(ProviderError) as error:
            call_llm("hello")
    assert error.value.status_code == 429
    assert post.call_count == 1


def test_embedding_normalization_and_retrieval_task():
    with patch("app.llm.requests.post", return_value=response(200, {"embeddings": [{"values": [3, 4]}]})) as post:
        assert embed(["text"], "RETRIEVAL_QUERY", dimensions=2) == [[0.6, 0.8]]
    assert post.call_args.kwargs["json"]["requests"][0]["taskType"] == "RETRIEVAL_QUERY"


@pytest.mark.parametrize("data", [{"embeddings": []}, {"embeddings": [{"values": [0, 0]}]},
                                  {"embeddings": [{"values": [float("nan"), 1]}]}])
def test_bad_embedding_response_is_rejected(data):
    with patch("app.llm.requests.post", return_value=response(200, data)):
        with pytest.raises(ProviderError):
            embed(["text"], "RETRIEVAL_QUERY", dimensions=2)


def test_truncated_generation_is_rejected():
    with patch("app.llm.requests.post", return_value=response(200, {"candidates": [{"finishReason": "MAX_TOKENS"}]})):
        with pytest.raises(InvalidModelOutput):
            call_llm("hello")
