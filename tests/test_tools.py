"""
tests/test_tools.py

Tests for the three FitFindr tools, including their documented failure modes.

Run with:
    python -m pytest tests/

LLM-backed tools (suggest_outfit, create_fit_card) are tested against a fake
Groq client so the suite is fast, deterministic, and doesn't depend on network
access or a valid API key -- except for the "LLM call raises" tests, which
exist specifically to prove the fallback path works without ever hitting the
network on success.
"""

from types import SimpleNamespace

import tools
from tools import (
    search_listings,
    suggest_outfit,
    create_fit_card,
    estimate_fair_price,
    get_trending_styles,
)
from utils.data_loader import get_example_wardrobe, get_empty_wardrobe
import agent
import style_memory


# -- fakes for the Groq client ----------------------------------------------------

class _FakeResponse:
    def __init__(self, text):
        self.choices = [SimpleNamespace(message=SimpleNamespace(content=text))]


class _FakeChatCompletions:
    def __init__(self, text):
        self._text = text

    def create(self, **kwargs):
        return _FakeResponse(self._text)


class _FakeClient:
    def __init__(self, text):
        self.chat = SimpleNamespace(completions=_FakeChatCompletions(text))


def _fake_client_returning(text):
    return lambda: _FakeClient(text)


def _raising_client():
    raise RuntimeError("simulated network failure")


# -- Tool 1: search_listings -------------------------------------------------------

def test_search_returns_results():
    results = search_listings("vintage graphic tee", size=None, max_price=50)
    assert isinstance(results, list)
    assert len(results) > 0


def test_search_empty_results():
    results = search_listings("designer ballgown", size="XXS", max_price=5)
    assert results == []  # empty list, no exception


def test_search_price_filter():
    results = search_listings("jacket", size=None, max_price=10)
    assert all(item["price"] <= 10 for item in results)


def test_search_size_filter_matches_slash_size():
    # "S/M" listings should match a query for size "M".
    results = search_listings("y2k tee", size="M", max_price=None)
    assert isinstance(results, list)
    assert all("m" in tools._size_tokens(item["size"]) for item in results)


# -- Tool 2: suggest_outfit ---------------------------------------------------------

def test_suggest_outfit_empty_wardrobe_returns_nonempty_string(monkeypatch):
    monkeypatch.setattr(
        tools, "_get_groq_client", _fake_client_returning("General styling advice here.")
    )
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    result = suggest_outfit(item, get_empty_wardrobe())
    assert isinstance(result, str)
    assert result.strip() != ""


def test_suggest_outfit_with_wardrobe_returns_nonempty_string(monkeypatch):
    monkeypatch.setattr(
        tools, "_get_groq_client", _fake_client_returning("Pair it with your jeans and sneakers.")
    )
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    result = suggest_outfit(item, get_example_wardrobe())
    assert isinstance(result, str)
    assert result.strip() != ""


def test_suggest_outfit_llm_failure_returns_fallback_not_exception(monkeypatch):
    monkeypatch.setattr(tools, "_get_groq_client", _raising_client)
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    result = suggest_outfit(item, get_example_wardrobe())
    assert isinstance(result, str)
    assert result.strip() != ""
    assert item["title"] in result


# -- Tool 3: create_fit_card ---------------------------------------------------------

def test_create_fit_card_empty_outfit_returns_error_string_not_exception():
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    result = create_fit_card("", item)
    assert isinstance(result, str)
    assert "outfit" in result.lower()


def test_create_fit_card_whitespace_outfit_returns_error_string():
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    result = create_fit_card("   ", item)
    assert isinstance(result, str)
    assert "outfit" in result.lower()


def test_create_fit_card_success_returns_nonempty_string(monkeypatch):
    monkeypatch.setattr(
        tools, "_get_groq_client", _fake_client_returning("thrifted this and it's giving everything")
    )
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    result = create_fit_card("Pair it with jeans and sneakers.", item)
    assert isinstance(result, str)
    assert result.strip() != ""


