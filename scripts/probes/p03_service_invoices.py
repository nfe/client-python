"""P03 — NFS-e read paths on the test company: list, retrieve, external id, downloads (read-only)."""

from __future__ import annotations

from collections import Counter
from typing import Any

from _probe import COMPANY_ID, brief, follow_redirect, request, save

BASE = f"/v1/companies/{COMPANY_ID}/serviceinvoices"


def main() -> None:
    results: list[dict[str, Any]] = []

    def run(path: str, **kw: Any) -> dict[str, Any]:
        r = request("api.nfe.io", path, **kw)
        results.append(r)
        loc = next((v for k, v in r["headers"].items() if k.lower() == "location"), None)
        print(brief(r), "| Location:", loc)
        return r

    def follow(r: dict[str, Any]) -> None:
        t = follow_redirect(r)
        if t:
            results.append(t)
            body = t["body"]
            head = body.get("_startsWith") or body.get("_binary_head_hex") if isinstance(body, dict) else None
            print("   ->", t["status"], t["request"]["host"], t["request"]["path"], t["headers"].get("Content-Type"),
                  t["bodyLength"], repr(head))

    run(BASE, params={"pageIndex": 0, "pageCount": 2})
    page1 = run(BASE, params={"pageIndex": 1, "pageCount": 50})
    run(BASE, params={"pageIndex": 1, "pageCount": 51})
    run(BASE, params={"pageIndex": 1, "pageCount": 100})
    run(BASE, params={"pageIndex": 1, "pageCount": 2, "hasTotals": "true"})
    run(BASE, params={"pageIndex": 1, "pageCount": 2, "issuedBegin": "2026-01-01", "issuedEnd": "2026-12-31"})
    invoices = page1["body"].get("serviceInvoices", []) if isinstance(page1["body"], dict) else []
    stats = {
        "flowStatus": Counter(i.get("flowStatus") for i in invoices),
        "status": Counter(i.get("status") for i in invoices),
        "withExternalId": sum(1 for i in invoices if i.get("externalId")),
        "keys_union": sorted({k for i in invoices for k in i}),
    }
    print("stats", stats)
    results.append({"stats": {k: (dict(v) if isinstance(v, Counter) else v) for k, v in stats.items()}})

    issued = next((i for i in invoices if i.get("flowStatus") == "Issued"), None)
    cancelled = next((i for i in invoices if i.get("flowStatus") == "Cancelled"), None)
    with_ext = next((i for i in invoices if i.get("externalId")), None)
    if invoices:
        run(f"{BASE}/{invoices[0]['id']}")
    if issued:
        run(f"{BASE}/{issued['id']}/pdf", accept="application/pdf")
        follow(run(f"{BASE}/{issued['id']}/pdf", accept="*/*"))
        run(f"{BASE}/{issued['id']}/xml", accept="application/xml")
        follow(run(f"{BASE}/{issued['id']}/xml", accept="*/*"))
        # second issued invoice, to avoid generalising from one sample
        other = next((i for i in invoices if i.get("flowStatus") == "Issued" and i is not issued), None)
        if other:
            follow(run(f"{BASE}/{other['id']}/xml", accept="*/*"))
    if cancelled:
        run(f"{BASE}/{cancelled['id']}")
        run(f"{BASE}/{cancelled['id']}/cancellation-xml", accept="*/*")
    if with_ext:
        run(f"{BASE}/external/{with_ext['externalId']}")
    run(f"{BASE}/external/sdk-python-probe-does-not-exist")
    run(f"{BASE}/000000000000000000000000")
    run(f"{BASE}/not-a-valid-id")
    run(f"{BASE}/000000000000000000000000/pdf", accept="*/*")
    print("saved", save("p03_service_invoices", results))


if __name__ == "__main__":
    main()
