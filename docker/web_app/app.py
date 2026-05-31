#!/usr/bin/env python3
"""
Evaluation Manager — stdlib-only HTTP server.

Manages evaluation jobs, serves the Apple-styled web UI, and exposes a REST API
for the frontend to call.

Endpoints
─────────
  GET  /                              → index.html
  GET  /api/health                    → {status, phoenix_ready}
  GET  /api/datasets                  → list bundled datasets + Phoenix upload status
  POST /api/datasets/<id>/upload      → upload dataset to Phoenix
  POST /api/datasets/upload-file      → upload a new custom dataset JSON
  GET  /api/metrics                   → list pre-defined metrics
  POST /api/metrics/define            → save a custom metric definition
  POST /api/evaluate                  → start evaluation job
  GET  /api/jobs                      → list all jobs
  GET  /api/jobs/<id>                 → job detail
"""

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict

# Allow importing sibling modules when running as /app/app.py
sys.path.insert(0, str(Path(__file__).parent))

import evaluator
import phoenix_client
from metrics import list_metrics, METRICS

# ── Configuration ─────────────────────────────────────────────────────────────

LISTEN_HOST   = "127.0.0.1"
LISTEN_PORT   = int(os.environ.get("MANAGER_PORT", 9000))
STATIC_DIR    = Path(__file__).parent / "static"
DATASETS_DIR  = Path(os.environ.get("DATASETS_DIR", "/app/datasets"))
DATA_DIR      = Path(os.environ.get("DATA_DIR", "/data"))

# ── State ─────────────────────────────────────────────────────────────────────

_jobs: Dict[str, evaluator.EvaluationJob] = {}
_lock = threading.Lock()


# ── Dataset helpers ───────────────────────────────────────────────────────────

def _list_datasets() -> list:
    datasets = []
    if not DATASETS_DIR.exists():
        return datasets
    for meta_file in sorted(DATASETS_DIR.glob("*/metadata.json")):
        try:
            meta = json.loads(meta_file.read_text())
            # Check if validation.json is present
            val_file = meta_file.parent / "validation.json"
            meta["available"] = val_file.exists()
            meta["phoenix_uploaded"] = phoenix_client.dataset_exists(meta.get("id", ""))
            datasets.append(meta)
        except Exception:
            pass
    return datasets


# ── HTTP handler ──────────────────────────────────────────────────────────────

