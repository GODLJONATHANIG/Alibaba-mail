import requests
import time
from datetime import datetime, timedelta, timezone

def test_live_scheduling():
    now = datetime.now(timezone.utc) + timedelta(seconds=15)
    future_str = now.strftime('%Y-%m-%d %H:%M:%S')
    print('Scheduling email for execution at:', future_str, 'UTC')

    res = requests.post('http://127.0.0.1:8000/api/send', json={
        'region': 'singapore',
        'sender': 'notifications-sg@directmail.example.com',
        'recipient': 'autonomous@example.com',
        'subject': 'Autonomous Scheduled Email Verification',
        'text_body': 'Testing background execution without browser',
        'scheduled_at': future_str,
        'timezone_name': 'UTC'
    })
    job_data = res.json()
    job_id = job_data['job_id']
    print(f"Created scheduled job: {job_id}, Initial Status: {job_data.get('status')}")

    print('Waiting 20 seconds for independent backend worker...')
    time.sleep(20)

    check_res = requests.get(f'http://127.0.0.1:8000/api/jobs/{job_id}')
    final_job = check_res.json()
    print(f"Final Job Status: {final_job['status']}, Sent At: {final_job.get('sent_at')}, RequestId: {final_job.get('api_request_id')}")
    assert final_job['status'] == 'sent', f"Expected sent, got {final_job['status']}"
    print("SUCCESS: Background worker picked up and dispatched scheduled email autonomously!")

if __name__ == '__main__':
    test_live_scheduling()
