"""
API Integration tests for FastAPI endpoints: regions, sending, scheduling, validation, and history.
"""
import unittest
import json
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from fastapi.testclient import TestClient

from backend.main import app
from backend.database import init_db

class TestApiEndpoints(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        init_db()
        cls.client = TestClient(app)

    def test_health_check(self):
        resp = self.client.get("/api/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "healthy")
        self.assertIn("scheduler_running", data)
        self.assertIn("test_mode", data)

    def test_get_regions(self):
        resp = self.client.get("/api/regions")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("regions", data)
        region_keys = [r["key"] for r in data["regions"]]
        self.assertIn("singapore", region_keys)
        self.assertIn("germany", region_keys)
        self.assertIn("united_states", region_keys)
        # Ensure AccessKey Secret is never exposed
        for r in data["regions"]:
            self.assertNotIn("access_key_secret", r)
            self.assertNotIn("ALIBABA_SG_ACCESS_KEY_SECRET", r)

    def test_send_single_email_now(self):
        payload = {
            "region": "singapore",
            "sender": "notifications-sg@directmail.example.com",
            "recipient": "customer@example.com",
            "subject": "Order Confirmation #1001",
            "text_body": "Your order has been confirmed.",
            "html_body": "<p>Your order has been <strong>confirmed</strong>.</p>"
        }
        resp = self.client.post("/api/send", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["status"], "sent")
        self.assertIsNotNone(data["job_id"])
        self.assertIsNotNone(data["request_id"])

    def test_schedule_single_email(self):
        future_dt = (datetime.now(ZoneInfo("Asia/Kolkata")) + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M")
        payload = {
            "region": "germany",
            "sender": "notifications-de@directmail.example.com",
            "recipient": "berlin.user@example.de",
            "subject": "Scheduled Maintenance Notice",
            "text_body": "Maintenance will start at 2 AM.",
            "scheduled_at": future_dt,
            "timezone_name": "Asia/Kolkata"
        }
        resp = self.client.post("/api/send", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["status"], "scheduled")
        self.assertIsNotNone(data["scheduled_at_utc"])

    def test_invalid_sender_rejection(self):
        payload = {
            "region": "singapore",
            "sender": "unauthorized-fake@attacker.com",
            "recipient": "target@example.com",
            "subject": "Phishing attempt",
            "text_body": "Test."
        }
        resp = self.client.post("/api/send", json=payload)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("not configured as a verified sender", resp.json()["detail"])

    def test_validate_recipients_api(self):
        csv_sample = "Email,Name\nvalid1@test.com,One\nvalid2@test.com,Two\nbad-address,Three\nvalid1@test.com,OneDup"
        resp = self.client.post("/api/validate-recipients", json={"csv_content": csv_sample})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data["valid"]), 2)
        self.assertEqual(len(data["invalid"]), 1)
        self.assertEqual(len(data["duplicates"]), 1)

    def test_bulk_send_api(self):
        payload = {
            "campaign_name": "Product Launch Beta",
            "region": "united_states",
            "sender": "notifications-us@directmail.example.com",
            "recipients": ["user1@domain.com", "user2@domain.com"],
            "subject": "Welcome to Beta!",
            "text_body": "You are invited."
        }
        resp = self.client.post("/api/send-bulk", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["total_recipients"], 2)

    def test_get_jobs_history_and_filtering(self):
        resp = self.client.get("/api/jobs?region=singapore&limit=10")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("items", data)
        self.assertIn("total", data)

    def test_reschedule_and_cancel_job(self):
        # 1. Schedule a job
        future_dt = (datetime.now(ZoneInfo("Asia/Kolkata")) + timedelta(hours=3)).strftime("%Y-%m-%d %H:%M")
        send_resp = self.client.post("/api/send", json={
            "region": "singapore",
            "sender": "notifications-sg@directmail.example.com",
            "recipient": "reschedule.test@example.com",
            "subject": "Will be rescheduled",
            "text_body": "Body",
            "scheduled_at": future_dt,
            "timezone_name": "Asia/Kolkata"
        })
        job_id = send_resp.json()["job_id"]

        # 2. Reschedule
        new_future_dt = (datetime.now(ZoneInfo("Asia/Kolkata")) + timedelta(hours=4)).strftime("%Y-%m-%d %H:%M")
        resched_resp = self.client.post(f"/api/jobs/{job_id}/reschedule", json={
            "scheduled_at": new_future_dt,
            "timezone_name": "Asia/Kolkata"
        })
        self.assertEqual(resched_resp.status_code, 200)
        self.assertTrue(resched_resp.json()["success"])

        # 3. Cancel
        cancel_resp = self.client.post(f"/api/jobs/{job_id}/cancel")
        self.assertEqual(cancel_resp.status_code, 200)
        self.assertTrue(cancel_resp.json()["success"])

if __name__ == "__main__":
    unittest.main()
