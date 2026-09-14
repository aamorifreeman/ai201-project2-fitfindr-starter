# FitFindr

A multi-tool AI agent that helps you find secondhand pieces and figure out how to style them. Give it a natural-language request — "vintage graphic tee under $30, size M" — and it searches a mock listings dataset, suggests an outfit using your existing wardrobe, and writes a shareable caption for the find, deciding on its own what to do when a step comes back empty. All 4 stretch features are implemented too: a price-fairness check, currently-trending styles that visibly shape the outfit suggestion, a remembered style profile across sessions, and automatic retry with loosened filters when a search comes up empty.

Built for CodePath AI201, Project 2.

**Demo video:** _[add your recorded demo link here before submitting]_

---

## Setup

**macOS / Linux:**
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Windows:**
```bash
python -m venv .venv
source .venv/Scripts/activate
pip install -r requirements.txt
```

Set your Groq API key in a `.env` file (same key from Project 1):
```
GROQ_API_KEY=your_key_here
```

Run the app:
```bash
python app.py
```
Then open the URL printed in your terminal (usually `http://localhost:7860`).

Run the tests:
```bash
python -m pytest tests/
```

Run the agent from the CLI (happy path with stretch tools, retry-with-fallback path, no-results path, and empty-wardrobe path):
```bash
python agent.py
```

---

## Tool Inventory

### `search_listings(description: str, size: str | None = None, max_price: float | None = None) -> list[dict]`

Searches the 40-item mock listings dataset. `description` is free-text keywords scored against each listing's title, description, category, style tags, and brand — a listing must share at least 2 overlapping keywords to be returned for a multi-word query (1 is enough for a single-word query), since requiring just 1 shared word let unrelated items through on nothing but common words like "vintage." `size` is optional and matched case-insensitively at the token level (a query of `"M"` matches a listing sized `"S/M"` because the listing's size string is split into tokens and checked for an exact token match, not a raw substring). `max_price` is an optional inclusive ceiling.

Returns a list of full listing dicts (`id`, `title`, `description`, `category`, `style_tags`, `size`, `condition`, `price`, `colors`, `brand`, `platform`), sorted by keyword-overlap score (best match first), with price as a tiebreaker. Returns `[]` — never raises — if nothing matches.

### `suggest_outfit(new_item: dict, wardrobe: dict) -> str`

Given a listing dict and a wardrobe dict (`{"items": [...]}`), asks the LLM for 1–2 outfit combinations. If the wardrobe has items, the prompt includes each item's name, category, colors, and style tags, and the LLM is asked to reference specific pieces by name. If `wardrobe["items"]` is empty, the prompt switches to general styling advice for the item on its own — this is not treated as a failure.

Always returns a non-empty string. If the Groq call itself raises, the exception is caught and a fallback string naming the item is returned instead of propagating.

### `create_fit_card(outfit: str, new_item: dict) -> str`

Given an outfit suggestion string and the listing dict, asks the LLM for a 2–4 sentence casual social-caption mentioning the item name, price, and platform once each, in the voice of a real OOTD post rather than a product description. Uses `temperature=0.9` so repeated calls on identical input vary in phrasing (verified — see Error Handling below and the demo).

If `outfit` is empty or whitespace-only, returns a descriptive error string (`"Can't build a fit card without an outfit -- generate an outfit suggestion first."`) without calling the LLM at all. If the Groq call raises, a fallback caption built from `new_item` alone is returned.

### `estimate_fair_price(item: dict) -> str` (stretch — Price Comparison Tool)

Finds "comparable" listings elsewhere in the dataset — same `category`, sharing at least one `style_tags` entry — computes their average price, and classifies the item as a good deal (>15% below average), fair (within ±15%), or priced high (>15% above), stating the comparable count and average in the returned string. Falls back to "same category only" if fewer than 2 style-matched comparables exist, and returns a plain "not enough data" string (no exception) if even that yields fewer than 2.

### `get_trending_styles(size: str | None = None) -> list[dict]` (stretch — Trend Awareness Tool)

Looks up currently "trending" style tags relevant to a given size from `data/trends.json`, sorted by trend score, capped to 5. Never raises. Passed into `suggest_outfit` as its optional `trending_styles` parameter so the outfit prompt can lean into a trend when it's a natural fit.

---

## Interaction Walkthrough

