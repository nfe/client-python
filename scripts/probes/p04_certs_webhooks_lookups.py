"""P04 — certificate envelopes, webhooks list/event types, data lookups and error shapes (read-only)."""

from __future__ import annotations

from typing import Any

from _probe import COMPANY_ID, KEYS, brief, request, save

CNPJ = "00000000000191"
CEP = "01310100"


def main() -> None:
    results: list[dict[str, Any]] = []

    def run(host: str, path: str, **kw: Any) -> dict[str, Any]:
        r = request(host, path, **kw)
        results.append(r)
        print(brief(r))
        return r

    # certificates
    run("api.nfe.io", f"/v1/companies/{COMPANY_ID}/certificate")
    run("api.nfse.io", f"/v1/companies/{COMPANY_ID}/certificate")
    run("api.nfse.io", f"/v2/companies/{COMPANY_ID}/certificates")

    # webhooks (secrets are redacted before saving)
    hooks = run("api.nfse.io", "/v2/webhooks")
    run("api.nfse.io", "/v2/webhooks/eventtypes")
    run("api.nfse.io", "/v2/webhooks/eventTypes")
    run("api.nfe.io", "/v1/hooks")
    run("api.nfe.io", "/v1/eventTypes")
    body = hooks["body"] if isinstance(hooks["body"], dict) else {}
    for h in body.get("webHooks") or []:
        if h.get("id"):
            results.append(request("api.nfse.io", f"/v2/webhooks/{h['id']}"))
            print(brief(results[-1]))
            break
    run("api.nfse.io", "/v2/webhooks/000000000000000000000000")
    for r in results:
        _redact_secrets(r.get("body"))

    # data lookups
    run("legalentity.api.nfe.io", f"/v1/legalentities/basicInfo/{CNPJ}", key="data")
    run("legalentity.api.nfe.io", f"/v2/legalentities/basicInfo/{CNPJ}", key="data")
    run("legalentity.api.nfe.io", f"/v3/legalentities/basicInfo/{CNPJ}", key="data")
    run("legalentity.api.nfe.io", f"/v2/legalentities/stateTaxInfo/DF/{CNPJ}", key="data")
    run("legalentity.api.nfe.io", "/v2/legalentities/basicInfo/00000000000100", key="data")  # bad DV
    run("legalentity.api.nfe.io", "/v2/legalentities/basicInfo/123", key="data")
    run("legalentity.api.nfe.io", "/v2/legalentities/basicInfo/00.000.000/0001-91", key="data")
    run("address.api.nfe.io", f"/v2/addresses/{CEP}", key="data")
    run("address.api.nfe.io", "/v2/addresses/01310-100", key="data")
    run("address.api.nfe.io", "/v2/addresses/00000000", key="data")
    run("address.api.nfe.io", "/v1/addresses/" + CEP, key="data")
    run("address.api.nfe.io", "/v2/addresses", key="data", params={"$filter": "city eq 'Curitiba'"})
    run("naturalperson.api.nfe.io", "/v1/naturalperson/status/52998224725/1990-01-01", key="data")
    run("naturalperson.api.nfe.io", "/v1/naturalperson/status/12345678900/1990-01-01", key="data")
    run("naturalperson.api.nfe.io", "/v1/naturalperson/status/52998224725/01-01-1990", key="data")

    # error shapes with a well-formed but wrong key (401 with key present)
    KEYS["bogus"] = "0" * 32
    run("api.nfe.io", "/v1/companies", key="bogus")
    run("api.nfse.io", "/v2/companies", key="bogus")
    run("api.nfe.io", "/v1/companies", params={"pageIndex": 1, "pageCount": 0})
    run("api.nfe.io", "/v1/companies", params={"pageIndex": -1, "pageCount": 2})
    run("api.nfe.io", "/v1/companies", params={"pageIndex": "abc"})
    del KEYS["bogus"]
    print("saved", save("p04_certs_webhooks_lookups", results))


def _redact_secrets(node: Any) -> None:
    if isinstance(node, dict):
        for k in list(node):
            if k.lower() in {"secret", "password"} and node[k]:
                node[k] = "<redacted>"
            else:
                _redact_secrets(node[k])
    elif isinstance(node, list):
        for x in node:
            _redact_secrets(x)


if __name__ == "__main__":
    main()
