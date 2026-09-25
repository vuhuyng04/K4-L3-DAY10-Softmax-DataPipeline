from __future__ import annotations

from datetime import date, timedelta
import math
import random

import pandas as pd

from core.utils import now_utc, write_json
from ingestion.cleaning import refresh_derived_columns

SEED = 42
DROP_LATEST_RATIO = 0.20
BLANK_SUMMARY_ROWS = 3
NOISE_ROWS = 3
TRUNCATE_TITLE_ROWS = 3
TRUNCATED_TITLE_CHARS = 6
STALE_RATIO = 0.30
STALE_SHIFT_DAYS = 365
DUPLICATE_ROWS = 3
NOISE_PREFIX = "@@## %%&& ~~** ||^^ zqx#@! lorem#$%"


def _take(rng: random.Random, pool: list[int], count: int) -> list[int]:
    chosen = sorted(rng.sample(pool, min(count, len(pool))))
    for index in chosen:
        pool.remove(index)
    return chosen


def _ids(df: pd.DataFrame, indices: list[int]) -> list[str]:
    return [str(df.at[index, "paper_id"]) for index in indices]


def corrupt_clean_dataframe(df: pd.DataFrame, output_log_path) -> pd.DataFrame:
    """Tiem 6 dang loi du lieu thuc te vao cleaned dataframe (tat dinh voi seed=42).

    Moi dang loi nham vao mot nhom dong rieng biet de co the quy tac dong ve dung loai loi.
    Log chi tiet (tham so + paper_id bi anh huong) duoc ghi vao `output_log_path`.
    """
    rng = random.Random(SEED)
    run_date = now_utc()
    rows_before = int(len(df))
    events: list[dict] = []
    corrupted = df.sort_values(["published", "paper_id"], ascending=[False, True]).reset_index(drop=True).copy()

    # 1. Drop latest records: mat 20% ban ghi moi nhat (ingestion fail -> stale knowledge).
    drop_count = math.ceil(len(corrupted) * DROP_LATEST_RATIO)
    dropped = list(range(drop_count))
    events.append(
        {
            "corruption_type": "drop_latest_records",
            "description": f"Dropped the {drop_count} most recently published records ({DROP_LATEST_RATIO:.0%}).",
            "params": {"ratio": DROP_LATEST_RATIO},
            "affected_count": drop_count,
            "affected_paper_ids": _ids(corrupted, dropped),
        }
    )
    corrupted = corrupted.drop(index=dropped).reset_index(drop=True)
    pool = list(range(len(corrupted)))

    # 2. Blank summary: scraper tra ve abstract rong.
    blanked = _take(rng, pool, BLANK_SUMMARY_ROWS)
    corrupted.loc[blanked, "summary"] = ""
    events.append(
        {
            "corruption_type": "blank_summary",
            "description": "Replaced the summary with an empty string.",
            "params": {"rows": BLANK_SUMMARY_ROWS},
            "affected_count": len(blanked),
            "affected_paper_ids": _ids(corrupted, blanked),
        }
    )

    # 3. Inject noise: chen chuoi ky tu rac vao dau summary.
    noisy = _take(rng, pool, NOISE_ROWS)
    corrupted.loc[noisy, "summary"] = [f"{NOISE_PREFIX} {corrupted.at[index, 'summary']}" for index in noisy]
    events.append(
        {
            "corruption_type": "inject_noise",
            "description": "Prepended garbage symbols to the summary.",
            "params": {"rows": NOISE_ROWS, "noise_prefix": NOISE_PREFIX},
            "affected_count": len(noisy),
            "affected_paper_ids": _ids(corrupted, noisy),
        }
    )

    # 4. Truncate title xuong duoi 8 ky tu.
    truncated = _take(rng, pool, TRUNCATE_TITLE_ROWS)
    original_titles = [str(corrupted.at[index, "title"]) for index in truncated]
    corrupted.loc[truncated, "title"] = [title[:TRUNCATED_TITLE_CHARS] for title in original_titles]
    events.append(
        {
            "corruption_type": "truncate_title",
            "description": f"Truncated the title to {TRUNCATED_TITLE_CHARS} characters.",
            "params": {"rows": TRUNCATE_TITLE_ROWS, "max_chars": TRUNCATED_TITLE_CHARS},
            "affected_count": len(truncated),
            "affected_paper_ids": _ids(corrupted, truncated),
        }
    )

    # 5. Stale date: lui ngay xuat ban 365 ngay (du lieu bi moc).
    stale_count = math.ceil(len(corrupted) * STALE_RATIO)
    staled = _take(rng, pool, stale_count)
    corrupted.loc[staled, "published"] = [
        (date.fromisoformat(str(corrupted.at[index, "published"])) - timedelta(days=STALE_SHIFT_DAYS)).isoformat()
        for index in staled
    ]
    events.append(
        {
            "corruption_type": "stale_date",
            "description": f"Shifted the published date {STALE_SHIFT_DAYS} days into the past.",
            "params": {"ratio": STALE_RATIO, "shift_days": STALE_SHIFT_DAYS},
            "affected_count": len(staled),
            "affected_paper_ids": _ids(corrupted, staled),
        }
    )

    # 6. Duplicate rows: nhan ban dong (duplicate index -> loang context).
    duplicated = sorted(rng.sample(range(len(corrupted)), min(DUPLICATE_ROWS, len(corrupted))))
    events.append(
        {
            "corruption_type": "duplicate_rows",
            "description": "Appended exact copies of existing rows.",
            "params": {"rows": DUPLICATE_ROWS},
            "affected_count": len(duplicated),
            "affected_paper_ids": _ids(corrupted, duplicated),
        }
    )
    corrupted = pd.concat([corrupted, corrupted.loc[duplicated]], ignore_index=True)

    # 7. Rebuild cac cot dan xuat (age_days, text_for_embedding, ...) tu du lieu da bi lam ban.
    corrupted = refresh_derived_columns(corrupted, run_date)

    write_json(
        output_log_path,
        {
            "meta": {
                "seed": SEED,
                "generated_at": run_date.isoformat(),
                "rows_before": rows_before,
                "rows_after": int(len(corrupted)),
                "corruption_types": [event["corruption_type"] for event in events],
            },
            "events": events,
        },
    )
    return corrupted