**User query:** `"vintage graphic tee under $30, size M"`

**Step 1 — Tool called:** `search_listings`
- Input: `description="vintage graphic tee", size="M", max_price=30.0`
- Why this tool: it's always the first call — nothing else can run until there's a candidate item.
- Output: a ranked list of matching listings; top result was **Y2K Baby Tee — Butterfly Print, $18.00, Depop, size S/M, excellent condition**.

**Step 2 — Tool called:** `suggest_outfit`
- Input: `new_item=<Y2K Baby Tee dict>, wardrobe=<example wardrobe>`
- Why this tool: `search_results` was non-empty, so the loop stores the top result as `selected_item` and proceeds — it does not stop here.
- Output (real output from a test run): *"Outfit 1 – Y2K vibes + street-ready: Slip the Y2K Baby Tee (size-up, so it's a cute cropped fit) into your baggy straight-leg jeans, dark wash, and cinch the waist with the brown leather belt for a little shape. Layer the vintage black denim jacket over the top, and finish with the chunky white sneakers and your black crossbody bag for a playful, early-2000s-meets-street look."*

**Step 3 — Tool called:** `create_fit_card`
- Input: `outfit=<outfit text above>, new_item=<Y2K Baby Tee dict>`
- Why this tool: `outfit_suggestion` was non-empty, so the loop proceeds to the final step.
- Output (real output from a test run): *"Channeling early-2000s street vibes with this butterfly-print Y2K Baby Tee — Butterfly Print. I snagged it for $18.00 on Depop and it's already a staple. Cropped into baggy straight-leg jeans, cinched with a brown leather belt, topped with a vintage black denim jacket, and finished off with chunky white sneakers and my black crossbody."*

**Final output to user:** three panels — the listing found, the outfit idea (referencing four real wardrobe items by name), and a ready-to-post fit card — with zero re-entry of the item or outfit at any step.

---

## Planning Loop

The loop is a fixed sequence of stages gated by explicit branches, not a fixed sequence of tool calls run unconditionally:

1. Parse the query into `description`, `size`, `max_price` with regex (see `agent.py::parse_query`).
2. Call `search_listings` with the parsed parameters.
3. **Retry-with-fallback (stretch):** if empty and a `size` was given, retry with `size=None`; if still empty and a `max_price` was given, retry again with both dropped. Each rung records what it loosened in `session["adjustments"]` and only fires if the previous attempt is still empty.
4. **Branch:** if `search_results` is still empty after every retry rung, set `session["error"]` to a specific message (naming the search terms, filters, and what was already tried) and return immediately — `suggest_outfit`, `create_fit_card`, and both stretch tools are never called on this path.
5. If results exist, take the top-ranked item as `selected_item`.
6. Call the stretch tools: `estimate_fair_price(selected_item)` and `get_trending_styles(size)`.
7. Call `suggest_outfit(selected_item, wardrobe, trending_styles=...)`.
8. Call `create_fit_card(outfit_suggestion, selected_item)`.
9. Return the session.

This is the adaptive behavior graded here: a query like `"designer ballgown size XXS under $5"` stops after step 4 with an error message and empty output panels, a query with a real but oddball size (`"...size XL"`) recovers via the retry ladder instead of failing outright, and a normal query runs the full pipeline. The agent's behavior visibly differs based on what the first tool returns — it doesn't call every tool in the same order regardless of context.

---

## State Management

A single `session` dict, created fresh per call to `run_agent()`, is threaded through every step by reference:

- `session["parsed"]` is set once after query parsing and read by `search_listings`.
- `session["selected_item"]` is set to the *exact dict object* returned inside `search_results[0]` — not a re-typed copy — so `suggest_outfit` receives the real listing data with nothing re-entered by the user.
- `session["adjustments"]` — a list of strings recording what the retry ladder loosened (e.g. `["removing the size filter"]`); empty if the first search already succeeded. `app.py` prefixes the listing panel with a note when non-empty.
- `session["price_assessment"]` and `session["trending_styles"]` — set right after `selected_item` is known; `trending_styles` also flows into `suggest_outfit` as its optional argument.
- `session["outfit_suggestion"]` is set after `suggest_outfit` runs and is read directly by `create_fit_card`.
- `session["fit_card"]` holds the final output.
- `session["error"]` stays `None` on a full run; when set, `outfit_suggestion` and `fit_card` stay `None`, which is how `app.py` tells a failed run from a successful one.

