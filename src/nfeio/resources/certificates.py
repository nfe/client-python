"""Digital certificates (A1) of a company: upload (multipart) and status."""

from __future__ import annotations

import builtins
import io
import os
from pathlib import Path
from typing import BinaryIO, Union

from .._config import ApiFamily, ClientConfig, RequestOptions
from .._core import multipart, paths
from .._core.ops import Op
from .._core.requestor import expect_list, expect_object, request, response_info
from ..errors import InvalidParameterError
from ..models import Certificate
from ._base import AsyncService, SyncService

FAMILY = ApiFamily.ACCOUNT
MAX_CERTIFICATE_BYTES = 1024 * 1024

#: A PFX/P12 as bytes, a filesystem path, or a binary file object.
CertificateFile = Union[bytes, bytearray, memoryview, str, "os.PathLike[str]", BinaryIO]


def _certificates_path(company_id: str) -> str:
    return f"/v2/companies/{paths.opaque_id(company_id, 'company_id')}/certificates"


def _read_file(file: CertificateFile, filename: str | None) -> tuple[bytes, str]:
    if isinstance(file, (bytes, bytearray, memoryview)):
        content = bytes(file)
        name = filename or "certificate.pfx"
    elif isinstance(file, (str, os.PathLike)):
        path = Path(file)
        try:
            size = path.stat().st_size
        except OSError as exc:
            raise InvalidParameterError(
                f"cannot read certificate file: {exc.strerror}", param="file"
            ) from None
        if size > MAX_CERTIFICATE_BYTES:
            raise InvalidParameterError("certificate file is larger than 1 MiB", param="file")
        content = path.read_bytes()
        name = filename or path.name
    elif isinstance(file, io.IOBase) or hasattr(file, "read"):
        data = file.read(MAX_CERTIFICATE_BYTES + 1)
        if not isinstance(data, (bytes, bytearray)):
            raise InvalidParameterError("certificate file object must be opened in binary mode")
        content = bytes(data)
        raw_name = getattr(file, "name", None)
        name = filename or (Path(raw_name).name if isinstance(raw_name, str) else "certificate.pfx")
    else:
        raise InvalidParameterError(
            "file must be bytes, a path or a binary file object", param="file"
        )
    if not content:
        raise InvalidParameterError("certificate file is empty", param="file")
    if len(content) > MAX_CERTIFICATE_BYTES:
        raise InvalidParameterError("certificate file is larger than 1 MiB", param="file")
    return content, name


def upload_op(
    cfg: ClientConfig,
    company_id: str,
    file: CertificateFile,
    password: str,
    filename: str | None,
    options: RequestOptions | None,
) -> Op[Certificate]:
    path = _certificates_path(company_id)
    if not isinstance(password, str) or not password:
        raise InvalidParameterError("password must be a non-empty string", param="password")
    content, name = _read_file(file, filename)
    body, content_type = multipart.encode(
        [("password", password)],
        [multipart.FilePart("file", name, content, "application/x-pkcs12")],
    )
    response = yield from request(
        cfg,
        "POST",
        FAMILY,
        path,
        body=body,
        content_type=content_type,
        options=options,
        secrets=(password,),
    )
    data = expect_object(response, unwrap="certificate")
    return Certificate._from_wire(data, response_info(response))


def list_op(
    cfg: ClientConfig, company_id: str, options: RequestOptions | None
) -> Op[list[Certificate]]:
    response = yield from request(
        cfg, "GET", FAMILY, _certificates_path(company_id), options=options
    )
    _, items = expect_list(response, "certificates")
    info = response_info(response)
    return [Certificate._from_wire(item, info) for item in items if isinstance(item, dict)]


class CertificatesService(SyncService):
    """``client.certificates`` — company digital certificates (synchronous)."""

    __slots__ = ()

    def upload(
        self,
        company_id: str,
        file: CertificateFile,
        password: str,
        *,
        filename: str | None = None,
        options: RequestOptions | None = None,
    ) -> Certificate:
        """Upload an A1 certificate (PFX/P12, at most 1 MiB) as multipart field ``file``.

        The password is never logged nor included in error messages. Not retried on 5xx.
        """
        return self._run(upload_op(self._cfg, company_id, file, password, filename, options))

    def list(
        self, company_id: str, *, options: RequestOptions | None = None
    ) -> builtins.list[Certificate]:
        """Certificates of the company (empty list when there is none)."""
        return self._run(list_op(self._cfg, company_id, options))


class AsyncCertificatesService(AsyncService):
    """``client.certificates`` — company digital certificates (asynchronous)."""

    __slots__ = ()

    async def upload(
        self,
        company_id: str,
        file: CertificateFile,
        password: str,
        *,
        filename: str | None = None,
        options: RequestOptions | None = None,
    ) -> Certificate:
        return await self._run(upload_op(self._cfg, company_id, file, password, filename, options))

    async def list(
        self, company_id: str, *, options: RequestOptions | None = None
    ) -> builtins.list[Certificate]:
        return await self._run(list_op(self._cfg, company_id, options))
