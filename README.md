# Oracle A1.Flex Availability Checker

Monitor ketersediaan **VM.Standard.A1.Flex** di Oracle Cloud region **ap-batam-1** (Batam) melalui GitHub Actions. Checker ini **read-only** — tidak pernah membuat atau memprovision VM.

## Cara Kerja

```
┌─────────────────────────────────────────────────────┐
│              GitHub Actions (setiap 60 menit)        │
│                                                      │
│  ┌──────────┐    ┌──────────┐    ┌──────────────┐   │
│  │  Config   │───▶│  Checker │───▶│  Notifier    │   │
│  │  (env)    │    │  (OCI    │    │  (SMTP email)│   │
│  └──────────┘    │   SDK)   │    └──────────────┘   │
│                  └──────────┘                        │
│                       │                              │
│                  ┌──────────┐                        │
│                  │  Results  │                        │
│                  │  (JSON)   │                        │
│                  └──────────┘                        │
└─────────────────────────────────────────────────────┘
```

### Status Klasifikasi

| Status | Arti | Email? |
|--------|------|--------|
| `AVAILABLE` | Shape ditemukan di AD + kuota tersedia | ✅ Ya |
| `QUOTA_ONLY` | Kuota tersedia tapi shape tidak terkonfirmasi di AD mana pun | ❌ Tidak |
| `UNAVAILABLE` | Kuota habis (OCPU atau RAM) | ❌ Tidak |
| `ERROR` | API error, timeout, atau rate limit | ❌ Tidak |

> **Penting:** Status `QUOTA_ONLY` **tidak pernah** dianggap sebagai kapasitas tersedia. OCI API tidak mengekspos real-time host capacity; listing shape per Availability Domain adalah sinyal terdekat tetapi tidak menjamin launch berhasil.

## Target Default

- **Shape:** VM.Standard.A1.Flex
- **Region:** ap-batam-1
- **OCPU:** 2
- **RAM:** 12 GB
- **Jadwal:** Setiap 60 menit

## Prasyarat

1. Akun Oracle Cloud (Free Tier atau berbayar)
2. OCI API Key (RSA key pair)
3. Akun email dengan SMTP access (contoh: Gmail dengan App Password)
4. Repository GitHub

## Setup OCI API Key

