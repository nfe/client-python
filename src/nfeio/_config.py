"""Client configuration, per-call options, timeouts, API families and secret masking."""

from __future__ import annotations

import enum
import math
import os
import platform
import re
import ssl
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Final
from urllib.parse import urlsplit

from ._version import __version__
from .errors import ConfigurationError

__all__ = [
    "DEFAULT_BASE_URLS",
    "ApiFamily",
    "ClientConfig",
    "RequestOptions",
    "SecretStr",
    "Timeout",
]


class ApiFamily(str, enum.Enum):
    """Group of endpoints that share a host and an API key.

    The value is the key accepted in ``NfeClient(base_urls={...})``.
    """

    #: NFS-e v1 — ``https://api.nfe.io`` — ``api_key``.
    SERVICE_INVOICES = "service_invoices"
    #: Companies v2, certificates, webhooks — ``https://api.nfse.io`` — ``api_key``.
    ACCOUNT = "account"
    #: CNPJ lookups — ``https://legalentity.api.nfe.io`` — ``data_api_key``.
    LEGAL_ENTITY = "legal_entity"
    #: CPF lookups — ``https://naturalperson.api.nfe.io`` — ``data_api_key``.
    NATURAL_PERSON = "natural_person"
    #: CEP lookups — ``https://address.api.nfe.io`` — ``data_api_key``.
    ADDRESS = "address"

    @property
    def uses_data_key(self) -> bool:
        return self in (ApiFamily.LEGAL_ENTITY, ApiFamily.NATURAL_PERSON, ApiFamily.ADDRESS)

    @property
    def key_param(self) -> str:
        """Name of the client parameter that holds this family's key."""
        return "data_api_key" if self.uses_data_key else "api_key"


DEFAULT_BASE_URLS: Final[Mapping[ApiFamily, str]] = MappingProxyType(
    {
        ApiFamily.SERVICE_INVOICES: "https://api.nfe.io",
        ApiFamily.ACCOUNT: "https://api.nfse.io",
        ApiFamily.LEGAL_ENTITY: "https://legalentity.api.nfe.io",
        ApiFamily.NATURAL_PERSON: "https://naturalperson.api.nfe.io",
        ApiFamily.ADDRESS: "https://address.api.nfe.io",
    }
)

DEFAULT_MAX_RESPONSE_BYTES: Final = 10 * 1024 * 1024
_PROTECTED_HEADERS: Final = frozenset({"authorization", "user-agent", "content-type"})
_TOKEN_RE: Final = re.compile(r"[A-Za-z0-9._+\-]{1,64}")
_HEADER_NAME_RE: Final = re.compile(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]{1,64}")


def mask_secret(value: str) -> str:
    """Return ``'****'`` plus at most the last 4 characters (none for short values)."""
    if len(value) <= 8:
        return "****"
    return "****" + value[-4:]


