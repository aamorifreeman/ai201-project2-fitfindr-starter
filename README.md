# FitFindr

A multi-tool AI agent that helps you find secondhand pieces and figure out how to style them. Give it a natural-language request — "vintage graphic tee under $30, size M" — and it searches a mock listings dataset, suggests an outfit using your existing wardrobe, and writes a shareable caption for the find, deciding on its own what to do when a step comes back empty.

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

Run the agent from the CLI (happy path, no-results path, and empty-wardrobe path):
```bash
python agent.py
```

---

## Tool Inventory

### `search_listings(description: str, size: str | None = None, max_price: float | None = None) -> list[dict]`

Searches the 40-item mock listings dataset. `description` is free-text keywords scored against each listing's title, description, category, style tags, and brand — a listing must share at least one keyword to be returned at all. `size` is optional and matched case-insensitively at the token level (a query of `"M"` matches a listing sized `"S/M"` because the listing's size string is split into tokens and checked for an exact token match, not a raw substring). `max_price` is an optional inclusive ceiling.

Returns a list of full listing dicts (`id`, `title`, `description`, `category`, `style_tags`, `size`, `condition`, `price`, `colors`, `brand`, `platform`), sorted by keyword-overlap score (best match first), with price as a tiebreaker. Returns `[]` — never raises — if nothing matches.

### `suggest_outfit(new_item: dict, wardrobe: dict) -> str`

Given a listing dict and a wardrobe dict (`{"items": [...]}`), asks the LLM for 1–2 outfit combinations. If the wardrobe has items, the prompt includes each item's name, category, colors, and style tags, and the LLM is asked to reference specific pieces by name. If `wardrobe["items"]` is empty, the prompt switches to general styling advice for the item on its own — this is not treated as a failure.

Always returns a non-empty string. If the Groq call itself raises, the exception is caught and a fallback string naming the item is returned instead of propagating.

### `create_fit_card(outfit: str, new_item: dict) -> str`

Given an outfit suggestion string and the listing dict, asks the LLM for a 2–4 sentence casual social-caption mentioning the item name, price, and platform once each, in the voice of a real OOTD post rather than a product description. Uses `temperature=0.9` so repeated calls on identical input vary in phrasing (verified — see Error Handling below and the demo).

If `outfit` is empty or whitespace-only, returns a descriptive error string (`"Can't build a fit card without an outfit -- generate an outfit suggestion first."`) without calling the LLM at all. If the Groq call raises, a fallback caption built from `new_item` alone is returned.

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

The loop is a fixed sequence of stages gated by one explicit branch, not a fixed sequence of tool calls run unconditionally:

1. Parse the query into `description`, `size`, `max_price` with regex (see `agent.py::parse_query`).
2. Call `search_listings` with the parsed parameters.
3. **Branch:** if `search_results` is empty, set `session["error"]` to a specific message (naming the search terms and which filter to loosen) and return immediately — `suggest_outfit` and `create_fit_card` are never called on this path.
4. If results exist, take the top-ranked item as `selected_item`.
5. Call `suggest_outfit(selected_item, wardrobe)`.
6. Call `create_fit_card(outfit_suggestion, selected_item)`.
7. Return the session.

This is the adaptive behavior graded here: a query like `"designer ballgown size XXS under $5"` stops after step 3 with an error message and two empty output panels, while a normal query runs all three tools. The agent's behavior visibly differs based on what the first tool returns — it doesn't call all three tools in the same order regardless of context.

---

## State Management

A single `session` dict, created fresh per call to `run_agent()`, is threaded through every step by reference:

- `session["parsed"]` is set once after query parsing and read by `search_listings`.
- `session["selected_item"]` is set to the *exact dict object* returned inside `search_results[0]` — not a re-typed copy — so `suggest_outfit` receives the real listing data with nothing re-entered by the user.
- `session["outfit_suggestion"]` is set after `suggest_outfit` runs and is read directly by `create_fit_card`.
- `session["fit_card"]` holds the final output.
- `session["error"]` stays `None` on a full run; when set, `outfit_suggestion` and `fit_card` stay `None`, which is how `app.py` tells a failed run from a successful one.

