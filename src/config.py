"""Configuration module for Oracle A1.Flex Availability Checker."""

import os
from dataclasses import dataclass


@dataclass
class Config:
    """All configuration for the checker, loaded from environment variables."""

    region: str
    compartment_id: str
    shape: str
    ocpus: float
    memory_gb: float
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    email_from: str
    email_to: str


_REQUIRED_ENV_VARS = {
    "OCI_COMPARTMENT_ID": "OCI compartment OCID",
    "SMTP_HOST": "SMTP server hostname",
    "SMTP_PORT": "SMTP server port",
    "SMTP_USER": "SMTP login username",
    "SMTP_PASSWORD": "SMTP login password",
    "EMAIL_FROM": "Sender email address",
    "EMAIL_TO": "Recipient email address",
}


def load_config() -> Config:
    """Load configuration from environment variables.

    Defaults:
        region      = ap-batam-1
        shape       = VM.Standard.A1.Flex
        ocpus       = 2.0
        memory_gb   = 12.0

    Raises ValueError if any required env var is missing.
    """
    missing = [
        name
        for name in _REQUIRED_ENV_VARS
        if not os.environ.get(name)
    ]
    if missing:
        descriptions = [
            f"  {name} — {_REQUIRED_ENV_VARS[name]}" for name in missing
        ]
        raise ValueError(
            "Missing required environment variables:\n"
            + "\n".join(descriptions)
        )

    return Config(
        region=os.environ.get("OCI_REGION", "ap-batam-1"),
        compartment_id=os.environ["OCI_COMPARTMENT_ID"],
        shape=os.environ.get("OCI_SHAPE", "VM.Standard.A1.Flex"),
        ocpus=float(os.environ.get("OCI_OCPUS", "2.0")),
        memory_gb=float(os.environ.get("OCI_MEMORY_GB", "12.0")),
        smtp_host=os.environ["SMTP_HOST"],
        smtp_port=int(os.environ["SMTP_PORT"]),
        smtp_user=os.environ["SMTP_USER"],
        smtp_password=os.environ["SMTP_PASSWORD"],
        email_from=os.environ["EMAIL_FROM"],
        email_to=os.environ["EMAIL_TO"],
    )
