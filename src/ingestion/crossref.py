from __future__ import annotations

from dataclasses import asdict, dataclass
import html
from pathlib import Path
import re
import time
from typing import Any

import requests

from core.config import Settings
from core.utils import normalize_whitespace, read_json, write_json

CROSSREF_WORKS_URL = "https://api.crossref.org/works"
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = 2.0
REQUEST_TIMEOUT_SECONDS = 30
USER_AGENT = "K4-Day10-DataPipeline-Lab/0.1 (educational; mailto:lab@example.com)"

_TAG_PATTERN = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class PaperRecord:
    paper_id: str
    title: str
    summary: str
    authors: list[str]
    categories: list[str]
    primary_category: str
    published: str
    updated: str
    abs_url: str
    pdf_url: str
    comment: str


def strip_markup(value: str | None) -> str:
    """Bo JATS/HTML tag (vd `<jats:p>`), decode HTML entities va gom khoang trang."""
    if not value:
        return ""
    return normalize_whitespace(html.unescape(_TAG_PATTERN.sub(" ", str(value))))


def _first_text(value: Any) -> str:
    if isinstance(value, list):
        value = next((item for item in value if item), "")
    return strip_markup(value)


def _date_from_parts(node: dict | None) -> str:
    if not node:
        return ""
    parts = (node.get("date-parts") or [[]])[0] or []
    if not parts or parts[0] is None:
        return ""
    year = int(parts[0])
    month = int(parts[1]) if len(parts) > 1 and parts[1] else 1
    day = int(parts[2]) if len(parts) > 2 and parts[2] else 1
    return f"{year:04d}-{month:02d}-{day:02d}"


def _published_date(item: dict) -> str:
    for key in ("published", "published-print", "published-online", "issued", "created"):
        value = _date_from_parts(item.get(key))
        if value:
            return value
    return ""


def _updated_date(item: dict, published: str) -> str:
    for key in ("created", "deposited", "indexed"):
        date_time = (item.get(key) or {}).get("date-time")
        if date_time:
            return str(date_time)[:10]
    return published


def _author_names(item: dict) -> list[str]:
    names: list[str] = []
    for author in item.get("author") or []:
        name = normalize_whitespace(" ".join(part for part in (author.get("given"), author.get("family")) if part))
        name = name or normalize_whitespace(author.get("name") or "")
        if name:
            names.append(name)
    return names


def _pdf_url(item: dict, fallback: str) -> str:
    for link in item.get("link") or []:
        url = link.get("URL")
        if url:
            return str(url)
    return fallback


def parse_crossref_payload(payload: dict) -> list[PaperRecord]:
    """Parse Crossref `/works` payload thanh list `PaperRecord`.

    Record thieu DOI, title, abstract hoac ngay xuat ban bi bo qua vi khong dung duoc cho RAG.
    """
    records: list[PaperRecord] = []
    for item in (payload.get("message") or {}).get("items") or []:
        paper_id = normalize_whitespace(item.get("DOI") or "")
        title = _first_text(item.get("title"))
        summary = strip_markup(item.get("abstract"))
        published = _published_date(item)
        if not (paper_id and title and summary and published):
            continue

        categories = [strip_markup(subject) for subject in item.get("subject") or [] if strip_markup(subject)]
        abs_url = str(item.get("URL") or f"https://doi.org/{paper_id}")
        records.append(
            PaperRecord(
                paper_id=paper_id,
                title=title,
                summary=summary,
                authors=_author_names(item),
                categories=categories,
                primary_category=categories[0] if categories else "Uncategorized",
                published=published,
                updated=_updated_date(item, published),
                abs_url=abs_url,
                pdf_url=_pdf_url(item, abs_url),
                comment=f"Crossref record {paper_id}",
            )
        )
    return records


def _request_live_payload(settings: Settings) -> dict:
    params = {
        "query": settings.source_query,
        "filter": settings.source_filter,
        "rows": settings.max_results,
    }
    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = requests.get(
                CROSSREF_WORKS_URL,
                params=params,
                headers={"User-Agent": USER_AGENT},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            if response.status_code in RETRYABLE_STATUS_CODES:
                raise requests.HTTPError(f"Crossref returned HTTP {response.status_code}", response=response)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            if attempt < MAX_ATTEMPTS:
                wait = BACKOFF_SECONDS * (2 ** (attempt - 1))
                print(f"[ingestion] Crossref attempt {attempt}/{MAX_ATTEMPTS} failed ({exc}); retry in {wait:.0f}s")
                time.sleep(wait)
    raise RuntimeError(f"Crossref API unavailable after {MAX_ATTEMPTS} attempts: {last_error}")


def fetch_source_records(settings: Settings) -> list[PaperRecord]:
    """Lay records tu Crossref (live) hoac snapshot offline, luu raw artifacts de giu lineage.

    - Mac dinh (offline/dev mode): doc snapshot `data/raw/crossref_response.json`, khong ghi de raw goc.
    - `REFRESH_SOURCE=1` (live mode): goi Crossref API co retry/backoff cho 429/5xx; that bai thi fallback snapshot.
    """
    paths = settings.paths
    payload: dict | None = None

    if settings.refresh_source:
        try:
            payload = _request_live_payload(settings)
            write_json(paths.raw_api_response, payload)
            print(f"[ingestion] Live mode: saved Crossref response to {paths.raw_api_response.name}")
        except RuntimeError as exc:
            print(f"[ingestion] {exc}. Falling back to local snapshot.")

    if payload is None:
        if not paths.raw_api_response.exists():
            raise FileNotFoundError(
                f"Offline snapshot not found at {paths.raw_api_response}. Set REFRESH_SOURCE=1 to fetch live data."
            )
        payload = read_json(paths.raw_api_response)

    records = parse_crossref_payload(payload)
    write_json(paths.raw_records_json, [asdict(record) for record in records])
    return records


def load_raw_records(path: Path) -> list[PaperRecord]:
    """Doc `crossref_records.json` va map lai thanh `PaperRecord`."""
    fields = PaperRecord.__dataclass_fields__.keys()
    return [PaperRecord(**{key: item.get(key) for key in fields}) for item in read_json(Path(path))]
