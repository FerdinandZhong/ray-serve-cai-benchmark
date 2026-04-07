#!/bin/bash
# Constant-rate health check attack — useful for measuring baseline overhead.
# Usage: ./run_health.sh [rate] [duration]

set -euo pipefail
cd "$(dirname "$0")/.."

set -a; source configs/cluster.env; set +a

RATE=${1:-50}
DURATION=${2:-15s}
OUT="results/vegeta_health_$(date +%Y%m%d_%H%M%S)"

echo "=== Vegeta Health Check Benchmark ==="
echo "  Rate:     ${RATE} rps"
echo "  Duration: ${DURATION}"
echo ""

envsubst < vegeta/targets/health_checks.txt > /tmp/vegeta_health_targets.txt

vegeta attack \
  -targets /tmp/vegeta_health_targets.txt \
  -rate "${RATE}" \
  -duration "${DURATION}" \
  -timeout 10s \
  -insecure \
  | tee "${OUT}.bin" \
  | vegeta report -type=text

echo ""
vegeta report -type='hist[0,5ms,10ms,50ms,100ms,500ms]' < "${OUT}.bin"
