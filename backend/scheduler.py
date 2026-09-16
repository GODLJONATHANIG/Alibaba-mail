"""
Independent Backend Scheduler and Worker.
Continuously processes scheduled emails and retries without relying on an open browser.
"""
import time
import threading
import logging
from typing import Optional

from backend.database import (
    get_due_scheduled_jobs,
    get_job,
    update_campaign_stats,
    utc_now_iso
)
from backend.router import router_instance

logger = logging.getLogger("scheduler")

class EmailScheduler:
    """Daemon scheduler polling persistent storage for due email jobs."""

    def __init__(self, poll_interval_seconds: float = 2.0):
        self.poll_interval = poll_interval_seconds
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self):
        """Start the background scheduler thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._worker_loop, daemon=True, name="DirectMailScheduler")
        self._thread.start()
        logger.info("[Scheduler] Independent background worker started.")

    def stop(self):
        """Stop the background scheduler thread."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        logger.info("[Scheduler] Background worker stopped.")

    def is_running(self) -> bool:
        """Check if scheduler thread is active."""
        return self._running and (self._thread.is_alive() if self._thread else False)

    def _worker_loop(self):
        """Main loop: periodically fetch due scheduled/retrying jobs and execute."""
        while self._running:
            try:
                due_jobs = get_due_scheduled_jobs(limit=10)
                for job in due_jobs:
                    job_id = job["id"]
                    logger.info(f"[Scheduler] Executing due job {job_id} (Type: {job.get('send_type', 'single')})")
                    res = router_instance.execute_job(job_id)
                    
                    # Update associated campaign if applicable
                    campaign_id = job.get("campaign_id")
                    if campaign_id:
                        if res.get("success"):
                            update_campaign_stats(campaign_id, sent_inc=1)
                        elif res.get("status") == "failed":
                            update_campaign_stats(campaign_id, failed_inc=1)

            except Exception as e:
                logger.error(f"[Scheduler Loop Error] {str(e)}", exc_info=True)

            time.sleep(self.poll_interval)

# Global Scheduler Instance
scheduler_instance = EmailScheduler()
