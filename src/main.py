"""Main entry point for the Oracle A1.Flex Availability Checker."""

import json
import logging
import os
import sys
from dataclasses import asdict

from src.checker import (
    STATUS_AVAILABLE,
    check_availability,
)
from src.config import load_config
from src.notifier import send_notification
from src.oci_auth import (
    build_oci_config,
    create_compute_client,
    create_limits_client,
)

import oci

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

RESULTS_DIR = "results"


def _write_result(result) -> str:
    """Persist the check result as JSON and return the file path."""
    os.makedirs(RESULTS_DIR, exist_ok=True)
    timestamp = result.timestamp.replace(":", "-")
    path = os.path.join(RESULTS_DIR, f"check-{timestamp}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(asdict(result), f, indent=2)
    logger.info("Result written to %s", path)
    return path


def main() -> int:
    """Run one availability check cycle."""
    try:
        config = load_config()
        oci_config = build_oci_config()
    except ValueError as exc:
        logger.error("Configuration error:\n%s", exc)
        return 1
    except Exception as exc:
        logger.error("Unexpected configuration failure: %s", exc)
        return 1

    try:
        compute_client = create_compute_client(oci_config)
        limits_client = create_limits_client(oci_config)
        identity_client = oci.identity.IdentityClient(oci_config)
    except Exception as exc:
        logger.error("Failed to create OCI clients: %s", exc)
        return 1

    try:
        result = check_availability(
            config, compute_client, limits_client, identity_client
        )
    except Exception as exc:
        logger.error("Availability check crashed: %s", exc)
        return 1

    _write_result(result)

    logger.info(
        "Status=%s quota=%s/%s OCPU shape_ad=%s details=%s",
        result.status,
        result.quota_available,
        result.quota_limit,
        result.ad_name,
        result.details,
    )

    if result.status == STATUS_AVAILABLE:
        send_notification(config, result)

    return 0


if __name__ == "__main__":
    sys.exit(main())
