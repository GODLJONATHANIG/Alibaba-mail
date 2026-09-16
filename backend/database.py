"""
Database layer for Alibaba Cloud DirectMail Automation Agent.
Uses SQLite for persistent, zero-dependency local storage.
"""
import sqlite3
import json
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from backend.config import DB_FILE_PATH, SUPPORTED_REGIONS, DEFAULT_TIMEZONE, DEFAULT_RATE_LIMIT_QPS, DEFAULT_MAX_RETRIES

def utc_now_iso() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def get_db_connection() -> sqlite3.Connection:
    """Create and return a database connection with dict-like row factory."""
    conn = sqlite3.connect(DB_FILE_PATH, timeout=20.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    """Initialize SQLite database tables and seed defaults."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # 1. Email Jobs table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS email_jobs (
                id TEXT PRIMARY KEY,
                campaign_id TEXT,
                region TEXT NOT NULL,
                sender TEXT NOT NULL,
                recipient TEXT NOT NULL,
                subject TEXT NOT NULL,
                text_body TEXT,
                html_body TEXT,
                from_alias TEXT,
                tag_name TEXT,
                address_type INTEGER DEFAULT 0,
                reply_to_address TEXT DEFAULT 'false',
                send_type TEXT NOT NULL DEFAULT 'single',
                status TEXT NOT NULL DEFAULT 'queued',
                scheduled_at TEXT,
                timezone_name TEXT DEFAULT 'Asia/Kolkata',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                sent_at TEXT,
                attempts INTEGER DEFAULT 0,
                max_attempts INTEGER DEFAULT 3,
                last_attempt_at TEXT,
                next_retry_at TEXT,
                error_code TEXT,
                error_message TEXT,
                api_request_id TEXT,
                api_env_id TEXT,
                api_response_raw TEXT,
                is_test_mode INTEGER DEFAULT 0
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON email_jobs(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_region ON email_jobs(region)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_scheduled_at ON email_jobs(scheduled_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_campaign ON email_jobs(campaign_id)")

        # 2. Campaigns table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS campaigns (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                region TEXT NOT NULL,
                sender TEXT NOT NULL,
                subject TEXT NOT NULL,
                total_recipients INTEGER DEFAULT 0,
                sent_count INTEGER DEFAULT 0,
                failed_count INTEGER DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'draft',
                scheduled_at TEXT,
                created_at TEXT NOT NULL,
                completed_at TEXT
            )
        """)

        # 3. Verified Senders table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS verified_senders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                region TEXT NOT NULL,
                email TEXT NOT NULL,
                alias TEXT,
                is_default INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                UNIQUE(region, email)
            )
        """)

        # 4. App Settings table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                description TEXT
            )
        """)

        # 5. Application Recipients table (clearly distinguished from Alibaba Cloud remote lists)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS application_recipients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE,
                name TEXT,
                tags TEXT,
                created_at TEXT NOT NULL
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_app_recipients_email ON application_recipients(email)")

        # 6. Email Templates table (Local HTML & Plain-text templates with Review & DirectMail Sync state)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS email_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                subject TEXT NOT NULL,
                from_alias TEXT,
                format TEXT DEFAULT 'html',
                html_body TEXT,
                text_body TEXT,
                template_type INTEGER DEFAULT 0,
                status TEXT DEFAULT 'draft',
                sync_status TEXT DEFAULT 'sync_pending',
                dm_template_id INTEGER,
                dm_region TEXT DEFAULT 'singapore',
                sync_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_templates_status ON email_templates(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_templates_sync_status ON email_templates(sync_status)")

        # 7. Audit Logs table (Immutable audit trail for templates, jobs, sync, exclusions, and reconciliation)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                actor TEXT DEFAULT 'system',
                action TEXT NOT NULL,
                object_type TEXT NOT NULL,
                object_id TEXT,
                result TEXT NOT NULL,
                details TEXT,
                error TEXT
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_logs(timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_logs(action)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_object ON audit_logs(object_type)")

        # 8. Email Tags table (Managed classification tags with optional DirectMail synchronization)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS email_tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                region TEXT DEFAULT 'singapore',
                dm_tag_id INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tags_name ON email_tags(name)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tags_region ON email_tags(region)")

        # Migrate email_jobs table columns additively
        cursor.execute("PRAGMA table_info(email_jobs)")
        existing_cols = {row[1] for row in cursor.fetchall()}
        new_cols = {
            "template_id": "INTEGER",
            "delivered_at": "TEXT",
            "provider_status": "TEXT",
            "provider_event_message": "TEXT",
            "reconciled_at": "TEXT",
            "open_count": "INTEGER DEFAULT 0",
            "unique_open_count": "INTEGER DEFAULT 0",
            "click_count": "INTEGER DEFAULT 0",
            "unique_click_count": "INTEGER DEFAULT 0",
            "last_event_time": "TEXT",
            "failure_reason": "TEXT",
            "bounce_reason": "TEXT"
        }
        for col_name, col_type in new_cols.items():
            if col_name not in existing_cols:
                cursor.execute(f"ALTER TABLE email_jobs ADD COLUMN {col_name} {col_type}")

        # Migrate campaigns table columns additively
        cursor.execute("PRAGMA table_info(campaigns)")
        camp_cols = {row[1] for row in cursor.fetchall()}
        new_camp_cols = {
            "tag_name": "TEXT",
            "template_id": "INTEGER",
            "timezone_name": "TEXT DEFAULT 'Asia/Kolkata'"
        }
        for col_name, col_type in new_camp_cols.items():
            if col_name not in camp_cols:
                cursor.execute(f"ALTER TABLE campaigns ADD COLUMN {col_name} {col_type}")

        # Migrate email_templates table columns additively
        cursor.execute("PRAGMA table_info(email_templates)")
        tpl_cols = {row[1] for row in cursor.fetchall()}
        new_tpl_cols = {
            "dm_status": "TEXT",
            "rejection_reason": "TEXT",
            "last_synced_at": "TEXT"
        }
        for col_name, col_type in new_tpl_cols.items():
            if col_name not in tpl_cols:
                cursor.execute(f"ALTER TABLE email_templates ADD COLUMN {col_name} {col_type}")

        # Seed verified senders if table empty
        cursor.execute("SELECT COUNT(*) FROM verified_senders")
        if cursor.fetchone()[0] == 0:
            now = utc_now_iso()
            for region_key, conf in SUPPORTED_REGIONS.items():
                for idx, email in enumerate(conf["default_senders"]):
                    cursor.execute("""
                        INSERT OR IGNORE INTO verified_senders (region, email, alias, is_default, created_at)
                        VALUES (?, ?, ?, ?, ?)
                    """, (region_key, email, f"Alibaba Mail ({conf['display_name']})", 1 if idx == 0 else 0, now))

        # Seed default app settings if not present
        default_settings = [
            ("test_mode", "true", "Simulate Alibaba Cloud DirectMail responses when true"),
            ("rate_limit_qps", str(DEFAULT_RATE_LIMIT_QPS), "Maximum requests per second to DirectMail"),
            ("max_retries", str(DEFAULT_MAX_RETRIES), "Maximum retry attempts for transient API failures"),
            ("default_timezone", DEFAULT_TIMEZONE, "Default UI timezone for scheduling"),
        ]
        for key, val, desc in default_settings:
            cursor.execute("""
                INSERT OR IGNORE INTO app_settings (key, value, description)
                VALUES (?, ?, ?)
            """, (key, val, desc))

        conn.commit()

# --- Job CRUD Helpers ---

def create_job(job_data: Dict[str, Any]) -> str:
    """Insert a new email job into the database."""
    now = utc_now_iso()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO email_jobs (
                id, campaign_id, region, sender, recipient, subject,
                text_body, html_body, from_alias, tag_name, template_id, address_type,
                reply_to_address, send_type, status, scheduled_at,
                timezone_name, created_at, updated_at, attempts,
                max_attempts, is_test_mode
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            job_data["id"],
            job_data.get("campaign_id"),
            job_data["region"],
            job_data["sender"],
            job_data["recipient"],
            job_data["subject"],
            job_data.get("text_body", ""),
            job_data.get("html_body", ""),
            job_data.get("from_alias", ""),
            job_data.get("tag_name", ""),
            job_data.get("template_id"),
            job_data.get("address_type", 0),
            str(job_data.get("reply_to_address", "false")).lower(),
            job_data.get("send_type", "single"),
            job_data.get("status", "queued"),
            job_data.get("scheduled_at"),
            job_data.get("timezone_name", DEFAULT_TIMEZONE),
            now,
            now,
            job_data.get("attempts", 0),
            job_data.get("max_attempts", 3),
            1 if job_data.get("is_test_mode", False) else 0
        ))
        conn.commit()
    return job_data["id"]

def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    """Fetch single email job by ID."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM email_jobs WHERE id = ?", (job_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

def update_job_status(job_id: str, status: str, **kwargs) -> bool:
    """Update job status and optional metadata (sent_at, error, api response, provider delivery)."""
    now = utc_now_iso()
    allowed_fields = {
        "sent_at", "attempts", "last_attempt_at", "next_retry_at",
        "error_code", "error_message", "api_request_id", "api_env_id",
        "api_response_raw", "scheduled_at", "template_id",
        "delivered_at", "provider_status", "provider_event_message", "reconciled_at"
    }
    updates = ["status = ?", "updated_at = ?"]
    params = [status, now]

    for key, val in kwargs.items():
        if key in allowed_fields:
            updates.append(f"{key} = ?")
            if isinstance(val, (dict, list)):
                params.append(json.dumps(val))
            else:
                params.append(val)

    params.append(job_id)
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(f"UPDATE email_jobs SET {', '.join(updates)} WHERE id = ?", params)
        conn.commit()
        return cursor.rowcount > 0

def list_jobs(
    region: Optional[str] = None,
    status: Optional[str] = None,
    send_type: Optional[str] = None,
    search: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
) -> Dict[str, Any]:
    """List jobs with filtering, date range support, and pagination."""
    query = "SELECT * FROM email_jobs WHERE 1=1"
    count_query = "SELECT COUNT(*) FROM email_jobs WHERE 1=1"
    params = []
    
    if region:
        query += " AND region = ?"
        count_query += " AND region = ?"
        params.append(region)
    if status:
        query += " AND status = ?"
        count_query += " AND status = ?"
        params.append(status)
    if send_type:
        query += " AND send_type = ?"
        count_query += " AND send_type = ?"
        params.append(send_type)
    if start_date:
        query += " AND created_at >= ?"
        count_query += " AND created_at >= ?"
        params.append(f"{start_date}T00:00:00Z" if len(start_date) == 10 else start_date)
    if end_date:
        query += " AND created_at <= ?"
        count_query += " AND created_at <= ?"
        params.append(f"{end_date}T23:59:59Z" if len(end_date) == 10 else end_date)
    if search:
        search_pattern = f"%{search}%"
        query += " AND (recipient LIKE ? OR subject LIKE ? OR sender LIKE ? OR error_message LIKE ? OR api_request_id LIKE ?)"
        count_query += " AND (recipient LIKE ? OR subject LIKE ? OR sender LIKE ? OR error_message LIKE ? OR api_request_id LIKE ?)"
        params.extend([search_pattern, search_pattern, search_pattern, search_pattern, search_pattern])

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(count_query, params)
        total = cursor.fetchone()[0]

        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        fetch_params = params + [limit, offset]
        cursor.execute(query, fetch_params)
        rows = [dict(r) for r in cursor.fetchall()]

    return {"total": total, "items": rows, "limit": limit, "offset": offset}

def get_due_scheduled_jobs(limit: int = 20) -> List[Dict[str, Any]]:
    """Retrieve jobs scheduled for execution that are due (scheduled_at <= utc_now)."""
    now = utc_now_iso()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM email_jobs
            WHERE (status = 'scheduled' AND scheduled_at <= ?)
               OR (status = 'retrying' AND next_retry_at <= ?)
            ORDER BY scheduled_at ASC, next_retry_at ASC
            LIMIT ?
        """, (now, now, limit))
        return [dict(r) for r in cursor.fetchall()]

