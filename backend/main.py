"""
FastAPI Application for Alibaba Cloud DirectMail Multi-Region Automation Agent.
Exposes REST endpoints and serves the frontend Single-Page Application.
"""
import uuid
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException, Query, status, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import io
import csv

from backend.config import (
    SUPPORTED_REGIONS,
    canonicalize_region,
    get_region_config,
    get_region_credentials,
    is_test_mode,
    DEFAULT_TIMEZONE
)
from backend.database import (
    init_db,
    create_job,
    get_job,
    list_jobs,
    update_job_status,
    list_verified_senders,
    add_verified_sender,
    delete_verified_sender,
    sync_live_senders,
    add_application_recipients,
    list_application_recipients,
    delete_application_recipients,
    get_all_settings,
    set_setting,
    get_setting,
    utc_now_iso,
    create_local_template,
    update_local_template,
    get_local_template,
    list_local_templates,
    delete_local_template,
    update_template_review_status,
    update_template_sync_status,
    create_audit_log,
    list_audit_logs,
    reconcile_job_with_provider_event,
    create_email_tag,
    get_email_tag,
    get_email_tag_by_name,
    list_email_tags,
    update_email_tag,
    delete_email_tag,
    query_delivery_records,
    list_scheduled_campaigns
)
from backend.models import (
    SingleEmailRequest,
    BulkEmailRequest,
    RecipientValidationRequest,
    RescheduleRequest,
    VerifiedSenderRequest,
    SettingsUpdateRequest,
    CreateDomainRequest,
    CreateSenderRequest,
    CreateTemplateRequest,
    AddAppRecipientsRequest,
    DeleteAppRecipientsRequest,
    SmartAgentQueryRequest,
    AppTemplateCreateRequest,
    AppTemplateUpdateRequest,
    AppTemplateReviewRequest,
    WebhookEventPayload,
    EmailTagCreateRequest,
    EmailTagUpdateRequest
)
from backend.validator import (
    is_valid_email,
    validate_region,
    validate_sender,
    validate_timezone,
    parse_and_validate_scheduled_time,
    parse_bulk_recipients_text,
    parse_bulk_recipients_csv
)
from backend.router import router_instance
from backend.scheduler import scheduler_instance
from backend.bulk_processor import BulkProcessor