class SecretStr:
    """A string that never shows itself in ``repr``/``str``/logs."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def get_secret_value(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return f"SecretStr({mask_secret(self._value)!r})"

    __str__ = __repr__

    def __eq__(self, other: object) -> bool:
        return isinstance(other, SecretStr) and other._value == self._value

    def __hash__(self) -> int:
        return hash(self._value)

    def __bool__(self) -> bool:
        return bool(self._value)

    def __reduce__(self) -> str | tuple[object, ...]:
        raise TypeError("SecretStr cannot be pickled")


def _check_seconds(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigurationError(f"{name} must be a number of seconds, got {type(value).__name__}")
    seconds = float(value)
    if not math.isfinite(seconds) or seconds <= 0:
        raise ConfigurationError(f"{name} must be a finite number of seconds greater than zero")
    return seconds


@dataclass(frozen=True)
class Timeout:
    """Network deadlines, in seconds, applied to each attempt.

    Attributes:
        connect: DNS + TCP + TLS handshake.
        read: each socket read (waiting for the response headers and each body chunk).
        total: whole attempt, from connecting to the last body byte.
    """

    connect: float = 10.0
    read: float = 60.0
    total: float = 120.0

    def __post_init__(self) -> None:
        for name in ("connect", "read", "total"):
            object.__setattr__(self, name, _check_seconds(f"timeout.{name}", getattr(self, name)))

    @classmethod
    def coerce(cls, value: float | Timeout | None) -> Timeout:
        """Accept a :class:`Timeout` or a number of seconds.

        A number ``t`` means "this attempt may take up to ``t`` seconds": ``read = total = t`` and
        ``connect = min(10, t)``. ``None``, zero, negative and infinite values are rejected.
        """
        if isinstance(value, Timeout):
            return value
        if value is None:
            raise ConfigurationError("timeout must be finite; None (no timeout) is not allowed")
        seconds = _check_seconds("timeout", value)
        return cls(connect=min(10.0, seconds), read=seconds, total=seconds)


def _check_retries(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > 10:
        raise ConfigurationError("max_retries must be an integer between 0 and 10")
    return value


def _check_header_value(name: str, value: object) -> str:
    if not isinstance(value, str) or any(ch in value for ch in "\r\n\x00"):
        raise ConfigurationError(f"invalid value for header {name!r}")
    return value


@dataclass(frozen=True, repr=False)
class RequestOptions:
    """Per-call overrides. Every field is optional; ``None`` keeps the client setting.

    Attributes:
        api_key: key used for this call instead of the one the resource would use.
        timeout: :class:`Timeout` or seconds (see :meth:`Timeout.coerce`).
        max_retries: retries for this call (0 disables). Never makes a POST retryable on
            ambiguous failures.
        idempotency_key: sent as ``Idempotency-Key``. The API ignores it today, so it does
            **not** change the retry policy.
        extra_headers: additional headers; cannot override ``Authorization``, ``User-Agent``
            or ``Content-Type``.
    """

    api_key: str | None = None
    timeout: float | Timeout | None = None
    max_retries: int | None = None
    idempotency_key: str | None = None
    extra_headers: Mapping[str, str] | None = field(default=None)

    def __post_init__(self) -> None:
        if self.api_key is not None and (not isinstance(self.api_key, str) or not self.api_key):
            raise ConfigurationError("api_key must be a non-empty string")
        if self.api_key is not None:
            _check_header_value("Authorization", self.api_key)
        if self.timeout is not None:
            object.__setattr__(self, "timeout", Timeout.coerce(self.timeout))
        if self.max_retries is not None:
            _check_retries(self.max_retries)
        if self.idempotency_key is not None:
            key = _check_header_value("Idempotency-Key", self.idempotency_key)
            if not key or len(key) > 255:
                raise ConfigurationError("idempotency_key must have 1 to 255 characters")
        if self.extra_headers is not None:
            frozen: dict[str, str] = {}
            for name, value in self.extra_headers.items():
                if not isinstance(name, str) or not _HEADER_NAME_RE.fullmatch(name):
                    raise ConfigurationError(f"invalid header name {name!r}")
                if name.lower() in _PROTECTED_HEADERS:
                    raise ConfigurationError(
                        f"extra_headers cannot override {name!r}; use the client options instead"
                    )
                frozen[name] = _check_header_value(name, value)
            object.__setattr__(self, "extra_headers", MappingProxyType(frozen))

    def __repr__(self) -> str:
        key = mask_secret(self.api_key) if self.api_key else None
        return (
            f"RequestOptions(api_key={key!r}, timeout={self.timeout!r}, "
            f"max_retries={self.max_retries!r}, idempotency_key={self.idempotency_key!r}, "
            f"extra_headers={dict(self.extra_headers) if self.extra_headers else None!r})"
        )


def _normalize_base_url(family: ApiFamily, url: object) -> str:
    if not isinstance(url, str):
        raise ConfigurationError(f"base URL for {family.value!r} must be a string")
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise ConfigurationError(f"base URL for {family.value!r} must use https: {url!r}")
    if not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise ConfigurationError(
            f"base URL for {family.value!r} must be https://host[:port][/prefix] without "
            "credentials, query or fragment"
        )
    return url.rstrip("/")


def build_user_agent(app_info: tuple[str, str] | None) -> str:
    system = platform.system().lower() or "unknown"
    ua = (
        f"nfe-io-python/{__version__} "
        f"python/{sys.version_info.major}.{sys.version_info.minor} {system}"
    )
    if app_info is not None:
        ua += f" {app_info[0]}/{app_info[1]}"
    return ua


def _check_app_info(app_info: object) -> tuple[str, str] | None:
    if app_info is None:
        return None
    if (
        not isinstance(app_info, tuple)
        or len(app_info) != 2
        or not all(isinstance(part, str) and _TOKEN_RE.fullmatch(part) for part in app_info)
    ):
        raise ConfigurationError(
            "app_info must be a (name, version) tuple of 1-64 characters from [A-Za-z0-9._+-]"
        )
    return (app_info[0], app_info[1])


def check_ssl_context(context: ssl.SSLContext) -> ssl.SSLContext:
    """Reject contexts that disable certificate or hostname verification."""
    if not isinstance(context, ssl.SSLContext):
        raise ConfigurationError("ssl_context must be an ssl.SSLContext")
    if context.verify_mode != ssl.CERT_REQUIRED or not context.check_hostname:
        raise ConfigurationError(
            "ssl_context must verify certificates and hostnames (CERT_REQUIRED and "
            "check_hostname=True); TLS verification cannot be disabled"
        )
    if context.minimum_version < ssl.TLSVersion.TLSv1_2:
        context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


def build_ssl_context(
    ssl_context: ssl.SSLContext | None = None, ca_bundle: str | os.PathLike[str] | None = None
) -> ssl.SSLContext:
    """Default verified context (TLS >= 1.2), optionally trusting an extra CA bundle."""
    if ssl_context is not None and ca_bundle is not None:
        raise ConfigurationError("pass either ssl_context or ca_bundle, not both")
    if ssl_context is not None:
        return check_ssl_context(ssl_context)
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    if ca_bundle is not None:
        try:
            context.load_verify_locations(cafile=os.fspath(ca_bundle))
        except (OSError, ssl.SSLError) as exc:
            raise ConfigurationError(f"could not load ca_bundle: {exc}") from None
    return check_ssl_context(context)


def _env_secret(explicit: str | None, env_name: str, param: str) -> SecretStr | None:
    value = explicit if explicit is not None else os.environ.get(env_name)
    if value is None or value == "":
        if explicit == "":
            raise ConfigurationError(f"{param} must not be empty")
        return None
    if not isinstance(value, str):
        raise ConfigurationError(f"{param} must be a string")
    _check_header_value("Authorization", value)
    return SecretStr(value.strip())


@dataclass(frozen=True, repr=False)
class ClientConfig:
    """Immutable, validated configuration shared by every call of a client."""

    api_key: SecretStr | None
    data_api_key: SecretStr | None
    base_urls: Mapping[ApiFamily, str]
    timeout: Timeout
    max_retries: int
    retry_base_delay: float
    retry_max_delay: float
    max_retry_after: float
    max_response_bytes: int
    user_agent: str
    #: Uniform random source in [0, 1) used for jitter (injectable for tests).
    random: Callable[[], float]

    @classmethod
    def build(
        cls,
        *,
        api_key: str | None = None,
        data_api_key: str | None = None,
        base_urls: Mapping[ApiFamily | str, str] | None = None,
        timeout: float | Timeout = Timeout(),  # noqa: B008 - frozen, immutable default
        max_retries: int = 3,
        retry_base_delay: float = 1.0,
        retry_max_delay: float = 30.0,
        max_retry_after: float = 60.0,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        app_info: tuple[str, str] | None = None,
        random: Callable[[], float] | None = None,
    ) -> ClientConfig:
        urls = dict(DEFAULT_BASE_URLS)
        for raw_family, url in (base_urls or {}).items():
            try:
                family = ApiFamily(raw_family)
            except ValueError:
                valid = ", ".join(f.value for f in ApiFamily)
                raise ConfigurationError(
                    f"unknown API family {raw_family!r} in base_urls (valid: {valid})"
                ) from None
            urls[family] = _normalize_base_url(family, url)
        if (
            isinstance(max_response_bytes, bool)
            or not isinstance(max_response_bytes, int)
            or max_response_bytes < 1024
        ):
            raise ConfigurationError("max_response_bytes must be an integer >= 1024")
        if random is None:
            import random as _random

            random = _random.SystemRandom().random
        return cls(
            api_key=_env_secret(api_key, "NFE_API_KEY", "api_key"),
            data_api_key=_env_secret(data_api_key, "NFE_DATA_API_KEY", "data_api_key"),
            base_urls=MappingProxyType(urls),
            timeout=Timeout.coerce(timeout),
            max_retries=_check_retries(max_retries),
            retry_base_delay=_check_seconds("retry_base_delay", retry_base_delay),
            retry_max_delay=_check_seconds("retry_max_delay", retry_max_delay),
            max_retry_after=_check_seconds("max_retry_after", max_retry_after),
            max_response_bytes=max_response_bytes,
            user_agent=build_user_agent(_check_app_info(app_info)),
            random=random,
        )

    def key_for(self, family: ApiFamily, options: RequestOptions | None) -> str:
        if options is not None and options.api_key is not None:
            return options.api_key
        secret = self.data_api_key if family.uses_data_key else self.api_key
        if secret is None:
            env = "NFE_DATA_API_KEY" if family.uses_data_key else "NFE_API_KEY"
            raise ConfigurationError(
                f"{family.key_param} is required for this operation: pass "
                f"NfeClient({family.key_param}=...) or set {env}"
            )
        return secret.get_secret_value()

    def __repr__(self) -> str:
        return (
            f"ClientConfig(api_key={self.api_key!r}, data_api_key={self.data_api_key!r}, "
            f"timeout={self.timeout!r}, max_retries={self.max_retries})"
        )