# --- Campaign CRUD Helpers ---

def create_campaign(camp_data: Dict[str, Any]) -> str:
    """Create a new bulk campaign record."""
    now = utc_now_iso()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO campaigns (
                id, name, region, sender, subject, total_recipients,
                sent_count, failed_count, status, scheduled_at, created_at,
                tag_name, template_id, timezone_name
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            camp_data["id"],
            camp_data["name"],
            camp_data["region"],
            camp_data["sender"],
            camp_data["subject"],
            camp_data.get("total_recipients", 0),
            0, 0,
            camp_data.get("status", "draft"),
            camp_data.get("scheduled_at"),
            now,
            camp_data.get("tag_name"),
            camp_data.get("template_id"),
            camp_data.get("timezone_name", DEFAULT_TIMEZONE)
        ))
        conn.commit()
    return camp_data["id"]

def update_campaign_stats(campaign_id: str, sent_inc: int = 0, failed_inc: int = 0, status: Optional[str] = None):
    """Increment campaign stats and optionally update status."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        updates = ["sent_count = sent_count + ?", "failed_count = failed_count + ?"]
        params = [sent_inc, failed_inc]
        if status:
            updates.append("status = ?")
            params.append(status)
            if status in ("completed", "failed", "cancelled"):
                updates.append("completed_at = ?")
                params.append(utc_now_iso())
        params.append(campaign_id)
        cursor.execute(f"UPDATE campaigns SET {', '.join(updates)} WHERE id = ?", params)
        conn.commit()

# --- Senders & Settings Helpers ---

def list_verified_senders(region: Optional[str] = None) -> List[Dict[str, Any]]:
    """List verified senders, optionally filtered by canonical region."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if region:
            cursor.execute("SELECT * FROM verified_senders WHERE region = ? ORDER BY is_default DESC, email ASC", (region,))
        else:
            cursor.execute("SELECT * FROM verified_senders ORDER BY region ASC, is_default DESC, email ASC")
        return [dict(r) for r in cursor.fetchall()]

