from __future__ import annotations

from nfeio.transport import Headers


def test_case_insensitive_and_repeated() -> None:
    headers = Headers([("Set-Cookie", "a=1"), ("set-cookie", "b=2"), ("X-Request-Id", "r1")])
    assert headers["SET-COOKIE"] == "a=1, b=2"
    assert "x-request-id" in headers
    assert not headers.__contains__(5)
    assert list(headers) == ["Set-Cookie", "X-Request-Id"]
    assert len(headers) == 2
    assert headers.get("missing") is None


def test_equality_and_repr_redaction() -> None:
    headers = Headers({"Authorization": "secret-key-123", "Accept": "x"})
    assert headers == {"authorization": "secret-key-123", "ACCEPT": "x"}
    assert headers != {"Accept": "y"}
    assert (headers == 3) is False
    assert "secret-key-123" not in repr(headers)
    assert "<redacted>" in repr(headers)
    assert Headers() == {}
