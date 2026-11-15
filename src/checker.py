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
    identity_client=None,
) -> dict:
    """Check OCPU and memory quota for A1 shapes.

    Tries region/compartment scope first. If the API returns 400
    indicating availabilityDomain is required (AD-scoped limits),
    queries each Availability Domain and aggregates.

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

    def _parse_availability(data):
        """Return (available, used, limit) from OCI ResourceAvailability."""
        fractional_used = getattr(data, "fractional_usage", None)
        raw_used = fractional_used if fractional_used is not None else getattr(data, "used", None)
        used = float(raw_used or 0)

        fractional_available = getattr(data, "fractional_availability", None)
        raw_available = (
            fractional_available
            if fractional_available is not None
            else getattr(data, "available", None)
        )
        if raw_available is not None:
            available = max(float(raw_available), 0.0)
        elif getattr(data, "effective_quota_value", None) is not None:
            available = max(float(data.effective_quota_value) - used, 0.0)
        else:
            available = 0.0

        effective_limit = getattr(data, "effective_quota_value", None)
        limit = float(effective_limit) if effective_limit is not None else available + used
        return available, used, limit

    def _query_tenancy_scope():
        ocpu_resp = limits_client.get_resource_availability(
            "compute",
            "standard-a1-core-count",
            config.compartment_id,
        )
        ocpu_data = ocpu_resp.data
        mem_resp = limits_client.get_resource_availability(
            "compute",
            "standard-a1-memory-count",
            config.compartment_id,
        )
        mem_data = mem_resp.data
        return ocpu_data, mem_data

    def _query_ad_scope(ads):
        total_ocpu_limit = 0.0
        total_ocpu_used = 0.0
        total_mem_limit = 0.0
        total_mem_used = 0.0
        any_ad_has_capacity = False

        for ad in ads:
            ocpu_resp = limits_client.get_resource_availability(
                "compute",
                "standard-a1-core-count",
                config.compartment_id,
                availability_domain=ad.name,
            )
            ocpu_avail, ocpu_used, ocpu_limit = _parse_availability(ocpu_resp.data)

            mem_resp = limits_client.get_resource_availability(
                "compute",
                "standard-a1-memory-count",
                config.compartment_id,
                availability_domain=ad.name,
            )
            mem_avail, mem_used, mem_limit = _parse_availability(mem_resp.data)

            logger.info(
                "AD %s quota: OCPU avail=%s used=%s limit=%s | RAM avail=%s used=%s limit=%s",
                ad.name,
                ocpu_avail,
                ocpu_used,
                ocpu_limit,
                mem_avail,
                mem_used,
                mem_limit,
            )

            total_ocpu_limit += ocpu_limit
            total_ocpu_used += ocpu_used
            total_mem_limit += mem_limit
            total_mem_used += mem_used

            if ocpu_avail >= config.ocpus and mem_avail >= config.memory_gb:
                any_ad_has_capacity = True

        return (
            total_ocpu_limit,
            total_ocpu_used,
            total_mem_limit,
            total_mem_used,
            any_ad_has_capacity,
        )

    try:
        try:
            ocpu_data, mem_data = _query_tenancy_scope()
            ocpu_avail, ocpu_used, ocpu_limit = _parse_availability(ocpu_data)
            mem_avail, mem_used, mem_limit = _parse_availability(mem_data)
            result["ocpu_limit"] = ocpu_limit
            result["ocpu_used"] = ocpu_used
            result["ocpu_available"] = ocpu_avail
            result["mem_limit"] = mem_limit
            result["mem_used"] = mem_used
            result["mem_available"] = mem_avail
            result["has_quota"] = (
                result["ocpu_available"] >= config.ocpus
                and result["mem_available"] >= config.memory_gb
            )
        except oci.exceptions.ServiceError as e:
            is_ad_scoped = (
                e.status == 400
                and "availabilityDomain" in str(e.message or "")
            )
            if not is_ad_scoped or identity_client is None:
                raise

            ads_resp = identity_client.list_availability_domains(
                config.compartment_id
            )
            (
                ocpu_limit,
                ocpu_used,
                mem_limit,
                mem_used,
                has_quota,
            ) = _query_ad_scope(ads_resp.data)

            result["ocpu_limit"] = ocpu_limit
            result["ocpu_used"] = ocpu_used
            result["ocpu_available"] = ocpu_limit - ocpu_used
            result["mem_limit"] = mem_limit
            result["mem_used"] = mem_used
            result["mem_available"] = mem_limit - mem_used
            result["has_quota"] = has_quota

    except oci.exceptions.ServiceError as e:
        logger.warning("Quota check ServiceError: %s", e.message)
        raise
    except Exception as e:
        logger.warning("Quota check error: %s", str(e))
        raise

    return result


def _check_host_capacity_report(
    config: Config, compute_client, ad_name: str
) -> tuple[Optional[str], Optional[int], Optional[str]]:
    """Check physical host capacity using OCI Compute Capacity Report API.

    Returns (availability_status, available_count, error_msg).
    Status values: 'AVAILABLE', 'OUT_OF_HOST_CAPACITY', 'HARDWARE_NOT_SUPPORTED', or None.
    """
    if not hasattr(compute_client, "create_compute_capacity_report"):
        return None, None, "compute_client has no create_compute_capacity_report"

    try:
        report_details = oci.core.models.CreateComputeCapacityReportDetails(
            compartment_id=config.compartment_id,
            availability_domain=ad_name,
            shape_availabilities=[
                oci.core.models.CreateCapacityReportShapeAvailabilityDetails(
                    instance_shape=config.shape,
                    instance_shape_config=oci.core.models.CapacityReportInstanceShapeConfig(
                        ocpus=config.ocpus,
                        memory_in_gbs=config.memory_gb,
                    ),
                )
            ],
        )
        report = compute_client.create_compute_capacity_report(report_details)
        if report.data and report.data.shape_availabilities:
            sa = report.data.shape_availabilities[0]
            status = getattr(sa, "availability_status", None)
            count = getattr(sa, "available_count", None)
            logger.info(
                "AD %s capacity report: shape=%s status=%s available_count=%s",
                ad_name,
                config.shape,
                status,
                count,
            )
            return status, count, None
    except Exception as exc:
        logger.warning(
            "Capacity report failed for AD %s: %s", ad_name, exc
        )
        return None, None, str(exc)

    return None, None, "No data returned in capacity report"


def _check_shape_in_ads(
    config: Config,
    compute_client,
    identity_client,
) -> dict:
    """Check if the target shape is available on physical hosts in any AD.

    1. Checks if the shape exists in the AD catalog with requested OCPU & RAM.
    2. Queries the Compute Capacity Report API to verify physical host capacity.
       - If status == 'AVAILABLE', capacity is confirmed.
       - If status == 'OUT_OF_HOST_CAPACITY', capacity is full.

    Returns dict with keys: shape_found, ad_name, details.
    """
    result = {"shape_found": False, "ad_name": None, "details": ""}
    last_report_status = None

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
            logger.info("AD %s: scanned %d shapes", ad.name, len(shapes_resp.data))
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

                if not (ocpu_ok and mem_ok):
                    continue

                cap_status, cap_count, cap_err = _check_host_capacity_report(
                    config, compute_client, ad.name
                )
                last_report_status = cap_status

                if cap_status == "AVAILABLE":
                    result["shape_found"] = True
                    result["ad_name"] = ad.name
                    result["details"] = (
                        f"Host capacity CONFIRMED available in AD {ad.name} "
                        f"for shape {config.shape} ({config.ocpus} OCPU, "
                        f"{config.memory_gb} GB RAM, available count: {cap_count})"
                    )
                    return result
                elif cap_status == "OUT_OF_HOST_CAPACITY":
                    result["details"] = (
                        f"Shape {config.shape} is cataloged in AD {ad.name}, "
                        f"but host capacity is full (OUT_OF_HOST_CAPACITY). "
                        f"Notification suppressed."
                    )
                elif cap_status is None:
                    # Capacity report API not available or errored
                    result["details"] = (
                        f"Shape {config.shape} found in AD {ad.name}, "
                        f"but host capacity could not be verified by API: {cap_err}. "
                        f"Notification suppressed to prevent false positives."
                    )
                else:
                    result["details"] = (
                        f"AD {ad.name} report status for {config.shape}: {cap_status}"
                    )

        if not result["details"]:
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
        quota = _check_quota(config, limits_client, identity_client)
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
        limit_hint = ""
        if quota.get("ocpu_limit") == 0.0:
            limit_hint = (
                f" (Limit is 0: verify OCI_COMPARTMENT_ID is the Root Tenancy OCID, "
                f"or check Service Limits in Console for region '{config.region}'. "
                f"Always Free A1 resources are only in your Home Region)"
            )
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
                f"(need {config.memory_gb}){limit_hint}"
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
