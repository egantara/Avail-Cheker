"""Tests for src.config module."""

import os
import unittest
from unittest.mock import patch

from src.config import Config, load_config


_FULL_ENV = {
    "OCI_COMPARTMENT_ID": "ocid1.compartment.oc1..test",
    "SMTP_HOST": "smtp.gmail.com",
    "SMTP_PORT": "587",
    "SMTP_USER": "user@gmail.com",
    "SMTP_PASSWORD": "pass",
    "EMAIL_FROM": "user@gmail.com",
    "EMAIL_TO": "dest@gmail.com",
}


class TestLoadConfigDefaults(unittest.TestCase):
    @patch.dict(os.environ, _FULL_ENV, clear=True)
    def test_returns_config_with_defaults(self):
        cfg = load_config()
        self.assertIsInstance(cfg, Config)
        self.assertEqual(cfg.region, "ap-batam-1")
        self.assertEqual(cfg.shape, "VM.Standard.A1.Flex")
        self.assertEqual(cfg.ocpus, 2.0)
        self.assertEqual(cfg.memory_gb, 12.0)

    @patch.dict(os.environ, {**_FULL_ENV, "OCI_REGION": "us-ashburn-1"}, clear=True)
    def test_region_override(self):
        cfg = load_config()
        self.assertEqual(cfg.region, "us-ashburn-1")

    @patch.dict(os.environ, {**_FULL_ENV, "OCI_OCPUS": "4", "OCI_MEMORY_GB": "24"}, clear=True)
    def test_ocpu_memory_override(self):
        cfg = load_config()
        self.assertEqual(cfg.ocpus, 4.0)
        self.assertEqual(cfg.memory_gb, 24.0)


class TestLoadConfigMissing(unittest.TestCase):
    @patch.dict(os.environ, {}, clear=True)
    def test_missing_compartment_raises(self):
        with self.assertRaises(ValueError) as ctx:
            load_config()
        self.assertIn("OCI_COMPARTMENT_ID", str(ctx.exception))

    @patch.dict(os.environ, {"OCI_COMPARTMENT_ID": "ocid1.test"}, clear=True)
    def test_missing_smtp_raises(self):
        with self.assertRaises(ValueError) as ctx:
            load_config()
        self.assertIn("SMTP_HOST", str(ctx.exception))

    @patch.dict(os.environ, _FULL_ENV, clear=True)
    def test_all_fields_populated(self):
        cfg = load_config()
        self.assertEqual(cfg.smtp_host, "smtp.gmail.com")
        self.assertEqual(cfg.smtp_port, 587)
        self.assertEqual(cfg.smtp_user, "user@gmail.com")
        self.assertEqual(cfg.smtp_password, "pass")
        self.assertEqual(cfg.email_from, "user@gmail.com")
        self.assertEqual(cfg.email_to, "dest@gmail.com")
        self.assertEqual(cfg.compartment_id, "ocid1.compartment.oc1..test")


if __name__ == "__main__":
    unittest.main()