def add_verified_sender(region: str, email: str, alias: Optional[str] = None, is_default: bool = False) -> bool:
    """Add a verified sender for a specific region."""
    now = utc_now_iso()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if is_default:
            cursor.execute("UPDATE verified_senders SET is_default = 0 WHERE region = ?", (region,))
        cursor.execute("""
            INSERT OR REPLACE INTO verified_senders (region, email, alias, is_default, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (region, email.strip().lower(), alias, 1 if is_default else 0, now))
        conn.commit()
        return True

def delete_verified_sender(sender_id: int) -> bool:
    """Delete a verified sender by row ID."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM verified_senders WHERE id = ?", (sender_id,))
        conn.commit()
        return cursor.rowcount > 0

def sync_live_senders(region: str, senders_list: List[Dict[str, Any]]) -> int:
    """
    Sync real senders fetched from Alibaba Cloud DirectMail API into database.
    Replaces example/dummy senders with authentic verified addresses.
    """
    now = utc_now_iso()
    count = 0
    with get_db_connection() as conn:
        cursor = conn.cursor()
        # Remove placeholder example senders for this region
        cursor.execute("DELETE FROM verified_senders WHERE region = ? AND email LIKE '%@directmail.example.com'", (region,))
        
        for idx, item in enumerate(senders_list):
            email = item.get("AccountName") or item.get("SenderAddress")
            if not email:
                continue
            email = email.strip().lower()
            alias = f"Alibaba Mail ({item.get('Sendtype', 'verified').capitalize()})"
            cursor.execute("""
                INSERT OR IGNORE INTO verified_senders (region, email, alias, is_default, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (region, email, alias, 1 if idx == 0 else 0, now))
            count += 1

        conn.commit()
    return count


def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    """Retrieve setting value by key."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM app_settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row[0] if row else default

def set_setting(key: str, value: str) -> bool:
    """Update setting value."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE app_settings SET value = ? WHERE key = ?", (str(value), key))
        conn.commit()
        return cursor.rowcount > 0

def get_all_settings() -> Dict[str, str]:
    """Retrieve all system settings as key-value pairs."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT key, value FROM app_settings")
        return {row[0]: row[1] for row in cursor.fetchall()}

