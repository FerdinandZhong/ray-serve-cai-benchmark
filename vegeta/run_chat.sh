#!/bin/bash
# Constant-rate chat completion attack with Vegeta.
# Usage: ./run_chat.sh [rate] [duration]
#   rate:     requests per second (default: 10)
#   duration: attack duration (default: 30s)

set -euo pipefail
cd "$(dirname "$0")/.."

# Load config
set -a; source configs/cluster.env; set +a

RATE=${1:-10}
DURATION=${2:-30s}
OUT="results/vegeta_chat_$(date +%Y%m%d_%H%M%S)"

echo "=== Vegeta Chat Completions Benchmark ==="
echo "  Target:   ${BASE_URL}${VLLM_ROUTE}/v1/chat/completions"
echo "  Rate:     ${RATE} rps"
echo "  Duration: ${DURATION}"
echo ""

# Expand env vars in target file
envsubst < vegeta/targets/chat_completions.txt > /tmp/vegeta_chat_targets.txt

vegeta attack \
  -targets /tmp/vegeta_chat_targets.txt \
  -body vegeta/bodies/chat_body.json \
  -rate "${RATE}" \
  -duration "${DURATION}" \
  -timeout 60s \
  -insecure \
  | tee "${OUT}.bin" \
  | vegeta report -type=text

echo ""
echo "Detailed report:"
vegeta report -type=json < "${OUT}.bin" > "${OUT}.json"
echo "  Text:  ${OUT}.bin (use: vegeta report < ${OUT}.bin)"
echo "  JSON:  ${OUT}.json"

# Histogram
echo ""
echo "Latency histogram:"
vegeta report -type='hist[0,100ms,200ms,500ms,1s,2s,5s,10s]' < "${OUT}.bin"
