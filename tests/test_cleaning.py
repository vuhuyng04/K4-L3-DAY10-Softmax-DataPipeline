from __future__ import annotations

from datetime import date

from ingestion.cleaning import CLEAN_COLUMNS, build_clean_dataframe, build_text_for_embedding, compute_age_days
from ingestion.crossref import PaperRecord
from tests.conftest import RUN_DATE


def _record(paper_id: str, **overrides) -> PaperRecord:
    values = {
        "paper_id": paper_id,
        "title": "Some   Title  <b>Here</b>",
        "summary": "<jats:p>An abstract with enough characters to embed.</jats:p>",
        "authors": ["Ada Lovelace", " Ada Lovelace ", "Alan Turing"],
        "categories": ["AI"],
        "primary_category": "",
        "published": "2026-07-01",
        "updated": "2026-07-01",
        "abs_url": "https://doi.org/x",
        "pdf_url": "https://doi.org/x",
        "comment": "c",
    }
    values.update(overrides)
    return PaperRecord(**values)


def test_clean_snapshot_has_expected_schema(clean_df):
    assert len(clean_df) == 24
    assert list(clean_df.columns) == CLEAN_COLUMNS
    assert clean_df["paper_id"].is_unique
    assert clean_df["published"].is_monotonic_decreasing
    assert (clean_df["summary_chars"] == clean_df["summary"].str.len()).all()


def test_text_for_embedding_has_five_parts(clean_df):
    parts = clean_df.loc[0, "text_for_embedding"].split("\n")
    assert [part.split(":", 1)[0] for part in parts] == ["Title", "Authors", "Published", "Categories", "Summary"]


def test_cleaning_rules_dedup_markup_and_age():
    records = [
        _record("10.1/A", updated="2026-07-01", title="Old version title"),
        _record("10.1/a", updated="2026-08-01", title="New   version <i>title</i>"),
        _record("10.1/B", title=""),
        _record("10.1/C", published="not-a-date"),
    ]
    df = build_clean_dataframe(records, RUN_DATE)
    assert len(df) == 1
    row = df.iloc[0]
    assert row["title"] == "New version title"
    assert row["summary"] == "An abstract with enough characters to embed."
    assert row["authors"] == ["Ada Lovelace", "Alan Turing"]
    assert row["authors_joined"] == "Ada Lovelace, Alan Turing"
    assert row["primary_category"] == "AI"
    assert row["age_days"] == (date(2026, 9, 25) - date(2026, 7, 1)).days


def test_helpers():
    assert compute_age_days("2026-09-20", date(2026, 9, 25)) == 5
    text = build_text_for_embedding("T", "A", "2026-01-01", "C", "S")
    assert text == "Title: T\nAuthors: A\nPublished: 2026-01-01\nCategories: C\nSummary: S"
