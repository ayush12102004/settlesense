"""Production End-to-End API Endpoint Verification Suite.

Tests all production endpoints against the running server:
  - GET /
  - GET /health
  - GET /api/dashboard
  - GET /api/metrics
  - GET /api/cash-position
  - GET /api/exceptions
  - GET /api/tax-reconciliation
  - GET /api/tax/report
  - GET /api/audit/export?format=json
  - GET /api/audit/export?format=csv
  - POST /api/cash-position/simulate
  - POST /api/chat
  - POST /api/agent/diagnose
"""

import json
import urllib.request

BASE_URL = "http://127.0.0.1:5000"


def test_endpoints():
    print(f"Testing SettleSense Production Server at {BASE_URL}...\n")

    get_endpoints = [
        ("/", 200, "text/html"),
        ("/health", 200, "application/json"),
        ("/api/dashboard", 200, "application/json"),
        ("/api/metrics", 200, "application/json"),
        ("/api/cash-position", 200, "application/json"),
        ("/api/exceptions", 200, "application/json"),
        ("/api/tax-reconciliation", 200, "application/json"),
        ("/api/tax/report", 200, "application/json"),
        ("/api/audit/export?format=json", 200, "application/json"),
        ("/api/audit/export?format=csv", 200, "text/csv"),
    ]

    for path, expected_status, content_type in get_endpoints:
        req = urllib.request.Request(f"{BASE_URL}{path}", method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            actual_type = resp.headers.get("Content-Type", "")
            assert resp.status == expected_status, f"Expected {expected_status} for {path}, got {resp.status}"
            assert content_type in actual_type, f"Expected {content_type} in {actual_type}"
            print(f"  [OK] GET  {path:<35} -> HTTP {resp.status} ({actual_type.split(';')[0]})")

    # POST /api/cash-position/simulate
    sim_payload = json.dumps({"lag_days": 2}).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}/api/cash-position/simulate",
        data=sim_payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        res = json.loads(resp.read().decode("utf-8"))
        assert resp.status == 200
        assert "projected_position_14d" in res
        print(f"  [OK] POST /api/cash-position/simulate         -> HTTP 200 (14d stress projection: Rs.{res['projected_position_14d']:,.2f})")

    # POST /api/chat
    chat_payload = json.dumps({"message": "What is our current match rate and total amount at risk?"}).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}/api/chat",
        data=chat_payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        res = json.loads(resp.read().decode("utf-8"))
        assert resp.status == 200
        assert "response" in res and len(res["response"]) > 0
        print(f"  [OK] POST /api/chat                          -> HTTP 200 (agent response length: {len(res['response'])} chars)")

    # Fetch first exception trace ID
    req = urllib.request.Request(f"{BASE_URL}/api/exceptions", method="GET")
    with urllib.request.urlopen(req, timeout=10) as resp:
        exceptions = json.loads(resp.read().decode("utf-8"))
        trace_id = exceptions[0]["trace_id"]

    # POST /api/agent/diagnose
    diag_payload = json.dumps({"trace_id": trace_id}).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}/api/agent/diagnose",
        data=diag_payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        res = json.loads(resp.read().decode("utf-8"))
        assert resp.status == 200
        assert "diagnosis" in res and len(res["diagnosis"]) > 0
        print(f"  [OK] POST /api/agent/diagnose                -> HTTP 200 (trace {trace_id}: diagnosis length {len(res['diagnosis'])} chars)")

    print("\n" + "=" * 60)
    print("ALL PRODUCTION ENDPOINTS PASSED WITH 100% HEALTH!")
    print("=" * 60)


if __name__ == "__main__":
    test_endpoints()
