# Oracle A1.Flex Availability Checker — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a read-only GitHub Actions workflow that checks OCI A1.Flex availability in ap-batam-1 every 60 minutes and emails when capacity is indicated.

**Architecture:** Python modules separated by concern: config, OCI auth, checker (quota + shape availability), notifier (SMTP), and a main entry point. GitHub Actions workflow runs on schedule and on manual dispatch. Results are classified into four statuses: `AVAILABLE` (shape availability + quota both positive), `QUOTA_ONLY` (quota exists but availability unconfirmed), `UNAVAILABLE`, and `ERROR`. Email fires only on `AVAILABLE`. All results are logged as workflow artifacts.

**Tech Stack:** Python 3.11+, `oci` SDK, `smtplib` (stdlib), `unittest` with `unittest.mock`, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-11-14-oracle-a1-checker-design.md` (inline — this plan is the spec for this small project)

## Global Constraints

- Read-only: no compute instance creation, no `LaunchInstance`, no `manage` permissions.
- OCI SDK only — no Terraform, no CLI wrappers.
- Email notification only on `AVAILABLE` status — never on `QUOTA_ONLY`, `UNAVAILABLE`, or `ERROR`.
- Target: shape `VM.Standard.A1.Flex`, region `ap-batam-1`, 2 OCPU, 12 GB RAM.
- All OCI credentials come from GitHub Secrets, never hardcoded.
- Handle API errors, rate limits (429), and timeouts with retry + exponential backoff.
- Log every check result to `results/check-YYYY-MM-DDTHH-MM-SS.json`.

## Review Focus

1. **Rate-limited API response (429):** Checker must retry with backoff, not crash or report `AVAILABLE`. Test in Task 3.
2. **SMTP auth failure:** Notifier must log the error and exit non-zero, not silently succeed. Test in Task 4.
3. **Missing GitHub Secret:** Main must fail with a clear message naming the missing variable, not a Python traceback. Test in Task 5.
4. **Quota exists but shape unavailable:** Must classify as `QUOTA_ONLY`, never `AVAILABLE`. Test in Task 3.
5. **OCI SDK timeout:** Must classify as `ERROR` with details, not hang indefinitely. Test in Task 3.

---

### Task 1: Project Scaffolding + Config Module

**Files:**
- Create: `requirements.txt`
- Create: `src/__init__.py`
- Create: `src/config.py`
- Create: `tests/__init__.py`
- Create: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `Config` dataclass with fields: `region: str`, `compartment_id: str`, `shape: str`, `ocpus: float`, `memory_gb: float`, `smtp_host: str`, `smtp_port: int`, `smtp_user: str`, `smtp_password: str`, `email_from: str`, `email_to: str`
  - `load_config() -> Config` that reads from environment variables with defaults for region/shape/ocpus/memory_gb

- [ ] **Step 1: Write failing test for `load_config`**

```python
# tests/test_config.py
import os, unittest
from unittest.mock import patch

class TestLoadConfig(unittest.TestCase):
    @patch.dict(os.environ, {
        "OCI_COMPARTMENT_ID": "ocid1.compartment.oc1..test",
        "SMTP_HOST": "smtp.gmail.com",
        "SMTP_PORT": "587",
        "SMTP_USER": "user@gmail.com",
        "SMTP_PASSWORD": "pass",
        "EMAIL_FROM": "user@gmail.com",
        "EMAIL_TO": "dest@gmail.com",
    })
    def test_load_config_defaults(self):
        from src.config import load_config
        cfg = load_config()
        self.assertEqual(cfg.region, "ap-batam-1")
        self.assertEqual(cfg.shape, "VM.Standard.A1.Flex")
        self.assertEqual(cfg.ocpus, 2.0)
        self.assertEqual(cfg.memory_gb, 12.0)
        self.assertEqual(cfg.smtp_host, "smtp.gmail.com")

    def test_load_config_missing_compartment_raises(self):
        from src.config import load_config
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError):
                load_config()
