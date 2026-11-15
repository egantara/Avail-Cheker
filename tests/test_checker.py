"""Tests for src.checker module."""

import unittest
from unittest.mock import MagicMock, patch, PropertyMock
from types import SimpleNamespace

import oci.exceptions

from src.checker import (
    STATUS_AVAILABLE,
    STATUS_ERROR,
    STATUS_QUOTA_ONLY,
    STATUS_UNAVAILABLE,
    LIMITATIONS_NOTICE,
    check_availability,
)
from src.config import Config


def _make_config(**overrides) -> Config:
    defaults = dict(
        region="ap-batam-1",
        compartment_id="ocid1.compartment.oc1..test",
        shape="VM.Standard.A1.Flex",
        ocpus=2.0,
        memory_gb=12.0,
        smtp_host="smtp.test",
        smtp_port=587,
        smtp_user="u",
        smtp_password="p",
        email_from="a@b.c",
        email_to="d@e.f",
    )
    defaults.update(overrides)
    return Config(**defaults)


def _mock_quota_response(limit_val, used_val, available_val=None):
    """Return a mock OCI response for get_resource_availability."""
    if available_val is None and limit_val is not None:
        available_val = limit_val - used_val
    data = SimpleNamespace(
        available=available_val,
        effective_quota_value=limit_val,
        used=used_val,
    )
    resp = MagicMock()
    resp.data = data
    return resp


def _mock_shape(name, ocpu_min=1, ocpu_max=80, mem_min=1, mem_max=512):
    shape = SimpleNamespace(
        shape=name,
        ocpu_options=SimpleNamespace(min=ocpu_min, max=ocpu_max),
        memory_options=SimpleNamespace(min_in_g_bs=mem_min, max_in_g_bs=mem_max),
    )
    return shape


def _mock_ad(name):
    return SimpleNamespace(name=name)


def _mock_capacity_report(status="AVAILABLE", count=1):
    """Mock a ComputeCapacityReport response."""
    entry = SimpleNamespace(
        instance_shape="VM.Standard.A1.Flex",
        availability_status=status,
        available_count=count,
    )
    return MagicMock(data=SimpleNamespace(shape_availabilities=[entry]))


