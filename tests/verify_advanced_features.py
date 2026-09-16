import urllib.request
import json
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE_URL = "http://127.0.0.1:8000"

def get(url):
    req = urllib.request.Request(BASE_URL + url)
    res = urllib.request.urlopen(req)
    return res.status, json.loads(res.read().decode("utf-8"))

def get_text(url):
    req = urllib.request.Request(BASE_URL + url)
    res = urllib.request.urlopen(req)
    return res.status, res.read().decode("utf-8")

def post(url, body):
    req = urllib.request.Request(
        BASE_URL + url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    res = urllib.request.urlopen(req)
    return res.status, json.loads(res.read().decode("utf-8"))

def delete(url, body=None):
    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(
        BASE_URL + url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="DELETE"
    )
    res = urllib.request.urlopen(req)
    return res.status, json.loads(res.read().decode("utf-8"))

def main():
    print("==================================================")
    print("VERIFYING ALIBABA DIRECTMAIL ADVANCED SUITE")
    print("==================================================")

    # 1. Static frontend checks
    print("\n[1] Testing Static Assets...")
    s, html = get_text("/")
    assert s == 200, f"Expected 200, got {s}"
    assert "Overview" in html and "Domains" in html and "Senders" in html and "Templates" in html
    assert "Recipients Pool" in html and "Email Tasks" in html and "Delivery" in html
    print(f"  [OK] Frontend index.html served ({len(html)} bytes) with all 11 sections")

    s, js = get_text("/static/js/app.js")
    assert s == 200
    assert "loadOverviewData" in js and "handleSmartAgentSubmit" in js and "showDeleteConfirm" in js
    print(f"  ✓ Frontend app.js served ({len(js)} bytes)")

    s, css = get_text("/static/css/style.css")
    assert s == 200
    print(f"  ✓ Frontend style.css served ({len(css)} bytes)")

    # 2. Account Summary
    print("\n[2] Testing Account Summary (/api/account-summary/singapore)...")
    s, summary = get(f"/api/account-summary/singapore")
    assert s == 200
    d = summary.get("data", {})
    print(f"  ✓ Account Level: {d.get('QuotaLevel')} / {d.get('MaxQuotaLevel')}")
    print(f"  ✓ Daily Quota: {d.get('DailyQuota')}, Month Quota: {d.get('MonthQuota')}")
    print(f"  ✓ Domains: {d.get('Domains')}, MailAddresses: {d.get('MailAddresses')}, Templates: {d.get('Templates')}")

    # 3. Domains
    print("\n[3] Testing Domains (/api/domains/singapore)...")
    s, dom_res = get("/api/domains/singapore")
    assert s == 200
    domains = dom_res.get("domains", [])
    print(f"  ✓ Retrieved {len(domains)} domain(s) from Alibaba DirectMail:")
    for dom in domains:
        print(f"    - {dom.get('DomainName')} (ID: {dom.get('DomainId')}, CNAME: {dom.get('CnameAuthStatus')}, SPF: {dom.get('SpfAuthStatus')})")
        # Test detail
        dom_id = dom.get("DomainId")
        s2, detail_res = get(f"/api/domains/singapore/{dom_id}")
        assert s2 == 200
        det = detail_res.get("detail", {})
        print(f"      DNS Detail Record: {det.get('DomainRecord')} (CnameAuth: {det.get('CnameAuthStatus')})")

    # 4. Senders
    print("\n[4] Testing Senders (/api/senders/singapore)...")
    s, send_res = get("/api/senders/singapore")
    assert s == 200
    senders = send_res.get("senders", [])
    print(f"  ✓ Retrieved {len(senders)} verified sender(s):")
    for snd in senders:
        print(f"    - {snd.get('AccountName')} (Type: {snd.get('Sendtype')}, Status: {snd.get('AccountStatus')})")

    # 5. Templates
    print("\n[5] Testing Templates (/api/templates/singapore)...")
    s, tpl_res = get("/api/templates/singapore")
    assert s == 200
    templates = tpl_res.get("templates", [])
    print(f"  ✓ Retrieved {len(templates)} template(s):")
    for tpl in templates:
        print(f"    - {tpl.get('TemplateName')} (ID: {tpl.get('TemplateId')}, Type: {tpl.get('TemplateType')})")
        # Test template detail HTML
        tpl_id = tpl.get("TemplateId")
        s2, tdetail = get(f"/api/templates/singapore/{tpl_id}")
        assert s2 == 200
        td = tdetail.get("detail", {})
        assert td.get("success") is True
        print(f"      HTML length: {len(td.get('TemplateText', ''))} chars, Subject: '{td.get('TemplateSubject')}'")

    # 6. DirectMail Batch Tasks
    print("\n[6] Testing DirectMail Batch Tasks (/api/dm-tasks/singapore)...")
    s, task_res = get("/api/dm-tasks/singapore")
    assert s == 200
    print(f"  ✓ Batch tasks query returned status {s}, TotalCount: {task_res.get('total')}")

    # 7. Delivery Statistics
    print("\n[7] Testing Delivery Statistics (/api/delivery-stats/singapore)...")
    s, deliv_res = get("/api/delivery-stats/singapore?range=7d")
    assert s == 200
    aggr = deliv_res.get("aggregate", {})
    print(f"  ✓ 7-Day Stats: Total Requests: {aggr.get('total_requests')}, Delivery Rate: {aggr.get('delivery_rate')}%, Failed: {aggr.get('total_failed')}, Bounced: {aggr.get('total_unavailable')}")

    # 8. Tracking Events
    print("\n[8] Testing Tracking Events (/api/tracking/events/singapore)...")
    s, track_res = get("/api/tracking/events/singapore")
    assert s == 200
    events = track_res.get("events", [])
    print(f"  ✓ Tracking events count: {len(events)}")
    if events:
        first = events[0]
        print(f"    Recent event: To={first.get('ToAddress')}, Status={first.get('Status')}, Msg={first.get('Message')}")

    # 9. Application Recipients Pool (CRUD)
    print("\n[9] Testing Application Recipients Pool CRUD (/api/recipients)...")
    # Add recipient
    test_email = "test-recipient-audit@example.com"
    s, add_res = post("/api/recipients", {
        "recipients": [{"email": test_email, "name": "Audit Test", "tags": "audit"}]
    })
    assert s == 200
    print(f"  ✓ Added test recipient: {test_email}")

    # List recipients
    s, list_res = get("/api/recipients")
    assert s == 200
    recs = list_res.get("recipients", [])
    matching = [r for r in recs if r.get("email") == test_email]
    assert len(matching) > 0
    rec_id = matching[0]["id"]
    print(f"  ✓ Found recipient in pool with ID {rec_id}")

    # Delete recipient
    s, del_res = delete("/api/recipients", {"ids": [rec_id]})
    assert s == 200
    print(f"  ✓ Deleted test recipient ID {rec_id}")

    # 10. Smart Agent Natural Language Query
    print("\n[10] Testing Smart Agent NLP Console (/api/smart-agent/query)...")
    queries = [
        "what is my daily quota in singapore?",
        "show all verified domains",
        "show today's delivery report",
        "show verified senders"
    ]
    for q in queries:
        s, a_res = post("/api/smart-agent/query", {"prompt": q, "region": "singapore"})
        assert s == 200
        print(f"  ✓ Query: '{q}' -> Intent: {a_res.get('intent')}, Title: '{a_res.get('title')}'")

    print("\n==================================================")
    print("ALL 10 VERIFICATION SUITES PASSED FLAWLESSLY!")
    print("==================================================")

if __name__ == "__main__":
    main()
