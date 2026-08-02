#!/usr/bin/env bash
# Poll an HTTP endpoint until it responds, printing Compose logs when it never does.
#
# Usage: scripts/wait_for_http.sh [url] [attempts] [delay_seconds]

set -euo pipefail

url="${1:-http://127.0.0.1/}"
attempts="${2:-30}"
delay="${3:-2}"

for _ in $(seq 1 "$attempts"); do
  if curl --fail --silent "$url" > /dev/null; then
    echo "$url responded successfully."
    exit 0
  fi
  sleep "$delay"
done

echo "$url did not respond after $attempts attempts."
docker compose logs
exit 1
