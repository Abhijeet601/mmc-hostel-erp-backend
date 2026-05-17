# MMC Hostel ERP Backend

## Run locally

```bash
cd hostel-erp-backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Database

`DATABASE_URL` supports:

- `sqlite:///./hostel_erp.db` for local demo mode
- `postgresql+psycopg2://...` for PostgreSQL
- `mysql+pymysql://...` for MySQL

On Railway, if no database environment variables are present, the app now falls back to the configured `DATABASE_URL`.
If that fallback is SQLite, the service will start, but this should be treated as demo-only because Railway storage is ephemeral and data can be lost on redeploy/restart.

See `.env.example` for SMTP, upload, and admin settings.

## Default admin

- `username`: `admin`
- `password`: `admin123`

Change these with `ADMIN_USERNAME` and `ADMIN_PASSWORD`.

## ERP endpoints

- `POST /api/register`
- `POST /api/login`
- `GET /api/application`
- `POST /api/application/draft`
- `POST /api/application/submit`
- `GET /api/dashboard`
- `POST /api/payment/application`
- `POST /api/payment/hostel`
- `POST /api/hostel/preference`
- `POST /api/admin/login`
- `GET /api/admin/dashboard`
- `GET /api/admin/students`
- `DELETE /api/admin/students/{id}`
- `PATCH /api/admin/students/{id}/verify`
- `PATCH /api/admin/students/{id}/shortlist`
- `PATCH /api/admin/students/{id}/allocate-hostel`
- `POST /api/admin/upload-shortlist`
- `GET /api/admin/export-excel`

## Notes

- Payments are demo/manual right now, but the flow and receipt generation are wired for later gateway integration.
- Merchant metadata and gateway secrets must be stored in backend `.env` only. Nothing sensitive is exposed to the frontend.
- Receipt emails are sent only when SMTP is configured; otherwise the API reports a simulated email status.
- Notices/admin notice management routes remain available under `/api/notices`.
