"""
Configuration module for Alibaba Cloud DirectMail Multi-Region Email Agent.
Manages region endpoints, credential resolution, and system defaults.
"""
import os
from pathlib import Path
from typing import Dict, Any, Optional
from dotenv import load_dotenv

# Load environment variables from .env file if present
BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"
load_dotenv(dotenv_path=ENV_PATH)

# Supported Alibaba Cloud DirectMail Regions
# Official API endpoints:
# Singapore: ap-southeast-1 -> dm.ap-southeast-1.aliyuncs.com
# Germany (Frankfurt): eu-central-1 -> dm.eu-central-1.aliyuncs.com
# United States: us-east-1 -> dm.us-east-1.aliyuncs.com

SUPPORTED_REGIONS: Dict[str, Dict[str, Any]] = {
    "singapore": {
        "key": "singapore",
        "display_name": "Singapore",
        "region_id": "ap-southeast-1",
        "endpoint": "dm.ap-southeast-1.aliyuncs.com",
        "env_key_id": "ALIBABA_SG_ACCESS_KEY_ID",
        "env_key_secret": "ALIBABA_SG_ACCESS_KEY_SECRET",
        "default_senders": [
            "notifications-sg@directmail.example.com",
            "support-sg@directmail.example.com"
        ]
    },
    "germany": {
        "key": "germany",
        "display_name": "Germany (Frankfurt)",
        "region_id": "eu-central-1",
        "endpoint": "dm.eu-central-1.aliyuncs.com",
        "env_key_id": "ALIBABA_GERMANY_ACCESS_KEY_ID",
        "env_key_secret": "ALIBABA_GERMANY_ACCESS_KEY_SECRET",
        "default_senders": [
            "notifications-de@directmail.example.com",
            "support-de@directmail.example.com"
        ]
    },
    "united_states": {
        "key": "united_states",
        "display_name": "United States (Virginia)",
        "region_id": "us-east-1",
        "endpoint": "dm.us-east-1.aliyuncs.com",
        "env_key_id": "ALIBABA_US_ACCESS_KEY_ID",
        "env_key_secret": "ALIBABA_US_ACCESS_KEY_SECRET",
        "default_senders": [
            "notifications-us@directmail.example.com",
            "support-us@directmail.example.com"
        ]
    }
}

# Aliases for flexible user input (e.g. "sg", "frankfurt", "us")
REGION_ALIASES = {
    "sg": "singapore",
    "singapore": "singapore",
    "ap-southeast-1": "singapore",
    "de": "germany",
    "germany": "germany",
    "frankfurt": "germany",
    "eu-central-1": "germany",
    "us": "united_states",
    "usa": "united_states",
    "united states": "united_states",
    "united_states": "united_states",
    "us-east-1": "united_states"
}

def canonicalize_region(region_input: str) -> Optional[str]:
    """Resolve regional aliases to standard keys: singapore, germany, united_states."""
    if not region_input:
        return None
    normalized = region_input.strip().lower()
    return REGION_ALIASES.get(normalized)

def get_region_config(region_key: str) -> Optional[Dict[str, Any]]:
    """Return region metadata for a canonical region key."""
    canonical = canonicalize_region(region_key)
    return SUPPORTED_REGIONS.get(canonical) if canonical else None

def get_region_credentials(region_key: str) -> Dict[str, Optional[str]]:
    """
    Retrieve server-side Alibaba Cloud credentials for a region.
    Never expose the returned secret to the frontend!
    """
    conf = get_region_config(region_key)
    if not conf:
        return {"access_key_id": None, "access_key_secret": None}
    
    key_id = os.getenv(conf["env_key_id"]) or None
    key_secret = os.getenv(conf["env_key_secret"]) or None
    return {
        "access_key_id": key_id.strip() if key_id else None,
        "access_key_secret": key_secret.strip() if key_secret else None
    }

def is_test_mode() -> bool:
    """Check if test/mock mode is active via environment."""
    val = os.getenv("TEST_MODE", "true").strip().lower()
    return val in ("1", "true", "yes", "on")

DEFAULT_TIMEZONE = os.getenv("DEFAULT_TIMEZONE", "Asia/Kolkata")
DB_FILE_PATH = os.getenv("DATABASE_PATH", str(BASE_DIR / "email_agent.db"))
API_HOST = os.getenv("HOST", "0.0.0.0")
API_PORT = int(os.getenv("PORT", "8000"))
DEFAULT_RATE_LIMIT_QPS = float(os.getenv("RATE_LIMIT_QPS", "5.0"))
DEFAULT_MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