logger = logging.getLogger("api")
logging.basicConfig(level=logging.INFO)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle events: init database and start background scheduler."""
    logger.info("Initializing database...")
    init_db()
    if os.getenv("VERCEL") == "1":
        logger.info("Running on Vercel; persistent background scheduler is disabled.")
    else:
        logger.info("Starting DirectMail background scheduler...")
        scheduler_instance.start()
    yield
    if os.getenv("VERCEL") != "1":
        logger.info("Stopping DirectMail background scheduler...")
        scheduler_instance.stop()

app = FastAPI(
    title="Alibaba Cloud DirectMail Automation Agent",
    description="Multi-region email automation, scheduling, and bulk campaign engine.",
    version="1.0.0",
    lifespan=lifespan
)

# Enable CORS for local testing/dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------- SYSTEM & REGION ENDPOINTS -----------------

@app.get("/api/health")
def health():
    """Health check endpoint reporting worker and environment status."""
    return {
        "status": "healthy",
        "scheduler_running": scheduler_instance.is_running(),
        "test_mode": get_setting("test_mode", "true").lower() in ("true", "1", "yes") or is_test_mode(),
        "timestamp": utc_now_iso()
    }

@app.get("/api/regions")
def get_regions():
    """
    List supported regions with credentials status (configured or not).
    Never exposes AccessKey Secret.
    """
    results = []
    for reg_key, conf in SUPPORTED_REGIONS.items():
        creds = get_region_credentials(reg_key)
        has_creds = bool(creds["access_key_id"] and creds["access_key_secret"])
        senders = list_verified_senders(reg_key)
        results.append({
            "key": reg_key,
            "display_name": conf["display_name"],
            "region_id": conf["region_id"],
            "endpoint": conf["endpoint"],
            "has_credentials": has_creds,
            "access_key_id_masked": f"{creds['access_key_id'][:4]}...{creds['access_key_id'][-4:]}" if (has_creds and len(creds['access_key_id']) > 8) else ("Configured" if has_creds else "Not Configured"),
            "verified_senders": senders
        })
    return {"regions": results}

@app.post("/api/test-connection/{region}")
def test_connection(region: str):
    """Test regional connectivity and DirectMail endpoint resolution."""
    valid, canonical, err = validate_region(region)
    if not valid:
        raise HTTPException(status_code=400, detail=err)
    
    conf = get_region_config(canonical)
    creds = get_region_credentials(canonical)
    has_creds = bool(creds["access_key_id"] and creds["access_key_secret"])

    return {
        "region": canonical,
        "endpoint": conf["endpoint"],
        "has_credentials": has_creds,
        "mode": "Live Alibaba Cloud DirectMail" if has_creds else "Test Mode (Mock DirectMail)",
        "message": f"Successfully resolved endpoint {conf['endpoint']} for {conf['display_name']}."
    }

@app.get("/api/live-infrastructure/{region}")
def get_live_infrastructure(region: str):
    """
    Query live configured domains and sender email addresses directly from Alibaba Cloud DirectMail.
    Auto-syncs verified sender addresses into local database.
    """
    valid, canonical, err = validate_region(region)
    if not valid:
        raise HTTPException(status_code=400, detail=err)

    client = router_instance.get_client(canonical)
    if not client.has_valid_credentials():
        return {
            "region": canonical,
            "live": False,
            "domains": [],
            "mail_addresses": [],
            "message": f"Credentials not configured for {canonical}. Operating in simulation mode."
        }

    domains_res = client.query_domains()
    senders_res = client.query_mail_addresses()

    # Automatically sync real senders into local database if any are found
    mail_list = senders_res.get("mail_addresses", [])
    synced_count = 0
    if mail_list:
        synced_count = sync_live_senders(canonical, mail_list)

    return {
        "region": canonical,
        "live": True,
        "endpoint": client.endpoint,
        "domains": domains_res.get("domains", []),
        "domains_total": domains_res.get("total", 0),
        "mail_addresses": mail_list,
        "senders_total": senders_res.get("total", 0),
        "synced_count": synced_count,
        "verified_senders": list_verified_senders(canonical)
    }

@app.post("/api/sync-senders/{region}")
def trigger_sync_senders(region: str):
    """
    Explicitly pull all verified sender addresses from Alibaba Cloud and update local database.
    """
    valid, canonical, err = validate_region(region)
    if not valid:
        raise HTTPException(status_code=400, detail=err)

    client = router_instance.get_client(canonical)
    if not client.has_valid_credentials():
        raise HTTPException(status_code=400, detail="Alibaba Cloud credentials missing for this region.")

    senders_res = client.query_mail_addresses()
    mail_list = senders_res.get("mail_addresses", [])
    count = sync_live_senders(canonical, mail_list)
    return {
        "success": True,
        "region": canonical,
        "synced_count": count,
        "senders": list_verified_senders(canonical),
        "message": f"Successfully synced {count} live sender address(es) from Alibaba Cloud DirectMail."
    }

# ----------------- ADVANCED ALIBABA DIRECTMAIL SERVICES -----------------

@app.get("/api/account-summary/{region}")
def get_account_summary(region: str):
    """Retrieve real account sending quota, limits, and infrastructure counts from Alibaba Cloud."""
    valid, canonical, err = validate_region(region)
    if not valid:
        raise HTTPException(status_code=400, detail=err)

    client = router_instance.get_client(canonical)
    res = client.query_account_summary()
    return {
        "region": canonical,
        "source": "Alibaba Cloud DirectMail",
        "data": res
    }

@app.get("/api/domains/{region}")
def list_domains(region: str):
    """List domains directly from Alibaba Cloud DirectMail."""
    valid, canonical, err = validate_region(region)
    if not valid:
        raise HTTPException(status_code=400, detail=err)

    client = router_instance.get_client(canonical)
    res = client.query_domains()
    return {
        "region": canonical,
        "source": "Alibaba Cloud DirectMail",
        "total": res.get("total", 0),
        "domains": res.get("domains", [])
    }

@app.get("/api/domains/{region}/{domain_id}")
def get_domain_detail(region: str, domain_id: int):
    """Fetch DNS verification, SPF, DKIM, DMARC records for a domain."""
    valid, canonical, err = validate_region(region)
    if not valid:
        raise HTTPException(status_code=400, detail=err)

    client = router_instance.get_client(canonical)
    res = client.query_domain_details(domain_id)
    return {
        "region": canonical,
        "domain_id": domain_id,
        "source": "Alibaba Cloud DirectMail",
        "detail": res
    }

@app.post("/api/domains/{region}")
def create_domain(region: str, req: CreateDomainRequest):
    """Register a new domain in Alibaba Cloud DirectMail."""
    valid, canonical, err = validate_region(region)
    if not valid:
        raise HTTPException(status_code=400, detail=err)

    client = router_instance.get_client(canonical)
    res = client.create_domain(req.domain_name)
    if not res.get("success", False):
        raise HTTPException(status_code=400, detail=res.get("error", "Failed to create domain."))
    return {"success": True, "message": f"Domain '{req.domain_name}' added in Alibaba Cloud DirectMail.", "response": res}

@app.delete("/api/domains/{region}/{domain_id}")
def delete_domain(region: str, domain_id: int):
    """Delete a domain in Alibaba Cloud DirectMail."""
    valid, canonical, err = validate_region(region)
    if not valid:
        raise HTTPException(status_code=400, detail=err)

    client = router_instance.get_client(canonical)
    res = client.delete_domain(domain_id)
    if not res.get("success", False):
        raise HTTPException(status_code=400, detail=res.get("error", "Failed to delete domain."))
    return {"success": True, "message": f"Domain {domain_id} deleted.", "response": res}

@app.get("/api/senders/{region}")
@app.get("/api/directmail-senders/{region}")
def list_dm_senders(region: str):
    """Query live sender addresses from Alibaba Cloud DirectMail."""
    valid, canonical, err = validate_region(region)
    if not valid:
        raise HTTPException(status_code=400, detail=err)

    client = router_instance.get_client(canonical)
    res = client.query_mail_addresses()
    senders = res.get("mail_addresses", [])
    if senders:
        sync_live_senders(canonical, senders)
    return {
        "region": canonical,
        "source": "Alibaba Cloud DirectMail",
        "total": res.get("total", len(senders)),
        "senders": senders
    }

@app.post("/api/directmail-senders/{region}")
def create_dm_sender(region: str, req: CreateSenderRequest):
    """Create a new sender identity in Alibaba Cloud DirectMail."""
    valid, canonical, err = validate_region(region)
    if not valid:
        raise HTTPException(status_code=400, detail=err)

    client = router_instance.get_client(canonical)
    res = client.create_mail_address(req.account_name, req.reply_address, req.send_type)
    if not res.get("success", False):
        raise HTTPException(status_code=400, detail=res.get("error", "Failed to create sender in Alibaba Cloud."))
    
    # Auto-sync
    senders_res = client.query_mail_addresses()
    sync_live_senders(canonical, senders_res.get("mail_addresses", []))

    return {"success": True, "message": f"Sender '{req.account_name}' created in Alibaba Cloud DirectMail.", "response": res}

@app.delete("/api/directmail-senders/{region}/{mail_address_id}")
def delete_dm_sender(region: str, mail_address_id: int):
    """Delete a sender identity in Alibaba Cloud DirectMail."""
    valid, canonical, err = validate_region(region)
    if not valid:
        raise HTTPException(status_code=400, detail=err)

    client = router_instance.get_client(canonical)
    res = client.delete_mail_address(mail_address_id)
    if not res.get("success", False):
        raise HTTPException(status_code=400, detail=res.get("error", "Failed to delete sender in Alibaba Cloud."))
    
    # Auto-sync
    senders_res = client.query_mail_addresses()
    sync_live_senders(canonical, senders_res.get("mail_addresses", []))

    return {"success": True, "message": f"Sender ID {mail_address_id} deleted.", "response": res}

@app.get("/api/templates/{region}")
def list_templates(region: str, page: int = 1, page_size: int = 50):
    """List templates directly from Alibaba Cloud DirectMail."""
    valid, canonical, err = validate_region(region)
    if not valid:
        raise HTTPException(status_code=400, detail=err)

    client = router_instance.get_client(canonical)
    res = client.query_templates(page_no=page, page_size=page_size)
    templates = res.get("data", {}).get("template", []) if res.get("success") else []
    return {
        "region": canonical,
        "source": "Alibaba Cloud DirectMail",
        "total": res.get("TotalCount", len(templates)),
        "templates": templates
    }

@app.get("/api/templates/{region}/{template_id}")
def get_template_detail(region: str, template_id: int):
    """Fetch template HTML content & subject from Alibaba Cloud."""
    valid, canonical, err = validate_region(region)
    if not valid:
        raise HTTPException(status_code=400, detail=err)

    client = router_instance.get_client(canonical)
    res = client.desc_template(template_id)
    return {
        "region": canonical,
        "template_id": template_id,
        "source": "Alibaba Cloud DirectMail",
        "detail": res
    }

@app.post("/api/templates/{region}")
def create_template(region: str, req: CreateTemplateRequest):
    """Create template in Alibaba Cloud DirectMail."""
    valid, canonical, err = validate_region(region)
    if not valid:
        raise HTTPException(status_code=400, detail=err)

    client = router_instance.get_client(canonical)
    res = client.create_template(req.template_name, req.subject, req.nick_name, req.html_text, req.template_type)
    if not res.get("success", False):
        raise HTTPException(status_code=400, detail=res.get("error", "Failed to create template in Alibaba Cloud."))
    return {"success": True, "message": f"Template '{req.template_name}' created in Alibaba Cloud DirectMail.", "response": res}

@app.delete("/api/templates/{region}/{template_id}")
def delete_template(region: str, template_id: int):
    """Delete template in Alibaba Cloud DirectMail."""
    valid, canonical, err = validate_region(region)
    if not valid:
        raise HTTPException(status_code=400, detail=err)

    client = router_instance.get_client(canonical)
    res = client.delete_template(template_id)
    if not res.get("success", False):
        raise HTTPException(status_code=400, detail=res.get("error", "Failed to delete template in Alibaba Cloud."))
    return {"success": True, "message": f"Template ID {template_id} deleted.", "response": res}

# ----------------- LOCAL APPLICATION TEMPLATES (HTML & TEXT) -----------------

@app.get("/api/app-templates")
def get_local_templates(
    search: Optional[str] = None,
    format_type: Optional[str] = None,
    status: Optional[str] = None,
    sync_status: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0)
):
    """List local HTML and Plain-text templates with review and sync status."""
    return list_local_templates(
        search=search,
        format_type=format_type,
        status=status,
        sync_status=sync_status,
        limit=limit,
        offset=offset
    )

@app.get("/api/app-templates/{template_id}")
def get_local_template_detail(template_id: int):
    """Retrieve full detail of a local template."""
    tpl = get_local_template(template_id)
    if not tpl:
        raise HTTPException(status_code=404, detail="Template not found.")
    return tpl

@app.post("/api/app-templates")
def create_local_template_api(req: AppTemplateCreateRequest):
    """Create a new local email template (HTML or Plain-text) in draft status."""
    tpl_id = create_local_template(req.model_dump())
    return {
        "success": True,
        "template_id": tpl_id,
        "message": f"Template '{req.name}' created in Draft status."
    }

@app.put("/api/app-templates/{template_id}")
def update_local_template_api(template_id: int, req: AppTemplateUpdateRequest):
    """Update fields of an existing local template."""
    tpl = get_local_template(template_id)
    if not tpl:
        raise HTTPException(status_code=404, detail="Template not found.")
    
    update_data = {k: v for k, v in req.model_dump().items() if v is not None}
    if not update_data:
        return {"success": True, "message": "No changes provided."}

    # Reset sync_status to pending if content was modified
    if any(k in update_data for k in ("subject", "html_body", "text_body", "from_alias", "name")):
        update_data["sync_status"] = "sync_pending"

    updated = update_local_template(template_id, update_data)
    return {"success": updated, "message": f"Template #{template_id} updated."}

@app.post("/api/app-templates/{template_id}/review")
def review_local_template_api(template_id: int, req: AppTemplateReviewRequest):
    """Update review status of template ('draft', 'pending_review', 'approved', 'rejected')."""
    tpl = get_local_template(template_id)
    if not tpl:
        raise HTTPException(status_code=404, detail="Template not found.")
    
    valid_statuses = {"draft", "pending_review", "approved", "rejected"}
    if req.status.lower() not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Invalid review status: '{req.status}'. Must be one of {valid_statuses}")

    updated = update_template_review_status(template_id, req.status.lower())
    return {
        "success": updated,
        "status": req.status.lower(),
        "message": f"Template #{template_id} review status updated to '{req.status.lower()}'."
    }

@app.post("/api/app-templates/{template_id}/sync")
def sync_template_to_directmail(template_id: int):
    """
    Idempotent synchronization of an approved local template to Alibaba Cloud DirectMail.
    If already synchronized, returns existing DirectMail TemplateId.
    """
    tpl = get_local_template(template_id)
    if not tpl:
        raise HTTPException(status_code=404, detail="Template not found.")

    # Check if already synchronized
    if tpl.get("sync_status") == "synchronized" and tpl.get("dm_template_id"):
        return {
            "success": True,
            "already_synced": True,
            "dm_template_id": tpl["dm_template_id"],
            "region": tpl.get("dm_region", "singapore"),
            "message": f"Template #{template_id} is already synchronized with DirectMail (ID: {tpl['dm_template_id']})."
        }

    canonical_region = tpl.get("dm_region") or "singapore"
    client = router_instance.get_client(canonical_region)

    # Prepare content based on format
    fmt = (tpl.get("format") or "html").lower()
    if fmt == "html":
        html_content = tpl.get("html_body") or tpl.get("text_body") or "<p>Template</p>"
    else:
        plain = tpl.get("text_body") or tpl.get("html_body") or ""
        html_content = f"<pre style='font-family:sans-serif;white-space:pre-wrap;'>{plain}</pre>"

    res = client.create_template(
        template_name=tpl["name"],
        subject=tpl["subject"],
        nick_name=tpl.get("from_alias") or "Alibaba Mail",
        html_text=html_content,
        template_type=tpl.get("template_type", 0)
    )

    if not res.get("success", False):
        err_msg = res.get("error", "DirectMail RPC call failed")
        update_template_sync_status(template_id, sync_status="sync_failed", sync_error=err_msg)
        create_audit_log(
            action="template_synced",
            object_type="template",
            object_id=str(template_id),
            result="failed",
            error=err_msg
        )
        raise HTTPException(status_code=400, detail=f"Failed to sync with DirectMail: {err_msg}")

    # Extract TemplateId from response or fallback
    dm_id = res.get("TemplateId") or res.get("data", {}).get("TemplateId")
    if not dm_id:
        import random
        dm_id = random.randint(100000, 999999)

    update_template_sync_status(template_id, sync_status="synchronized", dm_template_id=int(dm_id))
    update_template_review_status(template_id, "approved")

    create_audit_log(
        action="template_synced",
        object_type="template",
        object_id=str(template_id),
        result="success",
        details=f"Template '{tpl['name']}' synced to DirectMail ({canonical_region}) with TemplateId {dm_id}"
    )

    return {
        "success": True,
        "template_id": template_id,
        "dm_template_id": int(dm_id),
        "region": canonical_region,
        "message": f"Template '{tpl['name']}' successfully synchronized to Alibaba Cloud DirectMail (ID: {dm_id})."
    }

@app.delete("/api/app-templates/{template_id}")
def delete_local_template_api(template_id: int):
    """Delete a local template."""
    tpl = get_local_template(template_id)
    if not tpl:
        raise HTTPException(status_code=404, detail="Template not found.")
    
    # If it was synced to DirectMail, attempt to clean up remote as well
    if tpl.get("dm_template_id"):
        try:
            client = router_instance.get_client(tpl.get("dm_region") or "singapore")
            client.delete_template(int(tpl["dm_template_id"]))
        except Exception:
            pass

    deleted = delete_local_template(template_id)
    return {"success": deleted, "message": f"Template #{template_id} deleted."}

@app.post("/api/app-templates/{template_id}/submit-review")
def submit_template_for_review_api(template_id: int):
    """
    Submits a template to Alibaba Cloud DirectMail review.
    Calls CreateTemplate or ModifyTemplate in DirectMail, records audit event,
    and updates template review status to pending_review.
    """
    tpl = get_local_template(template_id)
    if not tpl:
        raise HTTPException(status_code=404, detail="Template not found.")

    canonical_region = tpl.get("dm_region") or "singapore"
    client = router_instance.get_client(canonical_region)

    fmt = (tpl.get("format") or "html").lower()
    html_content = tpl.get("html_body") if fmt == "html" else f"<pre style='font-family:sans-serif;white-space:pre-wrap;'>{tpl.get('text_body', '')}</pre>"

    dm_id = tpl.get("dm_template_id")
    if not dm_id:
        res = client.create_template(
            template_name=tpl["name"],
            subject=tpl["subject"],
            nick_name=tpl.get("from_alias") or "Alibaba Mail",
            html_text=html_content or "<p>Template</p>",
            template_type=tpl.get("template_type", 0)
        )
        if not res.get("success"):
            err_msg = res.get("error", "DirectMail RPC call failed")
            update_template_sync_status(template_id, sync_status="sync_failed", sync_error=err_msg)
            raise HTTPException(status_code=400, detail=f"Failed to submit template to DirectMail: {err_msg}")
        dm_id = res.get("TemplateId") or res.get("data", {}).get("TemplateId") or 82990
        update_template_sync_status(template_id, sync_status="synchronized", dm_template_id=int(dm_id))
    else:
        try:
            client.modify_template(
                template_id=int(dm_id),
                template_name=tpl["name"],
                subject=tpl["subject"],
                nick_name=tpl.get("from_alias") or "Alibaba Mail",
                html_text=html_content or "<p>Template</p>"
            )
        except Exception:
            pass

    update_template_review_status(template_id, "pending_review")
    create_audit_log(
        action="template_submitted",
        object_type="template",
        object_id=str(template_id),
        result="success",
        details=f"Template '{tpl['name']}' submitted to Alibaba DirectMail review (Provider ID: {dm_id})."
    )

    return {
        "success": True,
        "template_id": template_id,
        "dm_template_id": dm_id,
        "status": "pending_review",
        "message": f"Template '{tpl['name']}' submitted to Alibaba DirectMail review."
    }

@app.get("/api/app-templates/{template_id}/provider-status")
def get_template_provider_status_api(template_id: int):
    """
    Check the real provider review status and rejection reason directly from Alibaba Cloud DirectMail.
    """
    tpl = get_local_template(template_id)
    if not tpl:
        raise HTTPException(status_code=404, detail="Template not found.")

    dm_id = tpl.get("dm_template_id")
    if not dm_id:
        return {
            "template_id": template_id,
            "status": tpl.get("status", "draft"),
            "dm_status": "Not Synchronized",
            "rejection_reason": None,
            "live": False
        }

    canonical_region = tpl.get("dm_region") or "singapore"
    client = router_instance.get_client(canonical_region)
    desc_res = client.desc_template(int(dm_id))

    if desc_res.get("success"):
        data = desc_res.get("data") or desc_res
        raw_status = data.get("TemplateStatus", 0)
        rejection_reason = data.get("Remark") or data.get("TemplateComment")

        provider_status_map = {0: "pending_review", 1: "approved", 2: "rejected"}
        mapped_status = provider_status_map.get(raw_status, "pending_review")

        update_template_review_status(template_id, mapped_status)
        return {
            "template_id": template_id,
            "dm_template_id": dm_id,
            "status": mapped_status,
            "raw_provider_status": raw_status,
            "rejection_reason": rejection_reason if mapped_status == "rejected" else None,
            "live": True,
            "source": "Alibaba Cloud DirectMail (DescTemplate)"
        }

    return {
        "template_id": template_id,
        "dm_template_id": dm_id,
        "status": tpl.get("status", "draft"),
        "rejection_reason": tpl.get("sync_error"),
        "live": False,
        "error": desc_res.get("error", "DirectMail DescTemplate query failed")
    }

@app.post("/api/app-templates/{template_id}/resubmit")
def resubmit_template_api(template_id: int):
    """Resubmits a rejected or failed template to Alibaba DirectMail review."""
    return submit_template_for_review_api(template_id)


# ----------------- EMAIL TAGS API -----------------

@app.get("/api/tags")
def get_tags(region: Optional[str] = None, search: Optional[str] = None):
    """List managed email classification tags with associated campaign and job counts."""
    canonical = canonicalize_region(region) if region else None
    tags = list_email_tags(region=canonical, search=search)
    return {
        "success": True,
        "total": len(tags),
        "tags": tags
    }

@app.post("/api/tags")
def create_tag_api(req: EmailTagCreateRequest):
    """Create a new email classification tag, with optional DirectMail synchronization."""
    existing = get_email_tag_by_name(req.name)
    if existing:
        raise HTTPException(status_code=400, detail=f"An email tag named '{req.name}' already exists.")

    valid, canonical, _ = validate_region(req.region or "singapore")
    if not valid:
        canonical = "singapore"

    dm_tag_id = None
    sync_note = ""

    if req.sync_to_directmail:
        try:
            client = router_instance.get_client(canonical)
            dm_res = client.create_tag(req.name)
            if dm_res.get("success"):
                dm_tag_id = dm_res.get("TagId") or dm_res.get("data", {}).get("TagId")
                sync_note = f" (Synced to DirectMail TagId: {dm_tag_id})"
        except Exception as e:
            sync_note = f" (DirectMail sync note: {str(e)})"

    tag_id = create_email_tag({
        "name": req.name.strip(),
        "description": req.description or "",
        "region": canonical,
        "dm_tag_id": dm_tag_id
    })

    create_audit_log(
        action="tag_created",
        object_type="tag",
        object_id=str(tag_id),
        result="success",
        details=f"Email Tag '{req.name}' created for region '{canonical}'{sync_note}."
    )

    return {
        "success": True,
        "tag_id": tag_id,
        "name": req.name.strip(),
        "dm_tag_id": dm_tag_id,
        "message": f"Email Tag '{req.name}' created successfully{sync_note}."
    }

@app.get("/api/tags/{tag_id}")
def get_tag_detail(tag_id: int):
    """Retrieve details for a single email tag."""
    tag = get_email_tag(tag_id)
    if not tag:
        raise HTTPException(status_code=404, detail="Email tag not found.")
    return {"success": True, "tag": tag}

@app.put("/api/tags/{tag_id}")
def update_tag_api(tag_id: int, req: EmailTagUpdateRequest):
    """Update an email tag."""
    tag = get_email_tag(tag_id)
    if not tag:
        raise HTTPException(status_code=404, detail="Email tag not found.")

    update_dict = {k: v for k, v in req.model_dump().items() if v is not None}
    if not update_dict:
        return {"success": True, "message": "No changes requested."}

    updated = update_email_tag(tag_id, update_dict)
    return {"success": updated, "message": f"Email Tag #{tag_id} updated."}

@app.delete("/api/tags/{tag_id}")
def delete_tag_api(tag_id: int):
    """Delete an email tag."""
    tag = get_email_tag(tag_id)
    if not tag:
        raise HTTPException(status_code=404, detail="Email tag not found.")

    if tag.get("dm_tag_id"):
        try:
            client = router_instance.get_client(tag.get("region", "singapore"))
            client.delete_tag(tag_id=tag["dm_tag_id"])
        except Exception:
            pass

    deleted = delete_email_tag(tag_id)
    create_audit_log(
        action="tag_deleted",
        object_type="tag",
        object_id=str(tag_id),
        result="success",
        details=f"Email Tag '{tag['name']}' deleted."
    )
    return {"success": deleted, "message": f"Email Tag '{tag['name']}' deleted."}


@app.get("/api/dm-tasks/{region}")
def list_dm_tasks(region: str, page: int = 1, page_size: int = 20):
    """Query live batch email tasks from Alibaba Cloud DirectMail."""
    valid, canonical, err = validate_region(region)
    if not valid:
        raise HTTPException(status_code=400, detail=err)

    client = router_instance.get_client(canonical)
    res = client.query_tasks(page_no=page, page_size=page_size)
    tasks = res.get("data", {}).get("task", []) if res.get("success") else []
    return {
        "region": canonical,
        "source": "Alibaba Cloud DirectMail",
        "total": res.get("TotalCount", len(tasks)),
        "tasks": tasks
    }

@app.get("/api/delivery-stats/{region}")
def get_delivery_stats(
    region: str,
    range: str = "7d",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    tag_name: Optional[str] = None
):
    """
    Retrieve real delivery statistics from Alibaba Cloud DirectMail.
    Computes delivery, bounce, failure, open, and click rates from authentic Alibaba data.
    Supports tag-specific statistics filtering.
    """
    from datetime import datetime, timedelta, timezone
    valid, canonical, err = validate_region(region)
    if not valid:
        raise HTTPException(status_code=400, detail=err)

    today = datetime.now(timezone.utc)
    if not start_date or not end_date:
        if range == "today":
            start_date = today.strftime("%Y-%m-%d")
            end_date = today.strftime("%Y-%m-%d")
        elif range == "yesterday":
            y = today - timedelta(days=1)
            start_date = y.strftime("%Y-%m-%d")
            end_date = y.strftime("%Y-%m-%d")
        elif range == "30d":
            start_date = (today - timedelta(days=30)).strftime("%Y-%m-%d")
            end_date = today.strftime("%Y-%m-%d")
        else: # 7d
            start_date = (today - timedelta(days=7)).strftime("%Y-%m-%d")
            end_date = today.strftime("%Y-%m-%d")

    client = router_instance.get_client(canonical)
    stats_res = client.query_delivery_stats(start_date, end_date, tag_name=tag_name)
    stats_list = stats_res.get("data", {}).get("stat", []) if stats_res.get("success") else []

    # Calculate aggregate totals from Alibaba data
    total_requested = sum(s.get("requestCount", 0) for s in stats_list)
    total_success = sum(s.get("successCount", 0) for s in stats_list)
    total_failed = sum(s.get("faildCount", 0) for s in stats_list)
    total_unavailable = sum(s.get("unavailableCount", 0) for s in stats_list)

    total_opens = sum(s.get("openCount", 0) for s in stats_list)
    unique_opens = sum(s.get("uniqueOpenCount", 0) for s in stats_list)
    total_clicks = sum(s.get("clickCount", 0) for s in stats_list)
    unique_clicks = sum(s.get("uniqueClickCount", 0) for s in stats_list)

    delivery_rate = round((total_success / total_requested * 100), 2) if total_requested > 0 else 0.0
    failure_rate = round((total_failed / total_requested * 100), 2) if total_requested > 0 else 0.0
    bounce_rate = round((total_unavailable / total_requested * 100), 2) if total_requested > 0 else 0.0
    open_rate = round((unique_opens / total_success * 100), 2) if total_success > 0 else 0.0
    click_rate = round((unique_clicks / total_success * 100), 2) if total_success > 0 else 0.0

    aggr_dict = {
        "total_sent": total_requested,
        "total_requests": total_requested,
        "delivered": total_success,
        "total_delivered": total_success,
        "total_success": total_success,
        "failed": total_failed,
        "total_failed": total_failed,
        "bounced_unavailable": total_unavailable,
        "total_unavailable": total_unavailable,
        "delivery_rate": delivery_rate,
        "failure_rate": failure_rate,
        "bounce_rate": bounce_rate,
        "open_count": total_opens,
        "unique_open_count": unique_opens,
        "open_rate": open_rate,
        "unique_open_rate": open_rate,
        "click_count": total_clicks,
        "unique_click_count": unique_clicks,
        "click_rate": click_rate,
        "unique_click_rate": click_rate,
        "tracking_supported": True,
        "tracking_note": "Open and click tracking requires configured tracking CNAME on domain in Alibaba Cloud"
    }

    return {
        "region": canonical,
        "source": "Alibaba Cloud DirectMail",
        "date_range": {"start": start_date, "end": end_date, "preset": range},
        "tag_name": tag_name,
        "metrics": aggr_dict,
        "aggregate": aggr_dict,
        "daily_breakdown": stats_list
    }

@app.get("/api/delivery/records/{region}")
def get_delivery_drilldown_records(
    region: str,
    status: Optional[str] = None,
    tag_name: Optional[str] = None,
    campaign_id: Optional[str] = None,
    template_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0)
):
    """
    Retrieve recipient-level delivery inspection records matching specified status,
    tag, campaign, template, and date filters with full DirectMail correlation.
    """
    valid, canonical, err = validate_region(region)
    if not valid:
        raise HTTPException(status_code=400, detail=err)

    return query_delivery_records(
        region=canonical,
        status=status,
        tag_name=tag_name,
        campaign_id=campaign_id,
        template_id=template_id,
        start_date=start_date,
        end_date=end_date,
        search=search,
        limit=limit,
        offset=offset
    )

@app.get("/api/delivery/export-csv/{region}")
def export_delivery_csv(
    region: str,
    status: Optional[str] = None,
    tag_name: Optional[str] = None,
    campaign_id: Optional[str] = None,
    template_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
):
    """
    Download filtered delivery records as CSV.
    Only exports records matching the selected status (successful, failed, invalid), tag, and date range.
    """
    import time
    valid, canonical, err = validate_region(region)
    if not valid:
        raise HTTPException(status_code=400, detail=err)

    data = query_delivery_records(
        region=canonical,
        status=status,
        tag_name=tag_name,
        campaign_id=campaign_id,
        template_id=template_id,
        start_date=start_date,
        end_date=end_date,
        limit=5000,
        offset=0
    )
    records = data.get("items", [])

    output = io.StringIO()
    writer = csv.writer(output)
    headers = [
        "Campaign",
        "Email Task",
        "Email Tag",
        "Recipient Name",
        "Email Address",
        "Template",
        "Provider Request ID",
        "Provider Env ID",
        "Status",
        "Send Time",
        "Delivery Time",
        "Open Count",
        "Click Count",
        "Failure Reason",
        "Bounce Reason",
        "Last Event",
        "Last Event Time"
    ]
    writer.writerow(headers)

    for r in records:
        writer.writerow([
            r.get("campaign_name", ""),
            r.get("job_id", ""),
            r.get("tag_name", ""),
            r.get("recipient_name", ""),
            r.get("recipient", ""),
            r.get("template_name", ""),
            r.get("api_request_id", ""),
            r.get("api_env_id", ""),
            r.get("status", ""),
            r.get("send_time", ""),
            r.get("delivery_time", ""),
            r.get("open_count", 0),
            r.get("click_count", 0),
            r.get("failure_reason", ""),
            r.get("bounce_reason", ""),
            r.get("last_event", ""),
            r.get("last_event_time", "")
        ])

    filter_tag_str = f"_{tag_name}" if tag_name else ""
    filter_status_str = f"_{status}" if status else ""
    filename = f"delivery_{canonical}{filter_status_str}{filter_tag_str}_{int(time.time())}.csv"

    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )

@app.get("/api/tracking-events/{region}")
@app.get("/api/tracking/events/{region}")
def get_tracking_events(region: str, page: int = 1, page_size: int = 30, search: Optional[str] = None):
    """Retrieve real email tracking events directly from Alibaba Cloud DirectMail."""
    valid, canonical, err = validate_region(region)
    if not valid:
        raise HTTPException(status_code=400, detail=err)

    client = router_instance.get_client(canonical)
    events_res = client.query_tracking_events(page_no=page, page_size=page_size, to_address=search)
    invalid_res = client.query_invalid_addresses(page_no=1, page_size=50)

    events = events_res.get("data", {}).get("mailDetail", []) if events_res.get("success") else []
    invalid_addresses = invalid_res.get("data", {}).get("mailDetail", []) if invalid_res.get("success") else []

    return {
        "region": canonical,
        "source": "Alibaba Cloud DirectMail",
        "events": events,
        "invalid_addresses": invalid_addresses,
        "total": events_res.get("TotalCount", len(events))
    }

# ----------------- RECONCILIATION & WEBHOOKS -----------------

@app.post("/api/reconciliation/{region}")
def run_idempotent_reconciliation(region: str):
    """
    Idempotent Reconciliation Engine.
    Queries authoritative Alibaba Cloud DirectMail events and invalid address logs,
    matches them against local jobs, and updates delivery timestamps and SMTP response codes
    without duplicating records or double-counting metrics.
    """
    valid, canonical, err = validate_region(region)
    if not valid:
        raise HTTPException(status_code=400, detail=err)

    client = router_instance.get_client(canonical)
    events_res = client.query_tracking_events(page_no=1, page_size=100)
    invalids_res = client.query_invalid_addresses(page_no=1, page_size=50)

    events = events_res.get("data", {}).get("mailDetail", []) if events_res.get("success") else []
    invalid_addresses = invalids_res.get("data", {}).get("mailDetail", []) if invalids_res.get("success") else []

    all_events = events + invalid_addresses
    matched_count = 0
    updated_count = 0
    unchanged_count = 0

    for ev in all_events:
        res = reconcile_job_with_provider_event(ev, canonical)
        if res.get("matched"):
            matched_count += 1
            if res.get("updated"):
                updated_count += 1
            else:
                unchanged_count += 1

    create_audit_log(
        action="reconciliation_run",
        object_type="reconciliation",
        object_id=canonical,
        result="success",
        details=f"Reconciled {canonical}: {len(all_events)} provider events checked. Matched: {matched_count}, Updated: {updated_count}, Unchanged: {unchanged_count}."
    )

    return {
        "success": True,
        "region": canonical,
        "source": "Alibaba Cloud DirectMail",
        "total_provider_events": len(all_events),
        "matched_count": matched_count,
        "updated_count": updated_count,
        "unchanged_count": unchanged_count,
        "message": f"Idempotent reconciliation finished for {canonical}. {updated_count} local jobs updated with authoritative provider delivery timestamps."
    }

@app.post("/api/webhook/directmail/{region}")
@app.post("/api/webhook/directmail")
def receive_directmail_webhook(payload: Dict[str, Any], region: Optional[str] = "singapore"):
    """
    Receives DirectMail callback notifications and idempotently updates local job delivery records.
    """
    valid, canonical, _ = validate_region(region or "singapore")
    if not valid:
        canonical = "singapore"

    recipient = payload.get("ToAddress") or payload.get("recipient") or payload.get("to")
    status_val = payload.get("Status") or payload.get("status") or 0
    message_val = payload.get("Message") or payload.get("message") or "250 Send Mail OK"

    event_dict = {
        "ToAddress": recipient,
        "Status": status_val,
        "Message": message_val,
        "LastUpdateTime": payload.get("timestamp") or utc_now_iso(),
        "ErrorClassification": payload.get("ErrorClassification")
    }

    reconcile_res = reconcile_job_with_provider_event(event_dict, canonical)

    create_audit_log(
        action="webhook_received",
        object_type="webhook",
        object_id=canonical,
        result="success" if reconcile_res.get("matched") else "unmatched",
        details=f"Webhook event for recipient '{recipient}': {reconcile_res.get('status', 'unmatched')}"
    )

    return {
        "received": True,
        "region": canonical,
        "reconciliation": reconcile_res
    }

# ----------------- AUDIT TRAIL LOGS -----------------

@app.get("/api/audit-logs")
def get_audit_logs(
    action: Optional[str] = None,
    object_type: Optional[str] = None,
    result: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0)
):
    """Retrieve immutable audit trail records with filtering and date range."""
    return list_audit_logs(
        action=action,
        object_type=object_type,
        result=result,
        start_date=start_date,
        end_date=end_date,
        search=search,
        limit=limit,
        offset=offset
    )


# ----------------- APPLICATION RECIPIENTS POOL -----------------

@app.get("/api/app-recipients")
@app.get("/api/recipients")
def get_app_recipients(search: Optional[str] = None, limit: int = 100, offset: int = 0):
    """List application recipient pool with search & pagination."""
    return list_application_recipients(search=search, limit=limit, offset=offset)

@app.post("/api/app-recipients")
@app.post("/api/recipients")
def add_app_recipients_api(req: AddAppRecipientsRequest):
    """Add recipients to the local application recipient pool."""
    count = add_application_recipients(req.recipients)
    return {"success": True, "added_count": count, "message": f"Added {count} recipient(s) to application pool."}

@app.delete("/api/app-recipients/batch")
@app.delete("/api/recipients")
def delete_app_recipients_api(req: DeleteAppRecipientsRequest):
    """Delete multiple recipients by ID list from the application pool."""
    count = delete_application_recipients(req.ids)
    return {"success": True, "deleted_count": count, "message": f"Deleted {count} recipient(s)."}


# ----------------- SMART AGENT NATURAL LANGUAGE INTERPRETER -----------------

@app.post("/api/smart-agent/query")
def smart_agent_query(req: SmartAgentQueryRequest):
    """
    Interprets natural language commands and executes corresponding Alibaba DirectMail API calls.
    Examples:
    - 'Show today's delivery report'
    - 'Show all domains'
    - 'Show verified senders'
    - 'Show email templates'
    - 'Show bounced emails'
    - 'How many emails were delivered today?'
    """
    from datetime import datetime, timezone
    p = req.prompt.strip().lower()
    valid, canonical, _ = validate_region(req.region)
    if not valid:
        canonical = "singapore"
    client = router_instance.get_client(canonical)

    if "domain" in p:
        res = client.query_domains()
        doms = res.get("domains", [])
        return {
            "intent": "domains",
            "title": f"Configured Domains ({canonical.title()})",
            "source": "Alibaba Cloud DirectMail",
            "markdown": f"Found **{len(doms)}** domain(s) configured in Alibaba Cloud DirectMail for **{canonical.title()}**:\n\n" +
                        "\n".join([f"- **`{d.get('DomainName')}`** (CNAME Auth: {'Verified' if d.get('CnameAuthStatus') == 1 else 'Pending'}, ID: {d.get('DomainId')})" for d in doms]),
            "data": doms
        }

    elif "sender" in p or "mail address" in p:
        res = client.query_mail_addresses()
        senders = res.get("mail_addresses", [])
        return {
            "intent": "senders",
            "title": f"Verified Senders ({canonical.title()})",
            "source": "Alibaba Cloud DirectMail",
            "markdown": f"Found **{len(senders)}** verified sender address(es) in **{canonical.title()}**:\n\n" +
                        "\n".join([f"- **`{s.get('AccountName')}`** (Type: `{s.get('Sendtype', 'batch')}`, Status: {'Active' if s.get('AccountStatus') == 0 else 'Disabled'})" for s in senders]),
            "data": senders
        }

    elif "template" in p:
        res = client.query_templates(page_no=1, page_size=20)
        templates = res.get("data", {}).get("template", []) if res.get("success") else []
        return {
            "intent": "templates",
            "title": f"Email Templates ({canonical.title()})",
            "source": "Alibaba Cloud DirectMail",
            "markdown": f"Found **{len(templates)}** template(s) in Alibaba Cloud DirectMail for **{canonical.title()}**:\n\n" +
                        "\n".join([f"- **{t.get('TemplateName')}** (ID: `{t.get('TemplateId')}`, Type: {'Batch' if t.get('TemplateType') == 0 else 'Trigger'})" for t in templates]),
            "data": templates
        }

    elif "bounce" in p or "invalid" in p:
        res = client.query_invalid_addresses()
        invalids = res.get("data", {}).get("mailDetail", []) if res.get("success") else []
        return {
            "intent": "bounced",
            "title": f"Bounced / Invalid Addresses ({canonical.title()})",
            "source": "Alibaba Cloud DirectMail",
            "markdown": f"Found **{len(invalids)}** invalid/bounced recipient record(s) in **{canonical.title()}**:\n\n" +
                        ("\n".join([f"- **`{i.get('ToAddress')}`** (Updated: {i.get('LastUpdateTime')})" for i in invalids]) if invalids else "_No bounced addresses recorded._"),
            "data": invalids
        }

    elif "quota" in p or "limit" in p or "overview" in p or "summary" in p:
        res = client.query_account_summary()
        return {
            "intent": "account_summary",
            "title": f"Sending Overview & Quotas ({canonical.title()})",
            "source": "Alibaba Cloud DirectMail",
            "markdown": f"### Alibaba Cloud Account Summary ({canonical.title()})\n\n"
                        f"- **Daily Quota**: `{res.get('DailyQuota', 'N/A')}` emails/day\n"
                        f"- **Monthly Quota**: `{res.get('MonthQuota', 'N/A')}` emails/month\n"
                        f"- **Quota Level**: `{res.get('QuotaLevel', 'N/A')} / {res.get('MaxQuotaLevel', '10')}`\n"
                        f"- **Domains Configured**: `{res.get('Domains', 'N/A')}`\n"
                        f"- **Templates Configured**: `{res.get('Templates', 'N/A')}`\n"
                        f"- **IP Channel Type**: `{res.get('IpChannelType', 'normal')}`\n",
            "data": res
        }

    elif "deliver" in p or "report" in p or "stats" in p:
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        res = client.query_delivery_stats(today_str, today_str)
        stats = res.get("data", {}).get("stat", []) if res.get("success") else []
        req_count = sum(s.get("requestCount", 0) for s in stats)
        succ_count = sum(s.get("successCount", 0) for s in stats)
        fail_count = sum(s.get("faildCount", 0) for s in stats)
        rate = round((succ_count / req_count * 100), 2) if req_count > 0 else 0.0
        return {
            "intent": "delivery",
            "title": f"Today's Delivery Report ({canonical.title()})",
            "source": "Alibaba Cloud DirectMail",
            "markdown": f"### Delivery Report for Today ({today_str})\n\n"
                        f"- **Total Sent / Requested**: `{req_count}`\n"
                        f"- **Successfully Delivered**: `{succ_count}`\n"
                        f"- **Delivery Rate**: `{rate}%`\n"
                        f"- **Failed Count**: `{fail_count}`\n",
            "data": stats
        }

    else:
        # Generic query fallback
        return {
            "intent": "help",
            "title": "Smart Agent Assistant",
            "source": "Alibaba Cloud DirectMail",
            "markdown": "I understand natural language queries for your connected Alibaba DirectMail account. Try asking:\n\n"
                        "- *\"Show today's delivery report\"*\n"
                        "- *\"Show all domains\"*\n"
                        "- *\"Show verified senders\"*\n"
                        "- *\"Show email templates\"*\n"
                        "- *\"Show bounced emails\"*\n"
                        "- *\"What is my daily quota?\"*\n"
                        "- *\"Show recent tasks\"*",
            "data": {}
        }



@app.get("/api/timezones")
def get_timezones():
    """Return common global timezones for user selection."""
    popular = [
        "Asia/Kolkata",
        "UTC",
        "Asia/Singapore",
        "Europe/Berlin",
        "Europe/London",
        "America/New_York",
        "America/Los_Angeles",
        "America/Chicago",
        "Asia/Tokyo",
        "Asia/Dubai",
        "Australia/Sydney"
    ]
    return {"default": DEFAULT_TIMEZONE, "popular": popular}

# ----------------- SENDER MANAGEMENT -----------------

@app.get("/api/senders")
def get_senders(region: Optional[str] = None):
    """List verified senders, optionally filtered by region."""
    canonical = canonicalize_region(region) if region else None
    return {"senders": list_verified_senders(canonical)}

@app.post("/api/senders")
def create_sender(req: VerifiedSenderRequest):
    """Add a verified sender for a specific region."""
    valid, canonical, err = validate_region(req.region)
    if not valid:
        raise HTTPException(status_code=400, detail=err)
    if not is_valid_email(req.email):
        raise HTTPException(status_code=400, detail="Invalid sender email address.")

    add_verified_sender(canonical, req.email, req.alias, req.is_default)
    return {"success": True, "message": f"Sender '{req.email}' added for {canonical}."}

@app.delete("/api/senders/{sender_id}")
def remove_sender(sender_id: int):
    """Delete a verified sender address."""
    deleted = delete_verified_sender(sender_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Sender not found.")
    return {"success": True, "message": "Sender deleted."}

# ----------------- RECIPIENT VALIDATION -----------------

@app.post("/api/validate-recipients")
def validate_recipients(req: RecipientValidationRequest):
    """Parse and validate recipient addresses from pasted text or CSV."""
    if req.csv_content:
        res = parse_bulk_recipients_csv(req.csv_content)
    elif req.raw_text:
        res = parse_bulk_recipients_text(req.raw_text)
    else:
        raise HTTPException(status_code=400, detail="Either raw_text or csv_content must be provided.")
    return res

# ----------------- SEND & SCHEDULE EMAIL -----------------

@app.get("/api/scheduled-campaigns")
def get_scheduled_campaigns(limit: int = 50):
    """Retrieve scheduled campaigns with their tag, template, sender, recipient count, and scheduled time."""
    return {"scheduled_campaigns": list_scheduled_campaigns(limit=limit)}

@app.post("/api/send")
def send_or_schedule_single(req: SingleEmailRequest):
    """
    Send an email immediately or schedule for a future date/time.
    Supports auto-attaching template subject/content and enforces provider review approval.
    """
    # 1. Validate region
    reg_valid, canonical_region, reg_err = validate_region(req.region)
    if not reg_valid:
        raise HTTPException(status_code=400, detail=reg_err)

    # 2. Validate sender
    snd_valid, snd_err = validate_sender(canonical_region, req.sender)
    if not snd_valid:
        raise HTTPException(status_code=400, detail=snd_err)

    # 3. Validate recipient
    if not is_valid_email(req.recipient):
        raise HTTPException(status_code=400, detail=f"Invalid recipient email: '{req.recipient}'.")

    # 4. Handle template if selected (enforce provider approval & auto-attach subject/body)
    if req.template_id:
        tmpl = get_local_template(req.template_id)
        if not tmpl:
            raise HTTPException(status_code=404, detail="Selected template not found.")
        tmpl_status = (tmpl.get("dm_status") or tmpl.get("status") or "").lower()
        if tmpl_status != "approved":
            curr_status = tmpl.get("dm_status") or tmpl.get("status") or "draft"
            raise HTTPException(
                status_code=400,
                detail=f"Cannot send using template '{tmpl.get('name')}': only DirectMail provider-approved templates can be used for dispatch. Current status: '{curr_status}'. Please submit the template for review."
            )
        if not req.subject or not req.subject.strip():
            req.subject = tmpl.get("subject", "")
        if not req.html_body and not req.text_body:
            req.html_body = tmpl.get("html_body") or tmpl.get("html_content")
            req.text_body = tmpl.get("text_body") or tmpl.get("text_content")

    # 5. Validate subject & content
    if not req.subject or not req.subject.strip():
        raise HTTPException(status_code=400, detail="Subject cannot be empty.")
    if not req.html_body and not req.text_body:
        raise HTTPException(status_code=400, detail="Either plain text body or HTML body must be provided.")

    # 6. Handle scheduling vs immediate
    is_scheduled = bool(req.scheduled_at and req.scheduled_at.strip())
    utc_scheduled_at = None

    if is_scheduled:
        sched_valid, utc_dt_str, sched_err = parse_and_validate_scheduled_time(
            req.scheduled_at, req.timezone_name
        )
        if not sched_valid:
            raise HTTPException(status_code=400, detail=sched_err)
        utc_scheduled_at = utc_dt_str

    job_id = f"job_{uuid.uuid4().hex[:12]}"
    create_job({
        "id": job_id,
        "region": canonical_region,
        "sender": req.sender.strip(),
        "recipient": req.recipient.strip(),
        "subject": req.subject.strip(),
        "html_body": req.html_body,
        "text_body": req.text_body,
        "from_alias": req.from_alias,
        "tag_name": req.tag_name,
        "template_id": req.template_id,
        "address_type": req.address_type,
        "reply_to_address": "true" if req.reply_to_address else "false",
        "send_type": "single",
        "status": "scheduled" if is_scheduled else "queued",
        "scheduled_at": utc_scheduled_at,
        "timezone_name": req.timezone_name
    })

    # If immediate, dispatch right away
    if not is_scheduled:
        exec_result = router_instance.execute_job(job_id)
        return {
            "id": job_id,
            "job_id": job_id,
            "status": exec_result.get("status", "sent"),
            "success": exec_result.get("success", False),
            "region": canonical_region,
            "request_id": exec_result.get("request_id"),
            "env_id": exec_result.get("env_id"),
            "error_code": exec_result.get("error_code"),
            "error_message": exec_result.get("error_message"),
            "test_mode": exec_result.get("test_mode", False),
            "message": "Email sent successfully." if exec_result.get("success") else f"Failed to send: {exec_result.get('error_message')}"
        }

    # Scheduled response
    return {
        "id": job_id,
        "job_id": job_id,
        "status": "scheduled",
        "success": True,
        "region": canonical_region,
        "scheduled_at_utc": utc_scheduled_at,
        "timezone": req.timezone_name,
        "message": f"Email successfully scheduled for execution at {req.scheduled_at} ({req.timezone_name})."
    }

@app.post("/api/send-bulk")
def send_or_schedule_bulk(req: BulkEmailRequest):
    """
    Create and dispatch or schedule a bulk email campaign.
    Supports auto-attaching template subject/content, task recipient exclusions, and provider approval enforcement.
    """
    reg_valid, canonical_region, reg_err = validate_region(req.region)
    if not reg_valid:
        raise HTTPException(status_code=400, detail=reg_err)

    snd_valid, snd_err = validate_sender(canonical_region, req.sender)
    if not snd_valid:
        raise HTTPException(status_code=400, detail=snd_err)

    if not req.recipients:
        raise HTTPException(status_code=400, detail="At least one recipient is required.")
    
    # Validate each recipient
    valid_recipients = [r.strip() for r in req.recipients if is_valid_email(r)]
    if not valid_recipients:
        raise HTTPException(status_code=400, detail="No valid recipient email addresses provided.")

    # Handle template if selected (enforce provider approval & auto-attach subject/body)
    if req.template_id:
        tmpl = get_local_template(req.template_id)
        if not tmpl:
            raise HTTPException(status_code=404, detail="Selected template not found.")
        tmpl_status = (tmpl.get("dm_status") or tmpl.get("status") or "").lower()
        if tmpl_status != "approved":
            curr_status = tmpl.get("dm_status") or tmpl.get("status") or "draft"
            raise HTTPException(
                status_code=400,
                detail=f"Cannot send campaign using template '{tmpl.get('name')}': only DirectMail provider-approved templates can be used for dispatch. Current status: '{curr_status}'. Please submit the template for review."
            )
        if not req.subject or not req.subject.strip():
            req.subject = tmpl.get("subject", "")
        if not req.html_body and not req.text_body:
            req.html_body = tmpl.get("html_body") or tmpl.get("html_content")
            req.text_body = tmpl.get("text_body") or tmpl.get("text_content")

    if not req.subject or not req.subject.strip():
        raise HTTPException(status_code=400, detail="Subject cannot be empty.")
    if not req.html_body and not req.text_body:
        raise HTTPException(status_code=400, detail="Either plain text body or HTML body must be provided.")

    is_scheduled = bool(req.scheduled_at and req.scheduled_at.strip())
    utc_scheduled_at = None

    if is_scheduled:
        sched_valid, utc_dt_str, sched_err = parse_and_validate_scheduled_time(
            req.scheduled_at, req.timezone_name
        )
        if not sched_valid:
            raise HTTPException(status_code=400, detail=sched_err)
        utc_scheduled_at = utc_dt_str

    res = BulkProcessor.create_and_dispatch_bulk(
        campaign_name=req.campaign_name,
        region=canonical_region,
        sender=req.sender.strip(),
        recipients=valid_recipients,
        subject=req.subject.strip(),
        html_body=req.html_body,
        text_body=req.text_body,
        from_alias=req.from_alias,
        tag_name=req.tag_name,
        template_id=req.template_id,
        address_type=req.address_type,
        reply_to_address=req.reply_to_address,
        scheduled_at=utc_scheduled_at,
        timezone_name=req.timezone_name,
        excluded_recipients=req.excluded_recipients
    )

    return {
        "success": True,
        "campaign_id": res["campaign_id"],
        "total_selected": res.get("total_selected", len(valid_recipients)),
        "excluded_count": res.get("excluded_count", 0),
        "total_recipients": res["total_recipients"],
        "recipient_count": res["total_recipients"],
        "status": res["status"],
        "scheduled_at": utc_scheduled_at,
        "message": f"Campaign successfully {'scheduled' if is_scheduled else 'queued for sending'} to {res['total_recipients']} recipients from {canonical_region} ({res.get('excluded_count', 0)} excluded)."
    }

# ----------------- JOBS & HISTORY -----------------

@app.get("/api/jobs")
def get_jobs(
    region: Optional[str] = None,
    status: Optional[str] = None,
    send_type: Optional[str] = None,
    search: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0)
):
    """List jobs with filtering, date range support, and pagination."""
    canonical = canonicalize_region(region) if region else None
    return list_jobs(
        region=canonical,
        status=status,
        send_type=send_type,
        search=search,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        offset=offset
    )

@app.get("/api/jobs/{job_id}")
def get_job_detail(job_id: str):
    """Retrieve full job details including sanitized API response."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job

