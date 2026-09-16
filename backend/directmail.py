"""
Alibaba Cloud DirectMail API Client and HMAC-SHA1 RPC Signer.
Handles request signing, canonical query formation, network dispatch,
and test-mode simulation without credential exposure.
"""
import hmac
import hashlib
import base64
import uuid
import time
import re
import json
import logging
import urllib.parse
from datetime import datetime, timezone
from typing import Dict, Any, Tuple, Optional
import requests

from backend.config import get_region_config, get_region_credentials

logger = logging.getLogger("directmail")
logging.basicConfig(level=logging.INFO)

DIRECTMAIL_API_VERSION = "2015-11-23"

def percent_encode(value: Any) -> str:
    """
    Encode according to Alibaba Cloud POP/RPC signature rules:
    - Characters A-Z, a-z, 0-9, and '-', '_', '.', '~' are NOT encoded.
    - Other characters are encoded with %XY in uppercase.
    - Spaces are encoded as %20 (not +).
    - Asterisk '*' is encoded as %2A.
    """
    if value is None:
        return ""
    str_val = str(value)
    res = urllib.parse.quote(str_val, safe="~")
    # quote already handles '~' when safe='~', encodes space as %20, and encodes '*' as %2A
    return res

def build_canonicalized_query_string(params: Dict[str, Any]) -> str:
    """
    Sort parameters alphabetically by key and construct percent-encoded query string:
    key1=value1&key2=value2...
    """
    sorted_keys = sorted(params.keys())
    pairs = []
    for key in sorted_keys:
        val = params[key]
        if val is None or val == "":
            continue
        encoded_key = percent_encode(key)
        encoded_val = percent_encode(val)
        pairs.append(f"{encoded_key}={encoded_val}")
    return "&".join(pairs)

def calculate_signature(
    http_method: str,
    params: Dict[str, Any],
    access_key_secret: str
) -> Tuple[str, str]:
    """
    Calculate HMAC-SHA1 signature according to Alibaba Cloud RPC specification.
    Returns: (Signature, StringToSign)
    """
    canonical_query = build_canonicalized_query_string(params)
    string_to_sign = f"{http_method.upper()}&%2F&{percent_encode(canonical_query)}"
    
    secret_key = f"{access_key_secret}&"
    h = hmac.new(secret_key.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha1)
    signature = base64.b64encode(h.digest()).decode("utf-8")
    return signature, string_to_sign