```

- [ ] **Step 2: Run test — expect FAIL (module not found)**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Create `requirements.txt`**

```
oci>=2.125.0
```

- [ ] **Step 4: Create `src/__init__.py` (empty) and `tests/__init__.py` (empty)**

- [ ] **Step 5: Implement `src/config.py`**

`Config` as a `dataclass`. `load_config()` reads env vars, raises `ValueError` with the name of any missing required var (`OCI_COMPARTMENT_ID`, SMTP vars, email vars). Defaults: `region="ap-batam-1"`, `shape="VM.Standard.A1.Flex"`, `ocpus=2.0`, `memory_gb=12.0`.

- [ ] **Step 6: Run tests — expect PASS**

Run: `python -m pytest tests/test_config.py -v`
Expected: 2 passed

- [ ] **Step 7: Commit**

```bash
git add requirements.txt src/ tests/
git commit -m "feat: add config module with env-based loading"
```

---

### Task 2: OCI Auth Module

**Files:**
- Create: `src/oci_auth.py`
- Create: `tests/test_oci_auth.py`

**Interfaces:**
- Consumes: nothing (reads OCI env vars directly)
- Produces:
  - `build_oci_config() -> dict` — returns OCI SDK config dict from env vars
  - `create_compute_client(oci_config: dict) -> oci.core.ComputeClient`
  - `create_limits_client(oci_config: dict) -> oci.limits.LimitsClient`

- [ ] **Step 1: Write failing test**

```python
# tests/test_oci_auth.py
import os, unittest
from unittest.mock import patch, MagicMock

class TestBuildOciConfig(unittest.TestCase):
    @patch.dict(os.environ, {
        "OCI_USER_OCID": "ocid1.user.oc1..test",
        "OCI_TENANCY_OCID": "ocid1.tenancy.oc1..test",
        "OCI_FINGERPRINT": "aa:bb:cc",
        "OCI_API_KEY": "-----BEGIN RSA PRIVATE KEY-----\ntest\n-----END RSA PRIVATE KEY-----",
        "OCI_REGION": "ap-batam-1",
    })
    def test_build_config(self):
        from src.oci_auth import build_oci_config
        cfg = build_oci_config()
        self.assertEqual(cfg["user"], "ocid1.user.oc1..test")
        self.assertEqual(cfg["region"], "ap-batam-1")

    def test_missing_user_raises(self):
        from src.oci_auth import build_oci_config
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError):
                build_oci_config()
```

- [ ] **Step 2: Run test — expect FAIL**

Run: `python -m pytest tests/test_oci_auth.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `src/oci_auth.py`**

`build_oci_config()` reads `OCI_USER_OCID`, `OCI_TENANCY_OCID`, `OCI_FINGERPRINT`, `OCI_API_KEY`, `OCI_REGION` from env. Writes the private key to a temp file for OCI SDK compatibility. Raises `ValueError` naming any missing var. `create_compute_client` and `create_limits_client` instantiate SDK clients with retry strategy (max 3, backoff).

- [ ] **Step 4: Run tests — expect PASS**

Run: `python -m pytest tests/test_oci_auth.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/oci_auth.py tests/test_oci_auth.py
git commit -m "feat: add OCI auth module with env-based config"
```

---

### Task 3: Checker Module

**Files:**
- Create: `src/checker.py`
- Create: `tests/test_checker.py`

**Interfaces:**
- Consumes:
  - `Config` from `src.config`
  - `create_compute_client(dict) -> ComputeClient` from `src.oci_auth`
  - `create_limits_client(dict) -> LimitsClient` from `src.oci_auth`
- Produces:
  - `CheckResult` dataclass: `status: str` (one of `AVAILABLE`, `QUOTA_ONLY`, `UNAVAILABLE`, `ERROR`), `timestamp: str`, `quota_available: Optional[float]`, `quota_used: Optional[float]`, `quota_limit: Optional[float]`, `shape_available: bool`, `ad_name: Optional[str]`, `details: str`, `limitations: str`
  - `check_availability(config: Config, compute_client, limits_client) -> CheckResult`

