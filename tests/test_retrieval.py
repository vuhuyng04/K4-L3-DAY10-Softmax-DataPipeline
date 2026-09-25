from __future__ import annotations

from dataclasses import replace

import pytest

from core.config import normalized_provider, require_llm_credentials
from core.utils import read_json
from retrieval import agent as agent_module
from retrieval.index import LocalEmbeddingIndex
from retrieval.llm import build_llm
from retrieval.qa import answer_question


@pytest.fixture
def index(settings, clean_df):
    return LocalEmbeddingIndex.build(clean_df, settings, settings.paths.embeddings_json)


def test_index_build_persists_portable_manifest(settings, index):
    manifest = read_json(settings.paths.embeddings_json)
    assert manifest["collection_name"] == "papers-baseline"
    assert manifest["persist_path"] == "data/chroma"
    assert len(manifest["documents"]) == 24
    assert index.collection.count() == 24

    loaded = LocalEmbeddingIndex.load(settings)
    assert loaded.persist_path == settings.paths.project_dir / "data" / "chroma"
    assert loaded.search("data observability quality gates", top_k=2)


def test_collections_are_isolated_by_state(settings, clean_df):
    corrupted = LocalEmbeddingIndex.build(clean_df.head(10), settings, settings.paths.corrupted_embeddings_json)
    repaired = LocalEmbeddingIndex.build(clean_df, settings, settings.paths.repaired_embeddings_json)
    assert (corrupted.collection_name, repaired.collection_name) == ("papers-corrupted", "papers-repaired")
    assert corrupted.collection.count() == 10
    assert repaired.collection.count() == 24


def test_answer_question_extracts_from_exact_match(settings, index, clean_df):
    row = clean_df.iloc[3]
    result = answer_question(f"Who authored the paper '{row['title']}'?", settings=settings, index=index)
    assert result.answer == row["authors_joined"]
    assert result.retrieved_doc_ids[0] == row["paper_id"]
    assert len(result.retrieved_doc_ids) == settings.top_k

    date = answer_question(f"When was the paper '{row['title']}' published?", settings=settings, index=index)
    assert date.answer == row["published"]
    categories = answer_question(f"What categories does the paper '{row['title']}' belong to?", settings=settings, index=index)
    assert categories.answer == row["categories_joined"]
    assert index.lookup(row["paper_id"].upper())["title"] == row["title"]
    assert index.lookup("unknown") is None


def test_provider_router(settings):
    assert normalized_provider(replace(settings, llm_provider="Google")) == "gemini"
    assert normalized_provider(replace(settings, llm_provider="anthorpic")) == "anthropic"
    assert normalized_provider(replace(settings, llm_provider="custom-llm")) == "custom"
    assert type(build_llm(settings)).__name__ == "FakeListChatModel"

    openai = replace(settings, llm_provider="openai", model_name="gpt-4o-mini", openai_api_key="test-key")
    assert type(build_llm(openai)).__name__ == "ChatOpenAI"
    anthropic = replace(settings, llm_provider="anthropic", model_name="claude-haiku-4-5", anthropic_api_key="test-key")
    assert type(build_llm(anthropic)).__name__ == "ChatAnthropic"
    gemini = replace(settings, llm_provider="gemini", model_name="gemini-2.5-flash", google_api_key="test-key")
    assert type(build_llm(gemini)).__name__ == "ChatGoogleGenerativeAI"
    ollama = replace(settings, llm_provider="ollama", model_name="llama3")
    assert type(build_llm(ollama)).__name__ == "ChatOllama"
    openrouter = replace(settings, llm_provider="openrouter", model_name="x", openrouter_api_key="test-key")
    assert type(build_llm(openrouter)).__name__ == "ChatOpenAI"
    custom = replace(settings, llm_provider="custom", model_name="x", custom_llm_base_url="http://localhost:9999/v1")
    assert type(build_llm(custom)).__name__ == "ChatOpenAI"

    for provider in ("gemini", "openai", "anthropic", "openrouter", "custom", "unknown"):
        with pytest.raises(RuntimeError):
            require_llm_credentials(replace(settings, llm_provider=provider))


def test_agent_tools_and_runner(settings, index, clean_df, monkeypatch):
    captured = {}

    def fake_create_agent(model, tools, system_prompt, name):
        captured["tools"] = {tool.name: tool for tool in tools}
        return "agent"

    monkeypatch.setattr(agent_module, "create_agent", fake_create_agent)
    assert agent_module.build_agent(settings, index) == "agent"
    search_output = captured["tools"]["semantic_search_papers"].invoke({"query": "freshness SLA", "top_k": 2})
    assert search_output.count("paper_id:") == 2
    row = clean_df.iloc[0]
    assert row["title"] in captured["tools"]["lookup_paper"].invoke({"paper_id_or_title": row["paper_id"]})
    assert captured["tools"]["lookup_paper"].invoke({"paper_id_or_title": "nope"}) == "No exact paper match found."

    class StubAgent:
        def __init__(self, messages):
            self.messages = messages

        def invoke(self, payload):
            return {"messages": self.messages}

    class Message:
        content = "final answer"

    assert agent_module.run_agent_question(StubAgent([Message()]), "q") == "final answer"
    assert agent_module.run_agent_question(StubAgent([]), "q") == ""
