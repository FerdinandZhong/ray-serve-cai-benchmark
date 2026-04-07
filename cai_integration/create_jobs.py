#!/usr/bin/env python3
"""
Create/update CML jobs from configuration.

This script:
1. Loads jobs_config.yaml
2. Creates or updates all jobs (setup_environment, benchmarks)
3. Sets up parent job dependencies
4. Returns job IDs for next step

Usage:
    export CML_HOST=... CML_API_KEY=... CML_PROJECT_ID=...
    python3 cai_integration/create_jobs.py --project-id $CML_PROJECT_ID
    python3 cai_integration/create_jobs.py --project-id $CML_PROJECT_ID --config path/to/config.yaml
"""

import argparse
import json
import os
import sys
import yaml
import requests
from pathlib import Path
from typing import Dict, Optional, Any


class JobManager:
    """Handle CML job creation and updates."""

    def __init__(self):
        """Initialize CML REST API client."""
        self.cml_host = os.environ.get("CML_HOST")
        self.api_key = os.environ.get("CML_API_KEY")

        if not all([self.cml_host, self.api_key]):
            print("Error: Missing required environment variables")
            print("   Required: CML_HOST, CML_API_KEY")
            sys.exit(1)

        if not self.cml_host.startswith(("http://", "https://")):
            self.cml_host = f"https://{self.cml_host}"

        self.api_url = f"{self.cml_host.rstrip('/')}/api/v2"
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {self.api_key.strip()}",
        }

    def make_request(
        self, method: str, endpoint: str, data: dict = None, params: dict = None
    ) -> Optional[dict]:
        """Make an API request to CML."""
        url = f"{self.api_url}/{endpoint.lstrip('/')}"

        try:
            response = requests.request(
                method=method,
                url=url,
                headers=self.headers,
                json=data,
                params=params,
                timeout=30,
            )

            if 200 <= response.status_code < 300:
                if response.text:
                    try:
                        return response.json()
                    except json.JSONDecodeError:
                        return {}
                return {}
            else:
                print(f"API Error ({response.status_code}): {response.text[:200]}")
                return None

        except Exception as e:
            print(f"Request error: {e}")
            return None

    def load_jobs_config(self, config_path: str = None) -> Dict[str, Any]:
        """Load jobs configuration from YAML."""
        if config_path is None:
            config_path = Path(__file__).parent / "jobs_config.yaml"
        else:
            config_path = Path(config_path)

        try:
            with open(config_path) as f:
                config = yaml.safe_load(f)
            print(f"Loaded jobs config from {config_path}")
            return config
        except Exception as e:
            print(f"Failed to load jobs config: {e}")
            return {}

    def list_jobs(self, project_id: str) -> Dict[str, str]:
        """List all jobs in a project."""
        print("Listing existing jobs...")
        result = self.make_request("GET", f"projects/{project_id}/jobs")

        if result:
            jobs = {}
            for job in result.get("jobs", []):
                jobs[job.get("name", "")] = job.get("id", "")
            print(f"   Found {len(jobs)} existing jobs")
            return jobs
        print("   No existing jobs found")
        return {}

    def create_job(
        self,
        project_id: str,
        job_config: Dict[str, Any],
        parent_job_id: Optional[str] = None,
    ) -> Optional[str]:
        """Create a new job in the CML project."""
        job_name = job_config["name"]
        script_path = job_config["script"]
        print(f"   Creating job: {job_name}")

        job_data = {
            "name": job_name,
            "script": script_path,
            "cpu": job_config.get("cpu", 4),
            "memory": job_config.get("memory", 8),
            "timeout": job_config.get("timeout", 600),
        }

        if "gpu" in job_config and job_config["gpu"] > 0:
            job_data["nvidia_gpu"] = job_config["gpu"]

        if parent_job_id:
            job_data["parent_job_id"] = parent_job_id

        if "runtime_identifier" in job_config:
            job_data["runtime_identifier"] = job_config["runtime_identifier"]

        if "environment" in job_config:
            job_data["environment"] = job_config["environment"]

        result = self.make_request("POST", f"projects/{project_id}/jobs", data=job_data)

        if result:
            job_id = result.get("id")
            print(f"   Job created: {job_name} ({job_id})")
            return job_id
        else:
            print(f"   Failed to create job: {job_name}")
            return None

    def create_jobs_from_config(
        self,
        project_id: str,
        config_path: str = None,
        job_env_injections: Dict[str, Dict[str, str]] = None,
    ) -> Dict[str, str]:
        """Create all jobs from configuration."""
        print("\n" + "=" * 70)
        print("Creating CML Jobs")
        print("=" * 70)

        config = self.load_jobs_config(config_path)
        if not config or "jobs" not in config:
            print("Invalid or empty jobs configuration")
            return {}

        # Apply runner-environment injections
        if job_env_injections:
            for job_key, env_vars in job_env_injections.items():
                if job_key not in config["jobs"]:
                    print(f"  --job-env target '{job_key}' not found in config -- skipping")
                    continue
                config["jobs"][job_key].setdefault("environment", {}).update(env_vars)

        existing_jobs = self.list_jobs(project_id)
        job_ids = {}
        jobs_config = config["jobs"]
        processed = set()

        def create_job_with_deps(job_key: str):
            """Recursively create job and its dependencies."""
            if job_key in processed:
                return

            job_config = jobs_config[job_key]
            parent_job_key = job_config.get("parent_job_key")
            parent_job_id = None

            if parent_job_key:
                create_job_with_deps(parent_job_key)
                parent_job_id = job_ids.get(parent_job_key)

            job_name = job_config["name"]
            if job_name in existing_jobs:
                job_id = existing_jobs[job_name]
                print(f"   Job already exists: {job_name} ({job_id})")
                job_ids[job_key] = job_id
            else:
                job_id = self.create_job(project_id, job_config, parent_job_id)
                if job_id:
                    job_ids[job_key] = job_id

            processed.add(job_key)

        for job_key in jobs_config.keys():
            create_job_with_deps(job_key)

        print(f"\nCreated/verified {len(job_ids)} jobs")
        return job_ids

    def run(
        self,
        project_id: str,
        config_path: str = None,
        job_env_injections: Dict[str, Dict[str, str]] = None,
    ) -> bool:
        """Execute job creation."""
        print("=" * 70)
        print("CML Job Creation for ray-serve-cai-bench")
        print("=" * 70)

        job_ids = self.create_jobs_from_config(
            project_id, config_path, job_env_injections=job_env_injections
        )

        if not job_ids:
            print("Failed to create jobs")
            return False

        print("\n" + "=" * 70)
        print("Job Creation Complete!")
        print("=" * 70)
        print(f"\nCreated/verified {len(job_ids)} jobs")
        print(f"\nTo trigger jobs, run:")
        print(f"   python3 cai_integration/trigger_jobs.py --project-id {project_id}")

        return True


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Create CML jobs from configuration")
    parser.add_argument("--project-id", required=True, help="CML project ID")
    parser.add_argument("--config", help="Path to jobs configuration YAML")
    parser.add_argument(
        "--job-env",
        action="append",
        metavar="JOB_KEY:VAR_NAME",
        help=(
            "Inject an environment variable from the runner into a specific job. "
            "Format: JOB_KEY:VAR_NAME  (reads VAR_NAME from the current environment). "
            "Can be specified multiple times."
        ),
    )

    args, _ = parser.parse_known_args()

    job_env_injections: Dict[str, Dict[str, str]] = {}
    for spec in args.job_env or []:
        if ":" not in spec:
            print(f"Invalid --job-env format (expected JOB_KEY:VAR_NAME): {spec}")
            sys.exit(1)
        job_key, var_name = spec.split(":", 1)
        value = os.environ.get(var_name)
        if not value:
            print(f"  --job-env {spec}: {var_name} is not set in the runner environment -- skipping")
            continue
        job_env_injections.setdefault(job_key, {})[var_name] = value
        print(f"Will inject {var_name} into job '{job_key}' from runner environment")

    try:
        manager = JobManager()
        success = manager.run(args.project_id, args.config, job_env_injections=job_env_injections)
        if not success:
            sys.exit(1)
    except KeyboardInterrupt:
        print("\nJob creation cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
