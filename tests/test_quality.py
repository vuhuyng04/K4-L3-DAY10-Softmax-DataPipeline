from __future__ import annotations

import pandas as pd

from core.utils import read_json
from observability.quality import build_freshness_report, run_data_quality_checks


def _failed(report: dict) -> set[str]:
    return set(report["failed_expectations"])


def test_clean_data_passes_gx_gate(settings, clean_df):
    report = run_data_quality_checks(clean_df, settings, "baseline")
    assert report["success"] is True
    assert report["evaluated_expectations"] == 8
    assert report["engine"].startswith("great_expectations 1.")
    assert read_json(settings.paths.baseline_quality_report)["success"] is True


def test_gx_detects_each_corruption_signal(settings, clean_df):
    corrupted = clean_df.copy()
    corrupted.loc[0, "summary"] = ""
    corrupted.loc[1, "summary"] = "@@## %%&& garbage " + corrupted.loc[1, "summary"]
    corrupted.loc[2, "title"] = "Short"
    corrupted = pd.concat([corrupted, corrupted.iloc[[3]]], ignore_index=True)

    report = run_data_quality_checks(corrupted, settings, "corrupted")
    assert report["success"] is False
    assert _failed(report) == {
        "expect_column_values_to_be_unique(paper_id)",
        "expect_column_value_lengths_to_be_between(summary)",
        "expect_column_value_lengths_to_be_between(title)",
        "expect_column_values_to_not_match_regex(summary)",
    }


def test_gx_detects_nulls_and_row_count(settings, clean_df):
    tiny = clean_df.head(3).copy()
    tiny.loc[0, "title"] = None
    report = run_data_quality_checks(tiny, settings, "tiny")
    assert "expect_table_row_count_to_be_between(table)" in _failed(report)
    assert "expect_column_values_to_not_be_null(title)" in _failed(report)


def test_freshness_sla(settings, clean_df):
    fresh = build_freshness_report(clean_df, settings, settings.paths.freshness_report)
    assert fresh["is_fresh"] is True
    assert fresh["stale_rows"] == 1
    assert fresh["latest_published"] == "2026-07-22"
    assert read_json(settings.paths.freshness_report)["total_rows"] == 24

    stale_df = clean_df.assign(age_days=clean_df["age_days"] + 365)
    stale = build_freshness_report(stale_df, settings, settings.paths.quality_dir / "stale.json")
    assert stale["is_fresh"] is False
    assert stale["stale_ratio"] == 1.0

    empty = build_freshness_report(clean_df.head(0), settings, settings.paths.quality_dir / "empty.json")
    assert empty["is_fresh"] is False
