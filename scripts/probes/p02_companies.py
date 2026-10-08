"""P02 — companies v1 (offset, 1-based?) and v2 (cursor) shape, limits and parity (read-only)."""

from __future__ import annotations

from typing import Any

from _probe import COMPANY_ID, brief, request, save


def main() -> None:
    results: list[dict[str, Any]] = []

    def run(host: str, path: str, **kw: Any) -> dict[str, Any]:
        r = request(host, path, **kw)
        results.append(r)
        page = r["body"].get("page") if isinstance(r["body"], dict) else None
        extra = ""
        if isinstance(r["body"], dict):
            for k in ("companies",):
                if isinstance(r["body"].get(k), list):
                    extra += f" n={len(r['body'][k])}"
            if "hasMore" in r["body"]:
                extra += f" hasMore={r['body']['hasMore']}"
        print(brief(r), f"page={page}{extra}")
        return r

    # v1 pagination semantics: index 0 vs 1, pageCount limits
    for idx in (0, 1, 2):
        run("api.nfe.io", "/v1/companies", params={"pageIndex": idx, "pageCount": 2})
    for count in (1, 2, 50, 51, 100):
        run("api.nfe.io", "/v1/companies", params={"pageIndex": 1, "pageCount": count})
    run("api.nfe.io", "/v1/companies")  # server defaults
    # v1 retrieve by id and by tax number
    one = run("api.nfe.io", f"/v1/companies/{COMPANY_ID}")
    tax = None
    if isinstance(one["body"], dict):
        c = one["body"].get("companies") or one["body"]
        if isinstance(c, dict):
            tax = c.get("federalTaxNumber")
    if tax:
        run("api.nfe.io", f"/v1/companies/{tax}")
    run("api.nfe.io", "/v1/companies/000000000000000000000000")  # unknown id -> error shape

    # v2 cursor
    first = run("api.nfse.io", "/v2/companies", params={"limit": 2})
    if isinstance(first["body"], dict) and first["body"].get("companies"):
        last = first["body"]["companies"][-1]["id"]
        nxt = run("api.nfse.io", "/v2/companies", params={"limit": 2, "startingAfter": last})
        if isinstance(nxt["body"], dict) and nxt["body"].get("companies"):
            run(
                "api.nfse.io",
                "/v2/companies",
                params={"limit": 2, "endingBefore": nxt["body"]["companies"][0]["id"]},
            )
    for limit in (0, 1, 50, 51, 100):
        run("api.nfse.io", "/v2/companies", params={"limit": limit})
    run("api.nfse.io", "/v2/companies")  # server default limit
    run("api.nfse.io", f"/v2/companies/{COMPANY_ID}")
    run("api.nfse.io", "/v2/companies/000000000000000000000000")

    # parity: total count v1 vs full v2 iteration (bounded)
    v1_total = None
    r = run("api.nfe.io", "/v1/companies", params={"pageIndex": 1, "pageCount": 50})
    if isinstance(r["body"], dict):
        # observed 2026-10-08: "page" is an int (echo of pageIndex), no totals in the envelope
        page = r["body"].get("page")
        v1_total = page.get("totalResults") if isinstance(page, dict) else None
    v2_ids: list[str] = []
    cursor = None
    for _ in range(30):
        params: dict[str, Any] = {"limit": 50}
        if cursor:
            params["startingAfter"] = cursor
        r = request("api.nfse.io", "/v2/companies", params=params)
        body = r["body"] if isinstance(r["body"], dict) else {}
        batch = body.get("companies") or []
        v2_ids += [c["id"] for c in batch]
        if not body.get("hasMore") or not batch:
            break
        cursor = batch[-1]["id"]
    v1_ids: list[str] = []
    for idx in range(1, 40):
        r = request("api.nfe.io", "/v1/companies", params={"pageIndex": idx, "pageCount": 50})
        batch = (r["body"] or {}).get("companies") or [] if isinstance(r["body"], dict) else []
        v1_ids += [c["id"] for c in batch]
        if len(batch) < 50:
            break
    parity = {
        "v1_totalResults": v1_total,
        "v1_iterated": len(v1_ids),
        "v1_unique": len(set(v1_ids)),
        "v2_iterated": len(v2_ids),
        "v2_unique": len(set(v2_ids)),
        "only_in_v1": len(set(v1_ids) - set(v2_ids)),
        "only_in_v2": len(set(v2_ids) - set(v1_ids)),
        "test_company_in_v1": COMPANY_ID in v1_ids,
        "test_company_in_v2": COMPANY_ID in v2_ids,
    }
    print("parity", parity)
    results.append({"parity": parity})
    print("saved", save("p02_companies", results))


if __name__ == "__main__":
    main()
