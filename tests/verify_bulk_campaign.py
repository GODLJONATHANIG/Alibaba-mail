import requests
import time

def test_bulk_campaign():
    csv_data = """Name,Email
Alice,alice@example.com
Bob,bob@example.com
Invalid,not_an_email
AliceDuplicate,alice@example.com
Charlie,charlie@example.com
David,david@example.com
"""
    # 1. Test validation endpoint
    val_res = requests.post('http://127.0.0.1:8000/api/validate-recipients', json={'csv_content': csv_data})
    report = val_res.json()
    print('Validation Report:', report)
    assert len(report['valid']) == 4, f"Expected 4 valid, got {len(report['valid'])}"
    assert len(report['invalid']) == 1, f"Expected 1 invalid, got {len(report['invalid'])}"
    assert len(report['duplicates']) == 1, f"Expected 1 duplicate, got {len(report['duplicates'])}"

    # 2. Test bulk dispatch
    bulk_res = requests.post('http://127.0.0.1:8000/api/send-bulk', json={
        'campaign_name': 'Automated Test Campaign',
        'region': 'united_states',
        'sender': 'notifications-us@directmail.example.com',
        'recipients': report['valid'],
        'subject': 'Bulk Test Subject',
        'text_body': 'Hello all from US region'
    })
    camp_data = bulk_res.json()
    print('Bulk Campaign Response:', camp_data)
    assert camp_data['success'] is True
    camp_id = camp_data['campaign_id']

    # Wait 3 seconds for the rate-limited worker to finish the 4 jobs
    time.sleep(3)

    # Check jobs for this campaign
    jobs_res = requests.get(f'http://127.0.0.1:8000/api/jobs?limit=10')
    jobs = jobs_res.json()['items']
    camp_jobs = [j for j in jobs if j.get('campaign_id') == camp_id]
    print(f"Found {len(camp_jobs)} jobs for campaign {camp_id}")
    for j in camp_jobs:
        print(f" - Recipient: {j['recipient']}, Status: {j['status']}, RequestId: {j.get('api_request_id')}")
        assert j['status'] == 'sent', f"Job {j['id']} not sent"

    print("SUCCESS: Bulk campaign parsed, validated, rate-limited, and sent successfully!")

if __name__ == '__main__':
    test_bulk_campaign()
