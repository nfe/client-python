"""Data lookups (CNPJ v3, CPF, CEP). They use ``data_api_key`` and their own hosts.

Documents are validated locally (check digits) before any request: lookups may be billed.
"""

from __future__ import annotations

from datetime import date

from .._config import ApiFamily, ClientConfig, RequestOptions
from .._core import paths
from .._core.ops import Op
from .._core.requestor import expect_object, request, response_info
from ..models import Address, LegalEntity, NaturalPerson
from ._base import AsyncService, SyncService


def cnpj_op(
    cfg: ClientConfig,
    cnpj: str,
    update_address: bool | None,
    update_city_code: bool | None,
    options: RequestOptions | None,
) -> Op[LegalEntity]:
    path = f"/v3/legalentities/basicInfo/{paths.cnpj(cnpj)}"
    query = {"updateAddress": update_address, "updateCityCode": update_city_code}
    response = yield from request(
        cfg, "GET", ApiFamily.LEGAL_ENTITY, path, query=query, options=options
    )
    data = expect_object(response, unwrap="legalEntity")
    return LegalEntity._from_wire(data, response_info(response))


def cnpj_state_taxes_op(
    cfg: ClientConfig, cnpj: str, state: str, options: RequestOptions | None
) -> Op[LegalEntity]:
    path = f"/v3/legalentities/stateTaxInfo/{paths.uf(state)}/{paths.cnpj(cnpj)}"
    response = yield from request(cfg, "GET", ApiFamily.LEGAL_ENTITY, path, options=options)
    data = expect_object(response, unwrap="legalEntity")
    return LegalEntity._from_wire(data, response_info(response))


def cpf_op(
    cfg: ClientConfig, cpf: str, birth_date: date | str, options: RequestOptions | None
) -> Op[NaturalPerson]:
    path = f"/v1/naturalperson/status/{paths.cpf(cpf)}/{paths.iso_date(birth_date, 'birth_date')}"
    response = yield from request(cfg, "GET", ApiFamily.NATURAL_PERSON, path, options=options)
    data = expect_object(response, unwrap="naturalPerson")
    return NaturalPerson._from_wire(data, response_info(response))


def cep_op(cfg: ClientConfig, cep: str, options: RequestOptions | None) -> Op[Address]:
    path = f"/v2/addresses/{paths.cep(cep)}"
    response = yield from request(cfg, "GET", ApiFamily.ADDRESS, path, options=options)
    data = expect_object(response, unwrap="address")
    return Address._from_wire(data, response_info(response))


class LookupsService(SyncService):
    """``client.lookups`` — CNPJ, CPF and CEP lookups (synchronous, ``data_api_key``)."""

    __slots__ = ()

    def cnpj(
        self,
        cnpj: str,
        *,
        update_address: bool | None = None,
        update_city_code: bool | None = None,
        options: RequestOptions | None = None,
    ) -> LegalEntity:
        """Company registration data by CNPJ (numeric or alphanumeric, masked or not)."""
        return self._run(cnpj_op(self._cfg, cnpj, update_address, update_city_code, options))

    def cnpj_state_taxes(
        self, cnpj: str, state: str, *, options: RequestOptions | None = None
    ) -> LegalEntity:
        """State enrollments (inscrições estaduais) of a CNPJ in a UF (``stateTaxes``)."""
        return self._run(cnpj_state_taxes_op(self._cfg, cnpj, state, options))

    def cpf(
        self, cpf: str, birth_date: date | str, *, options: RequestOptions | None = None
    ) -> NaturalPerson:
        """CPF status. A CPF/birth date mismatch is reported by the API as ``NotFoundError``."""
        return self._run(cpf_op(self._cfg, cpf, birth_date, options))

    def cep(self, cep: str, *, options: RequestOptions | None = None) -> Address:
        """Address by CEP (8 digits, hyphen optional)."""
        return self._run(cep_op(self._cfg, cep, options))


class AsyncLookupsService(AsyncService):
    """``client.lookups`` — CNPJ, CPF and CEP lookups (asynchronous, ``data_api_key``)."""

    __slots__ = ()

    async def cnpj(
        self,
        cnpj: str,
        *,
        update_address: bool | None = None,
        update_city_code: bool | None = None,
        options: RequestOptions | None = None,
    ) -> LegalEntity:
        return await self._run(cnpj_op(self._cfg, cnpj, update_address, update_city_code, options))

    async def cnpj_state_taxes(
        self, cnpj: str, state: str, *, options: RequestOptions | None = None
    ) -> LegalEntity:
        return await self._run(cnpj_state_taxes_op(self._cfg, cnpj, state, options))

    async def cpf(
        self, cpf: str, birth_date: date | str, *, options: RequestOptions | None = None
    ) -> NaturalPerson:
        return await self._run(cpf_op(self._cfg, cpf, birth_date, options))

    async def cep(self, cep: str, *, options: RequestOptions | None = None) -> Address:
        return await self._run(cep_op(self._cfg, cep, options))