class TestCheckAvailability(unittest.TestCase):
    def test_out_of_host_capacity_is_not_available(self):
        """When capacity report says OUT_OF_HOST_CAPACITY, status must be
        QUOTA_ONLY or UNAVAILABLE, never AVAILABLE, and no email should fire."""
        config = _make_config()
        compute = MagicMock()
        limits = MagicMock()
        identity = MagicMock()

        limits.get_resource_availability.side_effect = [
            _mock_quota_response(4, 0),
            _mock_quota_response(24, 0),
        ]
        identity.list_availability_domains.return_value = MagicMock(
            data=[_mock_ad("AD-1")]
        )
        compute.list_shapes.return_value = MagicMock(
            data=[_mock_shape("VM.Standard.A1.Flex")]
        )
        compute.create_compute_capacity_report.return_value = _mock_capacity_report(
            status="OUT_OF_HOST_CAPACITY", count=0
        )

        result = check_availability(config, compute, limits, identity)

        self.assertNotEqual(result.status, STATUS_AVAILABLE)
        self.assertFalse(result.shape_available)
        self.assertIn("OUT_OF_HOST_CAPACITY", result.details)

    def test_available_only_when_capacity_report_confirms_available(self):
        """Capacity report status AVAILABLE confirms host capacity."""
        config = _make_config()
        compute = MagicMock()
        limits = MagicMock()
        identity = MagicMock()

        limits.get_resource_availability.side_effect = [
            _mock_quota_response(4, 0),
            _mock_quota_response(24, 0),
        ]
        identity.list_availability_domains.return_value = MagicMock(
            data=[_mock_ad("AD-1")]
        )
        compute.list_shapes.return_value = MagicMock(
            data=[_mock_shape("VM.Standard.A1.Flex")]
        )
        compute.create_compute_capacity_report.return_value = _mock_capacity_report(
            status="AVAILABLE", count=1
        )

        result = check_availability(config, compute, limits, identity)

        self.assertEqual(result.status, STATUS_AVAILABLE)
        self.assertTrue(result.shape_available)
        self.assertEqual(result.ad_name, "AD-1")

    def test_available_when_shape_and_quota(self):
        config = _make_config()
        compute = MagicMock()
        limits = MagicMock()
        identity = MagicMock()

        limits.get_resource_availability.side_effect = [
            _mock_quota_response(4, 0),
            _mock_quota_response(24, 0),
        ]
        identity.list_availability_domains.return_value = MagicMock(
            data=[_mock_ad("AD-1")]
        )
        compute.list_shapes.return_value = MagicMock(
            data=[_mock_shape("VM.Standard.A1.Flex")]
        )
        compute.create_compute_capacity_report.return_value = _mock_capacity_report(
            status="AVAILABLE", count=1
        )

        result = check_availability(config, compute, limits, identity)

        self.assertEqual(result.status, STATUS_AVAILABLE)
        self.assertTrue(result.shape_available)
        self.assertEqual(result.ad_name, "AD-1")
        self.assertEqual(result.quota_available, 4.0)
        self.assertIn(LIMITATIONS_NOTICE, result.limitations)

    def test_quota_only_when_shape_not_in_ad(self):
        config = _make_config()
        compute = MagicMock()
        limits = MagicMock()
        identity = MagicMock()

        limits.get_resource_availability.side_effect = [
            _mock_quota_response(4, 0),
            _mock_quota_response(24, 0),
        ]
        identity.list_availability_domains.return_value = MagicMock(
            data=[_mock_ad("AD-1")]
        )
        compute.list_shapes.return_value = MagicMock(
            data=[_mock_shape("VM.Standard.E2.1.Micro")]
        )

        result = check_availability(config, compute, limits, identity)

        self.assertEqual(result.status, STATUS_QUOTA_ONLY)
        self.assertFalse(result.shape_available)

    def test_unavailable_when_no_quota(self):
        config = _make_config()
        compute = MagicMock()
        limits = MagicMock()
        identity = MagicMock()

        limits.get_resource_availability.side_effect = [
            _mock_quota_response(4, 4),
            _mock_quota_response(24, 24),
        ]

        result = check_availability(config, compute, limits, identity)

        self.assertEqual(result.status, STATUS_UNAVAILABLE)
        self.assertFalse(result.shape_available)
        self.assertEqual(result.quota_available, 0.0)

    def test_error_on_api_timeout(self):
        config = _make_config()
        compute = MagicMock()
        limits = MagicMock()
        identity = MagicMock()

        limits.get_resource_availability.side_effect = Exception(
            "Connection timed out"
        )

        result = check_availability(config, compute, limits, identity)

        self.assertEqual(result.status, STATUS_ERROR)
        self.assertIn("timed out", result.details)

    def test_error_on_rate_limit(self):
        config = _make_config()
        compute = MagicMock()
        limits = MagicMock()
        identity = MagicMock()

        limits.get_resource_availability.side_effect = (
            oci.exceptions.ServiceError(
                status=429,
                code="TooManyRequests",
                headers={},
                message="Rate limit exceeded",
            )
        )

        result = check_availability(config, compute, limits, identity)

        self.assertEqual(result.status, STATUS_ERROR)
        self.assertIn("429", result.details)
        self.assertIn("Rate limit", result.details)

    def test_quota_falls_back_to_ad_scope(self):
        """A1 limits are AD-scoped: tenancy scope returns 400, so quota
        must be fetched per Availability Domain and aggregated."""
        config = _make_config()
        compute = MagicMock()
        limits = MagicMock()
        identity = MagicMock()

        identity.list_availability_domains.return_value = MagicMock(
            data=[_mock_ad("AD-1"), _mock_ad("AD-2")]
        )

        def quota_side_effect(
            service_name, limit_name, compartment_id,
            availability_domain=None, **kwargs
        ):
            if availability_domain is None:
                raise oci.exceptions.ServiceError(
                    status=400,
                    code="InvalidParameter",
                    headers={},
                    message="Invalid parameter 'availabilityDomain'",
                )
            if limit_name == "standard-a1-core-count":
                return _mock_quota_response(4, 1)
            return _mock_quota_response(24, 6)

        limits.get_resource_availability.side_effect = quota_side_effect
        compute.list_shapes.return_value = MagicMock(
            data=[_mock_shape("VM.Standard.A1.Flex")]
        )
        compute.create_compute_capacity_report.return_value = _mock_capacity_report(
            status="AVAILABLE", count=1
        )

        result = check_availability(config, compute, limits, identity)

        self.assertEqual(result.status, STATUS_AVAILABLE)
        self.assertEqual(result.quota_available, 6.0)
        self.assertEqual(result.quota_used, 2.0)
        self.assertEqual(result.memory_quota_available, 36.0)

    def test_ad_scoped_quota_exhausted_is_unavailable(self):
        """AD-scoped aggregation must still detect exhausted quota."""
        config = _make_config()
        compute = MagicMock()
        limits = MagicMock()
        identity = MagicMock()

        identity.list_availability_domains.return_value = MagicMock(
            data=[_mock_ad("AD-1")]
        )

        def quota_side_effect(
            service_name, limit_name, compartment_id,
            availability_domain=None, **kwargs
        ):
            if availability_domain is None:
                raise oci.exceptions.ServiceError(
                    status=400,
                    code="InvalidParameter",
                    headers={},
                    message="Invalid parameter 'availabilityDomain'",
                )
            if limit_name == "standard-a1-core-count":
                return _mock_quota_response(4, 4)
            return _mock_quota_response(24, 24)

        limits.get_resource_availability.side_effect = quota_side_effect

        result = check_availability(config, compute, limits, identity)

        self.assertEqual(result.status, STATUS_UNAVAILABLE)
        self.assertEqual(result.quota_available, 0.0)

    def test_quota_when_effective_quota_value_is_none(self):
        """When no quota policy exists, effective_quota_value is None.
        Quota must be read from available/fractional_availability."""
        config = _make_config()
        compute = MagicMock()
        limits = MagicMock()
        identity = MagicMock()

        identity.list_availability_domains.return_value = MagicMock(
            data=[_mock_ad("AD-1")]
        )

        def quota_side_effect(
            service_name, limit_name, compartment_id,
            availability_domain=None, **kwargs
        ):
            if availability_domain is None:
                raise oci.exceptions.ServiceError(
                    status=400,
                    code="InvalidParameter",
                    headers={},
                    message="Invalid parameter 'availabilityDomain'",
                )
            if limit_name == "standard-a1-core-count":
                # effective_quota_value is None, but available=4, used=0
                return _mock_quota_response(None, 0, available_val=4)
            return _mock_quota_response(None, 0, available_val=24)

        limits.get_resource_availability.side_effect = quota_side_effect
        compute.list_shapes.return_value = MagicMock(
            data=[_mock_shape("VM.Standard.A1.Flex")]
        )
        compute.create_compute_capacity_report.return_value = _mock_capacity_report(
            status="AVAILABLE", count=1
        )

        result = check_availability(config, compute, limits, identity)

        self.assertEqual(result.status, STATUS_AVAILABLE)
        self.assertEqual(result.quota_available, 4.0)
        self.assertEqual(result.memory_quota_available, 24.0)

    def test_unavailable_provides_diagnostic_hint_when_limit_zero(self):
        config = _make_config()
        compute = MagicMock()
        limits = MagicMock()
        identity = MagicMock()

        identity.list_availability_domains.return_value = MagicMock(
            data=[_mock_ad("AD-1")]
        )

        def quota_side_effect(
            service_name, limit_name, compartment_id,
            availability_domain=None, **kwargs
        ):
            if availability_domain is None:
                raise oci.exceptions.ServiceError(
                    status=400,
                    code="InvalidParameter",
                    headers={},
                    message="Invalid parameter 'availabilityDomain'",
                )
            return _mock_quota_response(0, 0, available_val=0)

        limits.get_resource_availability.side_effect = quota_side_effect
        limits.list_limit_values.return_value = MagicMock(data=[])

        result = check_availability(config, compute, limits, identity)

        self.assertEqual(result.status, STATUS_UNAVAILABLE)
        self.assertIn("Limit is 0", result.details)
        self.assertIn("Home Region", result.details)

    def test_quota_only_without_identity_client(self):
        config = _make_config()
        compute = MagicMock()
        limits = MagicMock()

        limits.get_resource_availability.side_effect = [
            _mock_quota_response(4, 0),
            _mock_quota_response(24, 0),
        ]

        result = check_availability(config, compute, limits, identity_client=None)

        self.assertEqual(result.status, STATUS_QUOTA_ONLY)

    def test_error_on_shape_api_failure(self):
        config = _make_config()
        compute = MagicMock()
        limits = MagicMock()
        identity = MagicMock()

        limits.get_resource_availability.side_effect = [
            _mock_quota_response(4, 0),
            _mock_quota_response(24, 0),
        ]
        identity.list_availability_domains.side_effect = (
            oci.exceptions.ServiceError(
                status=500,
                code="InternalServerError",
                headers={},
                message="Internal error",
            )
        )

        result = check_availability(config, compute, limits, identity)

        self.assertEqual(result.status, STATUS_ERROR)
        self.assertIn("500", result.details)

    def test_shape_found_but_ocpu_out_of_range(self):
        config = _make_config(ocpus=100.0)
        compute = MagicMock()
        limits = MagicMock()
        identity = MagicMock()

        limits.get_resource_availability.side_effect = [
            _mock_quota_response(100, 0),
            _mock_quota_response(600, 0),
        ]
        identity.list_availability_domains.return_value = MagicMock(
            data=[_mock_ad("AD-1")]
        )
        compute.list_shapes.return_value = MagicMock(
            data=[_mock_shape("VM.Standard.A1.Flex", ocpu_max=80)]
        )

        result = check_availability(config, compute, limits, identity)

        self.assertEqual(result.status, STATUS_QUOTA_ONLY)
        self.assertFalse(result.shape_available)


if __name__ == "__main__":
    unittest.main()
