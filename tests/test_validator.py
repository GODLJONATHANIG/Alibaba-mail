"""
Unit tests for email, region, timezone, scheduled date, and CSV parsing.
"""
import unittest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from backend.validator import (
    is_valid_email,
    validate_region,
    validate_timezone,
    parse_and_validate_scheduled_time,
    parse_bulk_recipients_text,
    parse_bulk_recipients_csv
)

class TestValidator(unittest.TestCase):

    def test_email_validation(self):
        self.assertTrue(is_valid_email("user@example.com"))
        self.assertTrue(is_valid_email("first.last+tag@sub.domain.org"))
        self.assertFalse(is_valid_email("plainaddress"))
        self.assertFalse(is_valid_email("@missinguser.com"))
        self.assertFalse(is_valid_email("user@.com"))
        self.assertFalse(is_valid_email(""))

    def test_region_validation(self):
        valid, key, _ = validate_region("singapore")
        self.assertTrue(valid)
        self.assertEqual(key, "singapore")

        valid, key, _ = validate_region("germany")
        self.assertTrue(valid)
        self.assertEqual(key, "germany")

        valid, key, _ = validate_region("frankfurt")
        self.assertTrue(valid)
        self.assertEqual(key, "germany")

        valid, key, _ = validate_region("united states")
        self.assertTrue(valid)
        self.assertEqual(key, "united_states")

        valid, key, _ = validate_region("usa")
        self.assertTrue(valid)
        self.assertEqual(key, "united_states")

        valid, _, err = validate_region("antarctica")
        self.assertFalse(valid)
        self.assertIn("Unsupported", err)

    def test_timezone_validation(self):
        valid, tz, _ = validate_timezone("Asia/Kolkata")
        self.assertTrue(valid)
        self.assertEqual(tz, "Asia/Kolkata")

        valid, tz, _ = validate_timezone("UTC")
        self.assertTrue(valid)

        valid, _, err = validate_timezone("NonExistent/Zone")
        self.assertFalse(valid)

    def test_scheduled_time_future(self):
        tz = "Asia/Kolkata"
        user_tz = ZoneInfo(tz)
        
        # Future date (+1 hour)
        future_dt = datetime.now(user_tz) + timedelta(hours=1)
        future_str = future_dt.strftime("%Y-%m-%d %H:%M")
        valid, utc_str, err = parse_and_validate_scheduled_time(future_str, tz)
        self.assertTrue(valid)
        self.assertTrue(utc_str.endswith("Z"))

        # Past date (-1 hour)
        past_dt = datetime.now(user_tz) - timedelta(hours=1)
        past_str = past_dt.strftime("%Y-%m-%d %H:%M")
        valid, _, err = parse_and_validate_scheduled_time(past_str, tz)
        self.assertFalse(valid)
        self.assertIn("must be in the future", err)

    def test_parse_bulk_text(self):
        text = """
        alice@example.com, bob@example.com
        invalid-email
        carol@domain.co; Alice@example.com
        """
        res = parse_bulk_recipients_text(text)
        self.assertEqual(len(res["valid"]), 3)  # alice, bob, carol
        self.assertEqual(len(res["invalid"]), 1) # invalid-email
        self.assertEqual(len(res["duplicates"]), 1) # Alice@example.com (case insensitive duplicate)

    def test_parse_bulk_csv(self):
        csv_data = """Name,Email,Company
Alice,alice@example.com,Acme
Bob,bob@example.com,Initech
BadGuy,not-an-email,None
AliceAgain,alice@example.com,Acme
Charlie,charlie@sample.org,Hooli
"""
        res = parse_bulk_recipients_csv(csv_data)
        self.assertIn("alice@example.com", res["valid"])
        self.assertIn("bob@example.com", res["valid"])
        self.assertIn("charlie@sample.org", res["valid"])
        self.assertEqual(len(res["valid"]), 3)
        self.assertEqual(len(res["invalid"]), 1)
        self.assertEqual(len(res["duplicates"]), 1)

if __name__ == "__main__":
    unittest.main()
