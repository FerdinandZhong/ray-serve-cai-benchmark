"""
Evaluation engine for text-to-SQL benchmarks.

Runs as background threads. Job state is updated in-place so app.py can
poll progress via /api/jobs/<id>.
"""

import json
import os
import re
import sqlite3
import subprocess
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

# ── Paths ──────────────────────────────────────────────────────────────────────

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
BUNDLED_DATASETS_DIR = Path("/app/datasets")

SPIDER_DB_URL = "https://github.com/taoyds/spider/archive/refs/heads/master.zip"


# ── Job state ──────────────────────────────────────────────────────────────────

@dataclass
class EvaluationJob:
    id: str
    dataset_id: str
    endpoint_url: str
    model_name: str
    metrics: list
    max_samples: int
    concurrency: int
    timeout: int
    temperature: float

    metric_config: dict = field(default_factory=dict)  # {metric_name: {cfg_key: val}}
    api_key: str = ""
    max_tokens: int = 512
    is_reasoning: bool = False
    system_prompt: str = ""  # template with {schema} placeholder; resolved from dataset default if empty

    status: str = "pending"       # pending | running | completed | failed
    progress: int = 0             # 0-100
    total: int = 0
    completed_count: int = 0
    accuracy: Optional[float] = None
    error: Optional[str] = None
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    results: list = field(default_factory=list)
    results_path: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "dataset_id": self.dataset_id,
            "endpoint_url": self.endpoint_url,
            "model_name": self.model_name,
            "metrics": self.metrics,
            "max_samples": self.max_samples,
            "concurrency": self.concurrency,
            "status": self.status,
            "progress": self.progress,
            "total": self.total,
            "completed_count": self.completed_count,
            "accuracy": self.accuracy,
            "error": self.error,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "results_path": self.results_path,
        }


def create_job(
    dataset_id: str,
    endpoint_url: str,
    model_name: str = "default",
    metrics: list = None,
    max_samples: int = 0,
    concurrency: int = 4,
    timeout: int = 60,
    temperature: float = 0.0,
    metric_config: dict = None,
    api_key: str = "",
    max_tokens: int = 512,
    is_reasoning: bool = False,
    system_prompt: str = "",
) -> EvaluationJob:
    return EvaluationJob(
        id=str(uuid.uuid4())[:8],
        dataset_id=dataset_id,
        endpoint_url=endpoint_url.rstrip("/"),
        model_name=model_name,
        metrics=metrics or ["execution_accuracy"],
        max_samples=max_samples,
        concurrency=concurrency,
        timeout=timeout,
        temperature=temperature,
        metric_config=metric_config or {},
        api_key=api_key or "",
        max_tokens=max_tokens,
        is_reasoning=is_reasoning,
        system_prompt=system_prompt or "",
    )


# ── Spider data preparation ────────────────────────────────────────────────────

def _get_validation_file(dataset_id: str) -> Path:
    """Return path to bundled validation JSON for a dataset."""
    path = BUNDLED_DATASETS_DIR / dataset_id / "validation.json"
    if not path.exists():
        raise FileNotFoundError(f"Validation file not found: {path}")
    return path


def _load_dataset_metadata(dataset_id: str) -> dict:
    meta_file = BUNDLED_DATASETS_DIR / dataset_id / "metadata.json"
    if meta_file.exists():
        return json.loads(meta_file.read_text())
    return {}


def _ensure_spider_databases() -> Path:
    """Download Spider SQLite databases to DATA_DIR/spider if not cached."""
    db_dir = DATA_DIR / "spider" / "databases"
    if db_dir.exists() and any(db_dir.iterdir()):
        print(f"[evaluator] Spider databases cached at {db_dir}", flush=True)
        return db_dir

    zip_path = DATA_DIR / "spider" / "spider-master.zip"
    db_dir.parent.mkdir(parents=True, exist_ok=True)

    print("[evaluator] Downloading Spider databases from GitHub...", flush=True)
    subprocess.run(
        ["curl", "-L", "-o", str(zip_path), SPIDER_DB_URL],
        check=True,
    )

    print("[evaluator] Extracting databases...", flush=True)
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.namelist():
            if member.startswith("spider-master/database/"):
                target = db_dir.parent / member.replace("spider-master/", "", 1)
                if member.endswith("/"):
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(member) as src, open(target, "wb") as dst:
                        dst.write(src.read())

    zip_path.unlink(missing_ok=True)
    print(f"[evaluator] Databases extracted to {db_dir}", flush=True)
    return db_dir


# ── Schema extraction ──────────────────────────────────────────────────────────

def _get_db_schema(db_path: Path) -> str:
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND sql IS NOT NULL;")
    schemas = [row[0] for row in cursor.fetchall()]
    conn.close()
    return "\n\n".join(schemas)


