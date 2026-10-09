"""Response models: immutable typed views over the API JSON (see :class:`NfeObject`).

Only fields that the SDK corrects or types have properties (ids, statuses, dates, money,
documents). Everything else is available by wire name: ``invoice["description"]``.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ._base import (
    DateTimeField,
    DecimalField,
    DocumentField,
    NfeObject,
    ObjectField,
    ResponseInfo,
    StrField,
    StrListField,
)

__all__ = [
    "Address",
    "Certificate",
    "Company",
    "LegalEntity",
    "NaturalPerson",
    "NfeObject",
    "Party",
    "ResponseInfo",
    "ServiceInvoice",
    "Webhook",
    "WebhookEventType",
]


class Party(NfeObject):
    """Borrower (tomador) or provider (prestador) nested in a service invoice."""

    __slots__ = ()

    id = StrField("id")
    #: CNPJ (14) or CPF (11) as a normalised string; the API may send it as an integer that
    #: lost its leading zeros. The sibling ``type`` field decides which one it is.
    federal_tax_number = DocumentField("federalTaxNumber", "auto", type_key="type")


class ServiceInvoice(NfeObject):
    """NFS-e (``/v1/companies/{company_id}/serviceinvoices``)."""

    __slots__ = ()

    id = StrField("id")
    external_id = StrField("externalId")
    environment = StrField("environment")
    #: Processing status (open set, see :class:`nfeio.types.FlowStatus`).
    flow_status = StrField("flowStatus")
    flow_message = StrField("flowMessage")
    status = StrField("status")
    services_amount = DecimalField("servicesAmount")
    base_tax_amount = DecimalField("baseTaxAmount")
    deductions_amount = DecimalField("deductionsAmount")
    iss_rate = DecimalField("issRate")
    iss_tax_amount = DecimalField("issTaxAmount")
    amount_net = DecimalField("amountNet")
    issued_on = DateTimeField("issuedOn")
    cancelled_on = DateTimeField("cancelledOn")
    created_on = DateTimeField("createdOn")
    modified_on = DateTimeField("modifiedOn")
    borrower = ObjectField("borrower", Party)
    provider = ObjectField("provider", Party)


class Company(NfeObject):
    """Company (contribuinte) from the Companies API v2 (``api.nfse.io/v2/companies``).

    Note: in v2 the wire field ``municipalTaxNumber`` holds the *id* of the municipal
    enrollment, not the enrollment number, so it has no typed property.
    """

    __slots__ = ()

    id = StrField("id")
    account_id = StrField("accountId")
    federal_tax_number = DocumentField("federalTaxNumber", "cnpj")
    tax_regime = StrField("taxRegime")
    status = StrField("status")
    #: Ids of the municipal enrollments (``municipalTaxes``).
    municipal_tax_ids = StrListField("municipalTaxes")
    #: Ids of the state enrollments (``stateTaxes``).
    state_tax_ids = StrListField("stateTaxes")
    created_on = DateTimeField("createdOn")
    modified_on = DateTimeField("modifiedOn")


class Certificate(NfeObject):
    """Digital certificate (A1) metadata of a company."""

    __slots__ = ()

    thumbprint = StrField("thumbprint")
    tax_id = DocumentField("taxId", "auto")
    status = StrField("status")
    provider_type = StrField("providerType")
    #: Expiration, read from ``validUntil`` (certificate API) or ``expiresOn`` (company list).
    expires_on = DateTimeField("validUntil", "expiresOn")
    modified_on = DateTimeField("modifiedOn")

    def is_expired(self, at: datetime | None = None) -> bool:
        """``True`` if the certificate is expired at ``at`` (default: now, UTC).

        A certificate without a readable expiration is reported as expired.
        """
        expires = self.expires_on
        if expires is None:
            return True
        moment = at if at is not None else datetime.now(timezone.utc)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return expires <= moment


class Webhook(NfeObject):
    """Account webhook (``/v2/webhooks``). ``contentType``/``status`` are strings on the wire."""

    __slots__ = ()

    id = StrField("id")
    status = StrField("status")
    content_type = StrField("contentType")
    created_on = DateTimeField("createdOn")
    modified_on = DateTimeField("modifiedOn")


class WebhookEventType(NfeObject):
    """Event type that a webhook can filter on (ids are free text on the wire)."""

    __slots__ = ()

    id = StrField("id")
    status = StrField("status")


class LegalEntity(NfeObject):
    """CNPJ lookup result (``legalentity.api.nfe.io/v3``)."""

    __slots__ = ()

    federal_tax_number = DocumentField("federalTaxNumber", "cnpj")
    status = StrField("status")
    opened_on = DateTimeField("openedOn")
    status_on = DateTimeField("statusOn")
    share_capital = DecimalField("shareCapital")


class NaturalPerson(NfeObject):
    """CPF status lookup result (``naturalperson.api.nfe.io``)."""

    __slots__ = ()

    federal_tax_number = DocumentField("federalTaxNumber", "cpf")
    status = StrField("status")
    birth_on = DateTimeField("birthOn")


class Address(NfeObject):
    """CEP lookup result (``address.api.nfe.io/v2``). City is ``address["city"]["code"]``."""

    __slots__ = ()

    #: 8-digit postal code without the hyphen.
    postal_code = DocumentField("postalCode", "cep")
