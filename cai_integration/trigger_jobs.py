#!/usr/bin/env python3
"""
Trigger and monitor CAI job execution.

This script:
1. Looks up jobs by name from jobs_config.yaml
2. Triggers only the root job (jobs with parent_job_key are auto-triggered by CAI)
3. Monitors root job execution and reports status
4. Child jobs with dependencies auto-trigger when parent succeeds

Usage:
    export CML_HOST=... CML_API_KEY=... CML_PROJECT_ID=...
    python3 cai_integration/trigger_jobs.py --project-id $CML_PROJECT_ID
    python3 cai_integration/trigger_jobs.py --project-id $CML_PROJECT_ID --job benchmark_chat
"""

import argparse
import json
import os
import sys
import time
import yaml
import requests
from pathlib import Path
from typing import Dict, Optional


class JobRunner:
    """Handle CML job execution and monitoring."""

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

    def load_jobs_config(self, config_path: str = None) -> Dict:
        """Load jobs configuration."""
        if config_path is None:
            config_path = Path(__file__).parent / "jobs_config.yaml"
        else:
            config_path = Path(config_path)

        with open(config_path) as f:
            return yaml.safe_load(f)

    def list_jobs(self, project_id: str) -> Dict[str, str]:
        """List all jobs in a project and return name -> ID mapping."""
        result = self.make_request("GET", f"projects/{project_id}/jobs")

        if result:
            jobs = {}
            for job in result.get("jobs", []):
                job_name = job.get("name", "")
                job_id = job.get("id", "")
                if job_name and job_id:
                    jobs[job_name] = job_id
            return jobs
        return {}

    def get_job_id_by_name(self, project_id: str, job_name: str) -> Optional[str]:
        """Get job ID by job name."""
        jobs = self.list_jobs(project_id)
        return jobs.get(job_name)

    def trigger_job(self, project_id: str, job_id: str, env_overrides: Dict = None) -> Optional[str]:
        """Trigger a job run."""
        data = {}
        if env_overrides:
            data["environment"] = env_overrides

        result = self.make_request("POST", f"projects/{project_id}/jobs/{job_id}/runs", data=data)

        if result:
            return result.get("id")
        return None

    def get_job_run_status(self, project_id: str, job_id: str, run_id: str) -> Optional[Dict]:
        """Get job run status."""
        return self.make_request("GET", f"projects/{project_id}/jobs/{job_id}/runs/{run_id}")

    def wait_for_job_completion(
        self, project_id: str, job_id: str, run_id: str, job_name: str, timeout: int = 3600
    ) -> bool:
        """Wait for job to complete."""
        print(f"Waiting for job '{job_name}' to complete...")

        start_time = time.time()
        last_status = None

        while time.time() - start_time < timeout:
            result = self.get_job_run_status(project_id, job_id, run_id)

            if result:
                status = result.get("status", "unknown")

                if status != last_status:
                    elapsed = int(time.time() - start_time)
                    print(f"   [{elapsed}s] Status: {status}")
                    last_status = status

                if status == "succeeded":
                    print("Job completed successfully")
                    return True
                elif status in ["failed", "stopped", "killed"]:
                    print(f"Job failed with status: {status}")
                    return False

            time.sleep(10)

        print(f"Timeout waiting for job completion ({timeout}s)")
        return False

    def get_root_job(self, config: Dict) -> Optional[str]:
        """Find root job (job with no parent)."""
        for job_key, job_config in config.get("jobs", {}).items():
            if job_config.get("parent_job_key") is None:
                return job_key
        return None

    def run(
        self,
        project_id: str,
        config_path: str = None,
        job_name: Optional[str] = None,
        env_overrides: Dict = None,
    ) -> bool:
        """Execute job pipeline by triggering root job or specific job."""
        print("=" * 70)
        print("ray-serve-cai-bench Job Execution")
        print("=" * 70)

        config = self.load_jobs_config(config_path)

        if job_name:
            target_job_name = job_name
            target_job_key = None
            for job_key, job_config in config.get("jobs", {}).items():
                if job_config.get("name") == job_name or job_key == job_name:
                    target_job_key = job_key
                    target_job_name = job_config.get("name", job_key)
                    break

            if not target_job_key:
                print(f"Job not found in config: {job_name}")
                return False
        else:
            target_job_key = self.get_root_job(config)
            if not target_job_key:
                print("Root job not found in configuration")
                return False
            target_job_name = config.get("jobs", {}).get(target_job_key, {}).get("name", target_job_key)

        target_job_config = config.get("jobs", {}).get(target_job_key, {})

        print(f"\nLooking up job: {target_job_name}")
        target_job_id = self.get_job_id_by_name(project_id, target_job_name)

        if not target_job_id:
            print(f"Job not found in project: {target_job_name}")
            print("   Make sure jobs are created first (run create_jobs.py)")
            return False

        print(f"   Found job ID: {target_job_id}")

        # Display job dependency chain
        print(f"\nJob dependency chain:")
        for job_key, job_config in config.get("jobs", {}).items():
            parent_key = job_config.get("parent_job_key")
            job_name_display = job_config.get("name", job_key)
            if parent_key:
                parent_name = config.get("jobs", {}).get(parent_key, {}).get("name", parent_key)
                print(f"   {parent_name} -> {job_name_display}")
            else:
                print(f"   {job_name_display} (root)")

        print(f"\nTriggering job: {target_job_name}")
        if not job_name:
            print("   (Child jobs will auto-trigger via CAI dependencies)\n")
        else:
            print()

        run_id = self.trigger_job(project_id, target_job_id, env_overrides)

        if not run_id:
            print("   Failed to trigger job\n")
            return False

        print(f"   Job triggered: {run_id}\n")

        timeout = target_job_config.get("timeout", 3600)
        if not self.wait_for_job_completion(
            project_id, target_job_id, run_id, target_job_name, timeout + 60
        ):
            print(f"Job failed: {target_job_name}")
            return False

        print("=" * 70)
        print("Job Completed Successfully!")
        print("=" * 70)

        if not job_name:
            print("\nNote: Child jobs with dependencies will auto-trigger in CAI.")
            print("   Monitor them in the CAI UI: Jobs > Job Runs\n")

        return True


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Trigger and monitor CML jobs")
    parser.add_argument("--project-id", required=True, help="CML project ID")
    parser.add_argument("--jobs-config", help="Path to jobs configuration YAML")
    parser.add_argument("--job", help="Specific job name to trigger (default: root job)")
    parser.add_argument(
        "--env",
        action="append",
        help="Environment variable override (format: KEY=VALUE, can be specified multiple times)",
    )

    args, _ = parser.parse_known_args()

    env_overrides = {}
    if args.env:
        for env_pair in args.env:
            if "=" in env_pair:
                key, value = env_pair.split("=", 1)
                env_overrides[key] = value

    try:
        runner = JobRunner()
        success = runner.run(args.project_id, args.jobs_config, args.job, env_overrides)
        if not success:
            sys.exit(1)
    except KeyboardInterrupt:
        print("\nJob execution cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
