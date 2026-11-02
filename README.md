# MediRoute — Pharmacy Reordering & Prescription Verification

A full-stack demonstration for a fictional Kolkata/Howrah pharmacy chain. It covers customer reordering, encrypted prescription upload, OCR-assisted draft extraction, pharmacist review, nearest-stocked-store routing, refill estimates and backend dispatch safety controls.

> **Demonstration only.** Do not use for real medicine sales, diagnosis, treatment, or storage of real patient data. It is not a legally compliant e-pharmacy deployment. Have qualified pharmacy, privacy, security and legal teams validate every rule before production.

## Stack

- Python + Flask REST API
- SQLite for local demo persistence
- Vanilla JavaScript, responsive HTML/CSS
- Tesseract OCR (optional system dependency) with fuzzy catalogue matching
- Fernet authenticated encryption for uploaded prescription bytes
- `unittest` for policy tests

## Quick start

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # Windows: copy .env.example .env
python app.py
```

Open http://127.0.0.1:5000.

The app creates `mediroute.db` and demo records on first launch. Demo OTP: `246810`.

### Demo accounts

| Role | Email | OTP |
|---|---|---|
| Customer | customer@mediroute.demo | 246810 |
| Pharmacist | pharmacist@mediroute.demo | 246810 |
| Operations | admin@mediroute.demo | 246810 |

## OCR setup

Install the Tesseract OCR binary separately and make sure `tesseract` is available on PATH. The Python `pytesseract` package is only a wrapper. If Tesseract is missing or the image is unreadable, the app records that no readable text was detected and requires manual pharmacist review. PDFs are routed to manual review in this demo.

## Tests

```bash
python -m unittest discover -s tests -v
python -m py_compile app.py safety.py
node --check static/app.js
```

## Sample inventory

Import `data/inventory_sample.csv` from Store & Stock as a pharmacist or operations user. The CSV format is `store,sku,stock`.

## Security and product notes

- Prescription uploads are encrypted at rest using Fernet; the key is derived from `SECRET_KEY`. Set a long, unique `SECRET_KEY` before deployment and back it up securely. Changing it makes existing uploaded documents unreadable.
- Prescription file access requires an authenticated owner or pharmacist/admin session and is logged.
- Session cookies are signed by Flask. For production, enable HTTPS, secure cookie flags, CSRF protection, rate limiting, MFA for staff, managed secrets and hardened session controls.
- Schedule H/H1 items require an attached prescription and pharmacist approval. H1 approval also requires prescriber and patient details in the register.
- Schedule X and narcotic categories are blocked from online sale in this demo.
- Dispatch checks are enforced by the backend and inventory is decremented after stock is rechecked.
- The OTP and payments are mock integrations. The demo code is intentionally exposed in non-production mode.
- Routing uses a central Kolkata demo origin and straight-line Haversine distance. Production must use a consented customer address, validated geocoding and a proper delivery-routing service.
- The seeded network contains 10 named stores plus a central warehouse, not all 46 live branches. Add the remaining client-provided store records before any client pilot.
- Refill calculations are reminders only and must not be interpreted as medical advice or change prescribed dosage.

## Main routes

- `POST /api/auth/request-otp`, `POST /api/login`, `POST /api/logout`
- `GET /api/medicines`, `GET /api/profiles`
- `POST /api/prescriptions`, `GET /api/prescriptions/:id/file`
- `POST /api/orders`, `GET /api/orders`
- `GET /api/queue`, `POST /api/verify/:item_id`
- `POST /api/orders/:id/dispatch`
- `GET/POST /api/refills`
- `GET /api/dashboard`, `POST /api/inventory/import`

## Production work still required

PostgreSQL migration, proper OTP provider, real UPI gateway, transactional outbox for notifications, complete 46-store master data, object storage/KMS key management, robust OCR/handwriting model evaluation, malware scanning, audit-log tamper resistance, consent and retention workflows, Bengali/Hindi translations, accessibility review, legal review, operational monitoring and end-to-end tests against a staging deployment.