- [ ] **Step 1: Write failing tests for status classification**

```python
# tests/test_checker.py — four test methods
class TestCheckAvailability(unittest.TestCase):
    def test_available_when_shape_and_quota(self):
        # Mock compute_client.list_shapes returns shape, limits_client returns quota > 0
        # Assert result.status == "AVAILABLE"

    def test_quota_only_when_no_shape_availability(self):
        # Mock compute_client.list_shapes returns shape but
        # list_availability_domains + capacity check is inconclusive
        # limits_client returns quota > 0
        # Assert result.status == "QUOTA_ONLY"

    def test_unavailable_when_no_quota(self):
        # Mock limits_client returns quota used == limit (0 remaining)
        # Assert result.status == "UNAVAILABLE"

    def test_error_on_api_timeout(self):
        # Mock compute_client.list_shapes raises oci.exceptions.RequestException
        # Assert result.status == "ERROR"
        # Assert "timeout" or error detail in result.details

    def test_error_on_rate_limit(self):
        # Mock raises ServiceError with status 429
        # Assert result.status == "ERROR"
        # Assert retry info in result.details
```

- [ ] **Step 2: Run tests — expect FAIL**

Run: `python -m pytest tests/test_checker.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `src/checker.py`**

`check_availability` does three things in order:
1. **Quota check**: `limits_client.get_resource_availability` for `standard-a1-core-count` and `standard-a1-memory-count` in the compartment. Computes remaining.
2. **Shape check**: `compute_client.list_shapes` filtered to `VM.Standard.A1.Flex` in the compartment. Confirms the shape is listed.
3. **Capacity signal**: attempts `compute_client.list_shapes` per AD, checks if the shape appears with the requested OCPU/memory within `ocpu_options` and `memory_options` ranges.

Classification:
- Shape listed + quota remaining > 0 + shape available in at least one AD → `AVAILABLE`
- Quota remaining > 0 but shape not confirmed in any AD → `QUOTA_ONLY`
- Quota remaining == 0 → `UNAVAILABLE`
- Any exception → `ERROR` with details

`limitations` field always states: "OCI API does not expose real-time host capacity. Shape listing per AD is the closest signal but does not guarantee launch success."

Wrap all API calls in try/except for `ServiceError` (check `.status` for 429 → retry) and `RequestException` (timeout).

- [ ] **Step 4: Run tests — expect PASS**

Run: `python -m pytest tests/test_checker.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/checker.py tests/test_checker.py
git commit -m "feat: add checker module with quota and shape availability"
```

---

### Task 4: Notifier Module

**Files:**
- Create: `src/notifier.py`
- Create: `tests/test_notifier.py`

**Interfaces:**
- Consumes:
  - `Config` from `src.config`
  - `CheckResult` from `src.checker`
- Produces:
  - `send_notification(config: Config, result: CheckResult) -> bool` — returns True if sent, False on error
  - `format_email_body(result: CheckResult) -> str`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_notifier.py
class TestNotifier(unittest.TestCase):
    def test_format_email_body_contains_status(self):
        # Create CheckResult with status="AVAILABLE"
        # Assert "AVAILABLE" in format_email_body(result)
        # Assert "ap-batam-1" in body
        # Assert "VM.Standard.A1.Flex" in body

    def test_send_notification_calls_smtp(self):
        # Mock smtplib.SMTP
        # Assert login called with config.smtp_user, config.smtp_password
        # Assert sendmail called

    def test_send_notification_returns_false_on_smtp_error(self):
        # Mock smtplib.SMTP.login raises SMTPAuthenticationError
        # Assert returns False
        # Assert error logged
```

- [ ] **Step 2: Run tests — expect FAIL**

