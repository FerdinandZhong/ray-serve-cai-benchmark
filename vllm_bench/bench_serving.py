#!/usr/bin/env python3
"""
Wrapper around vLLM's online serving benchmark.

Calls ``python -m vllm.benchmarks.serve`` pointed at the Ray Serve cluster
so results are directly comparable with upstream vLLM numbers.

Usage:
    python vllm_bench/bench_serving.py
    python vllm_bench/bench_serving.py --num-prompts 200 --request-rate 20
    python vllm_bench/bench_serving.py --dataset-name sharegpt

Requires: pip install 'ray-serve-cai-bench[vllm]'
"""

import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

_env_path = Path(__file__).resolve().parent.parent / "configs" / "cluster.env"
load_dotenv(_env_path)

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")
VLLM_ROUTE = os.environ.get("VLLM_ROUTE", "/qwen-2b")
VLLM_MODEL = os.environ.get("VLLM_MODEL", "/home/cdsw/models/Qwen3.5-2B")


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Run vLLM's online serving benchmark against the Ray Serve cluster."
    )
    parser.add_argument("--num-prompts", type=int, default=100)
    parser.add_argument("--request-rate", type=float, default=10.0)
    parser.add_argument("--dataset-name", type=str, default="sharegpt",
                        help="sharegpt, sonnet, or random")
    parser.add_argument("--backend", type=str, default="openai-chat",
                        choices=["openai-chat", "openai-completions"])
    parser.add_argument("--max-concurrency", type=int, default=None,
                        help="Max concurrent requests (default: unlimited)")
    args, extra = parser.parse_known_args()

    endpoint = f"{BASE_URL}{VLLM_ROUTE}"

    cmd = [
        sys.executable, "-m", "vllm.benchmarks.serve",
        "--backend", args.backend,
        "--base-url", endpoint,
        "--model", VLLM_MODEL,
        "--dataset-name", args.dataset_name,
        "--num-prompts", str(args.num_prompts),
        "--request-rate", str(args.request_rate),
    ]

    if args.max_concurrency is not None:
        cmd += ["--max-concurrency", str(args.max_concurrency)]

    # Pass through any extra args directly to vLLM benchmark
    cmd += extra

    print("=" * 60)
    print("vLLM Online Serving Benchmark")
    print("=" * 60)
    print(f"  Endpoint:     {endpoint}")
    print(f"  Model:        {VLLM_MODEL}")
    print(f"  Backend:      {args.backend}")
    print(f"  Prompts:      {args.num_prompts}")
    print(f"  Request rate: {args.request_rate} rps")
    print(f"  Dataset:      {args.dataset_name}")
    print()
    print(f"  Command: {' '.join(cmd)}")
    print()

    result = subprocess.run(cmd)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
