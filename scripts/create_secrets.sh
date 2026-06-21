#!/usr/bin/env bash
#
# Create (or update) the Secret Manager secrets required by the worker Cloud Run Job.
#
# These are referenced by the `--set-secrets` flag in
# .github/workflows/dev_executor_deploy.yaml as ENV_VAR=secret-name:latest.
#
# The secret *names* below must match the right-hand side of that mapping exactly.
#
# Usage:
#   PROJECT_ID=your-dev-project ./scripts/create_secrets.sh
#
# Optionally override the path to the YouTube service-account JSON:
#   YOUTUBE_SA_JSON_FILE=/path/to/yt-service-account.json \
#   PROJECT_ID=your-dev-project ./scripts/create_secrets.sh
#
# The script prompts for each secret value (input hidden) unless it is already
# provided via the matching environment variable. Re-running the script adds a
# new "latest" version rather than failing.

set -euo pipefail

# Load values from a .env file in the repo root if present, without clobbering
# variables already set in the environment.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$REPO_ROOT/.env}"
if [[ -f "$ENV_FILE" ]]; then
  echo "Loading values from $ENV_FILE"
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

PROJECT_ID="${PROJECT_ID:-}"
if [[ -z "$PROJECT_ID" ]]; then
  echo "ERROR: PROJECT_ID is required. Example:" >&2
  echo "  PROJECT_ID=your-dev-project ./scripts/create_secrets.sh" >&2
  exit 1
fi

# Path to the YouTube service-account JSON file. Defaults to repo root.
YOUTUBE_SA_JSON_FILE="${YOUTUBE_SA_JSON_FILE:-$REPO_ROOT/yt-service-account.json}"

# --- helpers ----------------------------------------------------------------

# secret_exists <secret-name>
secret_exists() {
  gcloud secrets describe "$1" --project="$PROJECT_ID" --quiet >/dev/null 2>&1
}

# upsert_secret <secret-name> <value>
# Creates the secret if missing, otherwise adds a new version.
upsert_secret() {
  local name="$1"
  local value="$2"
  if secret_exists "$name"; then
    printf '%s' "$value" | gcloud secrets versions add "$name" \
      --data-file=- --project="$PROJECT_ID" --quiet >/dev/null
    echo "  updated secret '$name' (new version added)"
  else
    printf '%s' "$value" | gcloud secrets create "$name" \
      --data-file=- --project="$PROJECT_ID" --quiet >/dev/null
    echo "  created secret '$name'"
  fi
}

# upsert_secret_from_file <secret-name> <file-path>
upsert_secret_from_file() {
  local name="$1"
  local file="$2"
  if [[ ! -f "$file" ]]; then
    echo "ERROR: file not found for secret '$name': $file" >&2
    exit 1
  fi
  if secret_exists "$name"; then
    gcloud secrets versions add "$name" \
      --data-file="$file" --project="$PROJECT_ID" --quiet >/dev/null
    echo "  updated secret '$name' from $file (new version added)"
  else
    gcloud secrets create "$name" \
      --data-file="$file" --project="$PROJECT_ID" --quiet >/dev/null
    echo "  created secret '$name' from $file"
  fi
}

# prompt_value <env-var-name> <prompt-label>
# Echoes the value from the named env var, or prompts (hidden input) if empty.
prompt_value() {
  local var_name="$1"
  local label="$2"
  local value="${!var_name:-}"
  if [[ -z "$value" ]]; then
    read -rsp "  Enter value for $label: " value
    echo >&2
  fi
  printf '%s' "$value"
}

# --- main -------------------------------------------------------------------

echo "Target project: $PROJECT_ID"
echo

# Smartproxy disabled for now.
# echo "smartproxy-gateway:"
# upsert_secret "smartproxy-gateway" "$(prompt_value SMARTPROXY_GATEWAY 'Smartproxy gateway (host:port)')"

# echo "smartproxy-username:"
# upsert_secret "smartproxy-username" "$(prompt_value SMARTPROXY_USERNAME 'Smartproxy username')"

# echo "smartproxy-password:"
# upsert_secret "smartproxy-password" "$(prompt_value SMARTPROXY_PASSWORD 'Smartproxy password')"

# Webshare disabled for now.
# echo "webshare-token:"
# upsert_secret "webshare-token" "$(prompt_value WEBSHARE_TOKEN 'Webshare API token')"

echo "dataimpulse-gateway:"
upsert_secret "dataimpulse-gateway" "$(prompt_value DATAIMPULSE_GATEWAY 'DataImpulse gateway (host:port)')"

echo "dataimpulse-username:"
upsert_secret "dataimpulse-username" "$(prompt_value DATAIMPULSE_USERNAME 'DataImpulse username')"

echo "dataimpulse-password:"
upsert_secret "dataimpulse-password" "$(prompt_value DATAIMPULSE_PASSWORD 'DataImpulse password')"

echo "youtube-content-owner-id:"
upsert_secret "youtube-content-owner-id" "$(prompt_value YOUTUBE_CONTENT_OWNER_ID 'YouTube content owner ID')"

echo "youtube-sa-json:"
upsert_secret_from_file "youtube-sa-json" "$YOUTUBE_SA_JSON_FILE"

echo
echo "Done. All worker secrets are present in project '$PROJECT_ID'."
