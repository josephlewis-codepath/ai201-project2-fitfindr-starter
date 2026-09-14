# FitFindr

FitFindr is an agentic secondhand-fashion shopping assistant. It takes a natural-language query plus the user's wardrobe and orchestrates three tools — `search_listings`, `suggest_outfit`, and `create_fit_card` — to find a listing, style it against pieces the user already owns, and produce a shareable Instagram-style caption. The agent branches on tool results: if `search_listings` finds nothing, the pipeline stops early and tells the user how to adjust the query instead of calling the downstream LLM tools with empty input.

## Demo Video

<!-- Paste your recorded video URL here before submission -->
📽 https://youtu.be/fUc58-jZeuw 

## Quickstart

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# .env file in the repo root:
#   GROQ_API_KEY=your_key_here

python app.py            # launches Gradio at http://localhost:7860
python -m pytest tests/  # 10 tests, all passing
python agent.py          # CLI harness — runs happy path + no-results branch
```

## Architecture

See [`planning.md`](planning.md) — the architecture ASCII diagram, planning-loop pseudo-code, and error-handling table live there in full. This README documents what was actually built and how it maps to that spec.

```
User query
    │
    ▼
Planning Loop (run_agent)  ────────────────────────────┐
    │                                                  │
    ├─► search_listings(description, size, max_price)  │
    │       │ results=[]                               │
    │       └──► [ERROR] set session["error"] → return │
    │       │ results=[item, ...]                      │
    │       ▼                                          │
    │   session["selected_item"] = results[0]          │
    │       │                                          │
    ├─► suggest_outfit(selected_item, wardrobe)        │
    │       │                                          │
    │   session["outfit_suggestion"] = "..."           │
    │       │                                          │
    └─► create_fit_card(outfit_suggestion, selected_item)
            │
        session["fit_card"] = "..."
            │
            ▼
        Return session