The `session` dict itself lives only for one `run_agent()` call. **Style Profile Memory (stretch)** is the one piece of state that survives across separate runs of the app: `style_memory.py` persists whatever wardrobe was used to a local `style_profile.json` file, and a later run can select "Saved profile (remembered)" to load it back with no re-entry.

---

## Error Handling

| Tool | Failure mode | Agent response |
|------|-------------|-----------------|
| `search_listings` | No results match the query, even after the retry ladder | Returns `[]` on each attempt. The planning loop tries retries first (see Planning Loop), then sets a specific error naming the search terms, filters, and what was already tried (e.g., *"No listings matched "designer ballgown" (size XXS, under $5.00). Try removing the size filter or raising your price limit."*) and returns immediately without calling the remaining tools. Verified live: querying `"designer ballgown size XXS under $5"` in the running app leaves every other panel empty and shows exactly that message. |
| `search_listings` | No results on the *first* try, but a retry with a loosened filter succeeds (stretch — Retry Logic with Fallback) | Not treated as a failure. Verified live: querying `"vintage graphic tee under $30, size XL"` (no listing in the dataset is actually sized XL) returns the Y2K Baby Tee anyway, with the listing panel prefixed *"(Note: no exact match for your filters -- showing results after removing the size filter.)"* |
| `suggest_outfit` | Wardrobe is empty | Not treated as a failure — the tool switches to a general-styling prompt and still returns a useful string. Verified: querying `"chunky white sneakers under $60"` with "Empty wardrobe (new user)" selected returns general styling advice with no wardrobe items referenced, instead of crashing or returning an empty panel. If the Groq call itself raises, the exception is caught and a fallback string naming the item is returned. |
| `create_fit_card` | Outfit input is empty/whitespace | Returns a descriptive error string without calling the LLM (`"Can't build a fit card without an outfit -- generate an outfit suggestion first."`) — covered by `tests/test_tools.py::test_create_fit_card_empty_outfit_returns_error_string_not_exception`. If the Groq call raises, a fallback caption built from item fields alone is returned instead of an exception — covered by `test_create_fit_card_llm_failure_returns_fallback_not_exception`. |
| `estimate_fair_price` | Fewer than 2 comparable listings, even after broadening from "category + style tag" to "category only" | Returns a plain string stating there isn't enough data to compare, instead of a verdict built on 0–1 data points — covered by `test_estimate_fair_price_insufficient_comparables_returns_message_not_exception`. |

---

## Stretch Features

All 4 stretch features (7 possible points) are implemented and verified live in the running app.

### Price Comparison Tool (+2)
**How comparisons are made:** "comparable" = same `category` plus at least one shared `style_tags` entry (falling back to same-category-only if fewer than 2 style-matched comparables exist). The mean price of that group is computed and the item is classified good-deal / fair / priced-high at a ±15% threshold. Verified live: searching `"vintage graphic tee under $30"` returned *"$18.00 looks like a good deal for Y2K Baby Tee — Butterfly Print. Based on 14 comparable listings (category and style), the average price is $22.00 (-18% vs. this item)."*

### Style Profile Memory (+2)
**Storage approach:** a flat JSON file (`style_profile.json`, gitignored — runtime user state, not codebase) via `style_memory.py`'s `save_style_profile()` / `load_style_profile()`. `app.py` adds a third wardrobe option, "Saved profile (remembered)"; selecting "Example wardrobe" auto-saves it. Verified live across two separate interactions: interaction 1 ran with "Example wardrobe" selected; interaction 2 selected "Saved profile (remembered)" with no wardrobe re-entry, and the outfit suggestion still referenced the same wardrobe pieces (baggy jeans, black cropped zip hoodie, chunky white sneakers, black crossbody bag) — proving the wardrobe was loaded from disk, not re-specified.

### Trend Awareness Tool (+2)
**Data source:** this project runs entirely on mock data (the 40-listing dataset, the wardrobe schema) with no external API beyond Groq for generation, and the assignment's setup promises "no new accounts or credits required" — building a real platform scraper would be out of scope and inconsistent with that. `data/trends.json` is a small hand-authored mock dataset (8 style tags with a trend score, optional size restriction, and a "why it's trending" note) standing in for what a real trend-scraping tool would return, the same mocking pattern the assignment already uses elsewhere. **Visible influence:** `get_trending_styles(size)` result is passed into `suggest_outfit`'s prompt. Verified live: with `#streetwear` and `#y2k` among the top trends for the searched size, the outfit suggestions explicitly said *"for that streetwear edge"* and *"Y2K street-vibe"* — wording that changes based on what's trending, not fixed boilerplate.