def _find_database(db_id: str, databases_dir: Path) -> Optional[Path]:
    db_path = databases_dir / db_id / f"{db_id}.sqlite"
    if db_path.exists():
        return db_path
    for d in databases_dir.iterdir():
        if d.name.lower() == db_id.lower() and d.is_dir():
            sqlite_file = d / f"{d.name}.sqlite"
            if sqlite_file.exists():
                return sqlite_file
    return None


# ── Model call ─────────────────────────────────────────────────────────────────

def _extract_sql(text: str, strip_thinking: bool = False) -> str:
    if strip_thinking:
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE).strip()
    match = re.search(r"```(?:sql)?\s*\n?(.*?)\n?```", text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return text.strip().rstrip(";")


def _call_model(question: str, schema: str, job: EvaluationJob) -> tuple:
    """Returns (generated_sql, error_or_None)."""
    import openai

    base = job.endpoint_url.rstrip("/")
    if not base.endswith("/v1"):
        base = f"{base}/v1"
    client = openai.OpenAI(
        base_url=base,
        api_key=job.api_key or os.environ.get("OPENAI_API_KEY", "dummy"),
    )
    if job.system_prompt:
        system_prompt = job.system_prompt.replace("{schema}", schema)
    else:
        system_prompt = (
            "You are a SQL expert. Given the database schema below, write a SQLite query "
            "that answers the user's question. Return ONLY the SQL query, no explanation.\n\n"
            f"Schema:\n{schema}"
        )
    try:
        response = client.chat.completions.create(
            model=job.model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question},
            ],
            temperature=job.temperature,
            max_tokens=job.max_tokens,
            timeout=job.timeout,
        )
        raw = response.choices[0].message.content.strip()
        return _extract_sql(raw, strip_thinking=job.is_reasoning), None
    except Exception as e:
        return "", str(e)


# ── SQL execution ──────────────────────────────────────────────────────────────

def _execute_sql(db_path: Path, sql: str) -> tuple:
    """Returns (result_set, error_or_None)."""
    try:
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA busy_timeout = 5000;")
        cursor = conn.cursor()
        cursor.execute(sql)
        results = set(cursor.fetchall())
        conn.close()
        return results, None
    except Exception as e:
        return None, str(e)


# ── Single example evaluation ──────────────────────────────────────────────────

def _evaluate_example(example: dict, db_dir: Path, job: EvaluationJob) -> dict:
    db_id = example["db_id"]
    question = example["question"]
    gold_sql = example["query"]

    result = {
        "question": question,
        "db_id": db_id,
        "gold_sql": gold_sql,
        "pred_sql": "",
        "correct": False,
        "error": None,
        "latency_ms": 0,
    }

    db_path = _find_database(db_id, db_dir)
    if not db_path:
        result["error"] = f"Database not found: {db_id}"
        return result

    schema = _get_db_schema(db_path)

    start = time.time()
    pred_sql, api_error = _call_model(question, schema, job)
    result["latency_ms"] = int((time.time() - start) * 1000)
    result["pred_sql"] = pred_sql

    if api_error:
        result["error"] = f"API error: {api_error}"
        return result
    if not pred_sql:
        result["error"] = "Empty SQL generated"
        return result

    gold_results, gold_err = _execute_sql(db_path, gold_sql)
    if gold_err:
        result["error"] = f"Gold SQL execution error: {gold_err}"
        return result

    pred_results, pred_err = _execute_sql(db_path, pred_sql)
    if pred_err:
        result["error"] = f"Predicted SQL execution error: {pred_err}"
        return result

    result["correct"] = gold_results == pred_results
    return result


# ── Text-based evaluation (no execution) ──────────────────────────────────────

