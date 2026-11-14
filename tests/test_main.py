"""Tests for src.main module."""

import json
import os
import shutil
import unittest
from unittest.mock import MagicMock, patch

from src.checker import CheckResult, STATUS_AVAILABLE, STATUS_QUOTA_ONLY, STATUS_UNAVAILABLE, STATUS_ERROR


class TestMain(unittest.TestCase):
    def setUp(self):
        if os.path.exists("results"):
            shutil.rmtree("results")

    def tearDown(self):
        if os.path.exists("results"):
            shutil.rmtree("results")

    @patch("src.main.send_notification")
    @patch("src.main.check_availability")
    @patch("src.main.oci")
    @patch("src.main.create_limits_client")
    @patch("src.main.create_compute_client")
    @patch("src.main.build_oci_config")
    @patch("src.main.load_config")
    def test_sends_email_on_available(
        self, mock_cfg, mock_oci_cfg, mock_compute, mock_limits,
        mock_oci_mod, mock_check, mock_notify
    ):
        mock_cfg.return_value = MagicMock()
        mock_oci_cfg.return_value = {"test": "config"}
        mock_check.return_value = CheckResult(
            status=STATUS_AVAILABLE,
            timestamp="2026-11-14T10-00-00Z",
            shape_available=True,
        )
        mock_notify.return_value = True

        from src.main import main
        code = main()

        self.assertEqual(code, 0)
        mock_notify.assert_called_once()

    @patch("src.main.send_notification")
    @patch("src.main.check_availability")
    @patch("src.main.oci")
    @patch("src.main.create_limits_client")
    @patch("src.main.create_compute_client")
    @patch("src.main.build_oci_config")
    @patch("src.main.load_config")
    def test_does_not_send_email_on_quota_only(
        self, mock_cfg, mock_oci_cfg, mock_compute, mock_limits,
        mock_oci_mod, mock_check, mock_notify
    ):
        mock_cfg.return_value = MagicMock()
        mock_oci_cfg.return_value = {"test": "config"}
        mock_check.return_value = CheckResult(
            status=STATUS_QUOTA_ONLY,
            timestamp="2026-11-14T10-00-00Z",
        )

        from src.main import main
        code = main()

        self.assertEqual(code, 0)
        mock_notify.assert_not_called()

    @patch("src.main.send_notification")
    @patch("src.main.check_availability")
    @patch("src.main.oci")
    @patch("src.main.create_limits_client")
    @patch("src.main.create_compute_client")
    @patch("src.main.build_oci_config")
    @patch("src.main.load_config")
    def test_does_not_send_email_on_unavailable(
        self, mock_cfg, mock_oci_cfg, mock_compute, mock_limits,
        mock_oci_mod, mock_check, mock_notify
    ):
        mock_cfg.return_value = MagicMock()
        mock_oci_cfg.return_value = {"test": "config"}
        mock_check.return_value = CheckResult(
            status=STATUS_UNAVAILABLE,
            timestamp="2026-11-14T10-00-00Z",
        )

        from src.main import main
        code = main()

        self.assertEqual(code, 0)
        mock_notify.assert_not_called()

    @patch("src.main.send_notification")
    @patch("src.main.check_availability")
    @patch("src.main.oci")
    @patch("src.main.create_limits_client")
    @patch("src.main.create_compute_client")
    @patch("src.main.build_oci_config")
    @patch("src.main.load_config")
    def test_writes_result_json(
        self, mock_cfg, mock_oci_cfg, mock_compute, mock_limits,
        mock_oci_mod, mock_check, mock_notify
    ):
        mock_cfg.return_value = MagicMock()
        mock_oci_cfg.return_value = {"test": "config"}
        mock_check.return_value = CheckResult(
            status=STATUS_AVAILABLE,
            timestamp="2026-11-14T10-00-00Z",
            shape_available=True,
        )
        mock_notify.return_value = True

        from src.main import main
        main()

        files = os.listdir("results")
        self.assertTrue(len(files) > 0)
        with open(os.path.join("results", files[0])) as f:
            data = json.load(f)
        self.assertIn("status", data)
        self.assertEqual(data["status"], STATUS_AVAILABLE)

    @patch("src.main.load_config")
    def test_config_error_returns_1(self, mock_cfg):
        mock_cfg.side_effect = ValueError("Missing OCI_COMPARTMENT_ID")

        from src.main import main
        code = main()

        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
