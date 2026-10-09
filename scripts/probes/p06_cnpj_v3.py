"""P06 — CNPJ v3 routes declared in consulta-cnpj-v3.json (read-only, data key)."""

from __future__ import annotations

from _probe import brief, request, save

CNPJ = "00000000000191"  # public sample (Banco do Brasil)


def main() -> None:
    results = [
        request("legalentity.api.nfe.io", f"/v3/legalentities/stateTaxInfo/DF/{CNPJ}", key="data"),
        request("legalentity.api.nfe.io", "/v3/legalentities/basicInfo/00000000000100", key="data"),
        request("legalentity.api.nfe.io", "/v3/legalentities/basicInfo/12ABC34501DE35", key="data"),
    ]
    for r in results:
        print(brief(r), str(r["body"])[:200])
    print("saved", save("p06_cnpj_v3", results))


if __name__ == "__main__":
    main()