def _evaluate_example_text(example: dict, schema: str, job: EvaluationJob) -> dict:
    """Evaluate using text metrics only — no database execution needed."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from metrics import METRICS

    question = example["question"]
    gold_sql = example["query"]

    result = {
        "question": question,
        "db_id": example.get("db_id", ""),
        "gold_sql": gold_sql,
        "pred_sql": "",
        "correct": False,
        "scores": {},
        "error": None,
        "latency_ms": 0,
    }

    start = time.time()
    pred_sql, api_error = _call_model(question, schema, job)
    result["latency_ms"] = int((time.time() - start) * 1000)
    result["pred_sql"] = pred_sql

    if api_error:
        result["error"] = f"API error: {api_error}"
        return result
    if not pred_sql:
        result["error"] = "Empty SQL generated"
        return result

    for metric_name in job.metrics:
        m = METRICS.get(metric_name)
        if m and metric_name != "execution_accuracy":
            cfg = dict(job.metric_config.get(metric_name, {}))
            if metric_name == "llm_as_judge_sql":
                cfg.setdefault("question", question)
                cfg.setdefault("schema", schema)
                from metrics.llm_judge import score_detailed
                score_val, judge_trace = score_detailed(gold_sql, pred_sql, config=cfg if cfg else None)
                result["scores"][metric_name] = score_val
                result.setdefault("judge_traces", {})[metric_name] = judge_trace
            else:
                result["scores"][metric_name] = m["fn"](gold_sql, pred_sql, config=cfg if cfg else None)

    # Primary correctness signal: exact_match if available, else best score
    if "exact_match" in result["scores"]:
        result["correct"] = result["scores"]["exact_match"] == 1.0
    elif result["scores"]:
        result["correct"] = max(result["scores"].values()) >= 0.9

    return result


# ── Main run loop ──────────────────────────────────────────────────────────────

def run_job(job: EvaluationJob, phoenix_client=None) -> None:
    """Execute evaluation job. Designed to run in a background thread."""
    job.status = "running"
    job.started_at = time.time()
    print(f"[evaluator] job {job.id} started — dataset={job.dataset_id} "
          f"endpoint={job.endpoint_url}", flush=True)

    try:
        # Prepare dataset
        meta = _load_dataset_metadata(job.dataset_id)
        requires_execution = meta.get("requires_execution", True)
        dataset_schema = meta.get("schema", "")

        # Resolve system prompt: user-supplied override takes priority over dataset default
        if not job.system_prompt:
            job.system_prompt = meta.get("system_prompt", "")

        val_file = _get_validation_file(job.dataset_id)
        with open(val_file) as f:
            examples = json.load(f)

        if job.max_samples > 0:
            examples = examples[: job.max_samples]

        job.total = len(examples)
        print(f"[evaluator] job {job.id}: {job.total} examples "
              f"(execution={'yes' if requires_execution else 'no'})", flush=True)

        # Run evaluation in parallel
        results = []
        if requires_execution:
            # Download SQLite databases on first run, then execute gold + pred SQL
            db_dir = _ensure_spider_databases()
            eval_fn = lambda ex: _evaluate_example(ex, db_dir, job)
        else:
            # Text-based metrics only — no database needed
            eval_fn = lambda ex: _evaluate_example_text(ex, dataset_schema, job)

        with ThreadPoolExecutor(max_workers=job.concurrency) as executor:
            futures = {
                executor.submit(eval_fn, ex): i
                for i, ex in enumerate(examples)
            }
            for future in as_completed(futures):
                result = future.result()
                results.append(result)
                job.completed_count = len(results)
                job.progress = int(job.completed_count / job.total * 100)

        # Compute accuracy
        correct = sum(1 for r in results if r["correct"])
        if results:
            if not requires_execution:
                # Text metrics: accuracy = mean of primary metric scores
                all_metric_scores: dict = {}
                for r in results:
                    for k, v in r.get("scores", {}).items():
                        all_metric_scores.setdefault(k, []).append(float(v))
                if all_metric_scores:
                    primary = (
                        "exact_match" if "exact_match" in all_metric_scores
                        else next(iter(all_metric_scores))
                    )
                    job.accuracy = sum(all_metric_scores[primary]) / len(results)
                else:
                    job.accuracy = 0.0
            else:
                job.accuracy = correct / len(results)
        else:
            job.accuracy = 0.0
        job.results = results

        # Save results to disk
        out_dir = DATA_DIR / "results" / f"{job.dataset_id}_{job.id}"
        out_dir.mkdir(parents=True, exist_ok=True)
        results_file = out_dir / "results.json"
        with open(results_file, "w") as f:
            json.dump({
                "job_id": job.id,
                "dataset_id": job.dataset_id,
                "endpoint_url": job.endpoint_url,
                "model_name": job.model_name,
                "accuracy": job.accuracy,
                "total": job.total,
                "correct": correct,
                "timestamp": datetime.now().isoformat(),
                "results": results,
            }, f, indent=2)
        job.results_path = str(results_file)

        # Upload to Phoenix if available
        if phoenix_client is not None:
            try:
                if not phoenix_client.dataset_exists(job.dataset_id):
                    records = json.loads(val_file.read_text())
                    phoenix_client.upload_dataset(
                        name=job.dataset_id,
                        records=records,
                        description=meta.get("description", ""),
                    )
                    print(f"[evaluator] job {job.id}: dataset '{job.dataset_id}' uploaded to Phoenix", flush=True)
            except Exception as e:
                print(f"[evaluator] job {job.id}: Phoenix dataset upload failed: {e}", flush=True)

            try:
                phoenix_client.upload_evaluation_results(
                    dataset_id=job.dataset_id,
                    job_id=job.id,
                    model_name=job.model_name,
                    results=results,
                )
                print(f"[evaluator] job {job.id}: results uploaded to Phoenix", flush=True)
            except Exception as e:
                print(f"[evaluator] job {job.id}: Phoenix upload failed: {e}", flush=True)

        job.status = "completed"
        print(f"[evaluator] job {job.id} completed — accuracy={job.accuracy:.1%}", flush=True)

    except Exception as e:
        job.status = "failed"
        job.error = str(e)
        print(f"[evaluator] job {job.id} FAILED: {e}", flush=True)

    finally:
        job.finished_at = time.time()
