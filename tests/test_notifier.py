"""Tests for src.notifier module."""

import smtplib
import unittest
from unittest.mock import MagicMock, patch

from src.checker import CheckResult, STATUS_AVAILABLE, STATUS_QUOTA_ONLY
from src.config import Config
from src.notifier import format_email_body, send_notification


def _config():
    return Config(
        region="ap-batam-1",
        compartment_id="ocid1.compartment.oc1..test",
        shape="VM.Standard.A1.Flex",
        ocpus=2.0,
        memory_gb=12.0,
        smtp_host="smtp.gmail.com",
        smtp_port=587,
        smtp_user="user@gmail.com",
        smtp_password="app-password",
        email_from="user@gmail.com",
        email_to="dest@gmail.com",
    )


def _available_result():
    return CheckResult(
        status=STATUS_AVAILABLE,
        timestamp="2026-11-14T10:00:00Z",
        quota_available=4.0,
        quota_used=0.0,
        quota_limit=4.0,
        memory_quota_available=24.0,
        memory_quota_used=0.0,
        memory_quota_limit=24.0,
        shape_available=True,
        ad_name="AD-1",
        details="Shape VM.Standard.A1.Flex available in AD AD-1",
    )


class TestFormatEmailBody(unittest.TestCase):
    def test_contains_status(self):
        body = format_email_body(_config(), _available_result())
        self.assertIn("AVAILABLE", body)

    def test_contains_region_and_shape(self):
        body = format_email_body(_config(), _available_result())
        self.assertIn("ap-batam-1", body)
        self.assertIn("VM.Standard.A1.Flex", body)

    def test_contains_quota_info(self):
        body = format_email_body(_config(), _available_result())
        self.assertIn("4.0", body)

    def test_contains_limitations(self):
        body = format_email_body(_config(), _available_result())
        self.assertIn("does not expose real-time host capacity", body)


class TestSendNotification(unittest.TestCase):
    @patch("src.notifier.smtplib.SMTP")
    def test_sends_for_available_status(self, mock_smtp_cls):
        mock_smtp = MagicMock()
        mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_smtp)
        mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

        result = send_notification(_config(), _available_result())

        self.assertTrue(result)
        mock_smtp.login.assert_called_once_with("user@gmail.com", "app-password")
        mock_smtp.send_message.assert_called_once()

    def test_suppressed_for_quota_only(self):
        qo_result = CheckResult(
            status=STATUS_QUOTA_ONLY,
            timestamp="2026-11-14T10:00:00Z",
        )
        result = send_notification(_config(), qo_result)
        self.assertFalse(result)

    @patch("src.notifier.smtplib.SMTP")
    def test_returns_false_on_smtp_auth_error(self, mock_smtp_cls):
        mock_smtp = MagicMock()
        mock_smtp.login.side_effect = smtplib.SMTPAuthenticationError(
            535, b"Bad credentials"
        )
        mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_smtp)
        mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

        result = send_notification(_config(), _available_result())

        self.assertFalse(result)

    @patch("src.notifier.smtplib.SMTP")
    def test_returns_false_on_connection_error(self, mock_smtp_cls):
        mock_smtp_cls.side_effect = OSError("Connection refused")

        result = send_notification(_config(), _available_result())

        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
