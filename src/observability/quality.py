from __future__ import annotations

import json
import os
from typing import Any

os.environ.setdefault("GX_ANALYTICS_ENABLED", "False")

import great_expectations as gx
import great_expectations.expectations as gxe
import pandas as pd

from core.config import Settings
from core.utils import now_utc, write_json

MIN_ROWS = 5
MAX_ROWS = 5000
MIN_SUMMARY_CHARS = 30
MIN_TITLE_CHARS = 8
MAX_STALE_RATIO = 0.25
# Chuoi >= 3 ky tu dac biet lien tiep khong xuat hien trong abstract binh thuong -> dau hieu nhieu/rac.
NOISE_REGEX = r"[#@$%^&*~|]{3,}"
LIST_COLUMNS = ("authors", "categories")
REQUIRED_NOT_NULL = ("paper_id", "title", "text_for_embedding")


def _build_expectations() -> list[gxe.Expectation]:
    expectations: list[gxe.Expectation] = [
        gxe.ExpectTableRowCountToBeBetween(min_value=MIN_ROWS, max_value=MAX_ROWS),
    ]
    expectations += [gxe.ExpectColumnValuesToNotBeNull(column=column) for column in REQUIRED_NOT_NULL]
    expectations += [
        gxe.ExpectColumnValuesToBeUnique(column="paper_id"),
        gxe.ExpectColumnValueLengthsToBeBetween(column="summary", min_value=MIN_SUMMARY_CHARS),
        gxe.ExpectColumnValueLengthsToBeBetween(column="title", min_value=MIN_TITLE_CHARS),
        gxe.ExpectColumnValuesToNotMatchRegex(column="summary", regex=NOISE_REGEX),
    ]
    return expectations


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def _summarize_result(result: Any) -> dict[str, Any]:
    config = result.expectation_config
    kwargs = {key: value for key, value in dict(config.kwargs).items() if key not in {"batch_id"}}
    details = dict(result.result or {})
    return _json_safe(
        {
            "expectation_type": config.type,
            "column": kwargs.get("column"),
            "kwargs": kwargs,
            "success": bool(result.success),
            "observed_value": details.get("observed_value"),
            "element_count": details.get("element_count"),
            "unexpected_count": details.get("unexpected_count"),
            "unexpected_percent": details.get("unexpected_percent"),
            "partial_unexpected_list": (details.get("partial_unexpected_list") or [])[:5],
        }
    )


def _freshness_payload(df: pd.DataFrame, settings: Settings) -> dict[str, Any]:
    threshold = settings.freshness_threshold_days
    total_rows = int(len(df))
    if total_rows == 0 or "age_days" not in df.columns:
        stale_rows, stale_ratio = 0, 1.0
        latest = oldest = None
        latest_age = None
    else:
        ages = pd.to_numeric(df["age_days"], errors="coerce")
        stale_rows = int((ages > threshold).sum())
        stale_ratio = stale_rows / total_rows
        published = df["published"].astype(str)
        latest, oldest = published.max(), published.min()
        latest_age = int(ages.min())
    return {
        "threshold_days": threshold,
        "max_stale_ratio": MAX_STALE_RATIO,
        "latest_published": latest,
        "oldest_published": oldest,
        "latest_age_days": latest_age,
        "stale_rows": stale_rows,
        "total_rows": total_rows,
        "stale_ratio": round(stale_ratio, 4),
        "is_fresh": total_rows > 0 and stale_ratio <= MAX_STALE_RATIO,
    }


def run_data_quality_checks(df: pd.DataFrame, settings: Settings, report_name: str) -> dict[str, Any]:
    """Chay Quality Gate bang Great Expectations 1.x va ghi `data/quality/<report_name>_quality_report.json`.

    `success` chi phu thuoc cac expectation GX (schema/completeness/uniqueness/validity).
    Freshness duoc dinh kem nhu tin hieu tham khao va duoc gate rieng qua `build_freshness_report`.
    """
    validation_df = df.drop(columns=[column for column in LIST_COLUMNS if column in df.columns]).reset_index(drop=True)

    context = gx.get_context(mode="ephemeral")
    data_source = context.data_sources.add_pandas(name="papers_source")
    data_asset = data_source.add_dataframe_asset(name="papers_asset")
    batch_def = data_asset.add_batch_definition_whole_dataframe("papers_batch")
    batch = batch_def.get_batch(batch_parameters={"dataframe": validation_df})

    suite = context.suites.add(gx.ExpectationSuite(name=f"papers_{report_name}_suite"))
    for expectation in _build_expectations():
        suite.add_expectation(expectation)
    validation = batch.validate(suite)

    expectations = [_summarize_result(result) for result in validation.results]
    failed = [f"{item['expectation_type']}({item['column'] or 'table'})" for item in expectations if not item["success"]]
    report = {
        "report_name": report_name,
        "generated_at": now_utc().isoformat(),
        "engine": f"great_expectations {gx.__version__}",
        "suite_name": suite.name,
        "success": bool(validation.success),
        "row_count": int(len(df)),
        "evaluated_expectations": len(expectations),
        "successful_expectations": len(expectations) - len(failed),
        "failed_expectations": failed,
        "expectations": expectations,
        "freshness_signal": _freshness_payload(df, settings),
    }
    write_json(settings.paths.quality_dir / f"{report_name}_quality_report.json", report)
    return report


def build_freshness_report(df: pd.DataFrame, settings: Settings, report_path) -> dict[str, Any]:
    """Freshness SLA: `is_fresh=False` khi ty le bai co `age_days > 180` vuot qua 25%."""
    report = {"generated_at": now_utc().isoformat(), **_freshness_payload(df, settings)}
    write_json(report_path, report)
    return report