# --- Application Recipient Helpers (Local Application Pool) ---

def add_application_recipients(recipients_list: List[Dict[str, str]]) -> int:
    """Add application recipients to local database. Duplicates are ignored."""
    now = utc_now_iso()
    count = 0
    with get_db_connection() as conn:
        cursor = conn.cursor()
        for r in recipients_list:
            email = r.get("email", "").strip().lower()
            if not email:
                continue
            name = r.get("name", "").strip() or None
            tags = r.get("tags", "").strip() or None
            cursor.execute("""
                INSERT OR IGNORE INTO application_recipients (email, name, tags, created_at)
                VALUES (?, ?, ?, ?)
            """, (email, name, tags, now))
            if cursor.rowcount > 0:
                count += 1
        conn.commit()
    return count

def list_application_recipients(search: Optional[str] = None, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
    """List application recipients with search and pagination."""
    query = "SELECT * FROM application_recipients WHERE 1=1"
    count_query = "SELECT COUNT(*) FROM application_recipients WHERE 1=1"
    params = []
    if search:
        pattern = f"%{search.strip().lower()}%"
        query += " AND (email LIKE ? OR name LIKE ? OR tags LIKE ?)"
        count_query += " AND (email LIKE ? OR name LIKE ? OR tags LIKE ?)"
        params.extend([pattern, pattern, pattern])

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(count_query, params)
        total = cursor.fetchone()[0]

        query += " ORDER BY id DESC LIMIT ? OFFSET ?"
        cursor.execute(query, params + [limit, offset])
        rows = [dict(r) for r in cursor.fetchall()]

    return {"total": total, "items": rows, "recipients": rows, "limit": limit, "offset": offset}

def delete_application_recipients(ids: List[int]) -> int:
    """Delete recipients by ID list."""
    if not ids:
        return 0
    placeholders = ", ".join(["?"] * len(ids))
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(f"DELETE FROM application_recipients WHERE id IN ({placeholders})", ids)
        conn.commit()
        return cursor.rowcount

# --- Audit Trail Logging Helpers ---

def create_audit_log(
    action: str,
    object_type: str,
    result: str,
    object_id: Optional[str] = None,
    actor: str = "system",
    details: Optional[str] = None,
    error: Optional[str] = None
) -> int:
    """Record an audit trail event for actions like template updates, sync, exclusion, and reconciliation."""
    now = utc_now_iso()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO audit_logs (timestamp, actor, action, object_type, object_id, result, details, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (now, actor, action, object_type, str(object_id) if object_id is not None else None, result, details, error))
        conn.commit()
        return cursor.lastrowid

def list_audit_logs(
    action: Optional[str] = None,
    object_type: Optional[str] = None,
    result: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
) -> Dict[str, Any]:
    """Query audit logs with filtering, date range support, and pagination."""
    query = "SELECT * FROM audit_logs WHERE 1=1"
    count_query = "SELECT COUNT(*) FROM audit_logs WHERE 1=1"
    params = []

    if action:
        query += " AND action = ?"
        count_query += " AND action = ?"
        params.append(action)
    if object_type:
        query += " AND object_type = ?"
        count_query += " AND object_type = ?"
        params.append(object_type)
    if result:
        query += " AND result = ?"
        count_query += " AND result = ?"
        params.append(result)
    if start_date:
        query += " AND timestamp >= ?"
        count_query += " AND timestamp >= ?"
        params.append(f"{start_date}T00:00:00Z" if len(start_date) == 10 else start_date)
    if end_date:
        query += " AND timestamp <= ?"
        count_query += " AND timestamp <= ?"
        params.append(f"{end_date}T23:59:59Z" if len(end_date) == 10 else end_date)
    if search:
        search_pattern = f"%{search}%"
        query += " AND (details LIKE ? OR object_id LIKE ? OR action LIKE ? OR error LIKE ?)"
        count_query += " AND (details LIKE ? OR object_id LIKE ? OR action LIKE ? OR error LIKE ?)"
        params.extend([search_pattern, search_pattern, search_pattern, search_pattern])

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(count_query, params)
        total = cursor.fetchone()[0]

        query += " ORDER BY id DESC LIMIT ? OFFSET ?"
        fetch_params = params + [limit, offset]
        cursor.execute(query, fetch_params)
        rows = [dict(r) for r in cursor.fetchall()]

    return {"total": total, "items": rows, "limit": limit, "offset": offset}

# --- Application Email Templates Helpers (HTML & Plain-Text with Review & DirectMail Sync) ---

def create_local_template(data: Dict[str, Any]) -> int:
    """Create a local template in draft review status."""
    now = utc_now_iso()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO email_templates (
                name, subject, from_alias, format, html_body, text_body,
                template_type, status, dm_status, sync_status, dm_template_id, dm_region,
                sync_error, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data["name"].strip(),
            data["subject"].strip(),
            data.get("from_alias", ""),
            data.get("format", "html").lower(),
            data.get("html_body", ""),
            data.get("text_body", ""),
            data.get("template_type", 0),
            data.get("status", "draft"),
            data.get("dm_status", "draft"),
            data.get("sync_status", "sync_pending"),
            data.get("dm_template_id"),
            data.get("dm_region", "singapore"),
            data.get("sync_error"),
            now,
            now
        ))
        conn.commit()
        tpl_id = cursor.lastrowid
    
    create_audit_log(
        action="template_created",
        object_type="template",
        object_id=str(tpl_id),
        result="success",
        details=f"Template '{data['name']}' created ({data.get('format', 'html')})"
    )
    return tpl_id

