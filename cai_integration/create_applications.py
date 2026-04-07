#!/usr/bin/env python3
"""
Create/update CAI Applications for Locust load testing.

This script uses the CML Applications API (/applications) to deploy
Locust web UI instances as persistent, browser-accessible applications.

Unlike jobs, applications get a reverse-proxied URL and CDSW_APP_PORT,
making the Locust web UI accessible from outside the cluster.

Usage:
    export CML_HOST=... CML_API_KEY=...
    python3 cai_integration/create_applications.py --project-id $CML_PROJECT_ID
"""

import argparse
import json
import os
import sys
import yaml
import requests
from pathlib import Path
from typing import Dict, Optional, Any


class ApplicationManager:
    """Handle CML application creation and updates."""

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

    def load_config(self, config_path: str = None) -> Dict[str, Any]:
        """Load configuration from YAML."""
        if config_path is None:
            config_path = Path(__file__).parent / "jobs_config.yaml"
        else:
            config_path = Path(config_path)

        try:
            with open(config_path) as f:
                config = yaml.safe_load(f)
            print(f"Loaded config from {config_path}")
            return config
        except Exception as e:
            print(f"Failed to load config: {e}")
            return {}

    def list_applications(self, project_id: str) -> Dict[str, dict]:
        """List all applications in a project. Returns name -> app mapping."""
        print("Listing existing applications...")
        result = self.make_request("GET", f"projects/{project_id}/applications")

        if result:
            apps = {}
            app_list = result.get("applications", [])
            if isinstance(result, list):
                app_list = result
            for app in app_list:
                name = app.get("name", "")
                if name:
                    apps[name] = app
            print(f"   Found {len(apps)} existing applications")
            return apps
        print("   No existing applications found")
        return {}

    def create_or_update_application(
        self,
        project_id: str,
        app_config: Dict[str, Any],
        default_runtime: str = "",
    ) -> Optional[str]:
        """Create or update an application in the CML project."""
        app_name = app_config["name"]
        print(f"   Processing application: {app_name}")

        app_data = {
            "name": app_name,
            "subdomain": app_config.get("subdomain", app_name.lower().replace(" ", "-")),
            "description": app_config.get("description", ""),
            "script": app_config["script"],
            "kernel": app_config.get("kernel", "python3"),
            "cpu": app_config.get("cpu", 4),
            "memory": app_config.get("memory", 8),
            "bypass_authentication": app_config.get("bypass_authentication", False),
        }

        if "gpu" in app_config and app_config["gpu"] > 0:
            app_data["nvidia_gpu"] = app_config["gpu"]

        runtime_id = app_config.get("runtime_identifier") or default_runtime
        if runtime_id:
            app_data["runtime_identifier"] = runtime_id

        if "environment" in app_config:
            app_data["environment"] = app_config["environment"]

        # Check if application already exists
        existing_apps = self.list_applications(project_id)
        existing_app = existing_apps.get(app_name)

        if existing_app:
            app_id = existing_app.get("id")
            print(f"   Application already exists: {app_name} ({app_id})")
            print(f"   Updating...")
            result = self.make_request(
                "PATCH",
                f"projects/{project_id}/applications/{app_id}",
                data=app_data,
            )
            if result is not None:
                print(f"   Application updated: {app_name}")
                # Restart to pick up changes
                self.make_request(
                    "POST",
                    f"projects/{project_id}/applications/{app_id}/restart",
                )
                print(f"   Application restart initiated")
                return app_id
            else:
                print(f"   Failed to update application: {app_name}")
                return None
        else:
            print(f"   Creating application: {app_name}")
            result = self.make_request(
                "POST",
                f"projects/{project_id}/applications",
                data=app_data,
            )
            if result:
                app_id = result.get("id")
                print(f"   Application created: {app_name} ({app_id})")
                return app_id
            else:
                print(f"   Failed to create application: {app_name}")
                return None

    def run(self, project_id: str, config_path: str = None) -> bool:
        """Create/update all applications from configuration."""
        print("=" * 70)
        print("CML Application Setup - ray-serve-cai-bench")
        print("=" * 70)

        config = self.load_config(config_path)
        if not config:
            print("Invalid or empty configuration")
            return False

        default_runtime = config.get("runtime_identifier", "")
        applications = config.get("applications", {})

        if not applications:
            print("No applications defined in configuration")
            return True

        print(f"\nCreating/updating {len(applications)} applications...")
        app_ids = {}

        for app_key, app_config in applications.items():
            app_id = self.create_or_update_application(
                project_id, app_config, default_runtime
            )
            if app_id:
                app_ids[app_key] = app_id

        print(f"\n{'=' * 70}")
        print(f"Application Setup Complete!")
        print(f"{'=' * 70}")
        print(f"\nCreated/updated {len(app_ids)} applications")

        for app_key, app_id in app_ids.items():
            app_name = applications[app_key].get("name", app_key)
            subdomain = applications[app_key].get("subdomain", app_key)
            print(f"   {app_name}: {self.cml_host}/applications/{subdomain}")

        print(f"\nSet INFERENCE_URL in each application's environment via the CAI UI.")

        return len(app_ids) > 0


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Create CML applications from configuration")
    parser.add_argument("--project-id", required=True, help="CML project ID")
    parser.add_argument("--config", help="Path to configuration YAML")

    args, _ = parser.parse_known_args()

    try:
        manager = ApplicationManager()
        success = manager.run(args.project_id, args.config)
        if not success:
            sys.exit(1)
    except KeyboardInterrupt:
        print("\nCancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
