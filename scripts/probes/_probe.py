"""Read-only live probe helpers for the NFE.io API (stdlib only).

Safety rails:
- Only GET and HEAD are allowed; any other method raises before touching the network.
- API keys are read from ``.env`` and never written to disk or stdout. Request headers
  saved to ``out/`` have credentials replaced by ``<redacted>``.
- Redirects are NOT followed automatically so the raw 3xx (e.g. pre-signed download URLs)
  is observable. Pre-signed query strings are stripped before saving.
- Response bodies are capped at ``MAX_BODY`` bytes.

Raw output goes to ``scripts/probes/out/`` (gitignored). It can contain real third-party
data; the versioned summary in ``docs/contrato/`` must be redacted by hand.
"""

from __future__ import annotations

import base64
import json
import os
import platform
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "out"
MAX_BODY = 512 * 1024
ALLOWED_METHODS = frozenset({"GET", "HEAD"})
USER_AGENT = (
    f"nfe-io-python-probe/0.0 python/{sys.version_info.major}.{sys.version_info.minor} "
    f"{platform.system().lower()}"
)
SENSITIVE_HEADERS = frozenset({"authorization", "x-nfe-apikey", "apikey"})


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    path = ROOT / ".env"
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


ENV = load_env()
KEYS = {"main": ENV.get("NFE_API_KEY", ""), "data": ENV.get("NFE_DATA_API_KEY", "")}
COMPANY_ID = ENV.get("NFE_COMPANY_ID", "")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


_OPENER = urllib.request.build_opener(
    _NoRedirect(), urllib.request.HTTPSHandler(context=ssl.create_default_context())
)


def _auth(key_name: str | None, scheme: str) -> tuple[dict[str, str], dict[str, str]]:
    """Return (headers, query) for the chosen key and auth scheme."""
    if key_name is None:
        return {}, {}
    key = KEYS[key_name]
    if not key:
        raise SystemExit(f"missing key {key_name} in .env")
    if scheme == "x-nfe-apikey":
        return {"X-NFE-APIKEY": key}, {}
    if scheme == "authorization":
        return {"Authorization": key}, {}
    if scheme == "basic":
        token = base64.b64encode(f"{key}:".encode()).decode()
        return {"Authorization": f"Basic {token}"}, {}
    if scheme == "query":
        return {}, {"apikey": key}
    raise ValueError(scheme)


def _strip_presigned(url: str) -> str:
    """Keep only query parameter NAMES of a redirect target (values may be bearer tokens)."""
    parts = urllib.parse.urlsplit(url)
    if not parts.query:
        return url
    names = ",".join(k for k, _ in urllib.parse.parse_qsl(parts.query, keep_blank_values=True))
    return urllib.parse.urlunsplit(parts._replace(query=f"<stripped:{names}>"))


def request(
    host: str,
    path: str,
    *,
    key: str | None = "main",
    scheme: str = "x-nfe-apikey",
    method: str = "GET",
    params: dict[str, Any] | None = None,
    accept: str = "application/json",
    timeout: float = 30.0,
) -> dict[str, Any]:
    method = method.upper()
    if method not in ALLOWED_METHODS:
        raise RuntimeError(f"probe refused: {method} is not read-only")
    auth_headers, auth_query = _auth(key, scheme)
    query = {**(params or {}), **auth_query}
    url = f"https://{host}{path}"
    if query:
        url += "?" + urllib.parse.urlencode(query)
    headers = {"Accept": accept, "User-Agent": USER_AGENT, **auth_headers}
    req = urllib.request.Request(url, method=method, headers=headers)
    started = time.monotonic()
    status: int | None
    try:
        resp = _OPENER.open(req, timeout=timeout)
        status, resp_headers, body = resp.status, dict(resp.headers.items()), resp.read(MAX_BODY + 1)
    except urllib.error.HTTPError as e:
        status, resp_headers, body = e.code, dict(e.headers.items()), e.read(MAX_BODY + 1)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        status, resp_headers, body = None, {}, f"<network error: {e!r}>".encode()
    elapsed = round(time.monotonic() - started, 3)
    truncated = len(body) > MAX_BODY
    body = body[:MAX_BODY]
    location = next((v for k, v in resp_headers.items() if k.lower() == "location"), None)
    for k in [k for k in resp_headers if k.lower() == "location"]:
        resp_headers[k] = _strip_presigned(resp_headers[k])
    safe_query = {k: ("<redacted>" if k == "apikey" else v) for k, v in query.items()}
    return {
        "request": {
            "method": method,
            "host": host,
            "path": path,
            "query": safe_query,
            "key": key,
            "authScheme": scheme if key else None,
            "headers": {
                k: ("<redacted>" if k.lower() in SENSITIVE_HEADERS else v) for k, v in headers.items()
            },
        },
        "status": status,
        "elapsedSeconds": elapsed,
        "headers": resp_headers,
        "bodyLength": len(body),
        "bodyTruncated": truncated,
        "body": _decode(body, _ct(resp_headers)),
        # raw redirect target kept in memory only (never saved): see follow_redirect()
        "_location": location,
    }


