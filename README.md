# ray-serve-cai-bench

Stress testing suite for [ray-serve-cai](../ray-serve-cai/) endpoints.

## Tools

| Tool | Purpose | Use when |
|------|---------|----------|
| **Locust** | Interactive load testing with web UI, ramping users | Exploring concurrency limits, finding breaking points |
| **Vegeta** | Constant-rate HTTP attacks, precise percentile reporting | Measuring latency at fixed QPS, SLA validation |
| **vLLM benchmarks** | Upstream vLLM's own serving benchmark | Apples-to-apples comparison with published numbers |

## Quick Start

```bash
# Install
cd ray-serve-cai-bench
pip install -e .

# Configure
cp configs/cluster.env configs/cluster.env.local
# Edit configs/cluster.env with your cluster URL

# Generate test datasets
python scripts/generate_prompts.py

# Run individual benchmarks
locust -f locust/locustfile_chat.py                           # web UI at :8089
locust -f locust/locustfile_chat.py --headless -u 10 -t 30s  # headless
bash vegeta/run_chat.sh 10 30s                                # 10 rps for 30s

# Run full suite
bash scripts/run_all.sh

# Generate charts from results
python scripts/plot_results.py results/run_<timestamp>/
```

## Benchmarks

### Locust

| File | Target | Description |
|------|--------|-------------|
| `locustfile_chat.py` | vLLM `/v1/chat/completions` | 60% non-stream, 30% stream (with TTFT), 10% long prompt |
| `locustfile_yolo.py` | YOLO `/v1/detect` | File upload detection with batch concurrency |
| `locustfile_mixed.py` | All engines | 50% chat + 30% YOLO + 15% health + 5% metrics |

### Vegeta

| Script | Target | Default |
|--------|--------|---------|
| `run_chat.sh` | Chat completions | 10 rps, 30s |
| `run_health.sh` | Health endpoints | 50 rps, 15s |

### vLLM Benchmarks

```bash
# Requires: pip install 'ray-serve-cai-bench[vllm]'
python vllm_bench/bench_serving.py --num-prompts 100 --request-rate 10
python vllm_bench/bench_serving.py --dataset-name sharegpt --request-rate 20
```

## Configuration

Edit `configs/cluster.env`:

```bash
BASE_URL=https://ray-cluster-head.ml-XXXX.example.cloudera.site
VLLM_ROUTE=/qwen-2b
YOLO_ROUTE=/yolo
VLLM_MODEL=/home/cdsw/models/Qwen3.5-2B
VERIFY_SSL=false
```

## Test Datasets

Pre-generated via `python scripts/generate_prompts.py`:

| File | Count | Description |
|------|-------|-------------|
| `prompts_short.jsonl` | 50 | 50-100 token QA/coding prompts |
| `prompts_long.jsonl` | 20 | 2K-4K token detailed technical prompts |
| `prompts_multi_turn.jsonl` | 15 | Multi-turn conversations |

Place test images in `datasets/sample_images/` for YOLO benchmarks.

## Results

`scripts/run_all.sh` saves everything to `results/run_<timestamp>/`:
- Locust CSV stats + logs
- Vegeta binary + JSON reports
- vLLM benchmark output

Generate charts: `python scripts/plot_results.py results/run_<timestamp>/`
