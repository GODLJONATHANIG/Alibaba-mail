"""
Bulk Email Processor.
Handles bulk campaign creation, batching, rate-limiting, and concurrent dispatch.
"""
import uuid
import time
import threading
import logging
from typing import List, Dict, Any, Optional

from backend.database import (
    create_campaign,
    create_job,
    update_campaign_stats,
    get_setting,
    utc_now_iso,
    create_audit_log
)
from backend.router import router_instance
from backend.config import DEFAULT_RATE_LIMIT_QPS

logger = logging.getLogger("bulk_processor")

class BulkProcessor:
    """Processes bulk email campaigns safely with rate-limiting."""

    @staticmethod
    def create_and_dispatch_bulk(
        campaign_name: str,
        region: str,
        sender: str,
        recipients: List[str],
        subject: str,
        html_body: Optional[str] = None,
        text_body: Optional[str] = None,
        from_alias: Optional[str] = None,
        tag_name: Optional[str] = None,
        template_id: Optional[int] = None,
        address_type: int = 0,
        reply_to_address: bool = False,
        scheduled_at: Optional[str] = None,
        timezone_name: str = "Asia/Kolkata",
        excluded_recipients: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Create campaign and constituent email jobs.
        Supports task-level recipient exclusions without deleting from master pool.
        If scheduled_at is provided, jobs are marked 'scheduled' for the background scheduler.
        If immediate, a background worker dispatches them subject to rate-limiting.
        """
        campaign_id = f"camp_{uuid.uuid4().hex[:10]}"
        is_scheduled = bool(scheduled_at)
        initial_status = "scheduled" if is_scheduled else "queued"

        # Filter out excluded recipients
        excluded_set = set(r.strip().lower() for r in (excluded_recipients or []))
        active_recipients = [r for r in recipients if r.strip().lower() not in excluded_set]

        # Create Campaign
        create_campaign({
            "id": campaign_id,
            "name": campaign_name or f"Campaign-{time.strftime('%Y%m%d-%H%M')}",
            "region": region,
            "sender": sender,
            "subject": subject,
            "total_recipients": len(active_recipients),
            "status": "scheduled" if is_scheduled else "running",
            "scheduled_at": scheduled_at,
            "tag_name": tag_name,
            "template_id": template_id,
            "timezone_name": timezone_name
        })

        # Record audit log with recipient counts
        create_audit_log(
            action="bulk_campaign_created",
            object_type="campaign",
            object_id=campaign_id,
            result="success",
            details=f"Campaign '{campaign_name or campaign_id}' created: {len(recipients)} selected, {len(excluded_set)} excluded, {len(active_recipients)} queued."
        )

        created_job_ids = []
        for r in active_recipients:
            job_id = f"job_{uuid.uuid4().hex[:12]}"
            create_job({
                "id": job_id,
                "campaign_id": campaign_id,
                "region": region,
                "sender": sender,
                "recipient": r,
                "subject": subject,
                "html_body": html_body,
                "text_body": text_body,
                "from_alias": from_alias,
                "tag_name": tag_name,
                "template_id": template_id,
                "address_type": address_type,
                "reply_to_address": "true" if reply_to_address else "false",
                "send_type": "bulk",
                "status": initial_status,
                "scheduled_at": scheduled_at,
                "timezone_name": timezone_name
            })
            created_job_ids.append(job_id)

        # If immediate send, spawn worker thread with rate-limiting
        if not is_scheduled and created_job_ids:
            threading.Thread(
                target=BulkProcessor._run_bulk_worker,
                args=(campaign_id, created_job_ids),
                daemon=True,
                name=f"BulkWorker-{campaign_id}"
            ).start()

        return {
            "campaign_id": campaign_id,
            "total_selected": len(recipients),
            "excluded_count": len(excluded_set),
            "total_recipients": len(active_recipients),
            "recipient_count": len(active_recipients),
            "scheduled": is_scheduled,
            "scheduled_at": scheduled_at,
            "status": initial_status
        }

    @staticmethod
    def _run_bulk_worker(campaign_id: str, job_ids: List[str]):
        """Dispatches bulk jobs sequentially or in batches according to QPS limits."""
        qps_str = get_setting("rate_limit_qps", str(DEFAULT_RATE_LIMIT_QPS))
        try:
            qps = float(qps_str)
            delay = 1.0 / max(0.1, qps)
        except Exception:
            delay = 0.2  # default 5 QPS

        logger.info(f"[BulkWorker] Starting campaign {campaign_id} ({len(job_ids)} jobs, rate limit delay: {delay:.2f}s)")

        for j_id in job_ids:
            try:
                res = router_instance.execute_job(j_id)
                if res.get("success"):
                    update_campaign_stats(campaign_id, sent_inc=1)
                elif res.get("status") == "failed":
                    update_campaign_stats(campaign_id, failed_inc=1)
            except Exception as e:
                logger.error(f"[BulkWorker Error] Job {j_id}: {str(e)}")
                update_campaign_stats(campaign_id, failed_inc=1)

            time.sleep(delay)

        update_campaign_stats(campaign_id, status="completed")
        logger.info(f"[BulkWorker] Finished campaign {campaign_id}")
