"""Checker module — queries OCI for A1.Flex quota and shape availability."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import oci

from src.config import Config

logger = logging.getLogger(__name__)

STATUS_AVAILABLE = "AVAILABLE"
STATUS_QUOTA_ONLY = "QUOTA_ONLY"
STATUS_UNAVAILABLE = "UNAVAILABLE"
STATUS_ERROR = "ERROR"

LIMITATIONS_NOTICE = (
    "OCI API does not expose real-time host capacity. "
    "Shape listing per Availability Domain is the closest signal "
    "but does not guarantee that a launch will succeed. "
    "QUOTA_ONLY means your tenancy has unused quota but the checker "
    "could not confirm shape availability in any AD."
)


@dataclass
class CheckResult:
    """Result of one availability check cycle."""

    status: str
    timestamp: str
    quota_available: Optional[float] = None
    quota_used: Optional[float] = None
    quota_limit: Optional[float] = None
    memory_quota_available: Optional[float] = None
    memory_quota_used: Optional[float] = None
    memory_quota_limit: Optional[float] = None
    shape_available: bool = False
    ad_name: Optional[str] = None
    details: str = ""
    limitations: str = LIMITATIONS_NOTICE


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _check_quota(
    config: Config,
    limits_client,
    tenancy_id: str,
) -> dict:
    """Check OCPU and memory quota for A1 shapes.

    Returns dict with keys: ocpu_available, ocpu_used, ocpu_limit,
    mem_available, mem_used, mem_limit, has_quota.
    """
    result = {
        "ocpu_available": None,
        "ocpu_used": None,
        "ocpu_limit": None,
        "mem_available": None,
        "mem_used": None,
        "mem_limit": None,
        "has_quota": False,
    }

    try:
        ocpu_resp = limits_client.get_resource_availability(
            "compute",
            "standard-a1-core-count",
            config.compartment_id,
            availability_domain=None,
        )
        ocpu_data = ocpu_resp.data
        result["ocpu_limit"] = float(ocpu_data.effective_quota_value or 0)
        result["ocpu_used"] = float(ocpu_data.used or 0)
        result["ocpu_available"] = result["ocpu_limit"] - result["ocpu_used"]

        mem_resp = limits_client.get_resource_availability(
            "compute",
            "standard-a1-memory-count",
            config.compartment_id,
            availability_domain=None,
        )
        mem_data = mem_resp.data
        result["mem_limit"] = float(mem_data.effective_quota_value or 0)
        result["mem_used"] = float(mem_data.used or 0)
        result["mem_available"] = result["mem_limit"] - result["mem_used"]

        result["has_quota"] = (
            result["ocpu_available"] >= config.ocpus
            and result["mem_available"] >= config.memory_gb
        )
    except oci.exceptions.ServiceError as e:
        logger.warning("Quota check ServiceError: %s", e.message)
        raise
    except Exception as e:
        logger.warning("Quota check error: %s", str(e))
        raise

    return result


def _check_shape_in_ads(
    config: Config,
    compute_client,
    identity_client,
) -> dict:
    """Check if the target shape is listed in any Availability Domain.

    Returns dict with keys: shape_found, ad_name, details.
    """
    result = {"shape_found": False, "ad_name": None, "details": ""}

    try:
        ads_resp = identity_client.list_availability_domains(
            config.compartment_id
        )
        ads = ads_resp.data

        for ad in ads:
            shapes_resp = compute_client.list_shapes(
                config.compartment_id,
                availability_domain=ad.name,
            )
            for shape in shapes_resp.data:
                if shape.shape != config.shape:
                    continue

                ocpu_ok = True
                if hasattr(shape, "ocpu_options") and shape.ocpu_options:
                    ocpu_ok = (
                        shape.ocpu_options.min <= config.ocpus
                        and config.ocpus <= shape.ocpu_options.max
                    )

                mem_ok = True
                if hasattr(shape, "memory_options") and shape.memory_options:
                    mem_ok = (
                        shape.memory_options.min_in_g_bs <= config.memory_gb
                        and config.memory_gb
                        <= shape.memory_options.max_in_g_bs
                    )

                if ocpu_ok and mem_ok:
                    result["shape_found"] = True
                    result["ad_name"] = ad.name
                    result["details"] = (
                        f"Shape {config.shape} available in AD {ad.name} "
                        f"(OCPU range: "
                        f"{getattr(shape.ocpu_options, 'min', 'N/A')}-"
                        f"{getattr(shape.ocpu_options, 'max', 'N/A')}, "
                        f"Memory range: "
                        f"{getattr(shape.memory_options, 'min_in_g_bs', 'N/A')}-"
                        f"{getattr(shape.memory_options, 'max_in_g_bs', 'N/A')} GB)"
                    )
                    return result

        result["details"] = (
            f"Shape {config.shape} not found in any AD "
            f"with requested config ({config.ocpus} OCPU, "
            f"{config.memory_gb} GB)"
        )
    except oci.exceptions.ServiceError as e:
        logger.warning("Shape check ServiceError: %s", e.message)
        raise
    except Exception as e:
        logger.warning("Shape check error: %s", str(e))
        raise

    return result


def check_availability(
    config: Config,
    compute_client,
    limits_client,
    identity_client=None,
) -> CheckResult:
    """Run the full availability check: quota + shape per AD.

    Classification:
      AVAILABLE   — shape listed in at least one AD AND quota remaining
      QUOTA_ONLY  — quota remaining but shape not confirmed in any AD
      UNAVAILABLE — no quota remaining
      ERROR       — API call failed

    identity_client is needed to list ADs. If not provided, the check
    skips shape-per-AD and relies on quota only.
    """
    timestamp = _now_iso()

    try:
        quota = _check_quota(config, limits_client, config.compartment_id)
    except oci.exceptions.ServiceError as e:
        status = STATUS_ERROR
        details = f"Quota API error (HTTP {e.status}): {e.message}"
        if e.status == 429:
            details = f"Rate limited (429) during quota check: {e.message}"
        return CheckResult(
            status=status,
            timestamp=timestamp,
            details=details,
        )
    except Exception as e:
        return CheckResult(
            status=STATUS_ERROR,
            timestamp=timestamp,
            details=f"Quota check failed: {str(e)}",
        )

    if not quota["has_quota"]:
        return CheckResult(
            status=STATUS_UNAVAILABLE,
            timestamp=timestamp,
            quota_available=quota["ocpu_available"],
            quota_used=quota["ocpu_used"],
            quota_limit=quota["ocpu_limit"],
            memory_quota_available=quota["mem_available"],
            memory_quota_used=quota["mem_used"],
            memory_quota_limit=quota["mem_limit"],
            shape_available=False,
            details=(
                f"Insufficient quota: "
                f"{quota['ocpu_available']} OCPU available "
                f"(need {config.ocpus}), "
                f"{quota['mem_available']} GB RAM available "
                f"(need {config.memory_gb})"
            ),
        )

    if identity_client is None:
        return CheckResult(
            status=STATUS_QUOTA_ONLY,
            timestamp=timestamp,
            quota_available=quota["ocpu_available"],
            quota_used=quota["ocpu_used"],
            quota_limit=quota["ocpu_limit"],
            memory_quota_available=quota["mem_available"],
            memory_quota_used=quota["mem_used"],
            memory_quota_limit=quota["mem_limit"],
            shape_available=False,
            details="Quota available but no identity client to check ADs",
        )

    try:
        shape_info = _check_shape_in_ads(
            config, compute_client, identity_client
        )
    except oci.exceptions.ServiceError as e:
        status = STATUS_ERROR
        details = f"Shape API error (HTTP {e.status}): {e.message}"
        if e.status == 429:
            details = f"Rate limited (429) during shape check: {e.message}"
        return CheckResult(
            status=status,
            timestamp=timestamp,
            quota_available=quota["ocpu_available"],
            quota_used=quota["ocpu_used"],
            quota_limit=quota["ocpu_limit"],
            memory_quota_available=quota["mem_available"],
            memory_quota_used=quota["mem_used"],
            memory_quota_limit=quota["mem_limit"],
            details=details,
        )
    except Exception as e:
        return CheckResult(
            status=STATUS_ERROR,
            timestamp=timestamp,
            quota_available=quota["ocpu_available"],
            quota_used=quota["ocpu_used"],
            quota_limit=quota["ocpu_limit"],
            memory_quota_available=quota["mem_available"],
            memory_quota_used=quota["mem_used"],
            memory_quota_limit=quota["mem_limit"],
            details=f"Shape check failed: {str(e)}",
        )

    if shape_info["shape_found"] and quota["has_quota"]:
        return CheckResult(
            status=STATUS_AVAILABLE,
            timestamp=timestamp,
            quota_available=quota["ocpu_available"],
            quota_used=quota["ocpu_used"],
            quota_limit=quota["ocpu_limit"],
            memory_quota_available=quota["mem_available"],
            memory_quota_used=quota["mem_used"],
            memory_quota_limit=quota["mem_limit"],
            shape_available=True,
            ad_name=shape_info["ad_name"],
            details=shape_info["details"],
        )

    return CheckResult(
        status=STATUS_QUOTA_ONLY,
        timestamp=timestamp,
        quota_available=quota["ocpu_available"],
        quota_used=quota["ocpu_used"],
        quota_limit=quota["ocpu_limit"],
        memory_quota_available=quota["mem_available"],
        memory_quota_used=quota["mem_used"],
        memory_quota_limit=quota["mem_limit"],
        shape_available=False,
        details=shape_info["details"],
    )
