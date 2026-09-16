import urllib.request
import urllib.parse
import json
import sys
import time
import datetime

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

def put(url, body):
    req = urllib.request.Request(
        BASE_URL + url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="PUT"
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
    print("=" * 70)
    print("VERIFICATION SUITE: ALIBABA DIRECTMAIL ADVANCED MASTER FEATURES")
    print("=" * 70)

    # 1. Verify Frontend Assets
    print("\n[1] Verifying Frontend Elements & UI Integration...")
    s, html = get_text("/")
    assert s == 200, f"Expected 200, got {s}"
    assert "nav-tags" in html, "Missing #nav-tags sidebar link"
    assert "view-tags" in html, "Missing #view-tags section"
    assert "send-template-select" in html, "Missing #send-template-select"
    assert "send-tag-select" in html, "Missing #send-tag-select"
    assert "single-sched-toggle" in html, "Missing #single-sched-toggle"
    assert "bulk-template-select" in html, "Missing #bulk-template-select"
    assert "bulk-tag-select" in html, "Missing #bulk-tag-select"
    assert "bulk-sched-toggle" in html, "Missing #bulk-sched-toggle"
    assert "bulk-audience-search" in html, "Missing #bulk-audience-search"
    assert "modal-delivery-drilldown" in html, "Missing #modal-delivery-drilldown"
    assert "deliv-tag-filter" in html, "Missing #deliv-tag-filter"
    assert "openDeliveryDrillDown" in html, "Missing openDeliveryDrillDown handler"
    assert "exportDeliveryCsv" in html, "Missing exportDeliveryCsv handler"
    print("  ✓ Frontend HTML contains all required UI components and handlers")

    s, js = get_text("/static/js/app.js")
    assert s == 200, f"Expected 200, got {js[:50]}"
    assert "loadEmailTagsTable" in js, "Missing loadEmailTagsTable in app.js"
    assert "submitTemplateToProviderReview" in js, "Missing submitTemplateToProviderReview in app.js"
    assert "handleSelectSendTemplate" in js, "Missing handleSelectSendTemplate in app.js"
    assert "excludeSelectedAudience" in js, "Missing excludeSelectedAudience in app.js"
    assert "loadDrilldownRecords" in js, "Missing loadDrilldownRecords in app.js"
    assert "loadScheduledCampaignsTable" in js, "Missing loadScheduledCampaignsTable in app.js"
    print("  ✓ Frontend app.js contains all required controller workflows")

    # 2. Email Tags CRUD & DirectMail Sync
    print("\n[2] Testing Email Tags CRUD & Sync (/api/tags)...")
    tag_name = f"verify-tag-{int(time.time())}"
    tag_data = {
        "name": tag_name,
        "description": "Tag created during master prompt verification",
        "region": "singapore"
    }
    s, created_tag = post("/api/tags", tag_data)
    assert s == 200, f"Tag create failed: {created_tag}"
    assert created_tag["name"] == tag_name
    tag_id = created_tag["tag_id"]
    print(f"  ✓ Tag created: id={tag_id}, name={tag_name}")

    # Read tag
    s, fetched_tag = get(f"/api/tags/{tag_id}")
    assert s == 200, f"Tag fetch failed: {fetched_tag}"
    assert fetched_tag["tag"]["id"] == tag_id

    # List tags
    s, tags_list = get("/api/tags")
    assert s == 200
    assert any(t["id"] == tag_id for t in tags_list["tags"]), "Created tag not found in tags list"
    print(f"  ✓ Tag listing verified (total tags: {len(tags_list['tags'])})")

    # Update tag
    s, updated_tag = put(f"/api/tags/{tag_id}", {
        "description": "Updated tag description"
    })
    assert s == 200
    assert updated_tag["success"] is True
    print("  ✓ Tag update verified")

    # 3. Template Review Workflow & Strict Enforcement
    print("\n[3] Testing Template Review Workflow & Provider Approval Enforcement...")
    tpl_name = f"review_tpl_{int(time.time())}"
    tpl_data = {
        "name": tpl_name,
        "subject": "Automated Verification Subject",
        "html_body": "<p>Hello {{UserName}}, your account statement is ready.</p>",
        "text_body": "Hello UserName, your account statement is ready.",
        "dm_region": "singapore"
    }
    s, created_tpl = post("/api/app-templates", tpl_data)
    assert s == 200, f"Template create failed: {created_tpl}"
    tpl_id = created_tpl["template_id"]
    s, tpl_obj = get(f"/api/app-templates/{tpl_id}")
    assert tpl_obj["dm_status"] in ["draft", "pending_review"], f"Unexpected initial status {tpl_obj['dm_status']}"
    print(f"  ✓ Template created: id={tpl_id}, name={tpl_name}, status={tpl_obj['dm_status']}")

    # Submit review
    s, review_resp = post(f"/api/app-templates/{tpl_id}/submit-review", {})
    assert s == 200, f"Submit review failed: {review_resp}"
    print(f"  ✓ Submit to provider review returned: status={review_resp.get('status')}")

    # Check provider status
    s, prov_status = get(f"/api/app-templates/{tpl_id}/provider-status")
    assert s == 200
    print(f"  ✓ Provider status checked: {prov_status.get('status')}")

    # Resubmit review
    s, resubmit_resp = post(f"/api/app-templates/{tpl_id}/resubmit", {})
    assert s == 200
    print(f"  ✓ Resubmit review succeeded: {resubmit_resp.get('status')}")

    # Strict Enforcement: Attempt to send email with an unapproved template
    print("  Testing strict enforcement on unapproved template...")
    # Get a sender from Singapore
    s, senders_resp = get("/api/senders/singapore")
    valid_sender = "noreply@notificationquickbooks.com"
    if s == 200 and senders_resp.get("senders"):
        valid_sender = senders_resp["senders"][0].get("address", valid_sender)

    send_payload_unapproved = {
        "from_alias": "Verification Tester",
        "sender": valid_sender,
        "recipient": "unapproved_test@example.com",
        "template_id": tpl_id,
        "region": "singapore"
    }
    try:
        post("/api/send", send_payload_unapproved)
        assert False, "Expected 400 error when sending with unapproved template, but call succeeded!"
    except urllib.error.HTTPError as e:
        err_body = json.loads(e.read().decode("utf-8"))
        assert e.code == 400, f"Expected 400, got {e.code}"
        assert "approved" in err_body["detail"].lower(), f"Expected approval error message, got: {err_body}"
        print(f"  ✓ Correctly rejected sending with unapproved template (HTTP 400: {err_body['detail']})")

    # Now approve template via API to test Auto-Subject Attachment
    print("  Testing auto-subject attachment when template is approved...")
    s, apprv_res = post(f"/api/app-templates/{tpl_id}/review", {"status": "approved"})
    assert s == 200, f"Approve template failed: {apprv_res}"
    
    # Send scheduled single email with template_id and NO subject/body provided
    future_time_single = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1)).strftime("%Y-%m-%d %H:%M")
    send_payload_approved = {
        "from_alias": "Verification Tester",
        "sender": valid_sender,
        "recipient": "auto_subject_test@example.com",
        "template_id": tpl_id,
        "tag_name": tag_name,
        "region": "singapore",
        "scheduled_at": future_time_single,
        "timezone_name": "Asia/Singapore"
    }
    s, send_res = post("/api/send", send_payload_approved)
    assert s == 200, f"Send failed: {send_res}"
    assert send_res["status"] == "scheduled"
    s, job_record = get(f"/api/jobs/{send_res['job_id']}")
    assert s == 200
    assert job_record["subject"] == "Automated Verification Subject", f"Subject not auto-attached: {job_record['subject']}"
    assert "UserName" in (job_record.get("html_body") or job_record.get("body") or ""), f"Body not auto-attached: {job_record}"
    assert job_record["template_id"] == tpl_id, "template_id not saved on job"
    assert job_record["tag_name"] == tag_name, "tag_name not saved on job"
    print("  ✓ Auto-subject & template body correctly attached without manual entry")

    # 4. Bulk Campaign Recipient Management & Non-Deletion Guarantee
    print("\n[4] Testing Bulk Audience Exclusion & Master Pool Non-Deletion Guarantee...")
    # Add 3 test recipients to master pool
    email1 = f"keep1_{int(time.time())}@example.com"
    email2 = f"keep2_{int(time.time())}@example.com"
    email3 = f"exclude_{int(time.time())}@example.com"
    s, add_res = post("/api/recipients", {
        "recipients": [
            {"email": email1, "name": "Keep 1"},
            {"email": email2, "name": "Keep 2"},
            {"email": email3, "name": "Exclude 3"}
        ]
    })
    assert s == 200, f"Failed to add recipients: {add_res}"

    # Create bulk campaign excluding email3
    future_time_bulk = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1, hours=2)).strftime("%Y-%m-%d %H:%M")
    bulk_payload = {
        "campaign_name": f"Audience Exclusion Test {int(time.time())}",
        "from_alias": "Verification Tester",
        "sender": valid_sender,
        "recipients": [email1, email2, email3],
        "excluded_recipients": [email3], # email3 excluded
        "template_id": tpl_id,
        "tag_name": tag_name,
        "region": "singapore",
        "scheduled_at": future_time_bulk,
        "timezone_name": "Asia/Singapore"
    }
    s, bulk_res = post("/api/send-bulk", bulk_payload)
    assert s == 200, f"Bulk campaign failed: {bulk_res}"
    camp_id = bulk_res["campaign_id"]
    assert bulk_res["recipient_count"] == 2, f"Expected 2 recipients, got {bulk_res['recipient_count']}"
    print(f"  ✓ Bulk campaign created with 2 recipients (1 excluded): campaign_id={camp_id}")

    # VERIFY NON-DELETION GUARANTEE: Check that email3 STILL exists in master recipients
    s, all_recips = get("/api/recipients")
    all_emails = [r["email"] for r in all_recips["recipients"]]
    assert email3 in all_emails, "CRITICAL ERROR: Excluded recipient was deleted from master recipients!"
    print(f"  ✓ Non-deletion guarantee verified: recipient '{email3}' is safely preserved in master pool")

    # 5. In-Workflow Direct Scheduling & Scheduled Campaigns List
    print("\n[5] Testing In-Workflow Direct Scheduling & Scheduled Campaigns List...")
    s, sched_camps = get("/api/scheduled-campaigns")
    assert s == 200
    assert "scheduled_campaigns" in sched_camps
    items = sched_camps["scheduled_campaigns"]["items"]
    found_camp = next((c for c in items if c["id"] == camp_id), None)
    assert found_camp is not None, f"Campaign {camp_id} not found in scheduled campaigns"
    assert found_camp["tag_name"] == tag_name
    assert found_camp["timezone_name"] == "Asia/Singapore"
    assert found_camp["total_recipients"] == 2
    assert found_camp["template_name"] == tpl_name
    assert found_camp["status"] == "scheduled"
    print(f"  ✓ Scheduled campaign found with full metadata: Name='{found_camp['campaign_name']}', Tag='{found_camp['tag_name']}', Template='{found_camp['template_name']}', Timezone='{found_camp['timezone_name']}'")

    # 6. Authoritative Delivery Metrics & Tag Filtering
    print("\n[6] Testing Authoritative Delivery Stats with Open/Click Rates & Tag Filter...")
    s, stats = get("/api/delivery-stats/singapore")
    assert s == 200
    metrics = stats.get("metrics") or stats
    required_metric_keys = [
        "total_sent", "total_delivered", "delivery_rate", "failure_rate",
        "open_rate", "unique_open_rate", "open_count", "unique_open_count",
        "click_rate", "unique_click_rate", "click_count", "unique_click_count"
    ]
    for key in required_metric_keys:
        assert key in metrics, f"Missing metric key '{key}' in delivery-stats metrics: {metrics}"
    print(f"  ✓ All 8+ authoritative metrics present: Open Rate={metrics['open_rate']}%, Click Rate={metrics['click_rate']}%, Delivery Rate={metrics['delivery_rate']}%")

    # Test filtering stats by tag
    s, filtered_stats = get(f"/api/delivery-stats/singapore?tag_name={urllib.parse.quote(tag_name)}")
    assert s == 200
    assert "metrics" in filtered_stats
    print(f"  ✓ Tag-filtered delivery stats endpoint verified for tag '{tag_name}'")

    # 7. Interactive Delivery Drill-Down Modal Records API
    print("\n[7] Testing Interactive Delivery Drill-Down Modal Records API...")
    s, drilldown = get("/api/delivery/records/singapore?limit=10&offset=0")
    assert s == 200
    assert "records" in drilldown
    assert "total" in drilldown
    print(f"  ✓ Drill-down records returned (total: {drilldown['total']}, count: {len(drilldown['records'])})")

    # Test status filtering in drilldown
    s, delivered_records = get("/api/delivery/records/singapore?status=delivered")
    assert s == 200
    assert all(r["status"] in ("delivered", "sent") for r in delivered_records["records"])
    print(f"  ✓ Status filter 'delivered' verified ({len(delivered_records['records'])} records)")

    # 8. Filtered CSV Export
    print("\n[8] Testing Filtered CSV Export Endpoints...")
    export_statuses = ["all", "success", "failed", "invalid"]
    for status_filter in export_statuses:
        s, csv_content = get_text(f"/api/delivery/export-csv/singapore?status={status_filter}")
        assert s == 200, f"CSV export failed for status {status_filter}: {s}"
        lines = [l.strip() for l in csv_content.strip().split("\n") if l.strip()]
        assert len(lines) >= 1, "CSV export returned empty content"
        header = lines[0]
        expected_columns = [
            "Campaign", "Email Task", "Email Tag", "Recipient Name",
            "Email Address", "Template", "Provider Request ID", "Provider Env ID", "Status",
            "Send Time", "Delivery Time", "Open Count", "Click Count",
            "Failure Reason", "Bounce Reason", "Last Event"
        ]
        for col in expected_columns:
            assert col in header, f"Missing column '{col}' in CSV header: {header}"
        print(f"  ✓ CSV Export status='{status_filter}' verified: {len(lines)} lines returned with required columns")

    # 9. Clean up tag
    print("\n[9] Cleaning up test tag...")
    s, del_res = delete(f"/api/tags/{tag_id}")
    assert s == 200
    print(f"  ✓ Test tag {tag_id} deleted successfully")

    print("\n" + "=" * 70)
    print("ALL VERIFICATION SUITE TESTS PASSED SUCCESSFULLY! (100% SUCCESS)")
    print("=" * 70)

if __name__ == "__main__":
    main()
