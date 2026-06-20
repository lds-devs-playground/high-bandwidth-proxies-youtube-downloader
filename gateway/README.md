# YouTube Downloader Gateway

FastAPI control-plane service that fronts the Cloud Run worker Job.

It authenticates callers, validates requests, mints a `JOB_ID`, and starts the
worker Job (fire-and-forget) with per-run environment overrides. Job status is
read back from the worker's Firestore collection — the gateway never downloads
or transcodes anything itself.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/jobs` | Enqueue a download. Returns a generated `job_id`. |
| `GET`  | `/jobs/{job_id}` | Read job status from Firestore. |
| `GET`  | `/healthz` | Liveness probe. |

Auth is handled at the platform edge. The service deploys with
`--ingress internal --no-allow-unauthenticated`, so only internal callers that
present a valid Cloud Run **IAM identity token** (a service account with
`roles/run.invoker` on this service) can reach it. There are no application-level
API keys. Every request must carry an `origin_id` so jobs stay attributable.

## Environment

| Var | Purpose |
|-----|---------|
| `GOOGLE_PROJECT_ID` | GCP project hosting the worker Job. |
| `REGION` | Cloud Run region (default `us-central1`). |
| `JOB_NAME` | Worker Cloud Run Job name. |
| `FIRESTORE_COLLECTION` | Collection the worker writes results to. |
| `FIRESTORE_DATABASE` | Firestore database (default `(default)`). |
| `DEFAULT_PROVIDER` | Proxy provider when the request omits one. |

## Run locally

```bash
cd gateway
uv run uvicorn src.main:app --reload --port 8080
```

```bash
curl -X POST localhost:8080/jobs \
  -H 'Content-Type: application/json' \
  -d '{"urls":["https://youtu.be/VIDEO_ID"],"origin_id":"project-a","callback_url":"https://example.com/cb"}'
```

Calling the deployed service from another internal service account:

```bash
TOKEN=$(gcloud auth print-identity-token)
curl -X POST "$GATEWAY_URL/jobs" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"urls":["https://youtu.be/VIDEO_ID"],"origin_id":"project-a"}'
```
