"""Companies (contribuintes), API v2 on ``https://api.nfse.io/v2/companies`` (cursor pages)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .._config import ApiFamily, ClientConfig, RequestOptions
from .._core import paths
from .._core.ops import Op
from .._core.requestor import decode_json, expect_list, expect_object, request, response_info
from ..errors import InvalidParameterError
from ..models import Company
from ..pagination import MAX_PAGE_SIZE, AsyncCursorPage, CursorPage, CursorState
from ..types import CompanyParams
from ._base import AsyncService, SyncService

FAMILY = ApiFamily.ACCOUNT
BASE = "/v2/companies"


def _company_path(company_id: str) -> str:
    return f"{BASE}/{paths.opaque_id(company_id, 'company_id')}"


def _check_limit(limit: int) -> int:
    # limit=0 returns an empty list with hasMore=true (endless loop): reject locally.
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_PAGE_SIZE:
        raise InvalidParameterError(f"limit must be between 1 and {MAX_PAGE_SIZE}", param="limit")
    return limit


def _body(params: CompanyParams | Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(params, Mapping):
        raise InvalidParameterError("params must be a mapping (the company)", param="params")
    return {"company": dict(params)}


def list_op(
    cfg: ClientConfig,
    starting_after: str | None,
    ending_before: str | None,
    limit: int,
    options: RequestOptions | None,
) -> Op[CursorState[Company]]:
    _check_limit(limit)
    if starting_after is not None and ending_before is not None:
        raise InvalidParameterError(
            "pass starting_after or ending_before, not both", param="starting_after"
        )
    query: dict[str, str | int | None] = {"limit": limit}
    if starting_after is not None:
        query["startingAfter"] = paths.opaque_id(starting_after, "starting_after")
    if ending_before is not None:
        query["endingBefore"] = paths.opaque_id(ending_before, "ending_before")
    response = yield from request(cfg, "GET", FAMILY, BASE, query=query, options=options)
    envelope, items = expect_list(response, "companies")
    info = response_info(response)
    companies = [Company._from_wire(item, info) for item in items if isinstance(item, dict)]

    def fetch(after: str | None, before: str | None, size: int) -> Op[CursorState[Company]]:
        return list_op(cfg, after, before, size, options)

    return CursorState(
        companies,
        info,
        bool(envelope.get("hasMore")),
        limit,
        ending_before is not None,
        fetch,
        ending_before if ending_before is not None else starting_after,
    )


def retrieve_op(cfg: ClientConfig, company_id: str, options: RequestOptions | None) -> Op[Company]:
    response = yield from request(cfg, "GET", FAMILY, _company_path(company_id), options=options)
    return Company._from_wire(expect_object(response, unwrap="company"), response_info(response))


def create_op(
    cfg: ClientConfig, params: CompanyParams | Mapping[str, Any], options: RequestOptions | None
) -> Op[Company]:
    body = _body(params)
    response = yield from request(cfg, "POST", FAMILY, BASE, json=body, options=options)
    return Company._from_wire(expect_object(response, unwrap="company"), response_info(response))


def update_op(
    cfg: ClientConfig,
    company_id: str,
    params: CompanyParams | Mapping[str, Any],
    options: RequestOptions | None,
) -> Op[Company]:
    path = _company_path(company_id)
    body = _body(params)
    response = yield from request(cfg, "PUT", FAMILY, path, json=body, options=options)
    return Company._from_wire(expect_object(response, unwrap="company"), response_info(response))


def delete_op(cfg: ClientConfig, company_id: str, options: RequestOptions | None) -> Op[None]:
    response = yield from request(cfg, "DELETE", FAMILY, _company_path(company_id), options=options)
    decode_json(response, allow_empty=True)
    return None


class CompaniesService(SyncService):
    """``client.companies`` — Companies API v2 (synchronous)."""

    __slots__ = ()

    def list(
        self,
        *,
        limit: int = 10,
        starting_after: str | None = None,
        ending_before: str | None = None,
        options: RequestOptions | None = None,
    ) -> CursorPage[Company]:
        """List companies by cursor (``limit`` 1-50). ``auto_paging_iter()`` walks them all."""
        state = self._run(list_op(self._cfg, starting_after, ending_before, limit, options))
        return CursorPage(state, self._runner)

    def retrieve(self, company_id: str, *, options: RequestOptions | None = None) -> Company:
        return self._run(retrieve_op(self._cfg, company_id, options))

    def create(
        self, params: CompanyParams | Mapping[str, Any], *, options: RequestOptions | None = None
    ) -> Company:
        """Create a company (body sent as ``{"company": params}``)."""
        return self._run(create_op(self._cfg, params, options))

    def update(
        self,
        company_id: str,
        params: CompanyParams | Mapping[str, Any],
        *,
        options: RequestOptions | None = None,
    ) -> Company:
        """Replace a company (full update: send every field you want to keep)."""
        return self._run(update_op(self._cfg, company_id, params, options))

    def delete(self, company_id: str, *, options: RequestOptions | None = None) -> None:
        """Delete a company. The API does a **soft delete**: it answers 204 and the company
        stays retrievable (and listed) with ``status == "Inactive"``."""
        self._run(delete_op(self._cfg, company_id, options))


class AsyncCompaniesService(AsyncService):
    """``client.companies`` — Companies API v2 (asynchronous)."""

    __slots__ = ()

    async def list(
        self,
        *,
        limit: int = 10,
        starting_after: str | None = None,
        ending_before: str | None = None,
        options: RequestOptions | None = None,
    ) -> AsyncCursorPage[Company]:
        state = await self._run(list_op(self._cfg, starting_after, ending_before, limit, options))
        return AsyncCursorPage(state, self._runner)

    async def retrieve(self, company_id: str, *, options: RequestOptions | None = None) -> Company:
        return await self._run(retrieve_op(self._cfg, company_id, options))

    async def create(
        self, params: CompanyParams | Mapping[str, Any], *, options: RequestOptions | None = None
    ) -> Company:
        return await self._run(create_op(self._cfg, params, options))

    async def update(
        self,
        company_id: str,
        params: CompanyParams | Mapping[str, Any],
        *,
        options: RequestOptions | None = None,
    ) -> Company:
        return await self._run(update_op(self._cfg, company_id, params, options))

    async def delete(self, company_id: str, *, options: RequestOptions | None = None) -> None:
        await self._run(delete_op(self._cfg, company_id, options))