```

## Tool Inventory

The signatures below match `tools.py` verbatim.

### `search_listings(description, size=None, max_price=None) → list[dict]`

| Parameter | Type | Meaning |
|---|---|---|
| `description` | `str` | Free-text query, e.g. `"vintage graphic tee"`. Tokenized (lowercase, alphanumeric) and matched against each listing's `title`, `category`, and `style_tags`. |
| `size` | `str \| None` | Size filter, e.g. `"M"` or `"W30"`. Case-insensitive substring match against the listing's `size` field. `None` skips the filter. |
| `max_price` | `float \| None` | Upper price bound in USD (`<=`). `None` skips the filter. |

**Returns:** `list[dict]` — 0 or more listing dicts with the full `listings.json` schema (`id`, `title`, `description`, `category`, `style_tags`, `size`, `condition`, `price`, `colors`, `brand`, `platform`). Sorted by relevance score descending (number of query tokens matched in `title + category + style_tags`), ties broken by lower price. Empty list on no match (no exception).

**Purpose:** Find candidate listings that satisfy the user's query, so the planning loop can pick a top item to style.

### `suggest_outfit(new_item, wardrobe) → str`

| Parameter | Type | Meaning |
|---|---|---|
| `new_item` | `dict` | A single listing dict (same shape as `search_listings` output). |
| `wardrobe` | `dict` | Wardrobe dict matching `data/wardrobe_schema.json` — has an `"items"` key with a list of wardrobe items. May have an empty `items` list. |

**Returns:** `str` — a 2–4 sentence styling suggestion. If the wardrobe has items, references them by name (e.g. *"Baggy straight-leg jeans, dark wash"*) and includes a wearing tip. If the wardrobe is empty, returns generic styling advice keyed off the new item's own `style_tags`. Never raises on empty wardrobe.

**Purpose:** Produce a wearable outfit description that pairs the new listing with pieces already in the user's closet.

### `create_fit_card(outfit, new_item) → str`

| Parameter | Type | Meaning |
|---|---|---|
| `outfit` | `str` | The styling suggestion string from `suggest_outfit`. |
| `new_item` | `dict` | The same listing dict that was styled — reads `title`, `price`, and `platform`. |

**Returns:** `str` — a 2–4 sentence social-media caption in casual first-person voice, referencing the item title, price, and platform each exactly once, with at most one emoji. If `outfit` is empty or whitespace-only, returns a descriptive error string (`"[fit_card_error] Cannot generate a caption without an outfit suggestion — call suggest_outfit first and pass its output in."`) — no exception.

**Purpose:** Turn the outfit + listing into ready-to-post caption copy the user can drop into an Instagram/TikTok post.

### LLM configuration

`suggest_outfit` and `create_fit_card` both call Groq. Model: `openai/gpt-oss-120b`. Temperatures: `0.7` for outfit suggestions (coherent), `1.0` for fit cards (so captions vary across runs on the same input).

## Planning Loop

Implemented as a fixed 3-tool pipeline with early exit on failure — no re-planning, no retries, always terminates in ≤ 3 tool calls. Lives in `run_agent()` in `agent.py`.

**Actual conditional logic:**

1. **Parse** — `_parse_query(query)` extracts `description`, `size`, and `max_price` from the natural-language query using regex. `size` looks for `size <token>`; `max_price` looks for `under $X` / `below X` / `less than X` / `max X`. The remaining tokens become `description`. Parsed values go into `session["parsed"]`.
2. **Search branch** — call `search_listings(**parsed)`. Store results in `session["search_results"]`.
   - **If `results == []`:** build a message that names what was searched (`description`, `size`, `max_price`) and lists three concrete adjustments (raise budget by $15, drop size filter, try adjacent term). Set `session["error"]` and **return the session immediately** — `suggest_outfit` and `create_fit_card` are never called.
   - **Else:** `session["selected_item"] = results[0]` (the top-ranked hit).
3. **Suggest outfit** — call `suggest_outfit(session["selected_item"], session["wardrobe"])`, store in `session["outfit_suggestion"]`. If the wardrobe is empty, the tool itself handles it and returns generic advice — the loop still proceeds.
4. **Fit card** — call `create_fit_card(session["outfit_suggestion"], session["selected_item"])`, store in `session["fit_card"]`.
5. **Return** the completed session dict.

The agent's behavior visibly differs across inputs: matching queries produce all three artifacts; the no-results branch short-circuits after Step 2 with only `session["error"]` set.

## State Management

State lives in a single `session` dict initialized in `_new_session(query, wardrobe)`. Every field is written by exactly one step and read by later steps — the same dict reference threads through the pipeline, so downstream tools receive real upstream output, not user-re-entered values.

| Key | Written by | Read by |
|---|---|---|
| `query` | `_new_session` | logging / debugging |
| `wardrobe` | `_new_session` | Step 3 (`suggest_outfit`) |
| `parsed` | Step 1 (parse) | Step 2 (`search_listings`) |
| `search_results` | Step 2 | Step 2 (selects `[0]`) |
| `selected_item` | Step 2 | Steps 3 and 4 |
| `outfit_suggestion` | Step 3 | Step 4 (`create_fit_card`) |
| `fit_card` | Step 4 | UI |
| `error` | any early-exit branch | UI |

**Identity verification:** `session["selected_item"] is session["search_results"][0]` is `True` after a successful run — the item passed into `suggest_outfit` is the exact same dict object, not a copy. `app.handle_query` in `app.py` reads the completed session and maps its fields directly to the three Gradio output panels.

## Error Handling

Each tool owns its failure mode. The planning loop respects those contracts and short-circuits when a step returns an error signal, rather than pushing empty inputs downstream.

| Tool | Failure mode | Agent response |
|---|---|---|
| `search_listings` | No listings match the query. | Returns `[]` (no exception). The planning loop sets `session["error"]` to a specific message: `"I couldn't find anything matching '{description}' under ${max_price} in size {size}. Try (1) raising the budget to ${max_price+15}, (2) dropping the size filter, or (3) searching an adjacent term like 'band tee' or 'y2k tee'."` The chain stops — `suggest_outfit` and `create_fit_card` are not called. `session["fit_card"]` stays `None`. |
| `suggest_outfit` | Wardrobe `items` list is empty. | Tool swaps to a "no wardrobe yet" prompt and returns generic styling advice keyed off `new_item["style_tags"]`. Never raises. Pipeline continues normally to `create_fit_card`. |
| `create_fit_card` | Outfit string is empty or whitespace. | Tool returns `"[fit_card_error] Cannot generate a caption without an outfit suggestion — call suggest_outfit first and pass its output in."` — a descriptive string, not an exception. No LLM call is wasted on empty input. |

**Concrete test example (from `python agent.py` no-results run):**

```
Query: "designer ballgown size XXS under $5"