def _ct(headers: dict[str, str]) -> str:
    return next((v for k, v in headers.items() if k.lower() == "content-type"), "")


def follow_redirect(r: dict[str, Any], accept: str = "*/*") -> dict[str, Any] | None:
    """GET the 3xx target WITHOUT credentials (an SDK must not forward the key cross-host)."""
    location = r.pop("_location", None)
    if not location:
        return None
    parts = urllib.parse.urlsplit(location)
    req = urllib.request.Request(location, method="GET", headers={"Accept": accept, "User-Agent": USER_AGENT})
    try:
        resp = _OPENER.open(req, timeout=60)
        status, hdrs, body = resp.status, dict(resp.headers.items()), resp.read(MAX_BODY + 1)
    except urllib.error.HTTPError as e:
        status, hdrs, body = e.code, dict(e.headers.items()), e.read(MAX_BODY + 1)
    for k in [k for k in hdrs if k.lower() == "location"]:
        hdrs[k] = _strip_presigned(hdrs[k])
    return {
        "request": {"method": "GET", "host": parts.netloc, "path": parts.path, "key": None,
                    "authScheme": None, "note": "redirect target fetched without credentials"},
        "status": status,
        "headers": hdrs,
        "bodyLength": min(len(body), MAX_BODY),
        "bodyTruncated": len(body) > MAX_BODY,
        "body": _decode(body[:MAX_BODY], _ct(hdrs)),
    }


def _decode(body: bytes, content_type: str) -> Any:
    ct = content_type.lower()
    if "json" in ct:
        try:
            return json.loads(body.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
    if ct.startswith("text/") or "xml" in ct or "json" in ct or not ct:
        try:
            text = body.decode("utf-8-sig")
            return {"_text_head": text[:2000], "_startsWith": text[:40]}
        except UnicodeDecodeError:
            pass
    return {"_binary_head_hex": body[:16].hex(), "_length": len(body)}


def save(name: str, results: Any) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}.json"
    _drop_private(results)
    text = json.dumps(results, ensure_ascii=False, indent=2, default=str)
    for secret in (*KEYS.values(),):
        if secret:
            assert secret not in text, "secret leaked into probe output"
    path.write_text(text, encoding="utf-8")
    return path


def _drop_private(node: Any) -> None:
    if isinstance(node, dict):
        node.pop("_location", None)
        for v in node.values():
            _drop_private(v)
    elif isinstance(node, list):
        for v in node:
            _drop_private(v)


def brief(r: dict[str, Any]) -> str:
    req = r["request"]
    body = r["body"]
    shape: Any
    if isinstance(body, dict):
        shape = sorted(body.keys())[:12]
    elif isinstance(body, list):
        shape = f"list[{len(body)}]"
    else:
        shape = type(body).__name__
    return (
        f"{r['status']!s:>4} {req['method']} {req['host']}{req['path']} "
        f"key={req['key']} auth={req['authScheme']} ct={_ct(r['headers']) or None} shape={shape}"
    )
