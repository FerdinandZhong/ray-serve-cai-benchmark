#!/bin/bash
# Full benchmark suite — runs all tests sequentially and collects results.
# Usage: bash scripts/run_all.sh

set -euo pipefail
cd "$(dirname "$0")/.."

set -a; source configs/cluster.env; set +a

RESULTS="results/run_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$RESULTS"

echo "============================================================"
echo "  ray-serve-cai Benchmark Suite"
echo "  $(date)"
echo "  Base URL: ${BASE_URL}"
echo "  Results:  ${RESULTS}/"
echo "============================================================"
echo ""

# ── 0. Health checks ────────────────────────────────────────────────────────
echo "=== [0/5] Health Checks ==="
for route in "${VLLM_ROUTE}/health" "${YOLO_ROUTE}/health" "/api/health"; do
    url="${BASE_URL}${route}"
    status=$(curl -sk -o /dev/null -w "%{http_code}" "$url" 2>/dev/null || echo "FAIL")
    echo "  ${route} → ${status}"
done
echo ""

# ── 1. Locust: chat completions ─────────────────────────────────────────────
echo "=== [1/5] Locust — Chat Completions (100 users, 60s) ==="
locust -f locust/locustfile_chat.py \
    --headless -u 100 -r 10 -t 60s \
    --csv "${RESULTS}/locust_chat" \
    --only-summary 2>&1 | tee "${RESULTS}/locust_chat.log"
echo ""

# ── 2. Locust: YOLO detection ───────────────────────────────────────────────
echo "=== [2/5] Locust — YOLO Detection (50 users, 60s) ==="
locust -f locust/locustfile_yolo.py \
    --headless -u 50 -r 10 -t 60s \
    --csv "${RESULTS}/locust_yolo" \
    --only-summary 2>&1 | tee "${RESULTS}/locust_yolo.log"
echo ""

# ── 3. Locust: mixed workload ───────────────────────────────────────────────
echo "=== [3/5] Locust — Mixed Workload (80 users, 90s) ==="
locust -f locust/locustfile_mixed.py \
    --headless -u 80 -r 10 -t 90s \
    --csv "${RESULTS}/locust_mixed" \
    --only-summary 2>&1 | tee "${RESULTS}/locust_mixed.log"
echo ""

# ── 4. Vegeta: constant-rate chat ───────────────────────────────────────────
echo "=== [4/5] Vegeta — Chat @ 10 rps for 30s ==="
if command -v vegeta &>/dev/null; then
    envsubst < vegeta/targets/chat_completions.txt > /tmp/vegeta_chat_targets.txt
    vegeta attack \
        -targets /tmp/vegeta_chat_targets.txt \
        -body vegeta/bodies/chat_body.json \
        -rate 10 -duration 30s -timeout 60s -insecure \
        | tee "${RESULTS}/vegeta_chat.bin" \
        | vegeta report -type=text
    vegeta report -type=json < "${RESULTS}/vegeta_chat.bin" > "${RESULTS}/vegeta_chat.json"
else
    echo "  [SKIP] vegeta not installed (brew install vegeta)"
fi
echo ""

# ── 5. vLLM benchmark (if available) ────────────────────────────────────────
echo "=== [5/5] vLLM Serving Benchmark (50 prompts, 5 rps) ==="
if python -c "import vllm" 2>/dev/null; then
    python vllm_bench/bench_serving.py \
        --num-prompts 50 --request-rate 5 \
        2>&1 | tee "${RESULTS}/vllm_bench.log"
else
    echo "  [SKIP] vllm not installed (pip install 'ray-serve-cai-bench[vllm]')"
fi
echo ""

# ── Summary ──────────────────────────────────────────────────────────────────
echo "============================================================"
echo "  Benchmark Complete"
echo "  Results saved to: ${RESULTS}/"
echo "============================================================"
ls -la "$RESULTS"/
