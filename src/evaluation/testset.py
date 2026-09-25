from __future__ import annotations

from typing import Any

import pandas as pd

from core.utils import compact_join, first_sentence, write_json

TEST_SET_SIZE = 10
QUESTION_TYPES = ("summary", "authors", "date", "categories")

# Cau hoi dat title trong dau '...' va dung dung keyword ma `retrieval.qa._extract_answer` nhan dien.
QUESTION_TEMPLATES = {
    "summary": "What is the summary of the paper '{title}'?",
    "authors": "Who authored the paper '{title}'?",
    "date": "When was the paper '{title}' published?",
    "categories": "What categories does the paper '{title}' belong to?",
}


def _joined(row: pd.Series, joined_column: str, list_column: str) -> str:
    value = row.get(joined_column)
    if isinstance(value, str) and value:
        return value
    items = row.get(list_column)
    return compact_join(items) if isinstance(items, list) else ""


def _ground_truth(question_type: str, row: pd.Series) -> str:
    if question_type == "summary":
        return first_sentence(str(row["summary"]))
    if question_type == "authors":
        return _joined(row, "authors_joined", "authors")
    if question_type == "date":
        return str(row["published"])[:10]
    return _joined(row, "categories_joined", "categories")


def _pick_evenly(n_rows: int, size: int) -> list[int]:
    if size == 1:
        return [0]
    return sorted({round(i * (n_rows - 1) / (size - 1)) for i in range(size)})


def build_test_set(df: pd.DataFrame, output_path) -> list[dict[str, Any]]:
    """Tao bo benchmark co dinh 10 cau hoi phu 4 dang nghiep vu tu cleaned dataframe.

    Paper duoc chon cach deu nhau theo thu tu `published` (moi -> cu) de phu ca bai moi lan bai cu;
    loai cau hoi xoay vong summary/authors/date/categories (3/3/2/2). Ket qua tat dinh.
    """
    candidates = df.drop_duplicates(subset="paper_id").sort_values(
        ["published", "paper_id"], ascending=[False, True]
    )
    candidates = candidates[candidates["title"].astype(str).str.len() > 0].reset_index(drop=True)
    if len(candidates) < TEST_SET_SIZE:
        raise ValueError(f"Need at least {TEST_SET_SIZE} unique documents to build the test set, got {len(candidates)}.")

    test_set: list[dict[str, Any]] = []
    for position, row_index in enumerate(_pick_evenly(len(candidates), TEST_SET_SIZE)):
        row = candidates.iloc[row_index]
        question_type = QUESTION_TYPES[position % len(QUESTION_TYPES)]
        test_set.append(
            {
                "id": f"eval_{position + 1:03d}",
                "question_type": question_type,
                "question": QUESTION_TEMPLATES[question_type].format(title=row["title"]),
                "ground_truth": _ground_truth(question_type, row),
                "ground_truth_doc_ids": [str(row["paper_id"])],
            }
        )

    write_json(output_path, test_set)
    return test_set
