"""Exact match after SQL normalization."""

import re


def _normalize(sql: str) -> str:
    sql = sql.strip().rstrip(";").lower()
    sql = re.sub(r"\s+", " ", sql)
    return sql.strip()


def score(gold_sql: str, pred_sql: str, config=None) -> float:
    return 1.0 if _normalize(gold_sql) == _normalize(pred_sql) else 0.0
