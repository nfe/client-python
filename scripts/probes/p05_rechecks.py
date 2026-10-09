"""P05 — re-check vault claims that may have changed (read-only).

- Basic auth variants ("Basic <raw key>" vs base64).
- Webhooks: same list on api.nfe.io and api.nfse.io?
- Companies v2 "poison record" cursor 500 (repro from the 2026-07 gate note).
- municipalTaxNumber v1 vs v2 for the test company.
- Off-spec NFS-e /status route; 503 vs 404 for an unknown company; people listings.
- CNPJ v3 for the test company's own CNPJ (alphanumeric-ready string?).
"""

from __future__ import annotations

import base64
from typing import Any

import _probe
from _probe import COMPANY_ID, KEYS, brief, request, save

POISON = "3450bc6208cb4b97a1a3616b89f77a4b"


def main() -> None:
    results: list[dict[str, Any]] = []

    def run(host: str, path: str, **kw: Any) -> dict[str, Any]:
        r = request(host, path, **kw)
        results.append(r)
        print(brief(r))
        return r

    # Basic variants: patch the auth header builder for two extra schemes
    key = KEYS["main"]
    original = _probe._auth

    def patched(key_name: str | None, scheme: str) -> tuple[dict[str, str], dict[str, str]]:
        if scheme == "basic-raw":
            return {"Authorization": f"Basic {key}"}, {}
        if scheme == "basic-b64-nocolon":
            return {"Authorization": "Basic " + base64.b64encode(key.encode()).decode()}, {}
        if scheme == "bearer":
            return {"Authorization": f"Bearer {key}"}, {}
        return original(key_name, scheme)

    _probe._auth = patched
    for scheme in ("basic-raw", "basic-b64-nocolon", "bearer"):
        run("api.nfe.io", "/v1/companies", scheme=scheme, params={"pageIndex": 1, "pageCount": 2})
        run("api.nfse.io", "/v2/companies", scheme=scheme, params={"limit": 2})
    _probe._auth = original

    # Webhooks parity across hosts
    a = run("api.nfe.io", "/v2/webhooks")
    b = run("api.nfse.io", "/v2/webhooks")
    ids_a = sorted(h["id"] for h in (a["body"] or {}).get("webHooks", []))
    ids_b = sorted(h["id"] for h in (b["body"] or {}).get("webHooks", []))
    parity = {"webhooks_same_ids_both_hosts": ids_a == ids_b, "n_api_nfe_io": len(ids_a), "n_api_nfse_io": len(ids_b)}
    print(parity)
    results.append({"webhooksHostParity": parity})

    # Poison cursor repro
    run("api.nfse.io", "/v2/companies", params={"limit": 1, "startingAfter": POISON})
    run("api.nfse.io", f"/v2/companies/{POISON}")

    # municipalTaxNumber v1 vs v2 (test company)
    v1 = run("api.nfe.io", f"/v1/companies/{COMPANY_ID}")
    v2 = run("api.nfse.io", f"/v2/companies/{COMPANY_ID}")
    c1 = (v1["body"] or {}).get("companies") or {}
    c2 = (v2["body"] or {}).get("company") or {}
    cmp = {
        "v1_keys_not_in_v2": sorted(set(c1) - set(c2)),
        "v2_keys_not_in_v1": sorted(set(c2) - set(c1)),
        "same_municipalTaxNumber": c1.get("municipalTaxNumber") == c2.get("municipalTaxNumber"),
        "federalTaxNumber_types": [type(c1.get("federalTaxNumber")).__name__, type(c2.get("federalTaxNumber")).__name__],
    }
    print(cmp)
    results.append({"companyV1vsV2": cmp})
    if c2.get("federalTaxNumber"):
        tax = str(c2["federalTaxNumber"]).zfill(14)
        run("legalentity.api.nfe.io", f"/v3/legalentities/basicInfo/{tax}", key="data")
    for mt in (c2.get("municipalTaxes") or [])[:1]:
        mt_id = mt.get("id") if isinstance(mt, dict) else mt
        run("api.nfse.io", f"/v2/companies/{COMPANY_ID}/municipaltaxes/{mt_id}")
    run("api.nfse.io", f"/v2/companies/{COMPANY_ID}/municipaltaxes", params={"limit": 5})

    # NFS-e /status (off-spec) and unknown company behaviour
    lst = request("api.nfe.io", f"/v1/companies/{COMPANY_ID}/serviceinvoices", params={"pageIndex": 1, "pageCount": 3})
    for inv in (lst["body"] or {}).get("serviceInvoices", [])[:2]:
        run("api.nfe.io", f"/v1/companies/{COMPANY_ID}/serviceinvoices/{inv['id']}/status")
    run("api.nfe.io", "/v1/companies/000000000000000000000000/serviceinvoices", params={"pageIndex": 1, "pageCount": 2})
    run("api.nfe.io", "/v1/companies/00000000000000000000000000000000/serviceinvoices", params={"pageIndex": 1, "pageCount": 2})
    run("api.nfe.io", f"/v1/companies/{COMPANY_ID}/serviceinvoices", params={"pageIndex": 0, "pageCount": 2})
    run("api.nfe.io", f"/v1/companies/{COMPANY_ID}/serviceinvoices", params={"pageIndex": 1, "pageCount": 1})

    # people listings (24-hex vs 32-hex company id)
    run("api.nfe.io", f"/v1/companies/{COMPANY_ID}/legalpeople")
    run("api.nfe.io", f"/v1/companies/{COMPANY_ID}/naturalpeople")

    # unserved path baseline (to distinguish "not served" 404 from "not found" 404)
    run("api.nfe.io", "/v1/this-route-does-not-exist", key=None)
    run("api.nfse.io", "/v2/this-route-does-not-exist", key=None)
    print("saved", save("p05_rechecks", results))


if __name__ == "__main__":
    main()
