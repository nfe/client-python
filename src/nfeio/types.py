"""Public constants and request-body types.

Request bodies use the **wire keys** (camelCase), exactly as in the NFE.io API documentation
(decision D2): copy an example from the docs and it works. Every ``TypedDict`` here is
``total=False`` because required fields vary by city/regime; the API validates them. Keys not
listed are still sent as-is at runtime (only the type checker will complain).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any, Final, TypedDict

__all__ = [
    "AddressParams",
    "BorrowerParams",
    "CityParams",
    "CompanyAddressParams",
    "CompanyParams",
    "FlowStatus",
    "Number",
    "ServiceInvoiceCreateParams",
    "WebhookParams",
]

#: Monetary values and rates accepted in request bodies (``Decimal`` is sent without loss).
Number = int | float | Decimal


class FlowStatus:
    """Known ``flowStatus`` values of a service invoice. The set is open: compare strings.

    Unknown values returned by the API are treated as *not terminal* by ``wait``.
    """

    ISSUED: Final = "Issued"
    CANCELLED: Final = "Cancelled"
    ISSUE_FAILED: Final = "IssueFailed"
    CANCEL_FAILED: Final = "CancelFailed"
    ERROR: Final = "Error"
    PULL_FROM_CITY_HALL: Final = "PullFromCityHall"
    WAITING_CALCULATE_TAXES: Final = "WaitingCalculateTaxes"
    WAITING_DEFINE_RPS_NUMBER: Final = "WaitingDefineRpsNumber"
    WAITING_SEND: Final = "WaitingSend"
    WAITING_SEND_CANCEL: Final = "WaitingSendCancel"
    WAITING_RETURN: Final = "WaitingReturn"
    WAITING_RETURN_CANCEL: Final = "WaitingReturnCancel"
    WAITING_DOWNLOAD: Final = "WaitingDownload"

    #: Terminal statuses meaning success.
    SUCCESS: Final = frozenset({ISSUED, CANCELLED})
    #: Terminal statuses meaning failure (``wait`` raises ``InvoiceProcessingError``).
    FAILURE: Final = frozenset({ISSUE_FAILED, CANCEL_FAILED, ERROR})
    TERMINAL: Final = SUCCESS | FAILURE


class CityParams(TypedDict, total=False):
    code: str
    name: str


class AddressParams(TypedDict, total=False):
    country: str
    postalCode: str
    street: str
    number: str
    additionalInformation: str
    district: str
    city: CityParams
    state: str


class BorrowerParams(TypedDict, total=False):
    """Tomador. ``federalTaxNumber`` accepts int or str (str keeps leading zeros)."""

    type: str
    name: str
    federalTaxNumber: int | str
    municipalTaxNumber: str
    stateTaxNumber: str
    taxRegime: str
    caepf: str
    phoneNumber: str
    email: str
    noTaxIdReason: str
    address: AddressParams


class ServiceInvoiceCreateParams(TypedDict, total=False):
    """Body of ``POST /v1/companies/{company_id}/serviceinvoices`` (NFS-e v1).

    Prefer the ``external_id=`` argument of ``create`` over the ``externalId`` key.
    """

    borrower: BorrowerParams
    externalId: str
    cityServiceCode: str
    federalServiceCode: str
    cnaeCode: str
    nbsCode: str
    description: str
    servicesAmount: Number
    rpsSerialNumber: str
    issuedOn: str
    rpsNumber: int
    taxationType: str
    issRate: Number
    issTaxAmount: Number
    deductionsAmount: Number
    discountUnconditionedAmount: Number
    discountConditionedAmount: Number
    irAmountWithheld: Number
    pisAmountWithheld: Number
    cofinsAmountWithheld: Number
    csllAmountWithheld: Number
    inssAmountWithheld: Number
    issAmountWithheld: Number
    othersAmountWithheld: Number
    approximateTax: Mapping[str, Any]
    additionalInformation: str
    location: Mapping[str, Any]
    activityEvent: Mapping[str, Any]
    ncmCode: str
    paidAmount: Number
    accrualOn: str
    cstPisCofins: str
    pisCofinsBaseTax: Number
    pisRate: Number
    pisAmount: Number
    cofinsRate: Number
    cofinsAmount: Number
    csllAmount: Number
    csllRate: Number
    inssRate: Number
    ipiRate: Number
    ipiAmount: Number
    immunityType: str
    retentionType: str
    isEarlyInstallmentPayment: bool
    intermediary: BorrowerParams
    recipient: BorrowerParams
    referenceSubstitution: Mapping[str, Any]
    lease: Mapping[str, Any]
    construction: Mapping[str, Any]
    realEstate: Mapping[str, Any]
    foreignTrade: Mapping[str, Any]
    deduction: Mapping[str, Any]
    benefit: Mapping[str, Any]
    suspension: Mapping[str, Any]
    serviceAmountDetails: Mapping[str, Any]
    additionalInformationGroup: Mapping[str, Any]
    approximateTotals: Mapping[str, Any]
    ibsCbs: Mapping[str, Any]


class CompanyAddressParams(TypedDict, total=False):
    state: str
    city: CityParams
    district: str
    additionalInformation: str
    street: str
    number: str
    postalCode: str
    country: str


class CompanyParams(TypedDict, total=False):
    """Body of ``POST``/``PUT /v2/companies`` (sent wrapped in ``{"company": ...}``).

    ``taxRegime``: ``SimplesNacional``, ``LucroPresumido``, ``LucroReal``,
    ``SimplesNacionalExcessoSublimite``, ``MicroempreendedorIndividual``, ``Isento``, ``None``.
    """

    name: str
    accountId: str
    tradeName: str
    federalTaxNumber: int | str
    municipalTaxNumber: str
    taxRegime: str
    address: CompanyAddressParams
    id: str


class WebhookParams(TypedDict, total=False):
    """Body of ``POST``/``PUT /v2/webhooks`` (sent wrapped in ``{"webHook": ...}``).

    ``update`` is a full replacement: omitting ``status`` deactivates the webhook.
    """

    uri: str
    secret: str
    contentType: str
    insecureSsl: bool
    status: str
    filters: Sequence[str]