def sanitize_for_logging(data: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy of data with sensitive parameters redacted."""
    sensitive_keys = {"AccessKeySecret", "access_key_secret", "Signature", "signature"}
    sanitized = {}
    for k, v in data.items():
        if k in sensitive_keys:
            sanitized[k] = "[REDACTED]"
        else:
            sanitized[k] = v
    return sanitized

def simulate_directmail_response(
    region_key: str,
    sender: str,
    recipient: str,
    subject: str,
    attempts: int = 1
) -> Dict[str, Any]:
    """
    Simulate authentic Alibaba Cloud DirectMail API response for dev/test environments.
    Guarantees full offline testability and realistic RFC-compliant responses.
    """
    time.sleep(0.08)  # simulate realistic API round-trip delay
    req_id = f"SIM-{uuid.uuid4().hex[:8].upper()}-{uuid.uuid4().hex[:4].upper()}-{uuid.uuid4().hex[:12].upper()}"
    env_id = f"2026{int(time.time())}{uuid.uuid4().hex[:6]}"

    # Test error simulation triggers
    if "[SIMULATE_RETRY]" in subject and attempts < 2:
        return {
            "success": False,
            "status_code": 503,
            "error_code": "ServiceUnavailable.Temporary",
            "error_message": "DirectMail service temporarily busy; retry recommended.",
            "request_id": req_id,
            "env_id": None,
            "is_retryable": True,
            "raw_response": {"Code": "ServiceUnavailable.Temporary", "Message": "DirectMail service temporarily busy", "RequestId": req_id}
        }

    if "[SIMULATE_FAIL]" in subject or "fail@error.invalid" in recipient:
        return {
            "success": False,
            "status_code": 400,
            "error_code": "InvalidToAddress.NotFound",
            "error_message": "Recipient address was rejected by mail host.",
            "request_id": req_id,
            "env_id": None,
            "is_retryable": False,
            "raw_response": {"Code": "InvalidToAddress.NotFound", "Message": "Simulated permanent delivery rejection", "RequestId": req_id}
        }

    return {
        "success": True,
        "status_code": 200,
        "error_code": None,
        "error_message": None,
        "request_id": req_id,
        "env_id": env_id,
        "is_retryable": False,
        "raw_response": {
            "EnvId": env_id,
            "RequestId": req_id,
            "Message": "Email accepted by DirectMail gateway (Test Mode)"
        }
    }

class DirectMailClient:
    """Client for dispatching SingleSendMail requests to Alibaba Cloud DirectMail."""

    def __init__(self, region_key: str):
        self.region_config = get_region_config(region_key)
        if not self.region_config:
            raise ValueError(f"Unsupported Alibaba Cloud region: {region_key}")
        self.region_key = self.region_config["key"]
        self.endpoint = self.region_config["endpoint"]
        self.region_id = self.region_config["region_id"]
        
        creds = get_region_credentials(self.region_key)
        self.access_key_id = creds["access_key_id"]
        self.access_key_secret = creds["access_key_secret"]

    def has_valid_credentials(self) -> bool:
        """Check whether credentials are set on server."""
        return bool(self.access_key_id and self.access_key_secret)

    def send_single_mail(
        self,
        sender: str,
        recipient: str,
        subject: str,
        html_body: Optional[str] = None,
        text_body: Optional[str] = None,
        from_alias: Optional[str] = None,
        tag_name: Optional[str] = None,
        address_type: int = 0,
        reply_to_address: bool = False,
        force_test_mode: bool = False,
        attempt: int = 1
    ) -> Dict[str, Any]:
        """
        Execute Alibaba Cloud DirectMail SingleSendMail API call.
        """
        # If test mode is active or credentials missing, run high-fidelity simulator
        if force_test_mode or not self.has_valid_credentials():
            logger.info(
                f"[DirectMail TEST MODE] Region: {self.region_key} | Sender: {sender} | Recipient: {recipient}"
            )
            return simulate_directmail_response(
                self.region_key, sender, recipient, subject, attempts=attempt
            )

        # Real Live Alibaba Cloud DirectMail SingleSendMail call
        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        nonce = str(uuid.uuid4())

        params: Dict[str, Any] = {
            "Format": "JSON",
            "Version": DIRECTMAIL_API_VERSION,
            "AccessKeyId": self.access_key_id,
            "SignatureMethod": "HMAC-SHA1",
            "Timestamp": now_utc,
            "SignatureVersion": "1.0",
            "SignatureNonce": nonce,
            "Action": "SingleSendMail",
            "RegionId": self.region_id,
            "AccountName": sender,
            "AddressType": int(address_type),
            "ReplyToAddress": "true" if reply_to_address else "false",
            "ToAddress": recipient,
            "Subject": subject,
        }

        if html_body:
            params["HtmlBody"] = html_body
        if text_body:
            params["TextBody"] = text_body
        if from_alias:
            params["FromAlias"] = from_alias
        if tag_name:
            params["TagName"] = tag_name

        # Calculate signature
        signature, _ = calculate_signature("POST", params, self.access_key_secret)
        params["Signature"] = signature

        url = f"https://{self.endpoint}/"
        headers = {
            "Content-Type": "application/x-www-form-urlencoded;charset=utf-8",
            "User-Agent": "Alibaba-DirectMail-Agent/1.0"
        }

        logger.info(
            f"[DirectMail LIVE] Region: {self.region_key} | Endpoint: {self.endpoint} | To: {recipient} | Subject: {subject[:30]}"
        )

        try:
            response = requests.post(url, data=params, headers=headers, timeout=15.0)
            status_code = response.status_code
            
            try:
                res_data = response.json()
            except Exception:
                res_data = {"raw_text": response.text[:500]}

            # DirectMail successful response contains EnvId / RequestId
            if 200 <= status_code < 300:
                req_id = res_data.get("RequestId", "")
                env_id = res_data.get("EnvId", "")
                return {
                    "success": True,
                    "status_code": status_code,
                    "error_code": None,
                    "error_message": None,
                    "request_id": req_id,
                    "env_id": env_id,
                    "is_retryable": False,
                    "raw_response": res_data
                }
            else:
                err_code = res_data.get("Code", f"HTTP_{status_code}")
                err_msg = res_data.get("Message", response.text[:200])
                req_id = res_data.get("RequestId", "")
                
                # Check retryability: 5xx, timeouts, throttling
                retryable_codes = {
                    "Throttling", "Rejected.Throttling", "ServiceUnavailable",
                    "InternalError", "RequestTimeout"
                }
                is_retryable = (status_code >= 500) or (err_code in retryable_codes)

                logger.warning(
                    f"[DirectMail Error] Region: {self.region_key} | Code: {err_code} | Msg: {err_msg} | ReqId: {req_id}"
                )

                return {
                    "success": False,
                    "status_code": status_code,
                    "error_code": err_code,
                    "error_message": err_msg,
                    "request_id": req_id,
                    "env_id": None,
                    "is_retryable": is_retryable,
                    "raw_response": res_data
                }

        except requests.exceptions.Timeout as ex:
            logger.error(f"[DirectMail Timeout] Region: {self.region_key}: {str(ex)}")
            return {
                "success": False,
                "status_code": 408,
                "error_code": "RequestTimeout",
                "error_message": "Network timeout calling Alibaba Cloud DirectMail API endpoint.",
                "request_id": None,
                "env_id": None,
                "is_retryable": True,
                "raw_response": {"error": "Timeout", "detail": str(ex)}
            }
        except requests.exceptions.ConnectionError as ex:
            logger.error(f"[DirectMail Connection Error] Region: {self.region_key}: {str(ex)}")
            return {
                "success": False,
                "status_code": 503,
                "error_code": "ConnectionError",
                "error_message": f"Failed to connect to Alibaba Cloud endpoint ({self.endpoint}).",
                "request_id": None,
                "env_id": None,
                "is_retryable": True,
                "raw_response": {"error": "ConnectionError", "detail": str(ex)}
            }
        except Exception as ex:
            logger.error(f"[DirectMail Unexpected Error] Region: {self.region_key}: {str(ex)}")
            return {
                "success": False,
                "status_code": 500,
                "error_code": "InternalError",
                "error_message": f"Unexpected error during DirectMail API dispatch: {str(ex)}",
                "request_id": None,
                "env_id": None,
                "is_retryable": False,
                "raw_response": {"error": type(ex).__name__, "detail": str(ex)}
            }

    def query_domains(self) -> Dict[str, Any]:
        """
        Query live configured email domains from Alibaba Cloud DirectMail (QueryDomainByParam).
        """
        if not self.has_valid_credentials():
            return {"total": 0, "domains": [], "live": False}
        
        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        nonce = str(uuid.uuid4())
        params = {
            "Format": "JSON",
            "Version": DIRECTMAIL_API_VERSION,
            "AccessKeyId": self.access_key_id,
            "SignatureMethod": "HMAC-SHA1",
            "Timestamp": now_utc,
            "SignatureVersion": "1.0",
            "SignatureNonce": nonce,
            "Action": "QueryDomainByParam",
            "RegionId": self.region_id,
            "PageNo": 1,
            "PageSize": 50
        }
        sig, _ = calculate_signature("POST", params, self.access_key_secret)
        params["Signature"] = sig
        url = f"https://{self.endpoint}/"
        try:
            r = requests.post(url, data=params, timeout=12.0)
            if r.status_code == 200:
                data = r.json()
                domain_list = data.get("data", {}).get("domain", [])
                return {
                    "total": data.get("TotalCount", len(domain_list)),
                    "domains": domain_list,
                    "live": True,
                    "request_id": data.get("RequestId")
                }
            return {"total": 0, "domains": [], "live": False, "error": r.text}
        except Exception as e:
            logger.error(f"[QueryDomainByParam Error] {str(e)}")
            return {"total": 0, "domains": [], "live": False, "error": str(e)}

    def query_mail_addresses(self) -> Dict[str, Any]:
        """
        Query live verified sender mail addresses from Alibaba Cloud DirectMail (QueryMailAddressByParam).
        """
        res = self._call_alibaba_rpc("QueryMailAddressByParam", {"PageNo": 1, "PageSize": 50})
        if res.get("success", False):
            mail_list = res.get("data", {}).get("mailAddress", [])
            return {
                "total": res.get("TotalCount", len(mail_list)),
                "mail_addresses": mail_list,
                "live": True,
                "request_id": res.get("RequestId")
            }
        return {"total": 0, "mail_addresses": [], "live": False, "error": res.get("error", "Failed")}

    def _call_alibaba_rpc(self, action: str, extra_params: Optional[Dict[str, Any]] = None, timeout: float = 12.0) -> Dict[str, Any]:
        """Generic helper to invoke any official Alibaba Cloud DirectMail RPC action."""
        if not self.has_valid_credentials():
            return {"success": False, "error": "Credentials not configured", "live": False}
        
        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        nonce = str(uuid.uuid4())
        params = {
            "Format": "JSON",
            "Version": DIRECTMAIL_API_VERSION,
            "AccessKeyId": self.access_key_id,
            "SignatureMethod": "HMAC-SHA1",
            "Timestamp": now_utc,
            "SignatureVersion": "1.0",
            "SignatureNonce": nonce,
            "Action": action,
            "RegionId": self.region_id
        }
        if extra_params:
            for k, v in extra_params.items():
                if v is not None:
                    params[k] = v

        sig, _ = calculate_signature("POST", params, self.access_key_secret)
        params["Signature"] = sig
        url = f"https://{self.endpoint}/"
        try:
            r = requests.post(url, data=params, timeout=timeout)
            try:
                res_data = r.json()
            except Exception:
                res_data = {"raw_text": r.text[:500]}
            
            if 200 <= r.status_code < 300:
                res_data["success"] = True
                res_data["live"] = True
                return res_data
            else:
                err_code = res_data.get("Code", f"HTTP_{r.status_code}")
                err_msg = res_data.get("Message", r.text[:200])
                return {"success": False, "live": True, "error_code": err_code, "error": err_msg, "raw": res_data}
        except Exception as e:
            logger.error(f"Alibaba RPC Error [{action}]: {str(e)}")
            return {"success": False, "live": False, "error": str(e)}

    def query_account_summary(self) -> Dict[str, Any]:
        """Fetch live account quota, limits, template counts from Alibaba Cloud."""
        return self._call_alibaba_rpc("DescAccountSummary")

    def query_domain_details(self, domain_id: int) -> Dict[str, Any]:
        """Fetch CNAME, SPF, DKIM, DMARC records for a domain."""
        return self._call_alibaba_rpc("DescDomain", {"DomainId": domain_id})

    def create_domain(self, domain_name: str) -> Dict[str, Any]:
        """Add a new email domain in Alibaba Cloud DirectMail."""
        return self._call_alibaba_rpc("CreateDomain", {"DomainName": domain_name.strip()})

    def delete_domain(self, domain_id: int) -> Dict[str, Any]:
        """Delete an email domain from Alibaba Cloud DirectMail."""
        return self._call_alibaba_rpc("DeleteDomain", {"DomainId": domain_id})

    def create_mail_address(self, account_name: str, reply_address: Optional[str] = None, send_type: str = "batch") -> Dict[str, Any]:
        """Add a new sender address in Alibaba Cloud DirectMail."""
        extra = {
            "AccountName": account_name.strip(),
            "Sendtype": send_type
        }
        if reply_address:
            extra["ReplyAddress"] = reply_address.strip()
        return self._call_alibaba_rpc("CreateMailAddress", extra)

    def delete_mail_address(self, mail_address_id: int) -> Dict[str, Any]:
        """Delete a sender address from Alibaba Cloud DirectMail."""
        return self._call_alibaba_rpc("DeleteMailAddress", {"MailAddressId": mail_address_id})

    def query_templates(self, page_no: int = 1, page_size: int = 50) -> Dict[str, Any]:
        """Query email templates list from Alibaba Cloud."""
        return self._call_alibaba_rpc("QueryTemplateByParam", {"PageNo": page_no, "PageSize": page_size})

    def desc_template(self, template_id: int) -> Dict[str, Any]:
        """Fetch template content & subject from Alibaba Cloud."""
        return self._call_alibaba_rpc("DescTemplate", {"TemplateId": template_id})

    def create_template(self, template_name: str, subject: str, nick_name: str, html_text: str, template_type: int = 0) -> Dict[str, Any]:
        """Create an email template in Alibaba Cloud DirectMail."""
        return self._call_alibaba_rpc("CreateTemplate", {
            "TemplateName": template_name.strip(),
            "TemplateSubject": subject.strip(),
            "TemplateNickName": nick_name.strip(),
            "TemplateText": html_text,
            "TemplateType": template_type
        })

    def delete_template(self, template_id: int) -> Dict[str, Any]:
        """Delete an email template from Alibaba Cloud DirectMail."""
        return self._call_alibaba_rpc("DeleteTemplate", {"TemplateId": template_id})

    def query_tasks(self, page_no: int = 1, page_size: int = 20, status: Optional[int] = None) -> Dict[str, Any]:
        """Query batch tasks from Alibaba Cloud DirectMail."""
        extra = {"PageNo": page_no, "PageSize": page_size}
        if status is not None:
            extra["TaskStatus"] = status
        return self._call_alibaba_rpc("QueryTaskByParam", extra)

    def query_tags(self, page_no: int = 1, page_size: int = 50) -> Dict[str, Any]:
        """Query classification tags from Alibaba Cloud DirectMail."""
        return self._call_alibaba_rpc("QueryTagByParam", {"PageNo": page_no, "PageSize": page_size})

    def create_tag(self, tag_name: str) -> Dict[str, Any]:
        """Create a classification tag in Alibaba Cloud DirectMail."""
        return self._call_alibaba_rpc("CreateTag", {"TagName": tag_name.strip()})

    def delete_tag(self, tag_id: Optional[int] = None, tag_name: Optional[str] = None) -> Dict[str, Any]:
        """Delete an email tag in Alibaba Cloud DirectMail."""
        extra: Dict[str, Any] = {}
        if tag_id:
            extra["TagId"] = tag_id
        if tag_name:
            extra["TagName"] = tag_name.strip()
        return self._call_alibaba_rpc("DeleteTag", extra)

    def modify_tag(self, tag_id: int, tag_name: str) -> Dict[str, Any]:
        """Update an email tag name in Alibaba Cloud DirectMail."""
        return self._call_alibaba_rpc("ModifyTag", {"TagId": tag_id, "TagName": tag_name.strip()})

    def modify_template(self, template_id: int, template_name: str, subject: str, nick_name: str, html_text: str) -> Dict[str, Any]:
        """Modify an existing email template in Alibaba Cloud DirectMail."""
        return self._call_alibaba_rpc("ModifyTemplate", {
            "TemplateId": template_id,
            "TemplateName": template_name.strip(),
            "TemplateSubject": subject.strip(),
            "TemplateNickName": nick_name.strip(),
            "TemplateText": html_text
        })

    def query_delivery_stats(self, start_date: str, end_date: str, tag_name: Optional[str] = None) -> Dict[str, Any]:
        """Query aggregate delivery statistics for a date range from Alibaba Cloud."""
        extra = {"StartTime": start_date, "EndTime": end_date}
        if tag_name:
            extra["TagName"] = tag_name
        return self._call_alibaba_rpc("SenderStatisticsByTagNameAndBatchID", extra)

    def query_tracking_events(self, page_no: int = 1, page_size: int = 30, start_time: Optional[str] = None, to_address: Optional[str] = None) -> Dict[str, Any]:
        """Query granular delivery and tracking events from Alibaba Cloud."""
        extra = {"PageNo": page_no, "PageSize": page_size}
        if start_time:
            extra["StartTime"] = start_time
        if to_address:
            extra["ToAddress"] = to_address
        return self._call_alibaba_rpc("SenderStatisticsDetailByParam", extra)

    def query_invalid_addresses(self, page_no: int = 1, page_size: int = 50) -> Dict[str, Any]:
        """Query bounced/invalid recipient addresses from Alibaba Cloud."""
        return self._call_alibaba_rpc("QueryInvalidAddress", {"PageNo": page_no, "PageSize": page_size})


