"""
Tests for tools.py — one test per failure mode plus happy-path coverage.

Run from the repo root:
    python -m pytest tests/
"""

import os

import pytest

from tools import create_fit_card, search_listings, suggest_outfit
from utils.data_loader import get_empty_wardrobe, get_example_wardrobe


needs_groq = pytest.mark.skipif(
    not os.environ.get("GROQ_API_KEY"),
    reason="GROQ_API_KEY not set — skipping LLM-dependent test",
)


# ── search_listings ──────────────────────────────────────────────────────────

def test_search_returns_results():
    results = search_listings("vintage graphic tee", size=None, max_price=50)
    assert isinstance(results, list)
    assert len(results) > 0
    for item in results:
        assert "title" in item
        assert "price" in item


def test_search_empty_results():
    results = search_listings("designer ballgown", size="XXS", max_price=5)
    assert results == []


def test_search_price_filter():
    results = search_listings("jacket", size=None, max_price=10)
    assert all(item["price"] <= 10 for item in results)


def test_search_size_filter_case_insensitive():
    results = search_listings("jacket", size="m", max_price=100)
    assert all("m" in item["size"].lower() for item in results)


def test_search_results_sorted_by_relevance():
    results = search_listings("vintage graphic tee band", size=None, max_price=100)
    assert len(results) >= 2
    top = results[0]
    blob = (
        top["title"].lower()
        + " "
        + " ".join(top["style_tags"]).lower()
    )
    assert "graphic tee" in blob or "band" in blob


# ── suggest_outfit ───────────────────────────────────────────────────────────

def _sample_new_item():
    return {
        "id": "lst_006",
        "title": "Graphic Tee — 2003 Tour Bootleg Style",
        "category": "tops",
        "style_tags": ["graphic tee", "vintage", "grunge", "band tee"],
        "colors": ["black"],
        "price": 24.0,
        "platform": "depop",
    }


@needs_groq
def test_suggest_outfit_with_wardrobe():
    result = suggest_outfit(_sample_new_item(), get_example_wardrobe())
    assert isinstance(result, str)
    assert result.strip() != ""


@needs_groq
def test_suggest_outfit_empty_wardrobe_does_not_crash():
    result = suggest_outfit(_sample_new_item(), get_empty_wardrobe())
    assert isinstance(result, str)
    assert result.strip() != ""


# ── create_fit_card ──────────────────────────────────────────────────────────

def test_create_fit_card_empty_outfit_returns_error_string():
    result = create_fit_card("", _sample_new_item())
    assert isinstance(result, str)
    assert result.strip() != ""
    assert "error" in result.lower() or "cannot" in result.lower()


def test_create_fit_card_whitespace_outfit_returns_error_string():
    result = create_fit_card("   \n  ", _sample_new_item())
    assert isinstance(result, str)
    assert "error" in result.lower() or "cannot" in result.lower()


@needs_groq
def test_create_fit_card_varies_across_calls():
    outfit = (
        "Pair with baggy dark-wash jeans and chunky white sneakers. "
        "Toss the black denim jacket over the top."
    )
    a = create_fit_card(outfit, _sample_new_item())
    b = create_fit_card(outfit, _sample_new_item())
    assert a.strip() != ""
    assert b.strip() != ""
    assert a != b, "captions should vary — bump temperature if this fails"
