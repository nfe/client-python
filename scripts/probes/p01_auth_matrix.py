"""P01 — which key and which auth scheme each host accepts (read-only).

For each family endpoint, try: no key, main key, data key; and for the accepted key,
each auth scheme (X-NFE-APIKEY, raw Authorization, Basic, ?apikey=).
"""

from __future__ import annotations

from _probe import COMPANY_ID, brief, request, save

# Public, non-personal sample values (Banco do Brasil CNPJ; Av. Paulista CEP; documented test CPF).
CNPJ = "00000000000191"
CEP = "01310100"
CPF = "52998224725"
BIRTH = "1990-01-01"

TARGETS = [
    ("api.nfe.io", "/v1/companies", {"pageIndex": 1, "pageCount": 2}),
    ("api.nfe.io", f"/v1/companies/{COMPANY_ID}/serviceinvoices", {"pageIndex": 1, "pageCount": 2}),
    ("api.nfse.io", "/v2/companies", {"limit": 2}),
    ("api.nfse.io", "/v2/webhooks", None),
    ("api.nfe.io", "/v2/webhooks", None),
    ("legalentity.api.nfe.io", f"/v2/legalentities/basicInfo/{CNPJ}", None),
    ("legalentity.api.nfe.io", f"/v1/legalentities/basicInfo/{CNPJ}", None),
    ("address.api.nfe.io", f"/v2/addresses/{CEP}", None),
    ("naturalperson.api.nfe.io", f"/v1/naturalperson/status/{CPF}/{BIRTH}", None),
]
SCHEMES = ["x-nfe-apikey", "authorization", "basic", "query"]


def main() -> None:
    results = []
    for host, path, params in TARGETS:
        accepted = None
        for key in (None, "main", "data"):
            r = request(host, path, key=key, params=params)
            results.append(r)
            print(brief(r))
            if accepted is None and r["status"] is not None and r["status"] < 400:
                accepted = key
        if accepted:
            for scheme in SCHEMES[1:]:
                r = request(host, path, key=accepted, scheme=scheme, params=params)
                results.append(r)
                print(brief(r))
    print("saved", save("p01_auth_matrix", results))


if __name__ == "__main__":
    main()
