#!/usr/bin/env python3
"""
Run Locust benchmarks against ray-serve-cai endpoints in CAI.

This script runs one or more Locust load test profiles (chat, yolo, mixed)
in headless mode and saves results to timestamped directories.

Environment Variables:
    BASE_URL:       Ray Serve cluster URL (required)
    VLLM_ROUTE:     vLLM engine route (default: /qwen-2b)
    VLLM_MODEL:     vLLM model path (default: /home/cdsw/models/Qwen3.5-2B)
    YOLO_ROUTE:     YOLO engine route (default: /yolo)
    VERIFY_SSL:     SSL verification (default: false)
    DATASET_DIR:    Path to image dataset directory for YOLO tests (default: datasets/sample_images)
    BENCHMARK_PROFILE: Comma-separated profiles: chat,yolo,mixed (default: chat)
    LOCUST_USERS:   Number of concurrent users (default: 50)
    LOCUST_RATE:    User spawn rate per second (default: 10)
    LOCUST_DURATION: Test duration (default: 60s)
"""

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def run_locust(
    locustfile: str,
    profile_name: str,
    results_dir: Path,
    users: int,
    rate: int,
    duration: str,
) -> bool:
    """Run a single Locust profile in headless mode.

    Args:
        locustfile: Path to locustfile
        profile_name: Name for result files
        results_dir: Directory to save CSV results
        users: Number of concurrent users
        rate: User spawn rate
        duration: Test duration (e.g., '60s')

    Returns:
        True if benchmark completed successfully
    """
    print(f"\n{'=' * 60}")
    print(f"  Locust Benchmark: {profile_name}")
    print(f"  Users: {users}, Rate: {rate}/s, Duration: {duration}")
    print(f"{'=' * 60}")

    csv_prefix = results_dir / f"locust_{profile_name}"
    log_file = results_dir / f"locust_{profile_name}.log"

    cmd = [
        sys.executable, "-m", "locust",
        "-f", locustfile,
        "--headless",
        "-u", str(users),
        "-r", str(rate),
        "-t", duration,
        "--csv", str(csv_prefix),
        "--only-summary",
    ]

    print(f"  Command: {' '.join(cmd)}")
    print()

    with open(log_file, "w") as lf:
        result = subprocess.run(
            cmd,
            cwd="/home/cdsw",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        lf.write(result.stdout)
        print(result.stdout)

    if result.returncode != 0:
        print(f"  Locust exited with code {result.returncode}")
        return False

    print(f"  Results saved to: {csv_prefix}_stats.csv")
    return True


def health_check(base_url: str, routes: list[str]) -> bool:
    """Verify endpoints are reachable before benchmarking."""
    import urllib.request
    import ssl

    verify_ssl = os.environ.get("VERIFY_SSL", "false").lower() not in ("false", "0", "no")
    ctx = None if verify_ssl else ssl.create_default_context()
    if not verify_ssl and ctx:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    print("Running health checks...")
    all_ok = True
    for route in routes:
        url = f"{base_url}{route}"
        try:
            req = urllib.request.Request(url, method="GET")
            urllib.request.urlopen(req, timeout=10, context=ctx)
            print(f"  {route} -> OK")
        except Exception as e:
            print(f"  {route} -> FAIL ({e})")
            all_ok = False

    return all_ok


def main():
    """Run benchmark suite."""
    project_root = Path("/home/cdsw")

    # Read configuration from environment
    base_url = os.environ.get("BASE_URL")
    if not base_url:
        print("Error: BASE_URL environment variable is required")
        sys.exit(1)

    vllm_route = os.environ.get("VLLM_ROUTE", "/qwen-2b")
    yolo_route = os.environ.get("YOLO_ROUTE", "/yolo")
    dataset_dir = os.environ.get("DATASET_DIR", "")
    profiles = os.environ.get("BENCHMARK_PROFILE", "chat").split(",")
    users = int(os.environ.get("LOCUST_USERS", "50"))
    rate = int(os.environ.get("LOCUST_RATE", "10"))
    duration = os.environ.get("LOCUST_DURATION", "60s")

    # Create timestamped results directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_dir = project_root / "results" / f"run_{timestamp}"
    results_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("  ray-serve-cai Benchmark Suite")
    print(f"  Base URL:    {base_url}")
    print(f"  Profiles:    {', '.join(profiles)}")
    print(f"  Dataset Dir: {dataset_dir or '(default: datasets/sample_images)'}")
    print(f"  Users:       {users}")
    print(f"  Rate:        {rate}/s")
    print(f"  Duration:    {duration}")
    print(f"  Results:     {results_dir}")
    print("=" * 60)

    # Propagate DATASET_DIR to locust subprocesses
    if dataset_dir:
        os.environ["DATASET_DIR"] = dataset_dir

    # Health checks
    health_routes = [f"{vllm_route}/health", f"{yolo_route}/health"]
    health_check(base_url, health_routes)

    # Profile -> locustfile mapping
    locust_dir = project_root / "locust"
    profile_map = {
        "chat": locust_dir / "locustfile_chat.py",
        "yolo": locust_dir / "locustfile_yolo.py",
        "mixed": locust_dir / "locustfile_mixed.py",
    }

    success = True
    for profile in profiles:
        profile = profile.strip()
        locustfile = profile_map.get(profile)
        if not locustfile:
            print(f"  Unknown profile: {profile} (available: {', '.join(profile_map)})")
            continue
        if not locustfile.exists():
            print(f"  Locustfile not found: {locustfile}")
            continue

        if not run_locust(str(locustfile), profile, results_dir, users, rate, duration):
            success = False

    # Summary
    print(f"\n{'=' * 60}")
    if success:
        print("  Benchmark Suite Complete")
    else:
        print("  Benchmark Suite Complete (some profiles had errors)")
    print(f"  Results saved to: {results_dir}")
    print("=" * 60)

    # List result files
    for f in sorted(results_dir.iterdir()):
        size_kb = f.stat().st_size / 1024
        print(f"  {f.name} ({size_kb:.1f} KB)")

    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
