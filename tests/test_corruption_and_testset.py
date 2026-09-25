from __future__ import annotations

from collections import Counter

import pytest

from core.utils import read_json
from evaluation.testset import QUESTION_TEMPLATES, build_test_set
from ingestion.corruption import corrupt_clean_dataframe
from observability.quality import build_freshness_report, run_data_quality_checks


def test_corruption_injects_six_logged_types(settings, clean_df):
    corrupted = corrupt_clean_dataframe(clean_df, settings.paths.corruption_log)
    log = read_json(settings.paths.corruption_log)
    assert [event["corruption_type"] for event in log["events"]] == [
        "drop_latest_records",
        "blank_summary",
        "inject_noise",
        "truncate_title",
        "stale_date",
        "duplicate_rows",
    ]
    assert log["meta"]["rows_before"] == 24
    assert log["meta"]["rows_after"] == len(corrupted) == 22
    latest_ids = set(clean_df.head(5)["paper_id"])
    assert set(log["events"][0]["affected_paper_ids"]) == latest_ids
    assert latest_ids.isdisjoint(corrupted["paper_id"])
    assert (corrupted["summary"] == "").sum() >= 3
    assert (corrupted["title"].str.len() < 8).sum() >= 3
    # clean_df khong bi mutate
    assert len(clean_df) == 24


def test_corruption_is_deterministic_and_detected(settings, clean_df):
    first = corrupt_clean_dataframe(clean_df, settings.paths.corruption_log)
    first_log = read_json(settings.paths.corruption_log)["events"]
    second = corrupt_clean_dataframe(clean_df, settings.paths.corruption_log)
    assert read_json(settings.paths.corruption_log)["events"] == first_log
    assert first.drop(columns="age_days").equals(second.drop(columns="age_days"))

    assert run_data_quality_checks(first, settings, "corrupted")["success"] is False
    freshness = build_freshness_report(first, settings, settings.paths.quality_dir / "c.json")
    assert freshness["is_fresh"] is False


def test_test_set_covers_four_types(settings, clean_df):
    test_set = build_test_set(clean_df, settings.paths.eval_testset)
    assert len(test_set) == 10
    assert Counter(item["question_type"] for item in test_set) == {"summary": 3, "authors": 3, "date": 2, "categories": 2}
    assert read_json(settings.paths.eval_testset) == test_set
    by_id = clean_df.set_index("paper_id")
    for item in test_set:
        [doc_id] = item["ground_truth_doc_ids"]
        title = by_id.loc[doc_id, "title"]
        assert item["question"] == QUESTION_TEMPLATES[item["question_type"]].format(title=title)
        if item["question_type"] == "date":
            assert item["ground_truth"] == by_id.loc[doc_id, "published"]
        if item["question_type"] == "authors":
            assert item["ground_truth"] == by_id.loc[doc_id, "authors_joined"]
    assert len({item["ground_truth_doc_ids"][0] for item in test_set}) == 10


def test_test_set_requires_enough_documents(settings, clean_df):
    with pytest.raises(ValueError):
        build_test_set(clean_df.head(5), settings.paths.eval_testset)