def update_local_template(template_id: int, data: Dict[str, Any]) -> bool:
    """Update fields of an existing local template."""
    now = utc_now_iso()
    allowed_fields = {
        "name", "subject", "from_alias", "format", "html_body",
        "text_body", "template_type", "status", "sync_status",
        "dm_template_id", "dm_region", "sync_error"
    }
    updates = ["updated_at = ?"]
    params = [now]

    for key, val in data.items():
        if key in allowed_fields:
            updates.append(f"{key} = ?")
            params.append(val)

    params.append(template_id)
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(f"UPDATE email_templates SET {', '.join(updates)} WHERE id = ?", params)
        conn.commit()
        updated = cursor.rowcount > 0

    if updated:
        create_audit_log(
            action="template_updated",
            object_type="template",
            object_id=str(template_id),
            result="success",
            details=f"Template #{template_id} updated: {list(data.keys())}"
        )
    return updated

def get_local_template(template_id: int) -> Optional[Dict[str, Any]]:
    """Retrieve single local template by ID."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM email_templates WHERE id = ?", (template_id,))
        row = cursor.fetchone()
        if not row:
            return None
        d = dict(row)
        if not d.get("dm_status"):
            d["dm_status"] = d.get("status") or "draft"
        return d

def list_local_templates(
    search: Optional[str] = None,
    format_type: Optional[str] = None,
    status: Optional[str] = None,
    sync_status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
) -> Dict[str, Any]:
    """List local templates with search, format, status filtering and pagination."""
    query = "SELECT * FROM email_templates WHERE 1=1"
    count_query = "SELECT COUNT(*) FROM email_templates WHERE 1=1"
    params = []

    if format_type:
        query += " AND format = ?"
        count_query += " AND format = ?"
        params.append(format_type.lower())
    if status:
        query += " AND status = ?"
        count_query += " AND status = ?"
        params.append(status.lower())
    if sync_status:
        query += " AND sync_status = ?"
        count_query += " AND sync_status = ?"
        params.append(sync_status.lower())
    if search:
        search_pattern = f"%{search}%"
        query += " AND (name LIKE ? OR subject LIKE ? OR from_alias LIKE ?)"
        count_query += " AND (name LIKE ? OR subject LIKE ? OR from_alias LIKE ?)"
        params.extend([search_pattern, search_pattern, search_pattern])

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(count_query, params)
        total = cursor.fetchone()[0]

        query += " ORDER BY id DESC LIMIT ? OFFSET ?"
        fetch_params = params + [limit, offset]
        cursor.execute(query, fetch_params)
        rows = []
        for r in cursor.fetchall():
            d = dict(r)
            if not d.get("dm_status"):
                d["dm_status"] = d.get("status") or "draft"
            rows.append(d)

    return {"total": total, "items": rows, "templates": rows, "limit": limit, "offset": offset}

def delete_local_template(template_id: int) -> bool:
    """Delete a local template by ID."""
    tpl = get_local_template(template_id)
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM email_templates WHERE id = ?", (template_id,))
        conn.commit()
        deleted = cursor.rowcount > 0

    if deleted and tpl:
        create_audit_log(
            action="template_deleted",
            object_type="template",
            object_id=str(template_id),
            result="success",
            details=f"Template '{tpl.get('name')}' (ID: {template_id}) deleted"
        )
    return deleted

def update_template_review_status(template_id: int, status: str) -> bool:
    """Set template review status ('draft', 'pending_review', 'approved', 'rejected')."""
    valid_statuses = {"draft", "pending_review", "approved", "rejected"}
    if status not in valid_statuses:
        return False
    now = utc_now_iso()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE email_templates SET status = ?, dm_status = ?, updated_at = ? WHERE id = ?", (status, status, now, template_id))
        conn.commit()
        updated = cursor.rowcount > 0
    if updated:
        create_audit_log(
            action="template_review_updated",
            object_type="template",
            object_id=str(template_id),
            result="success",
            details=f"Review status changed to '{status}'"
        )
    return updated

def update_template_sync_status(
    template_id: int,
    sync_status: str,
    dm_template_id: Optional[int] = None,
    sync_error: Optional[str] = None
) -> bool:
    """Set template sync status ('sync_pending', 'synchronized', 'sync_failed')."""
    now = utc_now_iso()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        updates = ["sync_status = ?", "updated_at = ?"]
        params = [sync_status, now]
        if dm_template_id is not None:
            updates.append("dm_template_id = ?")
            params.append(dm_template_id)
        if sync_error is not None:
            updates.append("sync_error = ?")
            params.append(sync_error)
        else:
            updates.append("sync_error = NULL")
        params.append(template_id)
        cursor.execute(f"UPDATE email_templates SET {', '.join(updates)} WHERE id = ?", params)
        conn.commit()
        return cursor.rowcount > 0

# --- Idempotent Reconciliation Correlation Engine ---

def reconcile_job_with_provider_event(event: Dict[str, Any], region: str) -> Dict[str, Any]:
    """
    Correlate a real DirectMail delivery event (SenderStatisticsDetailByParam or QueryInvalidAddress)
    with local email_jobs. Updates delivered_at and status idempotently without duplicating or doubling counts.
    """
    to_address = (event.get("ToAddress") or "").strip().lower()
    if not to_address:
        return {"matched": False, "reason": "No ToAddress in event"}

    status_code = event.get("Status")
    raw_message = event.get("Message") or "250 Send Mail OK"
    last_update_time = event.get("LastUpdateTime") or utc_now_iso()
    error_class = event.get("ErrorClassification")

    is_success = (status_code == 0 or status_code == "0" or "250" in str(raw_message))
    target_status = "delivered" if is_success else "failed"

    now = utc_now_iso()

    with get_db_connection() as conn:
        cursor = conn.cursor()
        # Find matching job for this recipient in the region
        cursor.execute("""
            SELECT id, status, delivered_at, provider_event_message FROM email_jobs
            WHERE recipient = ? AND region = ?
            ORDER BY created_at DESC LIMIT 1
        """, (to_address, region))
        row = cursor.fetchone()

        if not row:
            return {"matched": False, "recipient": to_address, "reason": "No local job matched for recipient"}

        job_id = row["id"]
        current_status = row["status"]
        current_delivered_at = row["delivered_at"]

        # If already reconciled and marked delivered with same event timestamp, avoid redundant write (Idempotent)
        if current_status == target_status and current_delivered_at:
            return {"matched": True, "job_id": job_id, "updated": False, "status": current_status}

        # Check for open/click/bounce signals in event
        is_open = "open" in str(raw_message).lower() or "open" in str(event.get("Action", "")).lower()
        is_click = "click" in str(raw_message).lower() or "click" in str(event.get("Action", "")).lower()
        is_bounce = "bounce" in str(raw_message).lower() or error_class == "Invalid" or status_code in (4, "4")

        open_inc = 1 if is_open else 0
        click_inc = 1 if is_click else 0
        bounce_note = raw_message if is_bounce else None
        fail_note = raw_message if not is_success else None

        cursor.execute("""
            UPDATE email_jobs
            SET status = ?,
                delivered_at = ?,
                provider_status = ?,
                provider_event_message = ?,
                reconciled_at = ?,
                updated_at = ?,
                open_count = open_count + ?,
                unique_open_count = CASE WHEN ? > 0 THEN 1 ELSE unique_open_count END,
                click_count = click_count + ?,
                unique_click_count = CASE WHEN ? > 0 THEN 1 ELSE unique_click_count END,
                last_event_time = ?,
                failure_reason = COALESCE(?, failure_reason),
                bounce_reason = COALESCE(?, bounce_reason)
            WHERE id = ?
        """, (
            target_status,
            last_update_time,
            str(status_code),
            f"{raw_message}{' [' + error_class + ']' if error_class else ''}",
            now,
            now,
            open_inc,
            open_inc,
            click_inc,
            click_inc,
            last_update_time,
            fail_note,
            bounce_note,
            job_id
        ))
        conn.commit()

    return {
        "matched": True,
        "job_id": job_id,
        "updated": True,
        "status": target_status,
        "delivered_at": last_update_time
    }


# ----------------- EMAIL TAGS MANAGEMENT -----------------

def create_email_tag(data: Dict[str, Any]) -> int:
    """Create a new managed email classification tag."""
    now = utc_now_iso()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO email_tags (name, description, region, dm_tag_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            data["name"].strip(),
            data.get("description", "").strip(),
            data.get("region", "singapore"),
            data.get("dm_tag_id"),
            now,
            now
        ))
        conn.commit()
        return cursor.lastrowid

def get_email_tag(tag_id: int) -> Optional[Dict[str, Any]]:
    """Retrieve an email tag by primary ID."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM email_tags WHERE id = ?", (tag_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

def get_email_tag_by_name(name: str) -> Optional[Dict[str, Any]]:
    """Retrieve an email tag by name."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM email_tags WHERE LOWER(name) = LOWER(?)", (name.strip(),))
        row = cursor.fetchone()
        return dict(row) if row else None

def list_email_tags(region: Optional[str] = None, search: Optional[str] = None) -> List[Dict[str, Any]]:
    """List all email tags with campaign and task usage counts."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        query = """
            SELECT t.*,
                (SELECT COUNT(*) FROM campaigns c WHERE c.tag_name = t.name) as campaign_count,
                (SELECT COUNT(*) FROM email_jobs j WHERE j.tag_name = t.name) as job_count
            FROM email_tags t
            WHERE 1=1
        """
        params = []
        if region:
            query += " AND (t.region = ? OR t.region = 'all')"
            params.append(region)
        if search:
            query += " AND (LOWER(t.name) LIKE ? OR LOWER(t.description) LIKE ?)"
            s = f"%{search.lower()}%"
            params.extend([s, s])

        query += " ORDER BY t.name ASC"
        cursor.execute(query, params)
        return [dict(r) for r in cursor.fetchall()]

def update_email_tag(tag_id: int, data: Dict[str, Any]) -> bool:
    """Update fields on an existing email tag."""
    now = utc_now_iso()
    fields = []
    values = []
    for k in ("name", "description", "region", "dm_tag_id"):
        if k in data and data[k] is not None:
            fields.append(f"{k} = ?")
            values.append(data[k])
    if not fields:
        return False
    fields.append("updated_at = ?")
    values.append(now)
    values.append(tag_id)

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(f"UPDATE email_tags SET {', '.join(fields)} WHERE id = ?", values)
        conn.commit()
        return cursor.rowcount > 0

def delete_email_tag(tag_id: int) -> bool:
    """Delete an email tag."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM email_tags WHERE id = ?", (tag_id,))
        conn.commit()
        return cursor.rowcount > 0