Run: `python -m pytest tests/test_notifier.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `src/notifier.py`**

`format_email_body` produces a plain-text email with: status, region, shape, OCPU, memory, quota details, AD info, timestamp, and limitations disclaimer. `send_notification` uses `smtplib.SMTP` with STARTTLS, logs success/failure, returns bool. Timeout on SMTP connection: 30 seconds.

- [ ] **Step 4: Run tests — expect PASS**

Run: `python -m pytest tests/test_notifier.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/notifier.py tests/test_notifier.py
git commit -m "feat: add SMTP email notifier module"
```

---

### Task 5: Main Entry Point + Result Logging

**Files:**
- Create: `src/main.py`
- Create: `tests/test_main.py`

**Interfaces:**
- Consumes:
  - `load_config() -> Config` from `src.config`
  - `build_oci_config() -> dict` from `src.oci_auth`
  - `create_compute_client`, `create_limits_client` from `src.oci_auth`
  - `check_availability(Config, ComputeClient, LimitsClient) -> CheckResult` from `src.checker`
  - `send_notification(Config, CheckResult) -> bool` from `src.notifier`
- Produces:
  - `main() -> int` — returns exit code 0 on success, 1 on error
  - Writes JSON log to `results/check-{timestamp}.json`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_main.py
class TestMain(unittest.TestCase):
    @patch("src.main.check_availability")
    @patch("src.main.send_notification")
    @patch("src.main.load_config")
    @patch("src.main.build_oci_config")
    @patch("src.main.create_compute_client")
    @patch("src.main.create_limits_client")
    def test_sends_email_only_on_available(self, ...):
        # Set check_availability return to status="AVAILABLE"
        # Assert send_notification called
        # Set status="QUOTA_ONLY" — assert send_notification NOT called
        # Set status="UNAVAILABLE" — assert send_notification NOT called

    def test_writes_result_json(self, ...):
        # Assert file created in results/ dir
        # Assert JSON contains "status", "timestamp"

    def test_missing_env_exits_with_error(self):
        # Clear env, assert SystemExit or return code 1
```

- [ ] **Step 2: Run tests — expect FAIL**

Run: `python -m pytest tests/test_main.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `src/main.py`**

`main()`: load config → build OCI config → create clients → check availability → log result JSON to `results/` → if `AVAILABLE`, send notification → print summary to stdout → return exit code. Wrap everything in try/except, print clear error message for `ValueError` (missing config).

- [ ] **Step 4: Run tests — expect PASS**

Run: `python -m pytest tests/test_main.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/main.py tests/test_main.py
git commit -m "feat: add main entry point with result logging"
```

---

### Task 6: GitHub Actions Workflow + README

**Files:**
- Create: `.github/workflows/check-availability.yml`
- Create: `README.md`

**Interfaces:**
- Consumes: `src/main.py` as entry point
- Produces: working CI workflow + deployment documentation

- [ ] **Step 1: Create `.github/workflows/check-availability.yml`**

Schedule: `cron: '0 * * * *'` (every 60 minutes). Also `workflow_dispatch` for manual runs. Steps:
1. Checkout repo
2. Setup Python 3.11
3. `pip install -r requirements.txt`
4. Run `python -m src.main` with env vars mapped from secrets: `OCI_USER_OCID`, `OCI_TENANCY_OCID`, `OCI_FINGERPRINT`, `OCI_API_KEY`, `OCI_COMPARTMENT_ID`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `EMAIL_FROM`, `EMAIL_TO`
5. Upload `results/` as artifact (retention 30 days)

- [ ] **Step 2: Create `README.md`**

Sections: Project overview, architecture diagram (text), prerequisites (OCI account, API key), GitHub Secrets setup (table of all required secrets with descriptions), how to generate OCI API key, how to configure SMTP (Gmail App Password example), manual run instructions, status classification explanation, limitations disclaimer, project structure.

- [ ] **Step 3: Run all tests**

Run: `python -m pytest tests/ -v`
Expected: all passed

- [ ] **Step 4: Commit**

```bash
git add .github/ README.md
git commit -m "feat: add GitHub Actions workflow and README"
```

---