1. Login ke [OCI Console](https://cloud.oracle.com)
2. Buka **Profile** → **My Profile** → **API Keys**
3. Klik **Add API Key** → **Generate API Key Pair**
4. Download private key (`.pem` file)
5. Catat informasi dari configuration file preview:
   - `user` → `OCI_USER_OCID`
   - `tenancy` → `OCI_TENANCY_OCID`
   - `fingerprint` → `OCI_FINGERPRINT`
   - `region` → `OCI_REGION`
6. Isi private key ke `OCI_API_KEY` (isi file `.pem`, bukan path)

### Mendapatkan Compartment ID

1. Buka **Identity & Security** → **Compartments**
2. Klik compartment yang ingin digunakan (atau root compartment)
3. Salin OCID → `OCI_COMPARTMENT_ID`

## Setup SMTP (Contoh: Gmail)

1. Aktifkan **2-Step Verification** di akun Google
2. Buka [App Passwords](https://myaccount.google.com/apppasswords)
3. Buat App Password untuk "Mail"
4. Gunakan:
   - `SMTP_HOST` = `smtp.gmail.com`
   - `SMTP_PORT` = `587`
   - `SMTP_USER` = email Gmail Anda
   - `SMTP_PASSWORD` = App Password yang dibuat

## GitHub Secrets

Buka **repository** → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

Tambahkan semua secret berikut:

| Secret | Deskripsi | Contoh |
|--------|-----------|--------|
| `OCI_USER_OCID` | OCID user OCI | `ocid1.user.oc1..aaa...` |
| `OCI_TENANCY_OCID` | OCID tenancy OCI | `ocid1.tenancy.oc1..aaa...` |
| `OCI_FINGERPRINT` | Fingerprint API key | `aa:bb:cc:dd:...` |
| `OCI_API_KEY` | Isi file PEM private key | `-----BEGIN RSA PRIVATE KEY-----...` |
| `OCI_REGION` | Region OCI | `ap-batam-1` |
| `OCI_COMPARTMENT_ID` | OCID compartment | `ocid1.compartment.oc1..aaa...` |
| `SMTP_HOST` | SMTP server | `smtp.gmail.com` |
| `SMTP_PORT` | SMTP port | `587` |
| `SMTP_USER` | SMTP username | `you@gmail.com` |
| `SMTP_PASSWORD` | SMTP password | `xxxx xxxx xxxx xxxx` |
| `EMAIL_FROM` | Pengirim email | `you@gmail.com` |
| `EMAIL_TO` | Penerima notifikasi | `you@gmail.com` |

### Secret Opsional (Override Default)

| Secret | Default | Deskripsi |
|--------|---------|-----------|
| `OCI_SHAPE` | `VM.Standard.A1.Flex` | Shape yang dicek |
| `OCI_OCPUS` | `2` | Jumlah OCPU target |
| `OCI_MEMORY_GB` | `12` | RAM target (GB) |

## Deployment

1. Fork atau clone repository ini
2. Tambahkan semua GitHub Secrets (lihat tabel di atas)
3. Workflow akan berjalan otomatis setiap 60 menit
4. Untuk menjalankan manual: **Actions** → **OCI A1.Flex Availability Checker** → **Run workflow**

## Menjalankan Lokal (Untuk Testing)

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
export OCI_USER_OCID="ocid1.user.oc1..xxx"
export OCI_TENANCY_OCID="ocid1.tenancy.oc1..xxx"
export OCI_FINGERPRINT="aa:bb:cc:..."
export OCI_API_KEY="$(cat ~/.oci/oci_api_key.pem)"
export OCI_REGION="ap-batam-1"
export OCI_COMPARTMENT_ID="ocid1.compartment.oc1..xxx"
export SMTP_HOST="smtp.gmail.com"
export SMTP_PORT="587"
export SMTP_USER="you@gmail.com"
export SMTP_PASSWORD="your-app-password"
export EMAIL_FROM="you@gmail.com"
export EMAIL_TO="you@gmail.com"

# Jalankan checker
python -m src.main

# Jalankan tests
python -m pytest tests/ -v
```

## Struktur Project

```
├── .github/
│   └── workflows/
│       └── check-availability.yml   # GitHub Actions workflow
├── src/
│   ├── __init__.py
│   ├── config.py                    # Konfigurasi dari env vars
│   ├── oci_auth.py                  # Autentikasi OCI SDK
│   ├── checker.py                   # Logic pengecekan quota + shape
│   ├── notifier.py                  # Notifikasi email SMTP
│   └── main.py                      # Entry point
├── tests/
│   ├── __init__.py
│   ├── test_config.py
│   ├── test_oci_auth.py
│   ├── test_checker.py
│   ├── test_notifier.py
│   └── test_main.py
├── requirements.txt
├── .gitignore
└── README.md
```

## Penanganan Error

| Error | Penanganan |
|-------|------------|
| API timeout | Retry otomatis (3x, exponential backoff) |
| Rate limit (429) | Retry otomatis via OCI SDK retry strategy |
| Missing secret | Exit code 1 dengan pesan yang menyebutkan variabel yang hilang |
| SMTP gagal | Log error, exit code 0 (checker tetap berhasil, hanya notifikasi gagal) |
| OCI SDK error | Status `ERROR`, detail dicatat di JSON log |

## Keterbatasan

- **OCI API tidak mengekspos real-time host capacity.** Listing shape per Availability Domain adalah sinyal terdekat, tetapi shape yang terdaftar tidak menjamin VM bisa di-launch.
- **`QUOTA_ONLY` bukan berarti kapasitas tersedia.** Kuota hanya menunjukkan batas tenancy, bukan kapasitas fisik host.
- Checker ini **tidak** membuat, memprovision, atau memodifikasi resource OCI apa pun.

## Lisensi

MIT
