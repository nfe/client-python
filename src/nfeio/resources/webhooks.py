"""Account webhooks, ``https://api.nfse.io/v2/webhooks``.

Signature verification of deliveries lives in :mod:`nfeio.webhooks` (no client needed).
There is deliberately no "delete all webhooks" operation.
"""

from __future__ import annotations

import builtins
from collections.abc import Mapping
from typing import Any

from .._config import ApiFamily, ClientConfig, RequestOptions
from .._core import paths
from .._core.ops import Op
from .._core.requestor import decode_json, expect_list, expect_object, request, response_info
from ..errors import InvalidParameterError
from ..models import Webhook, WebhookEventType
from ..types import WebhookParams
from ._base import AsyncService, SyncService

FAMILY = ApiFamily.ACCOUNT
BASE = "/v2/webhooks"


def _hook_path(webhook_id: str) -> str:
    return f"{BASE}/{paths.opaque_id(webhook_id, 'webhook_id')}"


def _body(params: WebhookParams | Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(params, Mapping):
        raise InvalidParameterError("params must be a mapping (the webhook)", param="params")
    return {"webHook": dict(params)}


def list_op(cfg: ClientConfig, options: RequestOptions | None) -> Op[list[Webhook]]:
    response = yield from request(cfg, "GET", FAMILY, BASE, options=options)
    _, items = expect_list(response, "webHooks")
    info = response_info(response)
    return [Webhook._from_wire(item, info) for item in items if isinstance(item, dict)]


def retrieve_op(cfg: ClientConfig, webhook_id: str, options: RequestOptions | None) -> Op[Webhook]:
    response = yield from request(cfg, "GET", FAMILY, _hook_path(webhook_id), options=options)
    return Webhook._from_wire(expect_object(response, unwrap="webHook"), response_info(response))


def create_op(
    cfg: ClientConfig, params: WebhookParams | Mapping[str, Any], options: RequestOptions | None
) -> Op[Webhook]:
    body = _body(params)
    secret = params.get("secret")
    response = yield from request(
        cfg,
        "POST",
        FAMILY,
        BASE,
        json=body,
        options=options,
        secrets=(secret,) if isinstance(secret, str) else (),
    )
    return Webhook._from_wire(expect_object(response, unwrap="webHook"), response_info(response))


def update_op(
    cfg: ClientConfig,
    webhook_id: str,
    params: WebhookParams | Mapping[str, Any],
    options: RequestOptions | None,
) -> Op[Webhook]:
    path = _hook_path(webhook_id)
    body = _body(params)
    secret = params.get("secret")
    response = yield from request(
        cfg,
        "PUT",
        FAMILY,
        path,
        json=body,
        options=options,
        secrets=(secret,) if isinstance(secret, str) else (),
    )
    return Webhook._from_wire(expect_object(response, unwrap="webHook"), response_info(response))


def delete_op(cfg: ClientConfig, webhook_id: str, options: RequestOptions | None) -> Op[None]:
    response = yield from request(cfg, "DELETE", FAMILY, _hook_path(webhook_id), options=options)
    decode_json(response, allow_empty=True)
    return None


def ping_op(cfg: ClientConfig, webhook_id: str, options: RequestOptions | None) -> Op[None]:
    path = f"{_hook_path(webhook_id)}/pings"
    yield from request(cfg, "PUT", FAMILY, path, options=options)
    return None


def event_types_op(cfg: ClientConfig, options: RequestOptions | None) -> Op[list[WebhookEventType]]:
    response = yield from request(cfg, "GET", FAMILY, f"{BASE}/eventtypes", options=options)
    _, items = expect_list(response, "eventTypes")
    info = response_info(response)
    return [WebhookEventType._from_wire(item, info) for item in items if isinstance(item, dict)]


class WebhooksService(SyncService):
    """``client.webhooks`` — account webhooks (synchronous)."""

    __slots__ = ()

    def list(self, *, options: RequestOptions | None = None) -> builtins.list[Webhook]:
        return self._run(list_op(self._cfg, options))

    def retrieve(self, webhook_id: str, *, options: RequestOptions | None = None) -> Webhook:
        return self._run(retrieve_op(self._cfg, webhook_id, options))

    def create(
        self, params: WebhookParams | Mapping[str, Any], *, options: RequestOptions | None = None
    ) -> Webhook:
        """Create a webhook (body sent as ``{"webHook": params}``)."""
        return self._run(create_op(self._cfg, params, options))

    def update(
        self,
        webhook_id: str,
        params: WebhookParams | Mapping[str, Any],
        *,
        options: RequestOptions | None = None,
    ) -> Webhook:
        """**Full replacement**, no merge: omitting ``status`` deactivates the webhook.
        Retrieve, change and send the whole object."""
        return self._run(update_op(self._cfg, webhook_id, params, options))

    def delete(self, webhook_id: str, *, options: RequestOptions | None = None) -> None:
        self._run(delete_op(self._cfg, webhook_id, options))

    def ping(self, webhook_id: str, *, options: RequestOptions | None = None) -> None:
        """Ask the API to send a signed ``ping`` delivery to the webhook URI."""
        self._run(ping_op(self._cfg, webhook_id, options))

    def event_types(
        self, *, options: RequestOptions | None = None
    ) -> builtins.list[WebhookEventType]:
        return self._run(event_types_op(self._cfg, options))


class AsyncWebhooksService(AsyncService):
    """``client.webhooks`` — account webhooks (asynchronous)."""

    __slots__ = ()

    async def list(self, *, options: RequestOptions | None = None) -> builtins.list[Webhook]:
        return await self._run(list_op(self._cfg, options))

    async def retrieve(self, webhook_id: str, *, options: RequestOptions | None = None) -> Webhook:
        return await self._run(retrieve_op(self._cfg, webhook_id, options))

    async def create(
        self, params: WebhookParams | Mapping[str, Any], *, options: RequestOptions | None = None
    ) -> Webhook:
        return await self._run(create_op(self._cfg, params, options))

    async def update(
        self,
        webhook_id: str,
        params: WebhookParams | Mapping[str, Any],
        *,
        options: RequestOptions | None = None,
    ) -> Webhook:
        return await self._run(update_op(self._cfg, webhook_id, params, options))

    async def delete(self, webhook_id: str, *, options: RequestOptions | None = None) -> None:
        await self._run(delete_op(self._cfg, webhook_id, options))

    async def ping(self, webhook_id: str, *, options: RequestOptions | None = None) -> None:
        await self._run(ping_op(self._cfg, webhook_id, options))

    async def event_types(
        self, *, options: RequestOptions | None = None
    ) -> builtins.list[WebhookEventType]:
        return await self._run(event_types_op(self._cfg, options))
