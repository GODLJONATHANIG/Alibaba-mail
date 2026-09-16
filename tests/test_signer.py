"""
Unit tests for Alibaba Cloud POP/RPC signature calculation and canonical encoding.
"""
import unittest
import urllib.parse
from backend.directmail import percent_encode, build_canonicalized_query_string, calculate_signature

class TestDirectMailSigner(unittest.TestCase):

    def test_percent_encode_rules(self):
        # Unreserved characters must not be encoded: A-Z, a-z, 0-9, -, _, ., ~
        self.assertEqual(percent_encode("abcXYZ123-_.~"), "abcXYZ123-_.~")
        
        # Space must be encoded as %20, not +
        self.assertEqual(percent_encode("hello world"), "hello%20world")
        
        # Asterisk must be encoded as %2A
        self.assertEqual(percent_encode("test*value"), "test%2Avalue")
        
        # Plus must be encoded as %2B
        self.assertEqual(percent_encode("a+b"), "a%2Bb")
        
        # Slash must be encoded as %2F
        self.assertEqual(percent_encode("/"), "%2F")

    def test_build_canonicalized_query_string_order(self):
        params = {
            "Version": "2015-11-23",
            "Action": "SingleSendMail",
            "Format": "JSON",
            "AccountName": "test@example.com",
            "Subject": "Hello World"
        }
        canonical = build_canonicalized_query_string(params)
        
        # Keys must be alphabetically sorted: AccountName, Action, Format, Subject, Version
        expected_keys = ["AccountName", "Action", "Format", "Subject", "Version"]
        actual_keys = [pair.split("=")[0] for pair in canonical.split("&")]
        self.assertEqual(actual_keys, expected_keys)
        self.assertIn("Subject=Hello%20World", canonical)

    def test_calculate_signature(self):
        params = {
            "Format": "JSON",
            "Version": "2015-11-23",
            "Action": "SingleSendMail",
            "AccessKeyId": "testid",
            "SignatureMethod": "HMAC-SHA1",
            "SignatureVersion": "1.0",
            "SignatureNonce": "123456",
            "Timestamp": "2026-09-15T12:00:00Z"
        }
        secret = "testsecret"
        sig, string_to_sign = calculate_signature("POST", params, secret)
        
        self.assertTrue(string_to_sign.startswith("POST&%2F&"))
        self.assertTrue(len(sig) > 10)
        # Verify idempotency of calculation
        sig2, _ = calculate_signature("POST", params, secret)
        self.assertEqual(sig, sig2)

if __name__ == "__main__":
    unittest.main()