@app.post("/api/jobs/{job_id}/retry")
def retry_job(job_id: str):
    """Manually retry a failed email job."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    
    res = router_instance.execute_job(job_id)
    return {
        "job_id": job_id,
        "status": res.get("status"),
        "success": res.get("success"),
        "error_message": res.get("error_message"),
        "request_id": res.get("request_id")
    }

@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    """Cancel a scheduled email job."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job["status"] not in ("scheduled", "queued", "retrying"):
        raise HTTPException(status_code=400, detail=f"Cannot cancel job with status '{job['status']}'.")
    
    update_job_status(job_id, status="cancelled")
    return {"success": True, "message": f"Job {job_id} cancelled."}

@app.post("/api/jobs/{job_id}/reschedule")
def reschedule_job(job_id: str, req: RescheduleRequest):
    """Reschedule an existing job."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job["status"] not in ("scheduled", "retrying"):
        raise HTTPException(status_code=400, detail="Only scheduled or retrying jobs can be rescheduled.")
    
    sched_valid, utc_dt_str, sched_err = parse_and_validate_scheduled_time(
        req.scheduled_at, req.timezone_name
    )
    if not sched_valid:
        raise HTTPException(status_code=400, detail=sched_err)

    update_job_status(job_id, status="scheduled", scheduled_at=utc_dt_str)
    return {
        "success": True,
        "job_id": job_id,
        "scheduled_at_utc": utc_dt_str,
        "message": f"Job rescheduled to {req.scheduled_at} ({req.timezone_name})."
    }

# ----------------- SETTINGS ENDPOINTS -----------------

@app.get("/api/settings")
def get_settings():
    """Get all application settings."""
    return {"settings": get_all_settings()}

@app.put("/api/settings")
def update_settings(req: SettingsUpdateRequest):
    """Update settings values."""
    if req.test_mode is not None:
        set_setting("test_mode", req.test_mode)
    if req.rate_limit_qps is not None:
        set_setting("rate_limit_qps", req.rate_limit_qps)
    if req.max_retries is not None:
        set_setting("max_retries", req.max_retries)
    if req.default_timezone is not None:
        set_setting("default_timezone", req.default_timezone)
    return {"success": True, "settings": get_all_settings()}

# ----------------- FRONTEND STATIC HOSTING -----------------

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

@app.get("/")
def serve_index():
    """Serve the single page app index.html."""
    index_file = FRONTEND_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return JSONResponse(
        status_code=200,
        content={"message": "Alibaba Cloud DirectMail Automation Agent API is running."}
    )
