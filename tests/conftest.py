from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import shutil

import pytest

from core.config import Settings, load_settings
from ingestion.cleaning import build_clean_dataframe
from ingestion.crossref import load_raw_records

PROJECT_DIR = Path(__file__).resolve().parents[1]
SNAPSHOT_DIR = PROJECT_DIR / "data" / "raw"
RUN_DATE = datetime(2026, 9, 25, tzinfo=UTC)
SECRET_ENV_VARS = (
    "GOOGLE_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENROUTER_API_KEY",
    "CUSTOM_LLM_API_KEY",
    "CUSTOM_LLM_BASE_URL",
    "REFRESH_SOURCE",
    "REFRESH_TEST_SET",
    "RUN_RAGAS",
)


@pytest.fixture(autouse=True)
def offline_mock_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Moi test chay offline voi mock LLM, khong bao gio dung API key that."""
    for name in SECRET_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_MODEL", "mock-model")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    raw_dir = tmp_path / "data" / "raw"
    raw_dir.mkdir(parents=True)
    for name in ("crossref_response.json", "crossref_records.json"):
        shutil.copy(SNAPSHOT_DIR / name, raw_dir / name)
    return load_settings(tmp_path)


@pytest.fixture
def raw_records(settings: Settings):
    return load_raw_records(settings.paths.raw_records_json)


@pytest.fixture
def clean_df(raw_records):
    return build_clean_dataframe(raw_records, RUN_DATE)


def crossref_item(doi: str = "10.1000/test.1", **overrides) -> dict:
    item = {
        "DOI": doi,
        "title": ["  A <i>Sample</i>   Paper Title  "],
        "abstract": "<jats:p>This abstract has   JATS markup &amp; extra   whitespace inside it.</jats:p>",
        "author": [{"given": "Ada", "family": "Lovelace"}, {"name": "Research Consortium"}],
        "subject": ["Computer Science", "Information Retrieval"],
        "published": {"date-parts": [[2026, 7, 1]]},
        "created": {"date-time": "2026-07-02T10:00:00Z"},
        "URL": f"https://doi.org/{doi}",
    }
    item.update(overrides)
    return item
