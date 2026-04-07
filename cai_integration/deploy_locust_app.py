#!/usr/bin/env python3
"""
Deploy Locust as a CAI Application with web UI.

This script launches Locust in web UI mode, binding to the CAI application
port so the UI is accessible through CAI's reverse proxy.

CAI injects CDSW_APP_PORT to tell the application which port to listen on.

Environment Variables:
    CDSW_APP_PORT:      Port assigned by CAI for the application (injected by CAI)
    INFERENCE_URL:      Full base URL of the inference service (required).
                        This is set as BASE_URL for locust so HttpUser.host resolves correctly.
    VLLM_ROUTE:         vLLM route prefix (default: /qwen-2b)
    VLLM_MODEL:         vLLM model path (default: /home/cdsw/models/Qwen3.5-2B)
    YOLO_ROUTE:         YOLO route prefix (default: /yolo)
    VERIFY_SSL:         SSL verification (default: false)
    DATASET_DIR:        Path to image dataset directory for YOLO tests
    LOCUST_FILE:        Locustfile to use (default: locust/locustfile_mixed.py)
    LOCUST_USERS:       Default number of users in UI (default: 10)
    LOCUST_RATE:        Default spawn rate in UI (default: 5)
"""

import os
import subprocess
import sys
from pathlib import Path


def main():
    """Launch Locust web UI as a CAI Application."""
    project_root = Path("/home/cdsw")

    # CAI injects this for applications
    app_port = os.environ.get("CDSW_APP_PORT", "8089")

    # INFERENCE_URL is the primary parameter — maps to BASE_URL for locust
    inference_url = os.environ.get("INFERENCE_URL", "")
    if not inference_url:
        # Fall back to BASE_URL if INFERENCE_URL not set
        inference_url = os.environ.get("BASE_URL", "")
    if not inference_url:
        print("Error: INFERENCE_URL (or BASE_URL) environment variable is required")
        print("   Set the full base URL of the inference service to test against.")
        sys.exit(1)

    # Propagate INFERENCE_URL as BASE_URL so locust/common.py picks it up
    os.environ["BASE_URL"] = inference_url

    locustfile = os.environ.get("LOCUST_FILE", "locust/locustfile_mixed.py")
    dataset_dir = os.environ.get("DATASET_DIR", "")

    locustfile_path = project_root / locustfile
    if not locustfile_path.exists():
        print(f"Error: Locustfile not found: {locustfile_path}")
        sys.exit(1)

    # Propagate DATASET_DIR for locust/common.py
    if dataset_dir:
        os.environ["DATASET_DIR"] = dataset_dir

    print("=" * 60)
    print("  Locust Web UI - CAI Application")
    print(f"  Port:           {app_port}")
    print(f"  Inference URL:  {inference_url}")
    print(f"  Locustfile:     {locustfile}")
    print(f"  Dataset Dir:    {dataset_dir or '(default)'}")
    print(f"  VLLM_ROUTE:     {os.environ.get('VLLM_ROUTE', '/qwen-2b')}")
    print(f"  YOLO_ROUTE:     {os.environ.get('YOLO_ROUTE', '/yolo')}")
    print("=" * 60)
    print()
    print("Locust web UI will be available at the CAI Application URL")
    print()

    cmd = [
        sys.executable, "-m", "locust",
        "-f", str(locustfile_path),
        "--web-host", "127.0.0.1",
        "--web-port", app_port,
    ]

    print(f"Command: {' '.join(cmd)}")
    print()

    # Run locust in foreground — CAI keeps the application alive
    result = subprocess.run(cmd, cwd=str(project_root))

    if result.returncode != 0:
        print(f"Locust exited with code {result.returncode}")
        sys.exit(result.returncode)


if __name__ == "__main__":
    main()