session["parsed"]:            {'description': 'designer ballgown', 'size': 'XXS', 'max_price': 5.0}
session["search_results"]:    []
session["selected_item"]:     None
session["outfit_suggestion"]: None
session["fit_card"]:          None
session["error"]: "I couldn't find anything matching 'designer ballgown' under $5 in size XXS.
                   Try (1) raising the budget to $20, (2) dropping the size filter, or
                   (3) searching an adjacent term like 'band tee' or 'y2k tee'."
```

`outfit_suggestion` and `fit_card` are both `None` — confirming `suggest_outfit` and `create_fit_card` were never invoked on the empty-results branch. All three failure modes are covered by pytest cases in `tests/test_tools.py` (`test_search_empty_results`, `test_suggest_outfit_empty_wardrobe_does_not_crash`, `test_create_fit_card_empty_outfit_returns_error_string`).

## Interaction Walkthrough

**User query:** *"looking for a vintage graphic tee under $30"* (with the example wardrobe selected in the Gradio UI)

**Step 1 — `search_listings`**
- Tool: `search_listings(description="vintage graphic tee", size=None, max_price=30.0)`
- Input: parsed from the raw query by `_parse_query` (regex).
- Why this tool: the query is a request for a listing; nothing else can be done until we have a specific item.
- Output: a ranked list of listing dicts. Top result is `lst_002` — *Y2K Baby Tee — Butterfly Print*, $18 on Depop, tags include `vintage` and `graphic tee`.

**Step 2 — `suggest_outfit`**
- Tool: `suggest_outfit(new_item=<lst_002 dict>, wardrobe=<example_wardrobe>)`
- Input: the exact `search_results[0]` dict from Step 1 (same object identity, not a copy) plus the 10-item example wardrobe.
- Why this tool: we have a specific item and a wardrobe — the next thing the user wants is a wearable pairing.
- Output: a multi-sentence styling suggestion naming specific wardrobe items — *"Baggy straight-leg jeans, dark wash, Brown leather belt, Vintage black denim jacket, Chunky white sneakers..."* — with concrete tips (tuck the front of the tee, roll the jean cuffs).

**Step 3 — `create_fit_card`**
- Tool: `create_fit_card(outfit=<Step 2 string>, new_item=<lst_002 dict>)`
- Input: the outfit string from Step 2 plus the same listing dict from Step 1.
- Why this tool: convert the styling advice into shareable caption copy.
- Output: *"just snagged the Y2K Baby Tee — Butterfly Print for $18 on depop and paired it with baggy straight-leg jeans, a brown leather belt, and my favorite vintage black denim jacket. tucked the front in, rolled the cuffs, and finished with chunky white sneakers and a black crossbody. feeling that retro street vibe 🌟"*

**Final output to user (Gradio):** three panels — the listing summary (title, price, platform, condition, size, description) in panel 1, the outfit suggestion in panel 2, the fit card caption in panel 3.

## Testing

10 pytest cases in `tests/test_tools.py`. Run from the repo root:

```bash
python -m pytest tests/
```

Coverage summary:
- `search_listings`: happy path, empty results (no exception), price filter, case-insensitive size filter, results ordered by relevance.
- `suggest_outfit`: with wardrobe, empty wardrobe (does not crash).
- `create_fit_card`: empty outfit returns error string, whitespace outfit returns error string, captions vary across calls on the same input (temperature check).

LLM-backed tests are gated with `@pytest.mark.skipif(not os.environ.get("GROQ_API_KEY"))` so the suite still exercises the pure-Python logic without a network dependency.

## Spec Reflection

**One way `planning.md` helped during implementation:** The planning-loop pseudo-code section — with explicit branch labels for `[ERROR: no_results]`, `[ERROR: outfit_failed]`, and `[ERROR: fit_card_failed]` — meant that when I wrote `run_agent`, the exit conditions were already decided. I didn't have to negotiate mid-implementation whether an empty search result should still fall through to `suggest_outfit` (it doesn't) or whether an empty wardrobe should skip `suggest_outfit` (it doesn't — the tool handles it). Every branch was pre-committed, so implementation was mechanical.

**One divergence from the spec, and why:** planning.md's error-handling table lists `outfit_failed` and `fit_card_failed` as distinct branches with `try/except` around each LLM call. In practice I only implemented graceful degradation inside `create_fit_card` itself (the empty-outfit guard). I did **not** wrap the `suggest_outfit` call in a `try/except` in `run_agent`, because the tool's contract already guarantees it returns a string (empty wardrobe → generic advice) rather than raising, so wrapping it would have been defensive code for a scenario the tool doesn't produce. The divergence made the loop simpler without weakening the failure story — if `suggest_outfit`'s contract changes later, the wrap can be added then.

## AI Usage

Claude Code was used throughout implementation. Two representative instances:

**1. `search_listings` implementation.** I gave Claude the Tool 1 block from `planning.md` (input parameters, return contract, empty-results behavior) plus the `load_listings()` signature from `utils/data_loader.py`, and asked it to implement `search_listings` in `tools.py`. Its first draft used a scoring function based on `Counter.most_common` and tokenized the description without dropping single-character tokens. I overrode two things before accepting it: (a) I switched to a `set(tokens)` scoring loop so duplicate tokens in the query don't inflate the score, and (b) I added a `len(t) > 1` filter so noise like the token `"a"` in `"a jacket"` wouldn't count as a match against `"casual"`. I also changed the tie-break rule to sort ties by lower price, which the spec called for but Claude's first draft didn't implement.

**2. Planning-loop implementation in `agent.py`.** I gave Claude the full Planning Loop pseudo-code and the Architecture ASCII diagram from `planning.md`, and asked it to implement `run_agent`. Its first draft called `suggest_outfit` and `create_fit_card` inside a single `try/except` block, which would have silently swallowed both failure modes into one generic error message. I rewrote that section to keep the branches distinct — the `search_listings == []` case is the only early-exit path in the final code, because the other two tools handle their own failure modes internally per the tool contracts. Claude also generated a version that assigned `session["selected_item"] = results[0].copy()`, which I changed to a direct assignment so that the `is`-identity check between `selected_item` and `search_results[0]` would hold — a state-passing guarantee I wanted to demonstrate.

---

## Reference — Data

`data/listings.json` — 40 mock secondhand listings. Each listing has: `id`, `title`, `description`, `category`, `style_tags`, `size`, `condition`, `price`, `colors`, `brand`, `platform`.

`data/wardrobe_schema.json` — wardrobe format plus an `example_wardrobe` (10 items) and an `empty_wardrobe` template.

Load via `utils/data_loader.py`:

```python
from utils.data_loader import load_listings, get_example_wardrobe, get_empty_wardrobe
```