class _Handler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        pass  # suppress noisy access log

    def _path(self) -> str:
        return self.path.split("?")[0].rstrip("/") or "/"

    def _send_json(self, code: int, obj) -> None:
        body = json.dumps(obj, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, body: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(raw)
        except Exception:
            return {}

    # ── GET ──────────────────────────────────────────────────────────────────

    def do_GET(self):
        p = self._path()

        if p in ("/", "/index.html"):
            html = (STATIC_DIR / "index.html").read_bytes()
            self._send_html(html)

        elif p == "/api/health":
            self._send_json(200, {
                "status": "ok",
                "phoenix_ready": phoenix_client.is_ready(),
                "phoenix_url": "/",
                "jobs_total": len(_jobs),
            })

        elif p == "/api/datasets":
            self._send_json(200, {"datasets": _list_datasets()})

        elif p == "/api/metrics":
            self._send_json(200, {"metrics": list_metrics()})

        elif p == "/api/jobs":
            with _lock:
                jobs_list = [j.to_dict() for j in _jobs.values()]
            self._send_json(200, {"jobs": jobs_list})

        elif p.startswith("/api/jobs/"):
            job_id = p.split("/")[-1]
            with _lock:
                job = _jobs.get(job_id)
            if job is None:
                self._send_json(404, {"error": f"Job {job_id} not found"})
            else:
                self._send_json(200, job.to_dict())

        else:
            self._send_json(404, {"error": "not found"})

    # ── POST ─────────────────────────────────────────────────────────────────

    def do_POST(self):
        p = self._path()

        # ── Start evaluation job ──────────────────────────────────────────
        if p == "/api/evaluate":
            body = self._read_body()
            endpoint_url = (body.get("endpoint_url") or "").strip()
            if not endpoint_url:
                self._send_json(400, {"error": "'endpoint_url' is required"})
                return

            dataset_id = body.get("dataset_id", "spider")
            metrics    = body.get("metrics", ["execution_accuracy"])

            job = evaluator.create_job(
                dataset_id=dataset_id,
                endpoint_url=endpoint_url,
                model_name=body.get("model_name", "default"),
                metrics=metrics,
                max_samples=int(body.get("max_samples", 0)),
                concurrency=int(body.get("concurrency", 4)),
                timeout=int(body.get("timeout", 60)),
                temperature=float(body.get("temperature", 0.0)),
                metric_config=body.get("metric_config", {}),
                api_key=body.get("api_key", ""),
                max_tokens=int(body.get("max_tokens", 512)),
                is_reasoning=bool(body.get("is_reasoning", False)),
                system_prompt=body.get("system_prompt", ""),
            )

            with _lock:
                _jobs[job.id] = job

            client = None
            if phoenix_client.is_ready():
                client = phoenix_client

            t = threading.Thread(
                target=evaluator.run_job,
                args=(job, client),
                daemon=True,
            )
            t.start()
            print(f"[app] started job {job.id}", flush=True)
            self._send_json(200, {"job_id": job.id, "status": "started"})

        # ── Upload existing bundled dataset to Phoenix ────────────────────
        elif p.startswith("/api/datasets/") and p.endswith("/upload"):
            parts = p.split("/")
            # /api/datasets/<id>/upload → parts[-2] is id
            dataset_id = parts[-2] if len(parts) >= 4 else ""
            val_file = DATASETS_DIR / dataset_id / "validation.json"
            meta_file = DATASETS_DIR / dataset_id / "metadata.json"

            if not val_file.exists():
                self._send_json(404, {"error": f"Dataset '{dataset_id}' not found"})
                return

            meta = json.loads(meta_file.read_text()) if meta_file.exists() else {}
            records = json.loads(val_file.read_text())

            if not phoenix_client.is_ready():
                self._send_json(503, {"error": "Phoenix is not ready yet"})
                return

            try:
                result = phoenix_client.upload_dataset(
                    name=dataset_id,
                    records=records,
                    description=meta.get("description", ""),
                )
                self._send_json(200, {"uploaded": dataset_id, "phoenix_response": result})
            except Exception as e:
                self._send_json(500, {"error": str(e)})

        # ── Upload new dataset file ───────────────────────────────────────
        elif p == "/api/datasets/upload-file":
            body = self._read_body()
            name = (body.get("name") or "").strip().replace(" ", "_").lower()
            records = body.get("records")

            if not name:
                self._send_json(400, {"error": "'name' is required"})
                return
            if not isinstance(records, list) or not records:
                self._send_json(400, {"error": "'records' must be a non-empty list"})
                return

            out_dir = DATASETS_DIR / name
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "validation.json").write_text(json.dumps(records, indent=2))
            (out_dir / "metadata.json").write_text(json.dumps({
                "id": name,
                "name": name,
                "description": body.get("description", ""),
                "size": len(records),
                "task_type": body.get("task_type", "text2sql"),
                "system_prompt": body.get("system_prompt", ""),
                "custom": True,
            }, indent=2))
            self._send_json(200, {"created": name, "size": len(records)})

        # ── Define custom metric ──────────────────────────────────────────
        elif p == "/api/metrics/define":
            body = self._read_body()
            name = (body.get("name") or "").strip().replace(" ", "_").lower()
            description = (body.get("description") or "").strip()

            if not name:
                self._send_json(400, {"error": "'name' is required"})
                return
            if name in METRICS:
                self._send_json(409, {"error": f"Metric '{name}' already exists"})
                return

            # Save a stub definition (implementation requires code changes for now)
            metrics_dir = DATA_DIR / "custom_metrics"
            metrics_dir.mkdir(parents=True, exist_ok=True)
            (metrics_dir / f"{name}.json").write_text(json.dumps({
                "name": name,
                "description": description,
                "type": body.get("type", "binary"),
                "custom": True,
            }, indent=2))
            self._send_json(200, {"defined": name,
                                  "note": "Custom metric saved. Restart to activate."})

        else:
            self._send_json(404, {"error": "not found"})

    # CORS pre-flight
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), _Handler)
    print(f"[app] listening on {LISTEN_HOST}:{LISTEN_PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
