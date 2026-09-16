"""
Validation module for email addresses, regions, senders, dates, timezones,
and bulk recipient lists.
"""
import re
import csv
import io
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, available_timezones
from typing import List, Dict, Any, Tuple, Optional

from backend.config import canonicalize_region, get_region_config, DEFAULT_TIMEZONE
from backend.database import list_verified_senders

EMAIL_REGEX = re.compile(
    r"^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+$"
)

def is_valid_email(email: str) -> bool:
    """Validate email format with standard RFC regex and length limits."""
    if not email or not isinstance(email, str):
        return False
    email = email.strip()
    if len(email) > 254 or len(email) < 5:
        return False
    return bool(EMAIL_REGEX.match(email))

def validate_region(region_input: str) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Validate that region is one of the supported Alibaba Cloud DirectMail regions.
    Returns: (is_valid, canonical_region_key, error_message)
    """
    if not region_input:
        return False, None, "Region is required (Singapore, Germany, or United States)."
    canonical = canonicalize_region(region_input)
    if not canonical:
        return False, None, f"Unsupported region '{region_input}'. Allowed: Singapore, Germany, United States."
    return True, canonical, None

def validate_sender(region_key: str, sender_email: str) -> Tuple[bool, Optional[str]]:
    """
    Verify that sender email is valid and belongs to the configured verified senders for the region.
    """
    if not is_valid_email(sender_email):
        return False, f"Invalid sender email format: '{sender_email}'."
    
    verified_list = list_verified_senders(region_key)
    configured_emails = {s["email"].lower() for s in verified_list}
    
    # Also check region default senders
    conf = get_region_config(region_key)
    if conf:
        configured_emails.update(e.lower() for e in conf.get("default_senders", []))

    if sender_email.strip().lower() not in configured_emails:
        return False, f"Sender '{sender_email}' is not configured as a verified sender for region '{region_key}'."
    
    return True, None

def validate_timezone(tz_name: str) -> Tuple[bool, str, Optional[str]]:
    """
    Validate that the timezone string is valid according to IANA database.
    Returns: (is_valid, canonical_tz_name, error_message)
    """
    if not tz_name or not tz_name.strip():
        return True, DEFAULT_TIMEZONE, None
    tz_clean = tz_name.strip()
    try:
        ZoneInfo(tz_clean)
        return True, tz_clean, None
    except Exception:
        return False, DEFAULT_TIMEZONE, f"Unknown timezone: '{tz_clean}'."

def parse_and_validate_scheduled_time(
    scheduled_str: str,
    tz_name: str = DEFAULT_TIMEZONE
) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Parse a user-provided date/time string with given timezone, verify it is in the future,
    and convert to UTC ISO 8601 string.
    Supported inputs: ISO format ('2026-09-15T16:30'), or date + time string.
    Returns: (is_valid, utc_iso_string, error_message)
    """
    if not scheduled_str:
        return False, None, "Scheduled timestamp is required."
    
    is_tz_valid, clean_tz, tz_err = validate_timezone(tz_name)
    if not is_tz_valid:
        return False, None, tz_err
    
    user_tz = ZoneInfo(clean_tz)
    
    # Try parsing multiple date formats
    clean_str = scheduled_str.strip().replace(" ", "T")
    parsed_dt = None
    formats = [
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d"
    ]
    for fmt in formats:
        try:
            parsed_dt = datetime.strptime(clean_str, fmt)
            break
        except ValueError:
            continue
    
    if not parsed_dt:
        return False, None, f"Could not parse scheduled time: '{scheduled_str}'. Expected format: YYYY-MM-DD HH:MM."

    # Attach the user's selected timezone
    localized_dt = parsed_dt.replace(tzinfo=user_tz)
    
    # Convert to UTC
    utc_dt = localized_dt.astimezone(timezone.utc)
    now_utc = datetime.now(timezone.utc)

    # Validate that it is in the future (at least 30 seconds ahead)
    diff = (utc_dt - now_utc).total_seconds()
    if diff <= 10:
        return False, None, f"Scheduled time must be in the future (current time in {clean_tz}: {now_utc.astimezone(user_tz).strftime('%Y-%m-%d %H:%M')})."

    utc_iso = utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return True, utc_iso, None

def parse_bulk_recipients_text(text: str) -> Dict[str, Any]:
    """
    Parse recipient emails from plain text or pasted list.
    Supports comma, newline, semicolon, or whitespace separation.
    """
    if not text:
        return {"total": 0, "valid": [], "invalid": [], "duplicates": []}
    
    # Split by comma, semicolon, newline
    tokens = re.split(r"[,;\n\r]+", text)
    valid = []
    invalid = []
    duplicates = []
    seen = set()

    for raw in tokens:
        item = raw.strip()
        if not item:
            continue
        # If item has angle brackets e.g. "John Doe <john@example.com>"
        match = re.search(r"<([^>]+)>", item)
        email = match.group(1).strip() if match else item

        if not is_valid_email(email):
            invalid.append(item)
            continue

        email_lower = email.lower()
        if email_lower in seen:
            duplicates.append(email)
        else:
            seen.add(email_lower)
            valid.append(email)

    return {
        "total": len(valid) + len(invalid) + len(duplicates),
        "valid": valid,
        "invalid": invalid,
        "duplicates": duplicates
    }

def parse_bulk_recipients_csv(csv_content: str) -> Dict[str, Any]:
    """
    Parse recipient emails from CSV content.
    Automatically detects column headers like 'email', 'e-mail', 'recipient', 'mail'
    or defaults to the first column.
    """
    valid = []
    invalid = []
    duplicates = []
    seen = set()

    f = io.StringIO(csv_content.strip())
    reader = csv.reader(f)
    rows = list(reader)
    if not rows:
        return {"total": 0, "valid": [], "invalid": [], "duplicates": []}

    header = [h.strip().lower() for h in rows[0]]
    email_col_idx = 0
    start_row = 0

    # Check if first row is header
    candidate_cols = ["email", "e-mail", "email address", "recipient", "mail", "to"]
    for idx, col_name in enumerate(header):
        if col_name in candidate_cols:
            email_col_idx = idx
            start_row = 1
            break
    else:
        # If first row contains an actual valid email, it is not a header
        if is_valid_email(rows[0][0]):
            start_row = 0
        else:
            start_row = 1  # Assume generic header

    for row in rows[start_row:]:
        if not row or email_col_idx >= len(row):
            continue
        raw_val = row[email_col_idx].strip()
        if not raw_val:
            continue
        
        match = re.search(r"<([^>]+)>", raw_val)
        email = match.group(1).strip() if match else raw_val

        if not is_valid_email(email):
            invalid.append(raw_val)
            continue

        email_lower = email.lower()
        if email_lower in seen:
            duplicates.append(email)
        else:
            seen.add(email_lower)
            valid.append(email)

    return {
        "total": len(valid) + len(invalid) + len(duplicates),
        "valid": valid,
        "invalid": invalid,
        "duplicates": duplicates
    }
