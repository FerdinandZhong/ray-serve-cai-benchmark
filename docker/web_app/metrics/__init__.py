"""Metric registry for evaluation benchmarks."""

from typing import Callable, Optional

METRICS: dict[str, dict] = {}


def register(
    name: str,
    fn: Callable,
    description: str,
    metric_type: str = "binary",
    requires_config: bool = False,
    config_fields: Optional[list] = None,
) -> None:
    METRICS[name] = {
        "name": name,
        "fn": fn,
        "description": description,
        "type": metric_type,
        "requires_config": requires_config,
        "config_fields": config_fields or [],
    }


def list_metrics() -> list[dict]:
    return [
        {
            "name": m["name"],
            "description": m["description"],
            "type": m["type"],
            "requires_config": m["requires_config"],
            "config_fields": m["config_fields"],
        }
        for m in METRICS.values()
    ]


# ── Built-in metrics ──────────────────────────────────────────────────────────

from . import execution_accuracy as _ea
from . import exact_match as _em
from . import token_f1 as _tf
from . import component_match as _cm
from . import llm_judge as _lj

register(
    "execution_accuracy",
    _ea.score,
    "Execute both gold and predicted SQL against the database and compare result sets.",
    "binary",
)
register(
    "exact_match",
    _em.score,
    "Exact string match after lowercasing and whitespace normalization.",
    "binary",
)
register(
    "token_f1",
    _tf.score,
    "Token-level F1 score between predicted and gold SQL.",
    "continuous",
)
register(
    "component_match",
    _cm.score,
    "Fraction of SQL clauses (SELECT/FROM/WHERE/GROUP BY/ORDER BY/HAVING) with matching token sets.",
    "continuous",
)
register(
    "llm_as_judge_sql",
    _lj.score,
    "Use an LLM to judge whether the predicted SQL is semantically equivalent to the gold SQL.",
    "binary",
    requires_config=True,
    config_fields=[
        {"name": "url",   "label": "Judge LLM URL",  "type": "url",      "placeholder": "https://your-judge-endpoint.example.com"},
        {"name": "token", "label": "API Token",       "type": "password", "placeholder": "sk-..."},
        {"name": "model", "label": "Model Name",      "type": "text",     "placeholder": "default"},
    ],
)
