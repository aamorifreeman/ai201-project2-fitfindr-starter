# FitFindr — planning.md

> Complete this document before writing any implementation code.
> Your spec and agent diagram are what you'll use to direct AI tools (Claude, Copilot, etc.) to generate your implementation — the more specific they are, the more useful the generated code will be.
> Your planning.md will be reviewed as part of your submission.
> Update it before starting any stretch features.

---

## Tools

List every tool your agent will use. For each tool, fill in all four fields.
You must have at least 3 tools. The three required tools are listed — add any additional tools below them.

### Tool 1: search_listings

**What it does:**
Searches the 40-item mock listings dataset for items whose title, description, category, style tags, and brand overlap with the user's description keywords, then filters by size and max price.

**Input parameters:**
- `description` (str): Free-text keywords describing what the user wants (e.g., "vintage graphic tee"). Tokenized and matched against each listing's searchable text.
- `size` (str | None): Size string to filter by, or `None` to skip size filtering. Matching is case-insensitive and token-based — a query of `"M"` matches a listing sized `"S/M"` because the listing's size string is split into tokens (`"s"`, `"m"`) and checked for an exact token match, not a raw substring, so `"M"` does not incorrectly match `"XM"`-style tokens.
- `max_price` (float | None): Maximum price (inclusive), or `None` to skip price filtering.

**What it returns:**
A `list[dict]`, each dict a full listing record (`id`, `title`, `description`, `category`, `style_tags`, `size`, `condition`, `price`, `colors`, `brand`, `platform`), sorted by relevance score (keyword overlap count) descending, with price ascending as a tiebreaker. Listings scoring 0 keyword overlap are dropped entirely, even if they pass the size/price filters — a size-M listing with zero relevance to "vintage graphic tee" should not be returned.

**What happens if it fails or returns nothing:**
Returns `[]` — never raises. The planning loop checks for this exact case, sets `session["error"]` to a specific, actionable message naming what was searched and what to loosen (e.g., remove the size filter, raise the price ceiling), and returns immediately without calling `suggest_outfit` or `create_fit_card`.

---

### Tool 2: suggest_outfit

**What it does:**
Given a specific thrifted item and the user's current wardrobe, asks the LLM to suggest one or two complete outfit combinations that pair the new item with pieces the user already owns (or, if the wardrobe is empty, general styling guidance for the item on its own).

**Input parameters:**
- `new_item` (dict): A listing dict, as returned by `search_listings` — the item under consideration.
- `wardrobe` (dict): A wardrobe dict with an `items` key holding a list of wardrobe item dicts (`id`, `name`, `category`, `colors`, `style_tags`, `notes`). `items` may be empty.

**What it returns:**
A non-empty `str` containing 1–2 outfit suggestions in natural language, referencing specific wardrobe items by name when the wardrobe is non-empty, or general style/vibe guidance when it is empty.

**What happens if it fails or returns nothing:**
If `wardrobe["items"]` is empty, the tool does not treat this as a failure — it switches prompts and asks the LLM for general styling advice for the item alone, still returning a useful non-empty string. If the Groq API call itself raises (network error, bad key, rate limit), the exception is caught inside the tool and a specific fallback string is returned (e.g., `"Couldn't reach the styling assistant right now — here's the item on its own: <title>. Try again in a moment."`) rather than propagating the exception up through the planning loop.

---

### Tool 3: create_fit_card

**What it does:**
Turns an outfit suggestion and the thrifted item into a short, casual, shareable caption — the kind of text someone would post alongside an OOTD photo.

**Input parameters:**
- `outfit` (str): The outfit suggestion string produced by `suggest_outfit`.
- `new_item` (dict): The listing dict for the thrifted item (used for name, price, platform).

**What it returns:**
A `str`, 2–4 sentences, mentioning the item name, price, and platform each once, written in a casual first-person voice. Uses a higher LLM temperature (0.9) so repeated calls on the same input produce varied phrasing rather than identical output.

**What happens if it fails or returns nothing:**
If `outfit` is empty or whitespace-only, the tool does not call the LLM at all — it returns a descriptive error string (e.g., `"Can't build a fit card without an outfit — generate an outfit suggestion first."`) as its normal return value, not an exception. If the Groq API call itself raises, the exception is caught and a fallback caption using only `new_item` fields is returned instead of crashing.

