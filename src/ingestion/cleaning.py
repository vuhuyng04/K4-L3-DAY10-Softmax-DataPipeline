from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime

import pandas as pd

from core.utils import compact_join, normalize_whitespace
from ingestion.crossref import PaperRecord, strip_markup

CLEAN_COLUMNS = [
    "paper_id",
    "title",
    "summary",
    "authors",
    "categories",
    "primary_category",
    "published",
    "updated",
    "abs_url",
    "pdf_url",
    "comment",
    "age_days",
    "authors_joined",
    "categories_joined",
    "summary_chars",
    "text_for_embedding",
]


def build_text_for_embedding(
    title: str,
    authors_joined: str,
    published: str,
    categories_joined: str,
    summary: str,
) -> str:
    """Ghep 5 phan ngu canh chuan dua vao embedding model."""
    return "\n".join(
        [
            f"Title: {title}",
            f"Authors: {authors_joined}",
            f"Published: {published}",
            f"Categories: {categories_joined}",
            f"Summary: {summary}",
        ]
    )


def compute_age_days(published: str, run_date: datetime | date) -> int:
    run_day = run_date.date() if isinstance(run_date, datetime) else run_date
    return (run_day - date.fromisoformat(published)).days


def refresh_derived_columns(df: pd.DataFrame, run_date: datetime | date) -> pd.DataFrame:
    """Tinh lai cac cot dan xuat tu cac cot goc (dung chung cho cleaning va corruption)."""
    df = df.copy()
    df["age_days"] = [compute_age_days(value, run_date) for value in df["published"]]
    df["authors_joined"] = [compact_join(authors) for authors in df["authors"]]
    df["categories_joined"] = [compact_join(categories) for categories in df["categories"]]
    df["summary_chars"] = df["summary"].str.len().astype(int)
    df["text_for_embedding"] = [
        build_text_for_embedding(row.title, row.authors_joined, row.published, row.categories_joined, row.summary)
        for row in df.itertuples(index=False)
    ]
    return df


def _normalize_date(value: str | None) -> str:
    if not value:
        return ""
    try:
        return pd.Timestamp(str(value)).date().isoformat()
    except (ValueError, TypeError):
        return ""


def _clean_list(values: list[str] | None) -> list[str]:
    cleaned: list[str] = []
    for value in values or []:
        text = strip_markup(value)
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned


def build_clean_dataframe(records: list[PaperRecord], run_date: datetime) -> pd.DataFrame:
    """Clean raw records thanh dataframe san sang de embed.

    Quy tac: bo tag JATS/HTML + khoang trang thua, chuan hoa ngay ISO, bo record thieu
    `paper_id`/`title`/`published`, dedup theo `paper_id` (giu ban `updated` moi nhat),
    tinh `age_days` va tao `text_for_embedding` 5 phan.
    """
    rows = []
    for record in records:
        raw = asdict(record) if isinstance(record, PaperRecord) else dict(record)
        published = _normalize_date(raw.get("published"))
        rows.append(
            {
                "paper_id": normalize_whitespace(raw.get("paper_id") or ""),
                "title": strip_markup(raw.get("title")),
                "summary": strip_markup(raw.get("summary")),
                "authors": _clean_list(raw.get("authors")),
                "categories": _clean_list(raw.get("categories")),
                "primary_category": strip_markup(raw.get("primary_category")),
                "published": published,
                "updated": _normalize_date(raw.get("updated")) or published,
                "abs_url": (raw.get("abs_url") or "").strip(),
                "pdf_url": (raw.get("pdf_url") or "").strip(),
                "comment": strip_markup(raw.get("comment")),
            }
        )

    df = pd.DataFrame(rows, columns=CLEAN_COLUMNS[:11])
    df = df[(df["paper_id"] != "") & (df["title"] != "") & (df["published"] != "")].copy()
    df["primary_category"] = [
        primary or (categories[0] if categories else "Uncategorized")
        for primary, categories in zip(df["primary_category"], df["categories"], strict=True)
    ]

    df = df.assign(_dedup_key=df["paper_id"].str.lower())
    df = df.sort_values(["_dedup_key", "updated"], ascending=[True, False])
    df = df.drop_duplicates(subset="_dedup_key", keep="first").drop(columns="_dedup_key")

    df = refresh_derived_columns(df, run_date)
    df = df.sort_values(["published", "paper_id"], ascending=[False, True]).reset_index(drop=True)
    return df[CLEAN_COLUMNS]
