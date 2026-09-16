"""
Pydantic models and schemas for the DirectMail Automation Agent REST API.
"""
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class SingleEmailRequest(BaseModel):
    region: str = Field(..., description="Target region: singapore, germany, or united_states")
    sender: str = Field(..., description="Verified sender address for the region")
    recipient: str = Field(..., description="Recipient email address")
    subject: Optional[str] = Field(None, max_length=256, description="Email subject (auto-populated if template is selected)")
    text_body: Optional[str] = Field(None, description="Plain text body")
    html_body: Optional[str] = Field(None, description="HTML formatted email body")
    from_alias: Optional[str] = Field(None, description="Display name / alias")
    tag_name: Optional[str] = Field(None, description="DirectMail classification tag")
    template_id: Optional[int] = Field(None, description="Optional template ID")
    address_type: int = Field(1, description="0: random account / trigger, 1: normal sender address")
    reply_to_address: bool = Field(False, description="Whether to use console reply-to address")
    scheduled_at: Optional[str] = Field(None, description="Scheduled datetime (e.g. 2026-09-15 17:00)")
    timezone_name: str = Field("Asia/Kolkata", description="Selected timezone name")

class BulkEmailRequest(BaseModel):
    campaign_name: Optional[str] = Field(None, description="Descriptive campaign title")
    region: str = Field(..., description="Target region: singapore, germany, or united_states")
    sender: str = Field(..., description="Verified sender address for the region")
    recipients: List[str] = Field(..., min_length=1, description="List of recipient email addresses")
    excluded_recipients: List[str] = Field(default_factory=list, description="Recipients excluded from this specific task without deleting from master pool")
    subject: Optional[str] = Field(None, max_length=256, description="Email subject (auto-populated if template is selected)")
    text_body: Optional[str] = Field(None, description="Plain text body")
    html_body: Optional[str] = Field(None, description="HTML formatted email body")
    from_alias: Optional[str] = Field(None, description="Display name / alias")
    tag_name: Optional[str] = Field(None, description="DirectMail classification tag")
    template_id: Optional[int] = Field(None, description="Optional template ID")
    address_type: int = Field(1, description="0 or 1")
    reply_to_address: bool = Field(False, description="Whether to use console reply-to address")
    scheduled_at: Optional[str] = Field(None, description="Scheduled datetime (optional)")
    timezone_name: str = Field("Asia/Kolkata", description="Selected timezone name")

class RecipientValidationRequest(BaseModel):
    raw_text: Optional[str] = None
    csv_content: Optional[str] = None

class RescheduleRequest(BaseModel):
    scheduled_at: str = Field(..., description="New scheduled datetime")
    timezone_name: str = Field("Asia/Kolkata", description="Timezone name")

class VerifiedSenderRequest(BaseModel):
    region: str = Field(..., description="Region key")
    email: str = Field(..., description="Verified sender email")
    alias: Optional[str] = None
    is_default: bool = False

class SettingsUpdateRequest(BaseModel):
    test_mode: Optional[str] = None
    rate_limit_qps: Optional[str] = None
    max_retries: Optional[str] = None
    default_timezone: Optional[str] = None

class CreateDomainRequest(BaseModel):
    domain_name: str = Field(..., min_length=3, description="Domain name to configure in DirectMail")

class CreateSenderRequest(BaseModel):
    account_name: str = Field(..., description="Sender email address (e.g. info@domain.com)")
    reply_address: Optional[str] = None
    send_type: str = Field("batch", description="batch or trigger")

class CreateTemplateRequest(BaseModel):
    template_name: str = Field(..., min_length=1, description="Unique template name")
    subject: str = Field(..., min_length=1, description="Email subject line")
    nick_name: str = Field(..., description="From alias / sender display nickname")
    html_text: str = Field(..., min_length=1, description="HTML content of email template")
    template_type: int = Field(0, description="0: batch, 1: trigger")

class AddAppRecipientsRequest(BaseModel):
    recipients: List[Dict[str, Any]] = Field(..., min_length=1, description="List of dicts with email, name, tags")

class DeleteAppRecipientsRequest(BaseModel):
    ids: List[int] = Field(..., min_length=1, description="List of recipient IDs to delete")

class SmartAgentQueryRequest(BaseModel):
    prompt: str = Field(..., min_length=1, description="Natural language prompt")
    region: str = Field("singapore", description="Target region")

class AppTemplateCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, description="Template title")
    subject: str = Field(..., min_length=1, description="Email subject line")
    from_alias: Optional[str] = Field(None, description="From alias / sender nickname")
    format: str = Field("html", description="'html' or 'text'")
    html_body: Optional[str] = Field(None, description="HTML formatted email body")
    text_body: Optional[str] = Field(None, description="Plain text body")
    template_type: int = Field(0, description="0: Batch, 1: Trigger")
    dm_region: str = Field("singapore", description="Target region for DirectMail sync")

class AppTemplateUpdateRequest(BaseModel):
    name: Optional[str] = None
    subject: Optional[str] = None
    from_alias: Optional[str] = None
    format: Optional[str] = None
    html_body: Optional[str] = None
    text_body: Optional[str] = None
    template_type: Optional[int] = None
    dm_region: Optional[str] = None

class AppTemplateReviewRequest(BaseModel):
    status: str = Field(..., description="Review status: draft, pending_review, approved, or rejected")
    note: Optional[str] = Field(None, description="Optional reviewer feedback note")

class WebhookEventPayload(BaseModel):
    event: Optional[str] = Field(None, description="Event type: delivery, bounce, click, open")
    recipient: Optional[str] = Field(None, description="Recipient email address")
    status: Optional[str] = Field(None, description="Status code or text")
    message: Optional[str] = Field(None, description="SMTP message e.g. 250 Send Mail OK")
    env_id: Optional[str] = Field(None, description="DirectMail envId")
    request_id: Optional[str] = Field(None, description="DirectMail RequestId")
    timestamp: Optional[str] = Field(None, description="Event timestamp")

class EmailTagCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="Unique tag name")
    description: Optional[str] = Field(None, max_length=250, description="Optional description / classification notes")
    region: str = Field("singapore", description="Target region (singapore, germany, united_states)")
    sync_to_directmail: bool = Field(False, description="Whether to also create in Alibaba Cloud DirectMail")

class EmailTagUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=250)
    region: Optional[str] = None