---

### Additional Tools (if any)

Two additional tools were added for stretch features (see `## Stretch Features` below for the full spec of each, plus how the two non-tool stretch features work):

### Tool 4: estimate_fair_price

**What it does:**
Given a listing, finds "comparable" listings elsewhere in the dataset (same category, sharing at least one style tag) and reports whether the item's price is low, fair, or high relative to that comparison group, with the reasoning shown.

**Input parameters:**
- `item` (dict): A listing dict, as returned by `search_listings`.

**What it returns:**
A `str` verdict with reasoning, e.g. naming the number of comparables found, their average price, and a good-deal/fair/high-priced judgment.

**What happens if it fails or returns nothing:**
If fewer than 2 comparables share a style tag, the comparison broadens to "same category" listings only. If still fewer than 2 comparables exist even at that level (a near-unique category), the tool returns a string saying there isn't enough data in the dataset to compare, rather than a misleading verdict built on 0–1 data points.

### Tool 5: get_trending_styles

**What it does:**
Looks up which style tags are currently "trending" (from a small mock trend dataset — see Stretch Features below for why this is mock data) that are relevant to a given size, so `suggest_outfit` can lean into trending styles when relevant instead of ignoring them.

**Input parameters:**
- `size` (str | None): The size the user searched for, or `None` for no size filtering. Used to prioritize trends tagged as relevant to that size range; trends with no size restriction always apply.

