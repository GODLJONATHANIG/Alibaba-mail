"""
Region Router layer for Alibaba Cloud DirectMail.
Routes requests to the strictly isolated regional client and updates database state.
"""
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from backend.config import get_region_config, canonicalize_region, is_test_mode
from backend.directmail import DirectMailClient
from backend.database import (
    update_job_status,
    get_job,
    get_setting,
    utc_now_iso
)

logger = logging.getLogger("router")

class RegionRouter:
    """Routes email execution requests to region-specific DirectMail clients."""

    def __init__(self):
        self._clients: Dict[str, DirectMailClient] = {}

    def get_client(self, region_key: str) -> DirectMailClient:
        """Get or create DirectMailClient for the canonical region."""
        canonical = canonicalize_region(region_key)
        if not canonical:
            raise ValueError(f"Invalid region specified: {region_key}")
        
        if canonical not in self._clients:
            self._clients[canonical] = DirectMailClient(canonical)
        return self._clients[canonical]

    def execute_job(self, job_id: str) -> Dict[str, Any]:
        """
        Execute an email job with regional isolation and safety tracking.
        Guarantees idempotency (will not re-send already 'sent' jobs).
        """
        job = get_job(job_id)
        if not job:
            return {"success": False, "error": f"Job {job_id} not found."}

        # Idempotency check
        if job["status"] == "sent":
            logger.info(f"Job {job_id} already marked 'sent'. Skipping duplicate execution.")
            return {
                "success": True,
                "already_sent": True,
                "job_id": job_id,
                "request_id": job.get("api_request_id")
            }

        region_key = job["region"]
        client = self.get_client(region_key)

        # Determine if test mode is active
        db_test_mode = get_setting("test_mode", "true").lower() in ("true", "1", "yes")
        env_test_mode = is_test_mode()
        force_test_mode = db_test_mode or env_test_mode or not client.has_valid_credentials()

        # Update status to sending & record attempt
        attempt_num = job.get("attempts", 0) + 1
        now_utc = utc_now_iso()
        update_job_status(
            job_id,
            status="sending",
            attempts=attempt_num,
            last_attempt_at=now_utc
        )

        # Call Alibaba Cloud DirectMail
        result = client.send_single_mail(
            sender=job["sender"],
            recipient=job["recipient"],
            subject=job["subject"],
            html_body=job.get("html_body"),
            text_body=job.get("text_body"),
            from_alias=job.get("from_alias"),
            tag_name=job.get("tag_name"),
            address_type=job.get("address_type", 0),
            reply_to_address=(job.get("reply_to_address") == "true"),
            force_test_mode=force_test_mode,
            attempt=attempt_num
        )

        if result["success"]:
            update_job_status(
                job_id,
                status="sent",
                sent_at=utc_now_iso(),
                api_request_id=result.get("request_id"),
                api_env_id=result.get("env_id"),
                api_response_raw=result.get("raw_response"),
                error_code=None,
                error_message=None
            )
            return {
                "success": True,
                "job_id": job_id,
                "region": region_key,
                "status": "sent",
                "request_id": result.get("request_id"),
                "env_id": result.get("env_id"),
                "test_mode": force_test_mode
            }
        else:
            # Handle failure
            is_retryable = result.get("is_retryable", False)
            max_attempts = job.get("max_attempts", 3)

            if is_retryable and attempt_num < max_attempts:
                # Schedule retry with exponential backoff: 5s, 20s, 60s
                backoff_seconds = 5 * (4 ** (attempt_num - 1))
                from datetime import timedelta
                next_retry = (datetime.now(timezone.utc) + timedelta(seconds=backoff_seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")
                update_job_status(
                    job_id,
                    status="retrying",
                    next_retry_at=next_retry,
                    error_code=result.get("error_code"),
                    error_message=result.get("error_message"),
                    api_request_id=result.get("request_id"),
                    api_response_raw=result.get("raw_response")
                )
                logger.info(f"Job {job_id} scheduled for retry #{attempt_num + 1} at {next_retry}")
            else:
                update_job_status(
                    job_id,
                    status="failed",
                    error_code=result.get("error_code"),
                    error_message=result.get("error_message"),
                    api_request_id=result.get("request_id"),
                    api_response_raw=result.get("raw_response")
                )
                logger.warning(f"Job {job_id} marked 'failed' after {attempt_num} attempts: {result.get('error_message')}")

            return {
                "success": False,
                "job_id": job_id,
                "region": region_key,
                "status": "retrying" if (is_retryable and attempt_num < max_attempts) else "failed",
                "error_code": result.get("error_code"),
                "error_message": result.get("error_message"),
                "request_id": result.get("request_id"),
                "is_retryable": is_retryable,
                "test_mode": force_test_mode
            }

# Global Router Instance
router_instance = RegionRouter()
