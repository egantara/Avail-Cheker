"""Tests for src.oci_auth module."""

import os
import unittest
from unittest.mock import patch, MagicMock


_VALID_OCI_ENV = {
    "OCI_USER_OCID": "ocid1.user.oc1..testuser",
    "OCI_TENANCY_OCID": "ocid1.tenancy.oc1..testtenancy",
    "OCI_FINGERPRINT": "aa:bb:cc:dd:ee:ff:00:11:22:33:44:55:66:77:88:99",
    "OCI_API_KEY": "-----BEGIN RSA PRIVATE KEY-----\nMIIBtest\n-----END RSA PRIVATE KEY-----",
    "OCI_REGION": "ap-batam-1",
}


class TestBuildOciConfig(unittest.TestCase):
    @patch("oci.config.validate_config")
    @patch.dict(os.environ, _VALID_OCI_ENV, clear=True)
    def test_build_config_populates_fields(self, mock_validate):
        from src.oci_auth import build_oci_config

        cfg = build_oci_config()
        self.assertEqual(cfg["user"], "ocid1.user.oc1..testuser")
        self.assertEqual(cfg["tenancy"], "ocid1.tenancy.oc1..testtenancy")
        self.assertEqual(cfg["region"], "ap-batam-1")
        self.assertIn("key_file", cfg)
        mock_validate.assert_called_once()

    @patch.dict(os.environ, {}, clear=True)
    def test_missing_user_raises(self):
        from src.oci_auth import build_oci_config

        with self.assertRaises(ValueError) as ctx:
            build_oci_config()
        self.assertIn("OCI_USER_OCID", str(ctx.exception))

    @patch.dict(os.environ, {"OCI_USER_OCID": "x"}, clear=True)
    def test_missing_multiple_raises(self):
        from src.oci_auth import build_oci_config

        with self.assertRaises(ValueError) as ctx:
            build_oci_config()
        self.assertIn("OCI_TENANCY_OCID", str(ctx.exception))

    @patch("oci.config.validate_config")
    @patch.dict(os.environ, _VALID_OCI_ENV, clear=True)
    def test_key_file_written(self, mock_validate):
        from src.oci_auth import build_oci_config

        cfg = build_oci_config()
        with open(cfg["key_file"], "r") as f:
            content = f.read()
        self.assertIn("BEGIN RSA PRIVATE KEY", content)
        os.unlink(cfg["key_file"])


class TestCreateClients(unittest.TestCase):
    @patch("oci.core.ComputeClient")
    def test_create_compute_client(self, mock_cls):
        from src.oci_auth import create_compute_client

        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance
        client = create_compute_client({"test": "config"})
        self.assertEqual(client, mock_instance)
        mock_cls.assert_called_once()

    @patch("oci.limits.LimitsClient")
    def test_create_limits_client(self, mock_cls):
        from src.oci_auth import create_limits_client

        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance
        client = create_limits_client({"test": "config"})
        self.assertEqual(client, mock_instance)
        mock_cls.assert_called_once()


if __name__ == "__main__":
    unittest.main()
