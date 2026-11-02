# MediRoute — Local Run & Deployment

## 1. Prerequisites

- Python 3.11 or newer
- pip and venv
- Optional: Tesseract OCR binary on PATH for image text extraction

## 2. Run locally

```bash
cd mediroute
python -m venv .venv
```

Activate the environment:

```powershell
# Windows PowerShell
.venv\Scripts\Activate.ps1
```

```bash
# macOS / Linux
source .venv/bin/activate
```

Install dependencies and start the server:

```bash
pip install -r requirements.txt
python app.py
```

Visit `http://127.0.0.1:5000`. SQLite tables and sample data are created automatically on first run.

## 3. Demo sign-in

| Role | Email | Demo OTP |
|---|---|---|
| Customer | customer@mediroute.demo | 246810 |
| Pharmacist | pharmacist@mediroute.demo | 246810 |
| Operations | admin@mediroute.demo | 246810 |

The OTP endpoint is a mock. It returns a demo code only when `APP_ENV` is not `production`. No SMS or WhatsApp is sent.

## 4. Environment variables

Copy `.env.example` to `.env` and configure these names. Never commit values.

- `SECRET_KEY` — required unique random secret for signed sessions and prescription encryption key derivation
- `DATABASE_PATH` — SQLite file path for local demo
- `UPLOAD_DIR` — private encrypted upload directory
- `PORT` — HTTP port
- `FLASK_DEBUG` — set to `0` outside local development
- `APP_ENV` — set to `production` to disable demo OTP disclosure
- `DEMO_OTP` — local mock OTP; use a real OTP provider instead of this in production

Changing `SECRET_KEY` after documents have been uploaded prevents decryption of those files. Back up and rotate keys using a managed key-encryption process in production.

## 5. Deploying a demo

This repository is a Flask application and can be deployed to a Python WSGI host (for example Render, Railway, or a managed container platform). Configure the start command as:

```bash
gunicorn app:app
```

Add `gunicorn` to `requirements.txt` for the chosen host. Configure persistent storage for SQLite and `UPLOAD_DIR`, or preferably migrate to PostgreSQL plus private object storage before a multi-instance deployment. Terminate TLS at the hosting platform and enable secure cookies, CSRF protection, rate limits and managed secrets. Do not expose the private upload directory as a static folder.

This demo has not been deployed to a public URL. Do not claim a live deployment until one has been completed and tested.

## 6. Sample inventory CSV

Use `data/inventory_sample.csv` in the Store & Stock screen. Required headers are `store,sku,stock`.

## 7. Tests

```bash
python -m unittest discover -s tests -v
python -m py_compile app.py safety.py
node --check static/app.js
```

## 8. Safety and limitations

- All payments are test labels only; no payment is collected.
- OTP and messaging are mocked.
- AI/OCR output is only a draft. Pharmacist approval is mandatory for Schedule H/H1 items.
- H1 approval requires prescriber and patient details to be recorded.
- Schedule X and narcotic categories are blocked.
- No medical advice is generated.
- The seeded locations are a subset of the proposed chain. Stock and route calculations are sample-only.
- Do not upload real patient prescriptions. The project is a take-home prototype, not a production e-pharmacy.
