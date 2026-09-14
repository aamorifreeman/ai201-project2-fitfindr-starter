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
from tools import search_listings, suggest_outfit, create_fit_card
from utils.data_loader import get_example_wardrobe, get_empty_wardrobe


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