### Retry Logic with Fallback (+1)
When `search_listings` returns empty, the loop retries once with the size filter dropped, then again with the price ceiling also dropped if still empty — never retrying a rung that isn't needed. Verified live: `"vintage graphic tee under $30, size XL"` (no tee in the dataset is actually sized XL) returned the Y2K Baby Tee anyway, with the panel showing *"(Note: no exact match for your filters -- showing results after removing the size filter.)"*

---

## Spec Reflection

**One way the spec helped:** Writing out the exact planning-loop branches in `planning.md` before touching code (step 3's "if results is empty, set error and return early") made the implementation almost mechanical — `agent.py::run_agent` is close to a direct transcription of that section. It also made the no-results test case obvious to write before any code existed, since the spec already said what the failure path had to look like.

**One divergence, and why:** The assignment and starter `README.md` specify `meta-llama/llama-4-scout-17b-16e-instruct` as the model. Groq deprecated that model in March 2026 — calling it returns a `404 model_not_found`. Course staff confirmed `openai/gpt-oss-120b` as the replacement (I'd already hit and resolved this same issue in Project 1). A second divergence surfaced while integrating it: `gpt-oss-120b` is a reasoning model that spends part of its `max_tokens` budget on hidden reasoning tokens before the visible answer — at `max_tokens=200` (a reasonable-looking default), responses came back completely empty (`finish_reason="length"`, 198/200 tokens spent on reasoning). Raising the budget to `600` fixed it. Both are documented as comments in `tools.py`.

**A third divergence, caught while building the stretch features:** while picking a demo query for the Retry Logic stretch feature, I noticed `search_listings("vintage graphic tee", ...)` was returning belts, khaki trousers, and a silk dress alongside actual tees — all pulled in because they shared just the single word "vintage" with the query. The original scoring only required `score > 0` (any keyword overlap at all). I tightened it to require at least 2 overlapping keywords for multi-word queries (single-word queries still only need 1), which is now documented as a comment directly above the filter in `tools.py`. This wasn't in the original plan — it surfaced from actually trying to build a clean stretch-feature demo, not from re-reading the spec.

---

## AI Usage Transparency

1. **`search_listings` and the size-matching logic:** I gave Claude the Tool 1 spec block from `planning.md` (exact parameters, return value, the failure mode) and the note that a query of `"M"` should match a listing sized `"S/M"`. Its first draft matched sizes with a raw substring check (`size.lower() in listing_size.lower()`), which I overrode after noticing it would also match `"M"` against a hypothetical size like `"XM"` — a false positive raw substring matching would allow. I asked it to switch to token-based matching instead (`_size_tokens`, splitting on non-alphanumeric characters and comparing sets), which is what's in `tools.py` now.

2. **The empty-response bug on `gpt-oss-120b`:** When `suggest_outfit` and `create_fit_card` started returning the "LLM unreachable" fallback string on every call despite a working API key, I used Claude to debug it by inspecting the raw Groq response object rather than guessing — it added a debug script printing `finish_reason` and `usage.completion_tokens_details`, which surfaced `reasoning_tokens: 198` out of a `max_tokens=200` budget. I reviewed that output myself before accepting the fix (raising `max_tokens` to 600) rather than taking the diagnosis on faith — I re-ran the debug script at a couple of different token budgets to confirm 600 was comfortably above what reasoning was consuming, not just barely enough.

3. **The search-relevance bug found while building stretch features:** while setting up a demo query for the Retry Logic stretch feature, Claude noticed `search_listings("vintage graphic tee", ...)` was returning a belt and khaki trousers alongside real tees. Rather than just patching the specific symptom, it printed the full result set with each listing's matched tokens to confirm the root cause (any single shared word was enough to pass the old `score > 0` filter), then proposed requiring 2+ overlapping keywords for multi-word queries. I reviewed the before/after result sets myself for three different queries before accepting the change, to make sure the tightened threshold didn't also start dropping genuinely relevant results.
