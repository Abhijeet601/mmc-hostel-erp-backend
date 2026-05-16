# Node-RED Bulk Old Students Flow

This sample flow uses the same FastAPI endpoint as the admin UI:

- `POST /api/bulk-upsert-old-students`

It sends JSON, not multipart, so Node-RED can call the endpoint directly after an Excel parser node has converted the workbook into `msg.payload.rows`.

## Expected payload

```json
{
  "rows": [
    {
      "row_number": 2,
      "name": "Asha Kumari",
      "email": "asha.bulk@example.com",
      "course": "B.A.",
      "category": "GEN",
      "hostel": "Vaidehi Hostel",
      "block": "A",
      "room": "101",
      "bed": "",
      "hostel_id": ""
    }
  ],
  "preview_only": true,
  "generate_ids": true,
  "update_existing": true,
  "allocate_rooms": true
}
```

## Environment variables

- `ERP_API_BASE`
  Example: `http://127.0.0.1:8000`
- `ERP_ADMIN_TOKEN`
  Bearer token from the admin login flow

## Recommended flow

1. Upload Excel in Node-RED Dashboard or watch a shared upload folder.
2. Parse the workbook into `msg.payload.rows`.
3. Send `preview_only: true` first and display the returned summary.
4. On confirmation, resend the same rows with `preview_only: false`.
5. Show `created`, `updated`, `errors`, `hostel_id_preview.next_ids`, and `error_report_url`.