**What it returns:**
A `list[dict]`, each with `style_tag`, `trend_score` (0–1), and `note` (why it's trending), sorted by trend score descending, capped to the top 5.

**What happens if it fails or returns nothing:**
Never raises — worst case (an unrecognized size) still returns the size-agnostic trends, so the list is empty only if the trend dataset itself is empty.

---

## Planning Loop

**How does your agent decide which tool to call next?**

The loop is a fixed set of stages gated by explicit checks on session state — it is not "call all three tools every time." Concretely:

1. Parse the raw query into `description`, `size`, `max_price` using regex (not an LLM call — deterministic and cheap to test). Store in `session["parsed"]`.
2. Call `search_listings(**session["parsed"])`. Store the result in `session["search_results"]`.
3. **Retry-with-fallback branch (stretch):** if `search_results` is empty AND a `size` was specified, retry with `size=None` (price and description unchanged). If that retry is non-empty, use those results and record the adjustment in `session["adjustments"]` (e.g. `"removing the size filter"`). If still empty and a `max_price` was specified, retry once more with `max_price=None` too, recording that adjustment as well. Each rung only fires if the previous one is still empty — a query that succeeds on the first try never touches this branch.
4. **Branch on the final result:** `if len(session["search_results"]) == 0` after every retry rung has been exhausted: set `session["error"]` to a specific message naming what was searched and which filters were already loosened, then `return session` immediately. `suggest_outfit`, `create_fit_card`, and the two stretch tools are never called on this path — this is the adaptive behavior the rubric is checking for: the agent does not run the full pipeline unconditionally regardless of what the first tool returned.
5. If results are non-empty: `session["selected_item"] = session["search_results"][0]` (top-ranked match).
6. **Stretch tool calls:** `estimate_fair_price(session["selected_item"])` → `session["price_assessment"]`, and `get_trending_styles(session["parsed"]["size"])` → `session["trending_styles"]`. Neither can fail the loop.
7. Call `suggest_outfit(session["selected_item"], session["wardrobe"], trending_styles=session["trending_styles"])`. Store in `session["outfit_suggestion"]`. This call always succeeds with *some* string (see Tool 2's failure handling above), so no branch is needed here — but the *content* of the prompt sent to the LLM branches internally on whether `wardrobe["items"]` is empty, and again on whether any trending styles were passed in.
8. Call `create_fit_card(session["outfit_suggestion"], session["selected_item"])`. Store in `session["fit_card"]`.
9. Return `session`.

The loop is done when either `session["error"]` is set (early exit after step 4, once retries are exhausted) or `session["fit_card"]` is populated (full success after step 8).

---

## State Management

**How does information from one tool get passed to the next?**

A single `session` dict (created fresh per call to `run_agent`) is threaded through every step by reference — no tool re-asks the user for information already produced by an earlier tool.

- `session["parsed"]` — set once, after query parsing, and read by `search_listings`.
- `session["search_results"]` and `session["selected_item"]` — set after `search_listings` runs; `selected_item` is the exact dict object returned inside `search_results[0]`, not a re-constructed copy, so downstream tools receive the real listing data (id, price, platform, etc.) with nothing re-typed by the user.
- `session["adjustments"]` — a list of strings describing any retry-ladder loosening applied before `search_results` was populated (e.g. `["removing the size filter"]`); empty list if the first search attempt already succeeded. Read by `app.py` to prefix the listing panel with a note when non-empty.
- `session["price_assessment"]` — set by `estimate_fair_price(selected_item)` right after `selected_item` is known.
- `session["trending_styles"]` — set by `get_trending_styles(size)`; read by `suggest_outfit` (passed in as its optional `trending_styles` argument) so trend context can shape the LLM prompt, and also read directly by `app.py` to display in its own panel.
- `session["outfit_suggestion"]` — set after `suggest_outfit` runs, using `selected_item` and `trending_styles` from the steps above; read by `create_fit_card`.
- `session["fit_card"]` — the final output, set after `create_fit_card` runs using both `selected_item` and `outfit_suggestion`.
- `session["error"]` — `None` unless the loop exits early; when set, `outfit_suggestion` and `fit_card` remain `None`, which is how callers (the CLI test block, `app.py`) distinguish a failed run from a successful one.

The `session` dict itself lives only for the duration of one `run_agent()` call — but the **wardrobe passed into it** can now come from a persisted style profile on disk (see Stretch Features → Style Profile Memory below), which is the one piece of state that *does* survive across separate runs of the app.

---

## Error Handling

For each tool, describe the specific failure mode you're handling and what the agent does in response.

| Tool | Failure mode | Agent response |
|------|-------------|----------------|
| search_listings | No results match the query (bad size/price/description combo) | Tool returns `[]`. The planning loop first tries the retry ladder (drop size, then drop price too — see Planning Loop above). Only if every rung is still empty does it set `session["error"]` to a specific message naming the search terms, the price/size filters used, and which loosenings were already tried (e.g., "No listings matched 'designer ballgown' under $5.00 in size XXS. Already tried removing the size filter. Try raising your price limit."). The loop returns immediately — `suggest_outfit`, `create_fit_card`, and the stretch tools are not called. |
| suggest_outfit | Wardrobe is empty (`wardrobe["items"] == []`) | Not treated as an error — the tool switches to a general-styling-advice prompt for the item alone and still returns a useful, non-empty string. If the underlying Groq call itself raises, the exception is caught and a fallback string naming the item is returned instead of propagating. |
| create_fit_card | Outfit input is missing or incomplete (empty/whitespace string) | Tool returns a descriptive error string (not an exception) telling the caller a fit card can't be built without an outfit. If the Groq call itself raises, a fallback caption built from `new_item` fields alone is returned. |
| estimate_fair_price | Fewer than 2 comparable listings exist even after broadening from "same category + shared style tag" to "same category" alone | Returns a string stating there isn't enough data in the dataset to make a comparison, instead of a verdict built on 0–1 data points. |
| get_trending_styles | Size doesn't match any size-restricted trend entry | Falls back to including the size-agnostic trend entries (empty `size_ranges`) so the list is only ever empty if the trend dataset itself is empty. |

---

## Architecture

```
User query (natural language) ── wardrobe: Example / Empty / Saved profile (disk)
      │
      ▼
┌───────────────────────────────────────────────────────────────────────┐
│                            run_agent()                                 │
│                                                                          │
│  1. parse_query(query) ──► session["parsed"]                           │
│                                                                          │
│  2. search_listings(description, size, max_price)                      │
│         │                                                                │
│         ├─ results == [] and size given                                │
│         │        ├─ retry: search_listings(description, None, price)  │
│         │        │      ├─ results == [] and price given               │
│         │        │      │      └─ retry: search_listings(desc,None,None)│
│         │        │      │             ├─ results == [] ──► [ERROR] STOP │
│         │        │      │             └─ results found → adjustments+= │
│         │        │      └─ results found → adjustments += "..."        │
│         │        └─ (size not given, price given) same fallback logic  │
│         │                                                                │
│         └─ results = [item, ...]                                       │
│                 ▼                                                        │
│         session["search_results"] = results                             │
│         session["selected_item"]  = results[0]                          │
│                 │                                                        │
│  3. estimate_fair_price(selected_item) ──► session["price_assessment"]  │
│  4. get_trending_styles(size) ──────────► session["trending_styles"]    │
│                 │                                                        │
│  5. suggest_outfit(selected_item, wardrobe, trending_styles) ─ LLM call │
│                 │  (wardrobe empty? → general-advice prompt)            │
│                 │  (trending_styles non-empty? → nudge toward trend)    │
│                 ▼                                                        │
│         session["outfit_suggestion"] = "..."                            │
│                 │                                                        │
│  6. create_fit_card(outfit_suggestion, selected_item) ─ LLM call        │
│                 │   (outfit empty? → error string, no LLM call)         │
│                 ▼                                                        │
│         session["fit_card"] = "..."                                      │
│                                                                          │
└───────────────────────────────────────────────────────────────────────┘
      │
      ▼
Return session → app.py maps session fields to the Gradio output panels,
                 and (if a non-empty wardrobe was used) saves it to
                 style_profile.json for the next run to load as "Saved profile"
```

Nodes: user, `run_agent` (planning loop), the 5 tools, the `session` dict (state), and the on-disk style profile (persistence across separate app runs). Arrows show data flow in both directions. The `[ERROR] STOP` branch is the only early-exit path and terminates before the two LLM-calling tools and both stretch tools run — it's reached only after every retry rung has already failed.

---

## AI Tool Plan

**Milestone 3 — Individual tool implementations:**
I'll use Claude (Claude Code) and give it the Tool 1/2/3 spec blocks above (what each does, exact parameter names/types, return value, failure mode) one tool at a time, plus the relevant TODO docstring already in `tools.py`. I'll ask it to implement only that function, using `load_listings()` from the data loader rather than re-reading the JSON file. Before trusting the generated code I'll check: does it accept exactly the parameters named in the spec (name, type, order)? Does it implement the specific failure behavior described (return `[]` / general-advice string / error string, never an exception)? Then I'll run each tool directly from the terminal against 3+ hand-picked inputs, including the documented failure-mode input, before moving on.

**Milestone 4 — Planning loop and state management:**
I'll give Claude the full Architecture diagram above plus the Planning Loop and State Management sections, and ask it to implement `run_agent()` in `agent.py` following the existing numbered TODO steps in the file. Before running the generated code I'll check: does it branch on `len(search_results) == 0` before calling `suggest_outfit`? Does it store `selected_item`, `outfit_suggestion`, and `fit_card` in the session dict rather than as local variables? Does it return early on the error path without calling the remaining two tools? I'll then run the built-in CLI test block in `agent.py` (happy path + no-results path) and confirm both behave as documented here before wiring up `app.py`.

**Milestone 7 — Stretch features (Price Comparison, Trend Awareness, Style Profile Memory, Retry with Fallback):**
For each of the two new tools (`estimate_fair_price`, `get_trending_styles`) I'll give Claude that tool's spec block from this file (inputs, return value, failure mode) the same way I did for the three required tools in Milestone 3, and check the generated code against the same criteria: right parameters, right failure behavior, no exceptions. For the retry ladder, I'll give it the updated Planning Loop section above (the three-rung retry description) and the updated Architecture diagram, and check specifically that each retry rung only fires when the previous one is still empty — not that it retries unconditionally. For Style Profile Memory, I described the storage approach (a flat JSON file, load/save functions) in prose myself first since it's a design decision more than an implementation detail, then had Claude implement the load/save functions against that description and verified round-tripping (save a wardrobe, restart, load it back) produces the identical dict before wiring it into `app.py`.

---

## Stretch Features

Update this section before starting each stretch feature, per the assignment's instructions.

### Price Comparison Tool (+2) — see Tool 4 (`estimate_fair_price`) above
Comparable listings are defined as: same `category`, plus at least one overlapping `style_tags` entry. The tool computes the mean price of that comparable group (excluding the item itself if it appears in it) and classifies the item's price as a good deal (more than 15% below the comparable average), fair (within ±15%), or priced high (more than 15% above), stating the comparable count and average price in the returned string so the reasoning is inspectable, not just a label.

### Style Profile Memory (+2)
**Storage approach:** a flat JSON file, `style_profile.json`, in the repo root (gitignored — it's runtime user state, not part of the codebase, the same way `.env` is). `save_style_profile(wardrobe)` writes the wardrobe dict currently in use to that file; `load_style_profile()` reads it back, returning `None` if the file doesn't exist yet. `app.py` gets a third wardrobe option, **"Saved profile (remembered)"** — when a query runs with "Example wardrobe" selected, that wardrobe is saved as the profile; a later run selecting "Saved profile" loads it back from disk with no re-selection or re-entry needed. This is real persistence across separate runs of the app (even after restarting `python app.py`), not just persistence within one `session` dict.

### Trend Awareness Tool (+2) — see Tool 5 (`get_trending_styles`) above
**Data source:** this project runs entirely on mock data (the 40-listing dataset, the wardrobe schema) with no external API calls beyond Groq for generation — there's no live-scraping infrastructure anywhere else in the project, and the assignment's own setup section promises "no new accounts or credits required." Building a real scraper for a specific platform would be inconsistent with that and out of scope for an ~8-9 hour project. `data/trends.json` is a small hand-authored mock dataset (8 style tags, a trend score, an optional size restriction, and a one-line "why it's trending" note) standing in for what a real trend-scraping tool would return — the same mocking pattern the assignment already uses for the listings and wardrobe data. This is stated plainly in the README so it's never presented as a live data source.
**How it influences the outfit suggestion:** `run_agent` calls `get_trending_styles(size)` right after finding a listing and passes the result into `suggest_outfit`'s new optional `trending_styles` parameter. When non-empty, the prompt sent to the LLM includes the top trending style tags and asks it to lean into one if it's a natural fit for the item — visibly changing the suggestion's wording versus a call with `trending_styles=None`.

### Retry Logic with Fallback (+1) — see Planning Loop, step 3, above
When `search_listings` comes back empty, the loop doesn't immediately give up: it retries once with the size filter removed, and if still empty, retries again with the price ceiling removed too. Each successful retry records what was loosened in `session["adjustments"]`, and `app.py` shows that as a note at the top of the listing panel (e.g., "Note: no exact match for your filters — showing results with the size filter removed.") so the user knows the result set isn't exactly what they asked for and why.

## A Complete Interaction (Step by Step)

Write out what a full user interaction looks like from start to finish — tool call by tool call. Use a specific example query.

**Example user query:** "I'm looking for a vintage graphic tee under $30. I mostly wear baggy jeans and chunky sneakers. What's out there and how would I style it?"

**Step 1:**
The agent parses the query: `description = "vintage graphic tee"`, `size = None` (no size mentioned), `max_price = 30.0` (from "under $30"). It calls `search_listings("vintage graphic tee", size=None, max_price=30.0)`. This returns a list of listings sorted by relevance — the Y2K Baby Tee and similar graphic tees under $30, ranked by keyword overlap with "vintage graphic tee."

**Step 2:**
The top result (`session["search_results"][0]`) becomes `session["selected_item"]` — for example, a "Y2K Baby Tee — Butterfly Print" at $18.00 on Depop. The agent calls `suggest_outfit(selected_item, wardrobe)` using the example wardrobe (which already contains baggy jeans and chunky white sneakers per its `items` list). The LLM returns an outfit suggestion pairing the new tee with the wardrobe's baggy straight-leg jeans and chunky white sneakers, referencing them by name.

**Step 3:**
The agent calls `create_fit_card(outfit_suggestion, selected_item)`. The LLM returns a short, casual caption mentioning the tee by name, its $18.00 price, and Depop, styled in the voice of a real thrifting post.

**Final output to user:**
The user sees three things: (1) the top listing found (title, price, platform, condition), (2) the outfit suggestion pairing it with their own baggy jeans and sneakers, and (3) a ready-to-post fit card caption — all without having re-entered the item or outfit anywhere along the way.
