# Audio Download Worker

Proxy-rotating YouTube → MP3 downloader, packaged as a **Cloud Run Job**. It
pulls audio with `yt-dlp` (via `ffmpeg`), rotates through SmartProxy or Webshare
proxies, optionally geo-targets restricted videos with the YouTube Data API, and
reports progress/results through a decoupled visibility layer (Pub/Sub +
Firestore + an optional HTTP callback), uploading the finished MP3 to GCS.


This is the **data plane**. It is triggered by the [gateway](../gateway) (or any
caller with `roles/run.developer`); it never exposes an HTTP API itself.

## Architecture

```
gateway / trigger
      │ run_job (per-run env overrides)
      ▼
┌─────────────────────────────┐
│  Cloud Run Job (this)       │
│  yt-dlp + ffmpeg            │
│  proxy rotation             │
└──────┬───────────┬──────────┘
       │           │
 progress      final asset
 (transient)   (persisted)
       │           │
   Pub/Sub     Firestore + callback_url
                   │
                  GCS (MP3 upload)
```

- **Progress** is transient → published to Pub/Sub only (no DB write-bloat).
- **Final assets** are persisted to Firestore and POSTed to the requester's
  `callback_url` ("return address" pattern), so the worker stays stateless with
  respect to other projects' databases.

## Layout

| Path | Responsibility |
|------|----------------|
| `src/main.py` | CLI / env entry point; routes to geo-targeting or the standard provider loop. |
| `src/config.py` | Centralized env-var config (Secret Manager injects secrets as env vars). |
| `src/downloader.py` | `yt-dlp` wrapper with proxy rotation + retries. |
| `src/proxy_manager.py` | Generic proxy pool (rotation, scoring, cooldown). |
| `src/providers/` | `ProxyProvider` implementations: `smartproxy`, `webshare`, `dataimpulse`. |
| `src/restrictions.py` | Resolves a SmartProxy country that can view a geo-restricted video. |
| `src/youtube_client.py` | Authenticated YouTube Data API client (content-owner SA or API key). |
| `src/storage/` | Visibility layer: events, Pub/Sub, Firestore, callback, GCS, `JobReporter`. |

The finished MP3 is **streamed** into `RESULT_BUCKET` as `<video_id>.mp3` (see
`src/storage/bucket.py` → `AudioStreamService`) using a resumable, chunked
upload so memory stays flat on Cloud Run's ephemeral disk. The resulting
`gs://` URI is recorded on the job's final asset (`asset_uri`).

## Run locally

Dependencies are managed with [uv](https://docs.astral.sh/uv/). `ffmpeg` must be
installed and on `PATH`.

```bash
cd worker

# SmartProxy rotating gateway
uv run python src/main.py "https://youtu.be/VIDEO_ID" \
  --provider smartproxy \
  --smartproxy-gateway gate.smartproxy.com:7000 \
  --smartproxy-username USER --smartproxy-password PASS

# Webshare via API token
uv run python src/main.py "https://youtu.be/VIDEO_ID" \
  --provider webshare --webshare-token YOUR_TOKEN

# DataImpulse rotating gateway
uv run python src/main.py "https://youtu.be/VIDEO_ID" \
  --provider dataimpulse \
  --dataimpulse-username LOGIN --dataimpulse-password PASS

# Bypass YouTube bot checks with browser cookies
uv run python src/main.py "https://youtu.be/VIDEO_ID" \
  --provider webshare --cookies-from-browser chrome
```

Credentials can also come from the environment (`SMARTPROXY_*`, `WEBSHARE_*`),
which is how they arrive in Cloud Run.

## Configuration (environment variables)

### Job inputs / behaviour
| Var | Description |
|-----|-------------|
| `VIDEO_URLS` | Comma/space/newline-separated URLs to download. |
| `PROVIDER` | `smartproxy` (default), `webshare`, or `dataimpulse`. |
| `OUTPUT_DIR` | Local working dir (default `downloads`). |
| `AUDIO_QUALITY` | MP3 bitrate in kbps (default `192`). |
| `MAX_ATTEMPTS` | Max proxy rotations per video (default `8`). |
| `COOKIES_FILE` | Path to a Netscape cookies.txt. |
| `VERIFY_COUNTRY` | Confirm the proxy exit country (default `true`). |

### Provider credentials (Secret Manager → env)
| Var | Description |
|-----|-------------|
| `SMARTPROXY_GATEWAY` / `SMARTPROXY_USERNAME` / `SMARTPROXY_PASSWORD` | SmartProxy rotating gateway creds. |
| `SMARTPROXY_API_URL` / `SMARTPROXY_COUNTRY_FORMAT` | Optional API-extraction list / country template. |
| `WEBSHARE_TOKEN` | Webshare API token (fetches the proxy list). |
| `WEBSHARE_USERNAME` / `WEBSHARE_PASSWORD` / `WEBSHARE_GATEWAY` | Webshare gateway creds. |
| `DATAIMPULSE_USERNAME` / `DATAIMPULSE_PASSWORD` | DataImpulse rotating gateway login. |
| `DATAIMPULSE_GATEWAY` / `DATAIMPULSE_COUNTRY_FORMAT` | Optional gateway override / country template. |

### YouTube Data API (geo-restriction resolution, SmartProxy only)
| Var | Description |
|-----|-------------|
| `YOUTUBE_SA_JSON` | Cross-project content-owner SA key JSON. |
| `YOUTUBE_CONTENT_OWNER_ID` | Content owner id for `onBehalfOfContentOwner`. |
| `YOUTUBE_API_KEY` | API key alternative to the SA. |

### Visibility / persistence
| Var | Description |
|-----|-------------|
| `JOB_ID` | Unique id for this run (set per execution by the gateway). |
| `ORIGIN_ID` | Correlation id of the requesting service. |
| `CALLBACK_URL` | URL to POST the final result to. |
| `PUBSUB_TOPIC` | Topic for transient progress events. |
| `FIRESTORE_COLLECTION` / `FIRESTORE_DATABASE` | Where final assets are persisted. |
| `RESULT_BUCKET` | GCS bucket the finished MP3 is uploaded to. |
| `GOOGLE_PROJECT_ID` / `ENVIRONMENT` | GCP context (set by the deploy workflow). |

## Build & deploy

The container is built and deployed to a Cloud Run Job by
[.github/workflows/dev_executor_deploy.yaml](../.github/workflows/dev_executor_deploy.yaml)
on push to `dev_executor_deploy`. It provisions the Pub/Sub topic and result
bucket, grants the runtime SA its IAM roles, and wires secrets via
`--set-secrets`.

Trigger a single run with per-execution inputs:

```bash
gcloud run jobs execute lds-sc-audio-download-job --region us-central1 \
  --update-env-vars JOB_ID=abc123,ORIGIN_ID=project-a,\
CALLBACK_URL=https://project-a.example/api/jobs/abc123,\
VIDEO_URLS="https://youtu.be/VIDEO_ID"
```

## Tests

```bash
cd worker
uv run python src/test_request.py
```
