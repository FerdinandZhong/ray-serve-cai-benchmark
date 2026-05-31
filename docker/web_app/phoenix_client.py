"""
Arize Phoenix client — dataset upload and evaluation trace logging.

Communicates with the self-hosted Phoenix instance running at
http://127.0.0.1:<PHOENIX_PORT>.

Correct Phoenix REST API (discovered from /openapi.json):
  POST /v1/datasets/upload?sync=true   → upload dataset rows
  GET  /v1/datasets                    → list datasets
  GET  /v1/datasets/{id}/examples      → list examples with stable IDs
  POST /v1/datasets/{id}/experiments   → create experiment
  POST /v1/experiments/{id}/runs       → create single experiment run
"""

import json
import os
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import Optional

PHOENIX_PORT = int(os.environ.get("PHOENIX_PORT", 6006))
_BASE = f"http://127.0.0.1:{PHOENIX_PORT}"


def _http(method: str, path: str, body: Optional[dict] = None, params: str = "") -> dict:
    url = f"{_BASE}{path}"
    if params:
        url = f"{url}?{params}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"} if data else {},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Phoenix {method} {path} → {e.code}: {e.read().decode()}") from e


def is_ready() -> bool:
    try:
        urllib.request.urlopen(f"{_BASE}/healthz", timeout=2)
        return True
    except Exception:
        return False


def _find_dataset(name: str) -> Optional[dict]:
    """Return the Phoenix dataset dict for the given name, or None."""
    try:
        result = _http("GET", "/v1/datasets")
        for d in result.get("data", []):
            if d.get("name") == name:
                return d
    except Exception:
        pass
    return None


def dataset_exists(name: str) -> bool:
    return _find_dataset(name) is not None


def upload_dataset(name: str, records: list, description: str = "") -> dict:
    """Upload records to Phoenix as a named dataset.

    Uses POST /v1/datasets/upload?sync=true with parallel arrays.
    Returns the Phoenix response {data: {dataset_id, version_id, ...}}.
    """
    inputs = [{"question": r.get("question", ""), "db_id": r.get("db_id", "")} for r in records]
    outputs = [{"gold_sql": r.get("query", "")} for r in records]
    metadata = [{k: v for k, v in r.items() if k not in ("question", "query")} for r in records]

    return _http("POST", "/v1/datasets/upload", {
        "name": name,
        "description": description,
        "action": "create",
        "inputs": inputs,
        "outputs": outputs,
        "metadata": metadata,
    }, params="sync=true")


def upload_evaluation_results(
    dataset_id: str,
    job_id: str,
    model_name: str,
    results: list,
) -> None:
    """Upload per-example evaluation results to Phoenix as an Experiment.

    Flow:
      1. Get Phoenix dataset record for dataset_id (name)
      2. Fetch its examples to get stable example IDs
      3. Create an Experiment linked to the dataset
      4. Create one run per result, matched to example by question text
    """
    now = datetime.now(timezone.utc).isoformat()
    experiment_name = f"{dataset_id}_{model_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    # 1. Get Phoenix dataset record
    ds = _find_dataset(dataset_id)
    if ds is None:
        raise RuntimeError(f"Dataset '{dataset_id}' not found in Phoenix")
    phoenix_dataset_id = ds["id"]

    # 2. Fetch examples to build question → example_id map
    examples_resp = _http("GET", f"/v1/datasets/{phoenix_dataset_id}/examples")
    example_id_by_question: dict = {}
    for ex in examples_resp.get("data", {}).get("examples", []):
        q = ex.get("input", {}).get("question", "")
        if q:
            example_id_by_question[q] = ex["id"]

    # 3. Create experiment
    exp_resp = _http("POST", f"/v1/datasets/{phoenix_dataset_id}/experiments", {
        "name": experiment_name,
        "metadata": {"model": model_name, "job_id": job_id},
    })
    experiment_id = exp_resp.get("data", {}).get("id") or exp_resp.get("id")
    if not experiment_id:
        raise RuntimeError(f"Unexpected experiment response: {exp_resp}")

    # 4. Create runs + evaluations — one run per result, one evaluation per metric score
    uploaded = 0
    for r in results:
        example_id = example_id_by_question.get(r.get("question", ""))
        if not example_id:
            continue
        try:
            run_output = {"pred_sql": r.get("pred_sql", "")}
            judge_traces = r.get("judge_traces", {})
            if judge_traces:
                run_output["judge_traces"] = judge_traces
            run_resp = _http("POST", f"/v1/experiments/{experiment_id}/runs", {
                "dataset_example_id": example_id,
                "output": run_output,
                "repetition_number": 1,
                "start_time": now,
                "end_time": now,
                "error": r.get("error"),
            })
            run_id = run_resp.get("data", {}).get("id") or run_resp.get("id")
            uploaded += 1

            # Log each metric score as a Phoenix evaluation so the UI can aggregate them
            scores = r.get("scores") or {}
            if not scores:
                # execution_accuracy path: derive from correct flag
                scores = {"execution_accuracy": 1.0 if r.get("correct") else 0.0}
            for metric_name, score_val in scores.items():
                if run_id:
                    try:
                        _http("POST", "/v1/experiment_evaluations", {
                            "experiment_run_id": run_id,
                            "name": metric_name,
                            "annotator_kind": "CODE",
                            "start_time": now,
                            "end_time": now,
                            "result": {
                                "score": float(score_val),
                                "label": "correct" if score_val >= 0.9 else "incorrect",
                            },
                        })
                    except Exception as e:
                        print(f"[phoenix] eval upload failed ({metric_name}): {e}", flush=True)

        except Exception as e:
            print(f"[phoenix] run upload failed for example {example_id}: {e}", flush=True)

    print(f"[phoenix] uploaded {uploaded}/{len(results)} runs to experiment '{experiment_name}'",
          flush=True)


def get_phoenix_url() -> str:
    return "/"
