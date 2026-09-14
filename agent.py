"""
agent.py

The FitFindr planning loop. Orchestrates the three tools in response to a
natural language user query, passing state between them via a session dict.

Usage:
    from agent import run_agent
    from utils.data_loader import get_example_wardrobe

    result = run_agent(
        query="vintage graphic tee under $30, size M",
        wardrobe=get_example_wardrobe(),
    )
    print(result["fit_card"])
    print(result["error"])   # None on success
"""

import re

from tools import (
    search_listings,
    suggest_outfit,
    create_fit_card,
    estimate_fair_price,
    get_trending_styles,
)


# -- query parsing ---------------------------------------------------------------

_PRICE_QUALIFIED_RE = re.compile(
    r"(under|below|less than|no more than|max(?:imum)?)\s*\$?\s*(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
_PRICE_FALLBACK_RE = re.compile(r"\$\s*(\d+(?:\.\d+)?)")
_SIZE_RE = re.compile(r"\bsize\s+([a-zA-Z0-9/]+)", re.IGNORECASE)


def parse_query(query: str) -> dict:
    """
    Extract description, size, and max_price from a natural language query
    using regex. This is deterministic and cheap to test, at the cost of
    missing phrasing the patterns don't anticipate (see README for tradeoffs).

    Returns:
        {"description": str, "size": str | None, "max_price": float | None}
    """
    remainder = query
    max_price = None

    qualified = _PRICE_QUALIFIED_RE.search(query)
    if qualified:
        max_price = float(qualified.group(2))
        remainder = remainder.replace(qualified.group(0), "")
    else:
        fallback = _PRICE_FALLBACK_RE.search(query)
        if fallback:
            max_price = float(fallback.group(1))
            remainder = remainder.replace(fallback.group(0), "")

    size = None
    size_match = _SIZE_RE.search(remainder)
    if size_match:
        size = size_match.group(1)
        remainder = remainder.replace(size_match.group(0), "")

    description = re.sub(r"\s+", " ", remainder).strip(" ,.")
    return {"description": description, "size": size, "max_price": max_price}


# -- session state ----------------------------------------------------------------

def _new_session(query: str, wardrobe: dict) -> dict:
    """
    Initialize and return a fresh session dict for one user interaction.

    The session dict is the single source of truth for everything that happens
    during a run -- it stores the original query, parsed parameters, tool results,
    and any error that caused early termination.
    """
    return {
        "query": query,              # original user query
        "parsed": {},                # extracted description / size / max_price
        "search_results": [],        # list of matching listing dicts
        "adjustments": [],           # filters loosened by the retry ladder (stretch)
        "selected_item": None,       # top result, passed into suggest_outfit
        "wardrobe": wardrobe,        # user's wardrobe dict
        "price_assessment": None,    # string returned by estimate_fair_price (stretch)
        "trending_styles": [],       # list returned by get_trending_styles (stretch)
        "outfit_suggestion": None,   # string returned by suggest_outfit
        "fit_card": None,            # string returned by create_fit_card
        "error": None,               # set if the interaction ended early
    }


# -- planning loop ------------------------------------------------------------------

def run_agent(query: str, wardrobe: dict) -> dict:
    """
    Main agent entry point. Runs the FitFindr planning loop for a single
    user interaction and returns the completed session dict.

    Args:
        query:    Natural language user request
                  (e.g., "vintage graphic tee under $30, size M")
        wardrobe: User's wardrobe dict -- use get_example_wardrobe() or
                  get_empty_wardrobe() from utils/data_loader.py

    Returns:
        The session dict after the interaction completes. Check session["error"]
        first -- if it is not None, the interaction ended early and the other
        output fields (outfit_suggestion, fit_card) will be None.
    """
    session = _new_session(query, wardrobe)

    # Step 1: parse the query into structured search parameters.
    session["parsed"] = parse_query(query)
    description = session["parsed"]["description"]
    size = session["parsed"]["size"]
    max_price = session["parsed"]["max_price"]

    # Step 2: search listings.
    session["search_results"] = search_listings(
        description=description, size=size, max_price=max_price
    )

    # Step 3 (stretch -- Retry Logic with Fallback): if nothing matched, retry
    # with progressively loosened constraints. Each rung only fires if the
    # previous attempt is still empty.
    if not session["search_results"] and size is not None:
        session["search_results"] = search_listings(
            description=description, size=None, max_price=max_price
        )
        if session["search_results"]:
            session["adjustments"].append("removing the size filter")

    if not session["search_results"] and max_price is not None:
        session["search_results"] = search_listings(
            description=description, size=None, max_price=None
        )
        if session["search_results"]:
            session["adjustments"].append("removing the price limit")

    # Step 4: branch on the final result, after every retry rung has been
    # exhausted. This is the adaptive part of the planning loop -- on no
    # results, we stop here instead of calling the remaining tools with
    # empty/garbage input.
    if not session["search_results"]:
        filters = []
        if size:
            filters.append(f"size {size}")
        if max_price is not None:
            filters.append(f"under ${max_price:.2f}")
        filter_text = f" ({', '.join(filters)})" if filters else ""
        tried_text = ""
        if session["adjustments"]:
            tried_text = f" Already tried {' and '.join(session['adjustments'])}."
        session["error"] = (
            f"No listings matched \"{description}\"{filter_text}.{tried_text} "
            "Try removing the size filter or raising your price limit."
        )
        return session

    # Step 5: pick the top-ranked match.
    session["selected_item"] = session["search_results"][0]

    # Step 6 (stretch tools): price comparison + trend awareness, both using
    # the selected item / requested size. Neither can fail this loop.
    session["price_assessment"] = estimate_fair_price(session["selected_item"])
    session["trending_styles"] = get_trending_styles(size)

    # Step 7: suggest an outfit using the selected item, wardrobe, and any
    # trending styles relevant to the requested size.
    session["outfit_suggestion"] = suggest_outfit(
        session["selected_item"],
        session["wardrobe"],
        trending_styles=session["trending_styles"],
    )

    # Step 8: build the shareable fit card.
    session["fit_card"] = create_fit_card(
        session["outfit_suggestion"], session["selected_item"]
    )

    # Step 9: done.
    return session


# -- CLI test --------------------------------------------------------------------

if __name__ == "__main__":
    from utils.data_loader import get_example_wardrobe, get_empty_wardrobe

    print("=== Happy path: graphic tee (+ stretch tools) ===\n")
    session = run_agent(
        query="looking for a vintage graphic tee under $30",
        wardrobe=get_example_wardrobe(),
    )
    if session["error"]:
        print(f"Error: {session['error']}")
    else:
        print(f"Found: {session['selected_item']['title']}")
        print(f"\nPrice assessment: {session['price_assessment']}")
        print(f"\nTrending styles considered: {[t['style_tag'] for t in session['trending_styles']]}")
        print(f"\nOutfit: {session['outfit_suggestion']}")
        print(f"\nFit card: {session['fit_card']}")

    print("\n\n=== Retry-with-fallback path: an oddball size ===\n")
    session_retry = run_agent(
        query="vintage graphic tee under $30, size XL",
        wardrobe=get_example_wardrobe(),
    )
    if session_retry["error"]:
        print(f"Error: {session_retry['error']}")
    else:
        print(f"Adjustments made: {session_retry['adjustments']}")
        print(f"Found anyway: {session_retry['selected_item']['title']}")

    print("\n\n=== No-results path (even after retries) ===\n")
    session2 = run_agent(
        query="designer ballgown size XXS under $5",
        wardrobe=get_example_wardrobe(),
    )
    print(f"Error message: {session2['error']}")

    print("\n\n=== Empty wardrobe path ===\n")
    session3 = run_agent(
        query="90s track jacket in size M",
        wardrobe=get_empty_wardrobe(),
    )
    if session3["error"]:
        print(f"Error: {session3['error']}")
    else:
        print(f"Found: {session3['selected_item']['title']}")
        print(f"\nOutfit (empty wardrobe): {session3['outfit_suggestion']}")
        print(f"\nFit card: {session3['fit_card']}")
