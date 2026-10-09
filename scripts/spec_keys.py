"""Extract the wire keys of the OpenAPI schemas the SDK models map to.

Writes ``tests/fixtures/spec-keys.json`` (versioned snapshot, so CI does not need the
``nfeio-docs`` checkout). Anchored on *paths* (not operationIds, which are duplicated in the
NFS-e spec). Run from the repo root:

    uv run python scripts/spec_keys.py            # regenerate the snapshot
    uv run python scripts/spec_keys.py --check    # fail if the snapshot is stale
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
SPECS = ROOT / "nfeio-docs" / "static" / "api"
OUT = ROOT / "tests" / "fixtures" / "spec-keys.json"


def _load(name: str) -> dict[str, Any]:
    text = (SPECS / name).read_text("utf-8")
    data = json.loads(text) if name.endswith(".json") else yaml.safe_load(text)
    assert isinstance(data, dict)
    return data


def _resolve(doc: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    while "$ref" in node:
        target: Any = doc
        for part in node["$ref"].lstrip("#/").split("/"):
            target = target[part]
        node = target
    if "allOf" in node:
        merged: dict[str, Any] = {"properties": {}}
        for sub in node["allOf"]:
            merged["properties"].update(_resolve(doc, sub).get("properties", {}))
        return merged
    return node


def _props(doc: dict[str, Any], node: dict[str, Any], *walk: str) -> list[str]:
    node = _resolve(doc, node)
    for step in walk:
        if step == "[]":
            node = _resolve(doc, node["items"])
        else:
            node = _resolve(doc, node["properties"][step])
    return sorted(node.get("properties", {}))


def _response(doc: dict[str, Any], path: str, method: str = "get", status: str = "200") -> Any:
    response = doc["paths"][path][method]["responses"][status]
    if "content" in response:
        return next(iter(response["content"].values()))["schema"]
    return response["schema"]


def _body(doc: dict[str, Any], path: str, method: str = "post") -> Any:
    content = doc["paths"][path][method]["requestBody"]["content"]
    return content.get("application/json", next(iter(content.values())))["schema"]


def extract() -> dict[str, list[str]]:
    nfse = _load("nf-servico-v1.yaml")
    taxpayers = _load("contribuintes-v2.json")
    cnpj = _load("consulta-cnpj-v3.json")
    cpf = _load("cpf-api.yaml")
    cep = _load("consulta-endereco.yaml")
    invoice = _response(nfse, "/v1/companies/{company_id}/serviceinvoices/{id}")
    create = _body(nfse, "/v1/companies/{company_id}/serviceinvoices")
    hooks = _response(nfse, "/v2/webhooks")
    hook_body = _body(nfse, "/v2/webhooks")
    company_schemas = taxpayers["components"]["schemas"]
    certs = _response(taxpayers, "/v2/companies/{company_id}/certificates")
    return {
        "ServiceInvoice": _props(nfse, invoice),
        "Party.borrower": _props(nfse, invoice, "borrower"),
        "Party.provider": _props(nfse, invoice, "provider"),
        "ServiceInvoiceCreateParams": _props(nfse, create),
        "BorrowerParams": _props(nfse, create, "borrower"),
        "AddressParams": _props(nfse, create, "borrower", "address"),
        "CityParams": _props(nfse, create, "borrower", "address", "city"),
        "Company": _props(
            taxpayers, company_schemas["DFeTech.TaxPayers.Resources.CompanyResourceItem"]
        ),
        "CompanyParams": sorted(
            set(
                _props(
                    taxpayers,
                    company_schemas["DFeTech.TaxPayers.Resources.CreateCompanyResourceItem"],
                )
            )
            | set(
                _props(
                    taxpayers,
                    company_schemas["DFeTech.TaxPayers.Resources.UpdateCompanyResourceItem"],
                )
            )
        ),
        "CompanyAddressParams": _props(
            taxpayers, company_schemas["DFeTech.TaxPayers.Resources.AddressResource"]
        ),
        "Certificate": _props(taxpayers, certs, "certificates", "[]"),
        "Webhook": _props(nfse, hooks, "webHooks", "[]"),
        "WebhookParams": _props(nfse, hook_body, "webHook"),
        "WebhookEventType": _props(
            nfse, _response(nfse, "/v2/webhooks/eventtypes"), "eventTypes", "[]"
        ),
        "LegalEntity": _props(
            cnpj, _response(cnpj, "/v3/legalentities/basicInfo/{federalTaxNumber}"), "legalEntity"
        ),
        "NaturalPerson": _props(
            cpf, _response(cpf, "/v1/naturalperson/status/{federalTaxNumber}/{birthDate}")
        ),
        # Spec wraps a list ("addresses"); the wire sends one "address" (divergence #32).
        "Address": _props(cep, _response(cep, "/v2/addresses/{postalCode}"), "addresses", "[]"),
    }


def main() -> int:
    snapshot = json.dumps(
        {"_generated_by": "scripts/spec_keys.py", "keys": extract()}, indent=2, sort_keys=True
    )
    if "--check" in sys.argv:
        if OUT.read_text("utf-8").strip() != snapshot.strip():
            print("tests/fixtures/spec-keys.json is stale: run scripts/spec_keys.py")
            return 1
        return 0
    OUT.write_text(snapshot + "\n", "utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
