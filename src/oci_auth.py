"""OCI authentication module — builds SDK config from environment variables."""

import os
import tempfile

import oci


_REQUIRED_ENV_VARS = {
    "OCI_USER_OCID": "OCI user OCID",
    "OCI_TENANCY_OCID": "OCI tenancy OCID",
    "OCI_FINGERPRINT": "API key fingerprint",
    "OCI_API_KEY": "PEM-encoded private key contents",
    "OCI_REGION": "OCI region identifier",
}


def build_oci_config() -> dict:
    """Build an OCI SDK config dict from environment variables.

    The private key is written to a temporary file because the SDK
    expects a file path, not inline PEM content.

    Raises ValueError if any required env var is missing.
    """
    missing = [
        name for name in _REQUIRED_ENV_VARS if not os.environ.get(name)
    ]
    if missing:
        descriptions = [
            f"  {name} — {_REQUIRED_ENV_VARS[name]}" for name in missing
        ]
        raise ValueError(
            "Missing required OCI environment variables:\n"
            + "\n".join(descriptions)
        )

    key_content = os.environ["OCI_API_KEY"]

    key_file = tempfile.NamedTemporaryFile(
        mode="w", suffix=".pem", delete=False
    )
    key_file.write(key_content)
    key_file.close()

    config = {
        "user": os.environ["OCI_USER_OCID"],
        "tenancy": os.environ["OCI_TENANCY_OCID"],
        "fingerprint": os.environ["OCI_FINGERPRINT"],
        "key_file": key_file.name,
        "region": os.environ["OCI_REGION"],
    }

    oci.config.validate_config(config)
    return config


def _retry_strategy():
    """Return an OCI retry strategy with exponential backoff."""
    return oci.retry.ExponentialBackoffRetryStrategyBase(
        max_retries=3,
        base_sleep_time_seconds=1,
        exponent_growth_factor=2,
        max_wait_between_calls_seconds=20,
    )


def create_compute_client(oci_config: dict) -> "oci.core.ComputeClient":
    """Create a ComputeClient with retry strategy."""
    return oci.core.ComputeClient(
        oci_config,
        retry_strategy=oci.retry.DEFAULT_RETRY_STRATEGY,
    )


def create_limits_client(oci_config: dict) -> "oci.limits.LimitsClient":
    """Create a LimitsClient with retry strategy."""
    return oci.limits.LimitsClient(
        oci_config,
        retry_strategy=oci.retry.DEFAULT_RETRY_STRATEGY,
    )
