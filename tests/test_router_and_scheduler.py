"""
Unit tests for Region Router, job state transitions, retries, and scheduler execution.
"""
import unittest
import uuid
from datetime import datetime, timedelta, timezone

from backend.database import (
    init_db,
    create_job,
    get_job,
    update_job_status,
    get_due_scheduled_jobs
)
from backend.router import router_instance

class TestRouterAndScheduler(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        init_db()

    def test_single_send_in_test_mode(self):
        job_id = f"test_job_{uuid.uuid4().hex[:8]}"
        create_job({
            "id": job_id,
            "region": "singapore",
            "sender": "notifications-sg@directmail.example.com",
            "recipient": "recipient1@example.com",
            "subject": "Test Single Send",
            "text_body": "This is a test email.",
            "status": "queued"
        })

        res = router_instance.execute_job(job_id)
        self.assertTrue(res["success"])
        self.assertEqual(res["status"], "sent")
        self.assertTrue(res["test_mode"])
        self.assertIsNotNone(res["request_id"])

        # Check in DB
        db_job = get_job(job_id)
        self.assertEqual(db_job["status"], "sent")
        self.assertIsNotNone(db_job["sent_at"])
        self.assertIsNotNone(db_job["api_request_id"])

    def test_idempotent_execution(self):
        job_id = f"test_idem_{uuid.uuid4().hex[:8]}"
        create_job({
            "id": job_id,
            "region": "germany",
            "sender": "notifications-de@directmail.example.com",
            "recipient": "recipient2@example.com",
            "subject": "Test Idempotent",
            "text_body": "Idempotency test.",
            "status": "queued"
        })

        res1 = router_instance.execute_job(job_id)
        self.assertTrue(res1["success"])
        
        # Second call must not re-send
        res2 = router_instance.execute_job(job_id)
        self.assertTrue(res2.get("already_sent"))

    def test_simulated_retry_backoff(self):
        job_id = f"test_retry_{uuid.uuid4().hex[:8]}"
        create_job({
            "id": job_id,
            "region": "united_states",
            "sender": "notifications-us@directmail.example.com",
            "recipient": "retry@example.com",
            "subject": "Subject with [SIMULATE_RETRY] tag",
            "text_body": "Testing retry.",
            "status": "queued",
            "max_attempts": 3
        })

        # First attempt -> triggers retryable failure
        res = router_instance.execute_job(job_id)
        self.assertFalse(res["success"])
        self.assertEqual(res["status"], "retrying")

        job_state = get_job(job_id)
        self.assertEqual(job_state["status"], "retrying")
        self.assertEqual(job_state["attempts"], 1)
        self.assertIsNotNone(job_state["next_retry_at"])

    def test_due_scheduled_jobs_polling(self):
        # Create a past due job
        past_due_job_id = f"due_{uuid.uuid4().hex[:8]}"
        past_time = (datetime.now(timezone.utc) - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        create_job({
            "id": past_due_job_id,
            "region": "singapore",
            "sender": "notifications-sg@directmail.example.com",
            "recipient": "due@example.com",
            "subject": "Due Scheduled Job",
            "status": "scheduled",
            "scheduled_at": past_time
        })

        due = get_due_scheduled_jobs()
        due_ids = [j["id"] for j in due]
        self.assertIn(past_due_job_id, due_ids)

if __name__ == "__main__":
    unittest.main()