def test_create_fit_card_llm_failure_returns_fallback_not_exception(monkeypatch):
    monkeypatch.setattr(tools, "_get_groq_client", _raising_client)
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    result = create_fit_card("Pair it with jeans and sneakers.", item)
    assert isinstance(result, str)
    assert result.strip() != ""
    assert item["platform"] in result


# -- Tool 4 (stretch): estimate_fair_price -------------------------------------------

def test_estimate_fair_price_returns_verdict_with_reasoning():
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    result = estimate_fair_price(item)
    assert isinstance(result, str)
    assert "$" in result
    assert "comparable" in result.lower()


def test_estimate_fair_price_insufficient_comparables_returns_message_not_exception():
    lonely_item = {
        "id": "zzz_unique",
        "title": "One-of-a-kind item",
        "description": "nothing else like it",
        "category": "nonexistent-category",
        "style_tags": ["nonexistent-tag"],
        "size": "M",
        "condition": "good",
        "price": 40.0,
        "colors": [],
        "brand": None,
        "platform": "depop",
    }
    result = estimate_fair_price(lonely_item)
    assert isinstance(result, str)
    assert "not enough" in result.lower()


# -- Tool 5 (stretch): get_trending_styles -------------------------------------------

def test_get_trending_styles_returns_sorted_list():
    trends = get_trending_styles(size=None)
    assert isinstance(trends, list)
    assert len(trends) > 0
    scores = [t["trend_score"] for t in trends]
    assert scores == sorted(scores, reverse=True)


def test_get_trending_styles_filters_by_size_without_raising():
    trends = get_trending_styles(size="xl")
    assert isinstance(trends, list)  # never raises, even if the list is short


def test_suggest_outfit_uses_trending_styles_when_provided(monkeypatch):
    captured_prompts = []

    def _capturing_factory():
        class _Client:
            class chat:
                class completions:
                    @staticmethod
                    def create(**kwargs):
                        captured_prompts.append(kwargs["messages"][0]["content"])
                        return _FakeResponse("styled suggestion")
        return _Client()

    monkeypatch.setattr(tools, "_get_groq_client", _capturing_factory)
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    trends = [{"style_tag": "y2k", "trend_score": 0.9, "note": "trending hard"}]
    suggest_outfit(item, get_example_wardrobe(), trending_styles=trends)
    assert any("y2k" in p.lower() for p in captured_prompts)


# -- Retry Logic with Fallback (stretch) ---------------------------------------------

def test_run_agent_retries_with_size_dropped_when_size_has_no_matches():
    # "XL" matches no vintage graphic tees in the dataset, but dropping the
    # size filter should surface results and record the adjustment.
    session = agent.run_agent(
        query="vintage graphic tee under $30, size XL",
        wardrobe=get_example_wardrobe(),
    )
    assert session["error"] is None
    assert "removing the size filter" in session["adjustments"]
    assert session["selected_item"] is not None


def test_run_agent_still_errors_when_no_retry_rung_finds_anything():
    session = agent.run_agent(
        query="designer ballgown size XXS under $5",
        wardrobe=get_example_wardrobe(),
    )
    assert session["error"] is not None
    assert session["fit_card"] is None


# -- Style Profile Memory (stretch) --------------------------------------------------

def test_style_profile_round_trip(tmp_path, monkeypatch):
    fake_path = tmp_path / "style_profile.json"
    monkeypatch.setattr(style_memory, "_PROFILE_PATH", str(fake_path))

    assert style_memory.load_style_profile() is None

    wardrobe = get_example_wardrobe()
    style_memory.save_style_profile(wardrobe)

    loaded = style_memory.load_style_profile()
    assert loaded == wardrobe


def test_style_profile_does_not_save_empty_wardrobe(tmp_path, monkeypatch):
    fake_path = tmp_path / "style_profile.json"
    monkeypatch.setattr(style_memory, "_PROFILE_PATH", str(fake_path))

    style_memory.save_style_profile(get_empty_wardrobe())
    assert style_memory.load_style_profile() is None
