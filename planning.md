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

None for the required build. (See stretch section if pursued: a 4th tool, `estimate_fair_price`, may be added for the Price Comparison stretch feature.)

---

## Planning Loop

**How does your agent decide which tool to call next?**

The loop is a fixed set of stages gated by explicit checks on session state — it is not "call all three tools every time." Concretely:

1. Parse the raw query into `description`, `size`, `max_price` using regex (not an LLM call — deterministic and cheap to test). Store in `session["parsed"]`.
2. Call `search_listings(**session["parsed"])`. Store the result in `session["search_results"]`.
3. **Branch on the result:** `if len(session["search_results"]) == 0:` set `session["error"]` to a specific message describing what was searched and what filter to loosen, then `return session` immediately. `suggest_outfit` and `create_fit_card` are never called on this path — this is the adaptive behavior the rubric is checking for: the agent does not run the full pipeline unconditionally regardless of what the first tool returned.
4. If results are non-empty: `session["selected_item"] = session["search_results"][0]` (top-ranked match).
5. Call `suggest_outfit(session["selected_item"], session["wardrobe"])`. Store in `session["outfit_suggestion"]`. This call always succeeds with *some* string (see Tool 2's failure handling above), so no branch is needed here — but the *content* of the prompt sent to the LLM branches internally on whether `wardrobe["items"]` is empty.
6. Call `create_fit_card(session["outfit_suggestion"], session["selected_item"])`. Store in `session["fit_card"]`.
7. Return `session`.

The loop is done when either `session["error"]` is set (early exit after step 3) or `session["fit_card"]` is populated (full success after step 6).

---

## State Management

**How does information from one tool get passed to the next?**

A single `session` dict (created fresh per call to `run_agent`) is threaded through every step by reference — no tool re-asks the user for information already produced by an earlier tool.

- `session["parsed"]` — set once, after query parsing, and read by `search_listings`.
- `session["search_results"]` and `session["selected_item"]` — set after `search_listings` runs; `selected_item` is the exact dict object returned inside `search_results[0]`, not a re-constructed copy, so downstream tools receive the real listing data (id, price, platform, etc.) with nothing re-typed by the user.
- `session["outfit_suggestion"]` — set after `suggest_outfit` runs, using `selected_item` from the step above; read by `create_fit_card`.
- `session["fit_card"]` — the final output, set after `create_fit_card` runs using both `selected_item` and `outfit_suggestion`.
- `session["error"]` — `None` unless the loop exits early; when set, `outfit_suggestion` and `fit_card` remain `None`, which is how callers (the CLI test block, `app.py`) distinguish a failed run from a successful one.

The dict lives only for the duration of one `run_agent()` call — there is no cross-session persistence in the required build (that's the Style Profile Memory stretch feature, not implemented here).

---

## Error Handling

For each tool, describe the specific failure mode you're handling and what the agent does in response.

| Tool | Failure mode | Agent response |
|------|-------------|----------------|
| search_listings | No results match the query (bad size/price/description combo) | Tool returns `[]`. Planning loop sets `session["error"]` to a specific message naming the search terms and price/size filters used, and suggesting the user loosen one of them (e.g., "No listings matched 'designer ballgown' under $5.00 in size XXS. Try raising your price limit or removing the size filter."). The loop returns immediately — `suggest_outfit` and `create_fit_card` are not called. |
| suggest_outfit | Wardrobe is empty (`wardrobe["items"] == []`) | Not treated as an error — the tool switches to a general-styling-advice prompt for the item alone and still returns a useful, non-empty string. If the underlying Groq call itself raises, the exception is caught and a fallback string naming the item is returned instead of propagating. |
| create_fit_card | Outfit input is missing or incomplete (empty/whitespace string) | Tool returns a descriptive error string (not an exception) telling the caller a fit card can't be built without an outfit. If the Groq call itself raises, a fallback caption built from `new_item` fields alone is returned. |

---

## Architecture

```
User query (natural language)
      │
      ▼
┌─────────────────────────────────────────────────────────────────┐
│                         run_agent()                              │
│                                                                    │
│  1. parse_query(query) ──► session["parsed"]                     │
│                                                                    │
│  2. search_listings(description, size, max_price)                │
│         │                                                          │
│         ├─ results == [] ──► [ERROR] session["error"] = "..."    │
│         │                     return session   (STOP — no │)     │
│         │                                        further calls)   │
│         │                                                          │
│         └─ results = [item, ...]                                 │
│                 ▼                                                  │
│         session["search_results"] = results                       │
│         session["selected_item"]  = results[0]                    │
│                 │                                                  │
│  3. suggest_outfit(selected_item, wardrobe) ─── LLM call          │
│                 │        (wardrobe empty? → general-advice prompt)│
│                 ▼                                                  │
│         session["outfit_suggestion"] = "..."                      │
│                 │                                                  │
│  4. create_fit_card(outfit_suggestion, selected_item) ─ LLM call  │
│                 │   (outfit empty? → error string, no LLM call)   │
│                 ▼                                                  │
│         session["fit_card"] = "..."                                │
│                                                                    │
└─────────────────────────────────────────────────────────────────┘
      │
      ▼
Return session  →  app.py maps session fields to the 3 Gradio output panels
```

Nodes: user, `run_agent` (planning loop), the 3 tools, and the `session` dict (state). Arrows show data flow in both directions (query in, session fields out). The error branch at step 2 is the only early-exit path and terminates before the two LLM-calling tools run.

---

## AI Tool Plan

**Milestone 3 — Individual tool implementations:**
I'll use Claude (Claude Code) and give it the Tool 1/2/3 spec blocks above (what each does, exact parameter names/types, return value, failure mode) one tool at a time, plus the relevant TODO docstring already in `tools.py`. I'll ask it to implement only that function, using `load_listings()` from the data loader rather than re-reading the JSON file. Before trusting the generated code I'll check: does it accept exactly the parameters named in the spec (name, type, order)? Does it implement the specific failure behavior described (return `[]` / general-advice string / error string, never an exception)? Then I'll run each tool directly from the terminal against 3+ hand-picked inputs, including the documented failure-mode input, before moving on.

**Milestone 4 — Planning loop and state management:**
I'll give Claude the full Architecture diagram above plus the Planning Loop and State Management sections, and ask it to implement `run_agent()` in `agent.py` following the existing numbered TODO steps in the file. Before running the generated code I'll check: does it branch on `len(search_results) == 0` before calling `suggest_outfit`? Does it store `selected_item`, `outfit_suggestion`, and `fit_card` in the session dict rather than as local variables? Does it return early on the error path without calling the remaining two tools? I'll then run the built-in CLI test block in `agent.py` (happy path + no-results path) and confirm both behave as documented here before wiring up `app.py`.

---

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
