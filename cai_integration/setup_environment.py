#!/usr/bin/env python3
"""
Setup Python environment for ray-serve-cai-bench in CAI.

This script is the Python entry point for the CAI job that:
1. Wraps the bash script setup_environment.sh
2. Handles exit codes and error reporting

The actual setup logic is in setup_environment.sh which:
1. Checks if venv exists (reuses if yes, creates if no)
2. Installs uv (ultra-fast Python package installer)
3. Installs locust, httpx, and other benchmark dependencies
4. Verifies installation
"""

import subprocess
import sys
from pathlib import Path


def main():
    """Execute environment setup via bash script."""
    project_root = Path("/home/cdsw")
    bash_script = project_root / "cai_integration" / "setup_environment.sh"

    # Ensure script is executable
    bash_script.chmod(0o755)

    print(f"Executing setup script: {bash_script}")
    result = subprocess.run(
        ["bash", str(bash_script)],
        cwd=str(project_root),
    )

    if result.returncode != 0:
        raise RuntimeError(f"Setup script failed with exit code {result.returncode}")

    print("Setup completed successfully")


if __name__ == "__main__":
    main()
