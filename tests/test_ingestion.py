from __future__ import annotations

from dataclasses import asdict, replace

import pytest
import requests

from core.utils import read_json
from ingestion import crossref
from ingestion.crossref import fetch_source_records, load_raw_records, parse_crossref_payload, strip_markup
from tests.conftest import crossref_item


def test_parse_crossref_payload_normalizes_fields():
    payload = {"message": {"items": [crossref_item(link=[{"URL": "https://example.org/paper.pdf"}])]}}
    [record] = parse_crossref_payload(payload)
    assert record.paper_id == "10.1000/test.1"
    assert record.title == "A Sample Paper Title"
    assert record.summary == "This abstract has JATS markup & extra whitespace inside it."
    assert record.authors == ["Ada Lovelace", "Research Consortium"]
    assert record.categories == ["Computer Science", "Information Retrieval"]
    assert record.primary_category == "Computer Science"
    assert record.published == "2026-07-01"
    assert record.updated == "2026-07-02"
    assert record.pdf_url == "https://example.org/paper.pdf"
    assert record.comment == "Crossref record 10.1000/test.1"


def test_parse_crossref_payload_skips_invalid_and_uses_fallbacks():
    items = [
        crossref_item("10.1000/no-abstract", abstract=None),
        crossref_item("10.1000/no-title", title=[]),
        crossref_item("10.1000/no-date", published=None, created=None),
        crossref_item(
            "10.1000/partial-date",
            published=None,
            **{"published-online": {"date-parts": [[2025, 3]]}},
            subject=[],
            URL=None,
            created=None,
        ),
    ]
    records = parse_crossref_payload({"message": {"items": items}})
    assert [record.paper_id for record in records] == ["10.1000/partial-date"]
    record = records[0]
    assert record.published == "2025-03-01"
    assert record.updated == "2025-03-01"
    assert record.primary_category == "Uncategorized"
    assert record.abs_url == "https://doi.org/10.1000/partial-date"
    assert parse_crossref_payload({}) == []


def test_strip_markup_handles_empty_values():
    assert strip_markup(None) == ""
    assert strip_markup("<jats:title>Hi</jats:title>&lt;tag&gt;") == "Hi <tag>"


def test_offline_fetch_reads_snapshot_and_preserves_lineage(settings):
    original = settings.paths.raw_api_response.read_bytes()
    records = fetch_source_records(settings)
    assert len(records) == 24
    assert settings.paths.raw_api_response.read_bytes() == original
    assert read_json(settings.paths.raw_records_json) == [asdict(record) for record in records]


def test_load_raw_records_roundtrip(settings):
    records = load_raw_records(settings.paths.raw_records_json)
    assert len(records) == 24
    assert records[0].paper_id.startswith("10.1145/")


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self) -> dict:
        return self._payload


def test_live_fetch_saves_raw_response(settings, monkeypatch):
    payload = {"status": "ok", "message": {"items": [crossref_item()]}}
    calls = []

    def fake_get(url, params, headers, timeout):
        calls.append(params)
        return _FakeResponse(200, payload)

    monkeypatch.setattr(crossref.requests, "get", fake_get)
    live = replace(settings, refresh_source=True)
    records = fetch_source_records(live)
    assert len(records) == 1
    assert read_json(settings.paths.raw_api_response) == payload
    assert calls[0]["rows"] == settings.max_results
    assert calls[0]["filter"] == settings.source_filter


def test_live_fetch_retries_then_falls_back_to_snapshot(settings, monkeypatch):
    attempts = []
    monkeypatch.setattr(crossref.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(crossref.requests, "get", lambda *args, **kwargs: attempts.append(1) or _FakeResponse(429))
    records = fetch_source_records(replace(settings, refresh_source=True))
    assert len(attempts) == crossref.MAX_ATTEMPTS
    assert len(records) == 24


def test_missing_snapshot_raises(settings):
    settings.paths.raw_api_response.unlink()
    with pytest.raises(FileNotFoundError):
        fetch_source_records(settings)
