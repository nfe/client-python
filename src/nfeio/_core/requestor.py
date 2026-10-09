"""Build requests per API family, send them with retry, decode bodies and map errors."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from typing import Any
from urllib.parse import urlencode, urljoin, urlsplit

from .._config import ApiFamily, ClientConfig, RequestOptions, Timeout
from ..errors import UnexpectedResponseError
from ..models._base import ResponseInfo
from . import jsonutil
from .error_mapping import error_from_response
from .ops import Op
from .redact import log_path
from .retry import send_with_retry
from .transport import HttpRequest, HttpResponse

logger = logging.getLogger("nfeio")

REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
MAX_REDIRECTS = 3

QueryValue = str | int | bool | None


def _encode_query(query: Mapping[str, QueryValue] | None) -> str:
    if not query:
        return ""
    pairs: list[tuple[str, str]] = []
    for key, value in query.items():
        if value is None:
            continue
        if isinstance(value, bool):
            pairs.append((key, "true" if value else "false"))
        else:
            pairs.append((key, str(value)))
    return "?" + urlencode(pairs) if pairs else ""


def _timeout(cfg: ClientConfig, options: RequestOptions | None) -> Timeout:
    if options is not None and isinstance(options.timeout, Timeout):
        return options.timeout
    return cfg.timeout


def _retries(cfg: ClientConfig, options: RequestOptions | None) -> int:
    if options is not None and options.max_retries is not None:
        return options.max_retries
    return cfg.max_retries


def request(
    cfg: ClientConfig,
    method: str,
    family: ApiFamily,
    path: str,
    *,
    query: Mapping[str, QueryValue] | None = None,
    json: Any = None,
    body: bytes | None = None,
    content_type: str | None = None,
    accept: str = "application/json",
    options: RequestOptions | None = None,
    external_id: str | None = None,
    secrets: Iterable[str] = (),
    allow_redirect: bool = False,
) -> Op[HttpResponse]:
    """Send an authenticated request and return the response if its status is < 300.

    Raises the mapped :class:`~nfeio.errors.APIError` for >= 400. A 3xx is returned only when
    ``allow_redirect`` is set (downloads, which follow it without credentials); anywhere else
    it raises :class:`UnexpectedResponseError` instead of being mistaken for an empty answer.
    """
    key = cfg.key_for(family, options)  # ConfigurationError before any I/O
    method = method.upper()
    url = cfg.base_urls[family] + path + _encode_query(query)
    headers: dict[str, str] = {
        "Authorization": key,
        "User-Agent": cfg.user_agent,
        "Accept": accept,
        "Accept-Encoding": "identity",
    }
    if json is not None:
        body = jsonutil.dumps(json)
        content_type = "application/json; charset=utf-8"
    if content_type is not None:
        headers["Content-Type"] = content_type
    if options is not None:
        if options.idempotency_key is not None:
            headers["Idempotency-Key"] = options.idempotency_key
        if options.extra_headers:
            headers.update(options.extra_headers)
    req = HttpRequest(
        method=method,
        url=url,
        headers=headers,
        body=body,
        timeout=_timeout(cfg, options),
        max_response_bytes=cfg.max_response_bytes,
    )
    response = yield from send_with_retry(
        cfg, req, max_retries=_retries(cfg, options), external_id=external_id
    )
    logger.debug(
        "nfeio request: %s %s%s -> %d (request_id=%s)",
        method,
        urlsplit(url).hostname,
        log_path(path),
        response.status_code,
        response.headers.get("x-request-id"),
    )
    if response.status_code >= 400:
        raise error_from_response(
            response,
            family=family,
            method=method,
            external_id=external_id,
            secrets=(key, *secrets),
        )
    if response.status_code >= 300 and not allow_redirect:
        raise UnexpectedResponseError(
            f"unexpected redirect status {response.status_code}",
            status_code=response.status_code,
            headers=response.headers,
        )
    return response


def follow_download(
    cfg: ClientConfig,
    response: HttpResponse,
    *,
    family: ApiFamily,
    origin_url: str,
    accept: str,
    options: RequestOptions | None,
) -> Op[HttpResponse]:
    """Follow up to 3 redirects of a download **without any credential**, https only."""
    current_url = origin_url
    hops = 0
    while response.status_code in REDIRECT_STATUSES:
        if hops >= MAX_REDIRECTS:
            raise UnexpectedResponseError(
                f"too many redirects (more than {MAX_REDIRECTS})",
                status_code=response.status_code,
                headers=response.headers,
            )
        location = response.headers.get("location")
        if not location:
            raise UnexpectedResponseError(
                "redirect without Location header",
                status_code=response.status_code,
                headers=response.headers,
            )
        target = urljoin(current_url, location.strip())
        parts = urlsplit(target)
        if parts.scheme != "https" or not parts.hostname:
            raise UnexpectedResponseError(
                "refusing to follow a redirect that is not https",
                status_code=response.status_code,
                headers=response.headers,
            )
        hops += 1
        # The pre-signed URL is self-authenticating: never forward the API key.
        req = HttpRequest(
            method="GET",
            url=target,
            headers={
                "User-Agent": cfg.user_agent,
                "Accept": accept,
                "Accept-Encoding": "identity",
            },
            timeout=_timeout(cfg, options),
            max_response_bytes=cfg.max_response_bytes,
        )
        response = yield from send_with_retry(cfg, req, max_retries=_retries(cfg, options))
        current_url = target
        if response.status_code >= 400:
            raise error_from_response(response, family=family, method="GET")
    return response


def decode_json(response: HttpResponse, *, allow_empty: bool = False) -> Any:
    """Decode a 2xx JSON body or raise :class:`UnexpectedResponseError`."""
    if not response.body.strip():
        if allow_empty:
            return None
        raise UnexpectedResponseError(
            "expected a JSON body but the response was empty",
            status_code=response.status_code,
            headers=response.headers,
        )
    try:
        return jsonutil.loads(response.body)
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise UnexpectedResponseError(
            "response body is not valid JSON",
            status_code=response.status_code,
            body=response.body,
            headers=response.headers,
        ) from None


def expect_object(response: HttpResponse, *, unwrap: str | None = None) -> dict[str, Any]:
    """Decode a JSON object, optionally unwrapping ``{unwrap: {...}}``."""
    data = decode_json(response)
    if unwrap is not None and isinstance(data, dict) and isinstance(data.get(unwrap), dict):
        data = data[unwrap]
    if not isinstance(data, dict):
        raise UnexpectedResponseError(
            "expected a JSON object in the response",
            status_code=response.status_code,
            body=response.body,
            headers=response.headers,
        )
    return data


def expect_list(response: HttpResponse, key: str) -> tuple[dict[str, Any], list[Any]]:
    """Decode ``{key: [...] , ...}`` and return ``(envelope, items)``."""
    data = decode_json(response)
    if not isinstance(data, dict) or not isinstance(data.get(key), list):
        raise UnexpectedResponseError(
            f"expected a JSON object with a {key!r} list",
            status_code=response.status_code,
            body=response.body,
            headers=response.headers,
        )
    return data, data[key]


def response_info(response: HttpResponse) -> ResponseInfo:
    return ResponseInfo(status_code=response.status_code, headers=response.headers)
