# CAI Benchmark Evaluation Platform
#
# Architecture (only port 8080 is externally reachable):
#
#   External HTTPS → :8080 (nginx)
#     /phoenix/  →  127.0.0.1:6006  — Arize Phoenix UI + API
#     /          →  127.0.0.1:9000  — web app (evaluation manager)
#
# Build:
#   docker build -f docker/Dockerfile -t cai-bench .
#
# Run:
#   docker run -p 8080:8080 -v cai-bench-data:/data cai-bench
#
# Environment variables:
#   DATA_DIR          /data     Volume mount for Spider DB cache
#   MANAGER_PORT      9000      Internal web app port
#   PHOENIX_PORT      6006      Internal Phoenix port

FROM python:3.11-slim

# ── System dependencies ────────────────────────────────────────────────────────
RUN apt-get update -qq && \
    apt-get install -y -qq --no-install-recommends \
        nginx curl sqlite3 && \
    rm -rf /var/lib/apt/lists/*

# ── Python dependencies ────────────────────────────────────────────────────────
RUN pip install --no-cache-dir \
    "arize-phoenix>=4.0" \
    "opentelemetry-sdk>=1.20" \
    "opentelemetry-exporter-otlp-proto-http>=1.20" \
    "openai>=1.0" \
    "datasets>=2.14"

# ── Application code ───────────────────────────────────────────────────────────
COPY docker/web_app/  /app/
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# ── Bundle Spider validation split (200 KB JSON, not the 300 MB databases) ────
COPY docker/datasets/ /app/datasets/
RUN python -c "\
import json, sys, pathlib; \
out = pathlib.Path('/app/datasets/spider/validation.json'); \
out.parent.mkdir(parents=True, exist_ok=True); \
print('Downloading Spider validation split from HuggingFace...', flush=True); \
from datasets import load_dataset; \
ds = load_dataset('xlangai/spider', split='validation'); \
records = [{'question': r['question'], 'query': r['query'], 'db_id': r['db_id']} for r in ds]; \
out.write_text(json.dumps(records, indent=2)); \
print(f'Saved {len(records)} examples to {out}', flush=True) \
"

# CAI routes external port 443 → container port 8080
EXPOSE 8080

ENTRYPOINT ["/entrypoint.sh"]