The dict lives only for one `run_agent()` call — there's no cross-session memory in this build (that would be the Style Profile Memory stretch feature).

---

## Error Handling

| Tool | Failure mode | Agent response |
|------|-------------|-----------------|
| `search_listings` | No results match the query | Returns `[]`. The planning loop sets a specific error naming the search terms and filters used and suggesting what to loosen (e.g., *"No listings matched "designer ballgown" (size XXS, under $5.00). Try removing the size filter or raising your price limit."*) and returns immediately without calling the other two tools. Verified live: querying `"designer ballgown size XXS under $5"` in the running app leaves the Outfit and Fit Card panels empty and shows exactly that message. |
| `suggest_outfit` | Wardrobe is empty | Not treated as a failure — the tool switches to a general-styling prompt and still returns a useful string. Verified: querying `"black combat boots size 8"` with "Empty wardrobe (new user)" selected returns general styling advice (dark denim, chambray, a camel trench) with no wardrobe items referenced, instead of crashing or returning an empty panel. If the Groq call itself raises, the exception is caught and a fallback string naming the item is returned. |
| `create_fit_card` | Outfit input is empty/whitespace | Returns a descriptive error string without calling the LLM (`"Can't build a fit card without an outfit -- generate an outfit suggestion first."`) — covered by `tests/test_tools.py::test_create_fit_card_empty_outfit_returns_error_string_not_exception`. If the Groq call raises, a fallback caption built from item fields alone is returned instead of an exception — covered by `test_create_fit_card_llm_failure_returns_fallback_not_exception`. |

---

## Spec Reflection

**One way the spec helped:** Writing out the exact planning-loop branches in `planning.md` before touching code (step 3's "if results is empty, set error and return early") made the implementation almost mechanical — `agent.py::run_agent` is close to a direct transcription of that section. It also made the no-results test case obvious to write before any code existed, since the spec already said what the failure path had to look like.

**One divergence, and why:** The assignment and starter `README.md` specify `meta-llama/llama-4-scout-17b-16e-instruct` as the model. Groq deprecated that model in March 2026 — calling it returns a `404 model_not_found`. Course staff confirmed `openai/gpt-oss-120b` as the replacement (I'd already hit and resolved this same issue in Project 1). A second divergence surfaced while integrating it: `gpt-oss-120b` is a reasoning model that spends part of its `max_tokens` budget on hidden reasoning tokens before the visible answer — at `max_tokens=200` (a reasonable-looking default), responses came back completely empty (`finish_reason="length"`, 198/200 tokens spent on reasoning). Raising the budget to `600` fixed it. Both are documented as comments in `tools.py`.

---

## AI Usage Transparency

1. **`search_listings` and the size-matching logic:** I gave Claude the Tool 1 spec block from `planning.md` (exact parameters, return value, the failure mode) and the note that a query of `"M"` should match a listing sized `"S/M"`. Its first draft matched sizes with a raw substring check (`size.lower() in listing_size.lower()`), which I overrode after noticing it would also match `"M"` against a hypothetical size like `"XM"` — a false positive raw substring matching would allow. I asked it to switch to token-based matching instead (`_size_tokens`, splitting on non-alphanumeric characters and comparing sets), which is what's in `tools.py` now.

2. **The empty-response bug on `gpt-oss-120b`:** When `suggest_outfit` and `create_fit_card` started returning the "LLM unreachable" fallback string on every call despite a working API key, I used Claude to debug it by inspecting the raw Groq response object rather than guessing — it added a debug script printing `finish_reason` and `usage.completion_tokens_details`, which surfaced `reasoning_tokens: 198` out of a `max_tokens=200` budget. I reviewed that output myself before accepting the fix (raising `max_tokens` to 600) rather than taking the diagnosis on faith — I re-ran the debug script at a couple of different token budgets to confirm 600 was comfortably above what reasoning was consuming, not just barely enough.
