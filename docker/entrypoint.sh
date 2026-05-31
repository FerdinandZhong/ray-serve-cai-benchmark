#!/usr/bin/env bash
# CAI Benchmark entrypoint — Phoenix + web app + nginx ingress.
#
# Architecture (only port 8080 is externally reachable):
#
#   External HTTPS → :8080 (nginx)
#     /phoenix/   →  127.0.0.1:${PHOENIX_PORT}  — Arize Phoenix
#     /           →  127.0.0.1:${MANAGER_PORT}  — web app (evaluation manager)
#
# Environment variables:
#   PHOENIX_PORT     Internal Phoenix port (default: 6006)
#   MANAGER_PORT     Internal web app port (default: 9000)
#   DATA_DIR         Volume for cached Spider databases (default: /data)

set -euo pipefail

PHOENIX_PORT="${PHOENIX_PORT:-6006}"
MANAGER_PORT="${MANAGER_PORT:-9000}"
DATA_DIR="${DATA_DIR:-/data}"
NGINX_RUNTIME_DIR="/tmp/nginx"

# ── Find nginx ──────────────────────────────────────────────────────────────
NGINX_BIN=""
for _c in /usr/sbin/nginx /usr/bin/nginx /usr/local/sbin/nginx; do
    if [[ -x "$_c" ]]; then NGINX_BIN="$_c"; break; fi
done
[[ -z "$NGINX_BIN" ]] && { echo "[entrypoint] nginx not found"; exit 1; }
echo "[entrypoint] nginx: $NGINX_BIN"

# ── Locate mime.types ───────────────────────────────────────────────────────
MIME_TYPES="/etc/nginx/mime.types"
for _mt in /etc/nginx/mime.types /usr/share/nginx/mime.types; do
    [[ -f "$_mt" ]] && { MIME_TYPES="$_mt"; break; }
done

# ── Write nginx.conf ────────────────────────────────────────────────────────
mkdir -p "${NGINX_RUNTIME_DIR}/logs" "${NGINX_RUNTIME_DIR}/run"

cat > "${NGINX_RUNTIME_DIR}/nginx.conf" <<NGINX_CONF
worker_processes auto;
error_log  ${NGINX_RUNTIME_DIR}/logs/error.log warn;
pid        ${NGINX_RUNTIME_DIR}/run/nginx.pid;

events { worker_connections 1024; }

http {
    include      ${MIME_TYPES};
    default_type application/octet-stream;

    sendfile          on;
    keepalive_timeout 65;

    # Long timeouts — evaluation runs can take minutes
    proxy_read_timeout    600;
    proxy_send_timeout    600;
    proxy_connect_timeout  10;

    server {
        listen      8080;
        server_name _;

        # ── Web app (evaluation manager) at /app/ ──
        location /app/ {
            proxy_pass         http://127.0.0.1:${MANAGER_PORT}/;
            proxy_set_header   Host \$host;
            proxy_set_header   X-Real-IP \$remote_addr;
            proxy_buffering    off;
            proxy_cache        off;
        }

        # ── Phoenix at / (needs root path for React Router) ──
        location / {
            proxy_pass         http://127.0.0.1:${PHOENIX_PORT};
            proxy_set_header   Host \$host;
            proxy_set_header   X-Real-IP \$remote_addr;
            proxy_set_header   X-Forwarded-For \$proxy_add_x_forwarded_for;
            proxy_set_header   Upgrade \$http_upgrade;
            proxy_set_header   Connection "upgrade";
            proxy_buffering    off;
            proxy_cache        off;
        }
    }
}
NGINX_CONF

echo "[entrypoint] nginx config written"

# ── Ensure data directory exists ────────────────────────────────────────────
mkdir -p "${DATA_DIR}/spider"
export DATA_DIR

# ── Start Arize Phoenix ─────────────────────────────────────────────────────
echo "[entrypoint] starting Phoenix on :${PHOENIX_PORT} ..."
export PHOENIX_PORT
export PHOENIX_HOST="127.0.0.1"
export PHOENIX_WORKING_DIR="${DATA_DIR}/phoenix"
mkdir -p "${PHOENIX_WORKING_DIR}"

phoenix serve \
    --port "${PHOENIX_PORT}" \
    --host "127.0.0.1" \
    2>&1 | sed 's/^/[phoenix] /' &
PHOENIX_PID=$!
sleep 1
if ! kill -0 "$PHOENIX_PID" 2>/dev/null; then
    echo "[entrypoint] ERROR: Phoenix failed to start. Check logs above."
fi
echo "[entrypoint] Phoenix started (pid=${PHOENIX_PID})"

# Wait for Phoenix health (up to 30s)
for _i in $(seq 1 60); do
    if python3 -c "
import urllib.request, sys
try:
    urllib.request.urlopen('http://127.0.0.1:${PHOENIX_PORT}/healthz', timeout=1)
    sys.exit(0)
except Exception:
    sys.exit(1)
" 2>/dev/null; then
        echo "[entrypoint] Phoenix ready"
        break
    fi
    sleep 0.5
done

# ── Start web app ───────────────────────────────────────────────────────────
export PHOENIX_PORT MANAGER_PORT
echo "[entrypoint] starting web app on :${MANAGER_PORT} ..."
python /app/app.py &
APP_PID=$!
echo "[entrypoint] web app started (pid=${APP_PID})"

# Wait for web app health (up to 10s)
for _i in $(seq 1 20); do
    if python3 -c "
import urllib.request, sys
try:
    urllib.request.urlopen('http://127.0.0.1:${MANAGER_PORT}/api/health', timeout=1)
    sys.exit(0)
except Exception:
    sys.exit(1)
" 2>/dev/null; then
        echo "[entrypoint] web app ready"
        break
    fi
    sleep 0.5
done

# ── Start nginx (foreground — keeps container alive) ────────────────────────
echo ""
echo "  Web UI   : http://<host>:8080/app/"
echo "  Phoenix  : http://<host>:8080/"
echo "  Health   : http://<host>:8080/app/api/health"
echo ""
echo "[entrypoint] starting nginx on :8080 ..."
exec "${NGINX_BIN}" -c "${NGINX_RUNTIME_DIR}/nginx.conf" -g "daemon off;"
