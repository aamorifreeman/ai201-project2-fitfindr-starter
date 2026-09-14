"""
tools.py

The three required FitFindr tools. Each tool is a standalone function that
can be called and tested independently before being wired into the agent loop.

Tools:
    search_listings(description, size, max_price)  -> list[dict]
    suggest_outfit(new_item, wardrobe)              -> str
    create_fit_card(outfit, new_item)               -> str
"""

import json
import os
import re

from dotenv import load_dotenv
from groq import Groq

from utils.data_loader import load_listings

load_dotenv()

# NOTE: the assignment specifies meta-llama/llama-4-scout-17b-16e-instruct,
# which Groq deprecated in March 2026. Course staff confirmed
# openai/gpt-oss-120b as the working replacement (same fix used in Project 1).
MODEL = "openai/gpt-oss-120b"


# -- Groq client ---------------------------------------------------------------

def _get_groq_client():
    """Initialize and return a Groq client using GROQ_API_KEY from .env."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY not set. Add it to a .env file in the project root."
        )
    return Groq(api_key=api_key)


# -- Tool 1: search_listings -----------------------------------------------------

_WORD_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> set[str]:
    """Lowercase and split into a set of word tokens."""
    return set(_WORD_RE.findall(text.lower()))


def _listing_searchable_text(listing: dict) -> str:
    """Concatenate the fields we score keyword overlap against."""
    parts = [
        listing.get("title", ""),
        listing.get("description", ""),
        listing.get("category", ""),
        " ".join(listing.get("style_tags", []) or []),
        listing.get("brand") or "",
    ]
    return " ".join(parts)


def _size_matches(query_size: str, listing_size: str) -> bool:
    """
    Case-insensitive, token-based size match.

    A listing sized "S/M" is split into tokens {"s", "m"}; a query of "M"
    matches because "m" is one of those tokens. This avoids the false
    positives a raw substring check would produce (e.g. "M" inside "XM").
    """
    query_tokens = _size_tokens(query_size)
    listing_tokens = _size_tokens(listing_size)
    return bool(query_tokens & listing_tokens)


def _size_tokens(size_str: str) -> set[str]:
    return set(re.split(r"[^a-z0-9]+", size_str.lower().strip())) - {""}


def search_listings(
    description: str,
    size: str | None = None,
    max_price: float | None = None,
) -> list[dict]:
    """
    Search the mock listings dataset for items matching the description,
    optional size, and optional price ceiling.

    Args:
        description: Keywords describing what the user is looking for
                     (e.g., "vintage graphic tee").
        size:        Size string to filter by, or None to skip size filtering.
                     Matching is case-insensitive (e.g., "M" matches "S/M").
        max_price:   Maximum price (inclusive), or None to skip price filtering.

    Returns:
        A list of matching listing dicts, sorted by relevance (best match first).
        Returns an empty list if nothing matches -- does NOT raise an exception.

    Each listing dict has the following fields:
        id, title, description, category, style_tags (list), size,
        condition, price (float), colors (list), brand, platform
    """
    listings = load_listings()

    candidates = []
    for listing in listings:
        if max_price is not None and listing["price"] > max_price:
            continue
        if size is not None and not _size_matches(size, listing["size"]):
            continue
        candidates.append(listing)

    query_tokens = _tokenize(description)
    # Require at least 2 overlapping keywords for multi-word queries -- a single
    # shared word (e.g. "vintage" alone) is too weak a signal and was pulling in
    # unrelated categories (a belt, khaki trousers) for a query like
    # "vintage graphic tee." Single-word queries still only need 1 match.
    min_score = 1 if len(query_tokens) <= 1 else 2
    scored = []
    for listing in candidates:
        listing_tokens = _tokenize(_listing_searchable_text(listing))
        score = len(query_tokens & listing_tokens)
        if score >= min_score:
            scored.append((score, listing))

    scored.sort(key=lambda pair: (-pair[0], pair[1]["price"]))
    return [listing for _score, listing in scored]


# -- Tool 2: suggest_outfit -------------------------------------------------------

def _format_wardrobe(wardrobe: dict) -> str:
    lines = []
    for item in wardrobe.get("items", []):
        colors = ", ".join(item.get("colors", []) or [])
        tags = ", ".join(item.get("style_tags", []) or [])
        note = f" ({item['notes']})" if item.get("notes") else ""
        lines.append(f"- {item['name']} [{item['category']}, {colors}, {tags}]{note}")
    return "\n".join(lines)


def _format_trends(trending_styles: list[dict]) -> str:
    return "; ".join(
        f"{t['style_tag']} (trend score {t['trend_score']:.2f})" for t in trending_styles
    )


def suggest_outfit(
    new_item: dict,
    wardrobe: dict,
    trending_styles: list[dict] | None = None,
) -> str:
    """
    Given a thrifted item and the user's wardrobe, suggest 1-2 complete outfits.

    Args:
        new_item: A listing dict (the item the user is considering buying).
        wardrobe: A wardrobe dict with an 'items' key containing a list of
                  wardrobe item dicts. May be empty -- handled gracefully.
        trending_styles: Optional list of trend dicts from get_trending_styles()
                  (stretch feature). When provided and non-empty, the prompt asks
                  the LLM to lean into a trending style tag if it's a natural fit
                  for the item -- when omitted, behavior is identical to the
                  required (non-stretch) version of this tool.

    Returns:
        A non-empty string with outfit suggestions.
        If the wardrobe is empty, offers general styling advice for the item
        rather than raising an exception or returning an empty string.
    """
    items = wardrobe.get("items", []) or []
    item_desc = (
        f"{new_item['title']} -- {new_item['description']} "
        f"(category: {new_item['category']}, colors: {', '.join(new_item.get('colors', []))}, "
        f"style tags: {', '.join(new_item.get('style_tags', []))})"
    )

    trend_line = ""
    if trending_styles:
        trend_line = (
            f"\nCurrently trending styles (from a resale-platform trend snapshot): "
            f"{_format_trends(trending_styles)}. If one of these is a natural fit for "
            "this item, lean into it and mention the vibe -- don't force it if it isn't."
        )

    if not items:
        prompt = (
            "A user is considering buying this secondhand item:\n"
            f"{item_desc}\n"
            f"{trend_line}\n\n"
            "They have not entered a wardrobe yet. Give general styling advice: "
            "what kinds of pieces would pair well with this item, and what overall "
            "vibe or occasions it suits. Keep it to 2-4 sentences, casual tone."
        )
    else:
        wardrobe_text = _format_wardrobe(wardrobe)
        prompt = (
            "A user is considering buying this secondhand item:\n"
            f"{item_desc}\n"
            f"{trend_line}\n\n"
            "Here is their current wardrobe:\n"
            f"{wardrobe_text}\n\n"
            "Suggest 1-2 complete outfit combinations that pair the new item with "
            "specific pieces from their wardrobe above, referring to those pieces "
            "by name. Keep it to 2-4 sentences, casual tone."
        )

    try:
        client = _get_groq_client()
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            # gpt-oss-120b is a reasoning model -- it spends a chunk of max_tokens
            # on hidden reasoning before the visible answer, so this needs real
            # headroom or the response comes back empty (finish_reason="length").
            max_tokens=600,
        )
        text = response.choices[0].message.content.strip()
        return text if text else f"Style this with whatever feels right -- {new_item['title']} works with most casual pieces."
    except Exception:
        return (
            f"Couldn't reach the styling assistant right now -- here's the item on its own: "
            f"{new_item['title']} ({', '.join(new_item.get('style_tags', []))}). Try again in a moment."
        )


# -- Tool 3: create_fit_card ------------------------------------------------------

def create_fit_card(outfit: str, new_item: dict) -> str:
    """
    Generate a short, shareable outfit caption for the thrifted find.

    Args:
        outfit:   The outfit suggestion string from suggest_outfit().
        new_item: The listing dict for the thrifted item.

    Returns:
        A 2-4 sentence string usable as an Instagram/TikTok caption.
        If outfit is empty or missing, returns a descriptive error message
        string -- does NOT raise an exception.
    """
    if not outfit or not outfit.strip():
        return "Can't build a fit card without an outfit -- generate an outfit suggestion first."

    prompt = (
        "Write a short, casual social media caption (2-4 sentences) for an OOTD post "
        "featuring this thrifted item and outfit. Mention the item name, price, and "
        "platform each exactly once, naturally woven in -- not like a product listing. "
        "Capture the specific vibe of the outfit.\n\n"
        f"Item: {new_item['title']} -- ${new_item['price']:.2f} on {new_item['platform']}\n"
        f"Outfit: {outfit}"
    )

    try:
        client = _get_groq_client()
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.9,
            max_tokens=600,  # see suggest_outfit's note on gpt-oss-120b reasoning tokens
        )
        text = response.choices[0].message.content.strip()
        if text:
            return text
        return (
            f"just copped this {new_item['title'].lower()} for ${new_item['price']:.2f} "
            f"off {new_item['platform']} and it's giving exactly what it needed to give"
        )
    except Exception:
        return (
            f"just copped this {new_item['title'].lower()} for ${new_item['price']:.2f} "
            f"off {new_item['platform']} -- full fit details coming soon"
        )


# -- Tool 4 (stretch): estimate_fair_price ----------------------------------------

def estimate_fair_price(item: dict) -> str:
    """
    Estimate whether an item's price is fair, relative to comparable listings
    in the dataset (Price Comparison stretch feature).

    Args:
        item: A listing dict, as returned by search_listings().

    Returns:
        A str verdict with reasoning: how many comparables were found, their
        average price, and whether the item looks like a good deal, fair, or
        priced high relative to that group. If fewer than 2 comparables exist
        even after broadening from "same category + shared style tag" to
        "same category" alone, returns a string saying there isn't enough
        data to compare -- never raises.
    """
    listings = load_listings()
    item_tags = set(item.get("style_tags", []) or [])

    same_category = [
        listing for listing in listings
        if listing["category"] == item["category"] and listing["id"] != item["id"]
    ]
    comparables = [
        listing for listing in same_category
        if item_tags & set(listing.get("style_tags", []) or [])
    ]
    comparison_basis = "category and style"

    if len(comparables) < 2:
        comparables = same_category
        comparison_basis = "category only -- not enough style-tag overlap for a tighter comparison"

    if len(comparables) < 2:
        return (
            f"Not enough comparable listings in the dataset to assess whether "
            f"${item['price']:.2f} for {item['title']} is a fair price."
        )

    avg_price = sum(listing["price"] for listing in comparables) / len(comparables)
    diff_pct = (item["price"] - avg_price) / avg_price

    if diff_pct <= -0.15:
        verdict = "a good deal"
    elif diff_pct >= 0.15:
        verdict = "priced high"
    else:
        verdict = "fairly priced"

    return (
        f"${item['price']:.2f} looks like {verdict} for {item['title']}. "
        f"Based on {len(comparables)} comparable listings ({comparison_basis}), "
        f"the average price is ${avg_price:.2f} "
        f"({diff_pct:+.0%} vs. this item)."
    )


# -- Tool 5 (stretch): get_trending_styles ----------------------------------------

_TRENDS_PATH = os.path.join(os.path.dirname(__file__), "data", "trends.json")


def _load_trends() -> list[dict]:
    with open(_TRENDS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def get_trending_styles(size: str | None = None) -> list[dict]:
    """
    Look up currently "trending" style tags relevant to a given size
    (Trend Awareness stretch feature). Backed by a small mock dataset
    (data/trends.json) representing a snapshot of a resale platform's
    trend data -- see README for why this is mock rather than live data.

    Args:
        size: The size the user searched for, or None to skip size filtering.

    Returns:
        A list[dict] (style_tag, trend_score, note), sorted by trend_score
        descending, capped to the top 5. Never raises -- trends with no size
        restriction always apply, so the list is empty only if the trend
        dataset itself is empty.
    """
    trends = _load_trends()

    if size is not None:
        query_tokens = _size_tokens(size)
        trends = [
            t for t in trends
            if not t.get("size_ranges") or (set(t["size_ranges"]) & query_tokens)
        ]

    trends = sorted(trends, key=lambda t: -t["trend_score"])
    return trends[:5]