# ----------------- RECIPIENT-LEVEL DELIVERY DRILLDOWN & CSV -----------------

def query_delivery_records(
    region: str,
    status: Optional[str] = None,
    tag_name: Optional[str] = None,
    campaign_id: Optional[str] = None,
    template_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
) -> Dict[str, Any]:
    """
    Query recipient-level delivery drill-down records with full traceability
    to Alibaba DirectMail status, provider IDs, and SMTP messages.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        query = """
            SELECT 
                j.id as job_id,
                j.recipient,
                COALESCE(r.name, '') as recipient_name,
                j.sender,
                COALESCE(j.campaign_id, '') as campaign_id,
                COALESCE(c.name, 'Direct Task') as campaign_name,
                j.template_id,
                COALESCE(t.name, 'Standard Template') as template_name,
                COALESCE(j.tag_name, c.tag_name, '') as tag_name,
                COALESCE(j.api_request_id, '') as api_request_id,
                COALESCE(j.api_env_id, '') as api_env_id,
                COALESCE(j.sent_at, j.created_at) as send_time,
                COALESCE(j.delivered_at, '') as delivery_time,
                j.status,
                COALESCE(j.open_count, 0) as open_count,
                COALESCE(j.unique_open_count, 0) as unique_open,
                COALESCE(j.click_count, 0) as click_count,
                COALESCE(j.unique_click_count, 0) as unique_click,
                COALESCE(j.provider_event_message, j.status) as last_event,
                COALESCE(j.last_event_time, j.delivered_at, j.updated_at) as last_event_time,
                COALESCE(j.failure_reason, j.error_message, '') as failure_reason,
                COALESCE(j.bounce_reason, CASE WHEN j.provider_event_message LIKE '%bounce%' THEN j.provider_event_message ELSE '' END) as bounce_reason,
                COALESCE(j.error_message, '') as provider_error
            FROM email_jobs j
            LEFT JOIN campaigns c ON j.campaign_id = c.id
            LEFT JOIN email_templates t ON j.template_id = t.id
            LEFT JOIN application_recipients r ON LOWER(j.recipient) = LOWER(r.email)
            WHERE j.region = ?
        """
        params: List[Any] = [region]

        if status:
            s_low = status.strip().lower()
            if s_low in ("successful", "success", "delivered"):
                query += " AND j.status IN ('delivered', 'sent')"
            elif s_low == "failed":
                query += " AND j.status = 'failed'"
            elif s_low == "undelivered":
                query += " AND j.status IN ('failed', 'bounced', 'cancelled', 'retrying')"
            elif s_low == "bounced":
                query += " AND (j.status = 'bounced' OR j.provider_event_message LIKE '%bounce%' OR j.provider_status = '4')"
            elif s_low == "invalid":
                query += " AND (j.status = 'failed' AND (j.error_code LIKE '%Invalid%' OR j.error_message LIKE '%invalid%' OR j.provider_event_message LIKE '%invalid%' OR j.provider_status = '4'))"
            elif s_low == "opened":
                query += " AND (j.open_count > 0 OR j.provider_event_message LIKE '%open%')"
            elif s_low == "clicked":
                query += " AND (j.click_count > 0 OR j.provider_event_message LIKE '%click%')"
            else:
                query += " AND j.status = ?"
                params.append(status)

        if tag_name:
            query += " AND (j.tag_name = ? OR c.tag_name = ?)"
            params.extend([tag_name, tag_name])

        if campaign_id:
            query += " AND j.campaign_id = ?"
            params.append(campaign_id)

        if template_id:
            query += " AND j.template_id = ?"
            params.append(template_id)

        if start_date:
            query += " AND j.created_at >= ?"
            params.append(f"{start_date}T00:00:00")

        if end_date:
            query += " AND j.created_at <= ?"
            params.append(f"{end_date}T23:59:59")

        if search:
            query += " AND (j.recipient LIKE ? OR r.name LIKE ? OR c.name LIKE ? OR j.api_request_id LIKE ?)"
            s_term = f"%{search}%"
            params.extend([s_term, s_term, s_term, s_term])

        count_query = f"SELECT COUNT(*) FROM ({query})"
        cursor.execute(count_query, params)
        total_count = cursor.fetchone()[0]

        query += " ORDER BY j.created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor.execute(query, params)
        rows = [dict(r) for r in cursor.fetchall()]

        return {
            "total": total_count,
            "region": region,
            "items": rows,
            "records": rows,
            "limit": limit,
            "offset": offset
        }


# ----------------- SCHEDULED CAMPAIGNS -----------------

def list_scheduled_campaigns(limit: int = 50, offset: int = 0) -> Dict[str, Any]:
    """Retrieve scheduled campaigns with tags, templates, and schedule details."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                c.id, c.name as campaign_name, c.region, c.sender, c.subject,
                c.total_recipients, c.status, c.scheduled_at, c.created_at,
                c.tag_name, c.template_id, c.timezone_name,
                COALESCE(t.name, 'Standard Template') as template_name
            FROM campaigns c
            LEFT JOIN email_templates t ON c.template_id = t.id
            WHERE c.status = 'scheduled'
            ORDER BY c.scheduled_at ASC
            LIMIT ? OFFSET ?
        """, (limit, offset))
        campaigns_list = [dict(r) for r in cursor.fetchall()]

        cursor.execute("SELECT COUNT(*) FROM campaigns WHERE status = 'scheduled'")
        total = cursor.fetchone()[0]

        return {"total": total, "items": campaigns_list, "limit": limit, "offset": offset}



