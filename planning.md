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
<!-- Describe what this tool does in 1–2 sentences -->
Filters the mock listings dataset (`data/listings.json`, loaded via `load_listings()`) against a natural-language description, an optional size, and an optional maximum price. Returns matching listings ranked by relevance so the planning loop can pick the top hit.

**Input parameters:**
<!-- List each parameter, its type, and what it represents -->
- `description` (str): free-text query such as "vintage graphic tee" — lowercased and split into tokens, then matched (case-insensitive) against each listing's `title`, `category`, and `style_tags`.
- `size` (str | None): size filter like `"M"` or `"W30"` — compared against the listing's `size` field with a case-insensitive substring check. If `None`, no size filter is applied.
- `max_price` (float | None): upper price bound in USD. Excludes any listing whose `price` is greater than this value. If `None`, no price filter is applied.

**What it returns:**
<!-- Describe the return value — what fields does a result contain? -->
A `list[dict]` of 0 or more listing dicts, sorted descending by a relevance score (number of query tokens matched in `title` + `style_tags`, ties broken by lower price). Each dict contains every field from `listings.json`: `id`, `title`, `description`, `category`, `style_tags`, `size`, `condition`, `price`, `colors`, `brand`, `platform`. An empty list means no listings satisfied all filters.

**What happens if it fails or returns nothing:**
<!-- What should the agent do if no listings match? -->
If the returned list is empty, the planning loop sets `session.error = "no_results"` and returns a user-facing message suggesting concrete ways to loosen the query — raise `max_price`, drop the size filter, or try adjacent terms like `"band tee"` or `"y2k tee"`. The agent must NOT call `suggest_outfit` or `create_fit_card` in this branch.

---

### Tool 2: suggest_outfit

**What it does:**
<!-- Describe what this tool does in 1–2 sentences -->
Takes the chosen listing and the user's wardrobe and returns a natural-language styling suggestion that pairs the new item with specific pieces from the user's closet. Cross-references `colors` and `style_tags` between the new item and each wardrobe item to pick complementary bottoms, shoes, and layers.

**Input parameters:**
<!-- List each parameter, its type, and what it represents -->
- `new_item` (dict): a single listing dict in the exact shape returned by `search_listings` (fields: `id`, `title`, `category`, `colors`, `style_tags`, `price`, `platform`, etc.). Must contain at minimum `title`, `category`, `colors`, and `style_tags`.
- `wardrobe` (dict): a wardrobe dict matching `data/wardrobe_schema.json` — has an `"items"` key whose value is a list of wardrobe items. Each item has `id`, `name`, `category`, `colors`, `style_tags`, and optional `notes`. Sourced via `get_example_wardrobe()` or `get_empty_wardrobe()`.

**What it returns:**
<!-- Describe the return value -->
A styling suggestion `str` of roughly 2–4 sentences. The string names 1–3 specific wardrobe items by their `name` (e.g. "Baggy straight-leg jeans, dark wash"), references the new item's title, and includes at least one wearing tip (tucking, cuffing, layering, roll sleeves). No emojis in this string — that's the fit card's job.

**What happens if it fails or returns nothing:**
<!-- What should the agent do if the wardrobe is empty or no outfit can be suggested? -->
If `wardrobe["items"]` is empty, the tool still returns a valid string but keys styling advice off the new item's own `style_tags` alone (e.g. "Style this with wide-leg dark denim and platform shoes for a 90s look"), and the planning loop appends `"empty_wardrobe"` to `session.warnings` so the final reply can prompt the user to add wardrobe items. If `new_item` is missing required fields (`title`, `category`, `colors`, or `style_tags`), the tool raises `ValueError`; the planning loop catches it, sets `session.error = "outfit_failed"`, skips `create_fit_card`, and returns the listing alone.

---

### Tool 3: create_fit_card

**What it does:**
<!-- Describe what this tool does in 1–2 sentences -->
Turns the styling suggestion plus the listing metadata into a short, social-post-style caption (Depop / Instagram tone) that the user could copy-paste. Combines a "just scored this" framing (using `price` + `platform`) with a compressed reference to the wardrobe pairing.

**Input parameters:**
<!-- List each parameter, its type, and what it represents -->
- `outfit` (str): the styling suggestion string returned by `suggest_outfit`. The tool paraphrases it into casual social-media voice — it does not quote it verbatim.
- `new_item` (dict): the same listing dict passed to `suggest_outfit`. The tool reads `title`, `price`, and `platform` to insert the "found this on Depop for $24" framing.

**What it returns:**
<!-- Describe the return value -->
A caption `str` of 1–3 sentences in first-person lowercase social-media voice. Includes the item's `price` and `platform`, a compressed nod to the wardrobe pairing from `outfit`, and at most one emoji. Length target: under 240 characters so it fits standard post caption previews.

**What happens if it fails or returns nothing:**
<!-- What should the agent do if the outfit data is incomplete? -->
If `outfit` is an empty/whitespace string or `new_item` is missing any of `title`, `price`, or `platform`, the tool returns a minimal fallback caption using whichever fields it does have (e.g. `"new pickup — full fit in stories 🖤"`). The planning loop then sets `session.error = "fit_card_degraded"` and surfaces the listing + `session.outfit` from Step 2 in the final reply so the user still gets value from the earlier steps.

---

### Additional Tools (if any)

<!-- Copy the block above for any tools beyond the required three -->

---

## Planning Loop

**How does your agent decide which tool to call next?**
<!-- Describe the logic your planning loop uses. What does it look at? What conditions change its behavior? How does it know when it's done? -->

The planning loop is a fixed 3-step pipeline with early exits on failure. It always terminates in ≤ 3 tool calls — no re-planning, no retries.

**Step A — Parse and initialize.**
Extract `description` (str, required), `size` (str or None), and `max_price` (float or None) from the user query. Initialize `session = {"query": ..., "selected_item": None, "outfit": None, "fit_card": None, "warnings": [], "error": None}`.

**Step B — Call `search_listings`.**
```
results = search_listings(description, size, max_price)
if len(results) == 0:
    session["error"] = "no_results"
    return build_no_results_message(description, size, max_price)   # STOP — do not call further tools
else:
    session["selected_item"] = results[0]                            # top-ranked hit
    # proceed to Step C
```

**Step C — Call `suggest_outfit`.**
```
if len(session["wardrobe"]["items"]) == 0:
    session["warnings"].append("empty_wardrobe")   # still call the tool; it handles empty wardrobe
try:
    session["outfit"] = suggest_outfit(
        new_item=session["selected_item"],
        wardrobe=session["wardrobe"],
    )
except ValueError:
    session["error"] = "outfit_failed"
    return build_listing_only_reply(session)       # STOP — skip Step D
```

**Step D — Call `create_fit_card`.**
```
try:
    session["fit_card"] = create_fit_card(
        outfit=session["outfit"],
        new_item=session["selected_item"],
    )
except Exception:
    session["error"] = "fit_card_failed"
    return build_listing_and_outfit_reply(session) # STOP — return steps B+C output without caption
```

**Step E — Assemble and return.**
Return a three-part reply built from `session["selected_item"]` (listing summary), `session["outfit"]` (styling), and `session["fit_card"]` (caption). Append any messages implied by `session["warnings"]` (e.g. prompt to add wardrobe items if `"empty_wardrobe"` is present).

**Termination condition:** the loop returns after Step B (on no results), after Step C (on outfit_failed), after Step D (on fit_card_failed), or after Step E (success). There is no loop back to Step B — a single user query drives exactly one pass through the pipeline.

---

## State Management

**How does information from one tool get passed to the next?**
<!-- Describe how your agent stores and accesses state within a session. What data is tracked? How is it passed between tool calls? -->

---

## Error Handling

For each tool, describe the specific failure mode you're handling and what the agent does in response.

| Tool | Failure mode | Agent response |
|------|-------------|----------------|
| search_listings | No results match the query | Set `session.error = "no_results"` and stop the chain — do NOT call `suggest_outfit` or `create_fit_card`. Return a message that echoes back what was searched and gives three concrete adjustments: `"I couldn't find anything for '{description}' under ${max_price}{, size {size} if set}. Try (1) raising the budget to ${max_price + 15}, (2) removing the size filter, or (3) searching an adjacent term like 'band tee' or 'y2k tee'."` |
| suggest_outfit | Wardrobe is empty | Still call the tool — it returns generic style advice keyed off `new_item["style_tags"]`. Append `"empty_wardrobe"` to `session.warnings`. In the final reply, prepend: `"Your wardrobe is empty, so this is a general styling take. Add a few pieces to your wardrobe and I can suggest outfits using what you already own."` Then continue to `create_fit_card` normally — the user still gets a listing, styling, and caption. |
| create_fit_card | Outfit input is missing or incomplete | Do not raise. Return the fallback caption (`"new pickup — full fit in stories 🖤"`) and set `session.error = "fit_card_degraded"`. In the final reply to the user, surface the listing summary + `session.outfit` from Step 2, then append: `"I couldn't generate a polished caption for this one — here's the listing and styling if you want to write your own."` The user still gets the two upstream artifacts rather than a bare error. |

---

## Architecture

<!-- Draw a diagram of your agent showing how the components connect:
     User input → Planning Loop → Tools (search_listings, suggest_outfit, create_fit_card)
                                                                          ↕
                                                                   State / Session
     Show what triggers each tool, how state flows between them, and where error paths branch off.
     Use ASCII art or a Mermaid diagram (https://mermaid.js.org/syntax/flowchart.html).
     Do NOT embed an image — graders need to read your diagram directly in the file;
     an embedded image or screenshot cannot be evaluated.
     You'll share this diagram with an AI tool when asking it to implement
     the planning loop and each individual tool. -->

```
                    ┌───────────────────────────┐
                    │        USER               │
                    │  "vintage graphic tee     │
                    │   under $30, size M"      │
                    └────────────┬──────────────┘
                                 │ raw query
                                 ▼
    ┌──────────────────────────────────────────────────────────────┐
    │                     PLANNING LOOP                            │
    │  parse → search → suggest → fit_card → assemble reply        │
    │                                                              │
    │   reads/writes ▲                                             │
    │                │                                             │
    │                ▼                                             │
    │   ┌──────────────────────────────────────────────────┐       │
    │   │                 SESSION STATE                    │       │
    │   │  query, wardrobe, selected_item, outfit,         │       │
    │   │  fit_card, warnings[], error                     │       │
    │   └──────────────────────────────────────────────────┘       │
    │                                                              │
    │   STEP B ──────────────────────────────────────────────┐     │
    │   ▼                                                    │     │
    │  search_listings(description, size, max_price)         │     │
    │        │                                               │     │
    │        │ results = []                                  │     │
    │        ├──► [ERROR: no_results]                        │     │
    │        │    write session.error = "no_results"         │     │
    │        │    build "loosen your query" message ─────────┼──┐  │
    │        │                                               │  │  │
    │        │ results = [listing, ...]                      │  │  │
    │        ▼                                               │  │  │
    │   session.selected_item = results[0]  (full dict:      │  │  │
    │     id, title, price, colors, style_tags, platform…)   │  │  │
    │                                                        │  │  │
    │   STEP C ──────────────────────────────────────────────┤  │  │
    │   ▼                                                    │  │  │
    │  suggest_outfit(new_item=selected_item,                │  │  │
    │                 wardrobe=session.wardrobe)             │  │  │
    │        │                                               │  │  │
    │        │ wardrobe.items == []                          │  │  │
    │        │   → append "empty_wardrobe" to warnings,      │  │  │
    │        │     still call tool (generic advice)          │  │  │
    │        │                                               │  │  │
    │        │ raises ValueError (bad new_item)              │  │  │
    │        ├──► [ERROR: outfit_failed]                     │  │  │
    │        │    build listing-only reply ──────────────────┼──┤  │
    │        │                                               │  │  │
    │        ▼                                               │  │  │
    │   session.outfit = "Pair with baggy jeans + chunky…"   │  │  │
    │                                                        │  │  │
    │   STEP D ──────────────────────────────────────────────┤  │  │
    │   ▼                                                    │  │  │
    │  create_fit_card(outfit=session.outfit,                │  │  │
    │                  new_item=selected_item)               │  │  │
    │        │                                               │  │  │
    │        │ raises / degraded input                       │  │  │
    │        ├──► [ERROR: fit_card_failed]                   │  │  │
    │        │    build listing+outfit reply ────────────────┼──┤  │
    │        │                                               │  │  │
    │        ▼                                               │  │  │
    │   session.fit_card = "scored this off depop for $24…"  │  │  │
    │                                                        │  │  │
    │   STEP E — assemble final reply                        │  │  │
    │   listing summary + outfit + fit_card + warnings ──────┼──┤  │
    │                                                        │  │  │
    └────────────────────────────────────────────────────────┼──┼──┘
                                                             │  │
                                     all exit paths converge │  │
                                                             ▼  ▼
                                             ┌───────────────────────┐
                                             │       USER            │
                                             │  final reply (success │
                                             │  or error message)    │
                                             └───────────────────────┘
```

**Legend:**
- **Solid blocks** are components (user, planning loop, session state).
- **Tool calls** are step-labeled (B/C/D) inside the planning loop.
- **`[ERROR: ...]`** branches short-circuit the pipeline — they skip all remaining tools and route directly to the "assemble reply" exit.
- **Session state** is the single source of truth for cross-tool data: `selected_item` is written by Step B and read by Steps C and D; `outfit` is written by Step C and read by Step D; `warnings` and `error` are accumulated across steps and consulted at Step E.

---

## AI Tool Plan

<!-- For each part of the implementation below, describe:
     - Which AI tool you plan to use (Claude, Copilot, ChatGPT, etc.)
     - What you'll give it as input (which sections of this planning.md, your agent diagram)
     - What you expect it to produce
     - How you'll verify the output matches your spec before moving on

     "I'll use AI to help me code" is not a plan.
     "I'll give Claude my Tool 1 spec (inputs, return value, failure mode) and ask it to implement
     search_listings() using load_listings() from the data loader — then test it against 3 queries
     before trusting it" is a plan. -->

**Milestone 3 — Individual tool implementations:**

I'll use **Claude Code** for all three tools, one at a time in the same repo.

- **search_listings** — I'll give Claude Code the "Tool 1: search_listings" block from this planning.md plus `utils/data_loader.py`, and ask it to implement `tools/search_listings.py` using `load_listings()`. Description tokens should be matched (case-insensitive) against `title` / `category` / `style_tags`; `size` via case-insensitive substring against the listing's `size` field; `max_price` via `<=`. Verification before I trust it: read the diff and confirm (a) all three parameters actually filter, (b) `None` defaults skip the filter rather than error, (c) empty result returns `[]` (does not raise), and (d) results are sorted by relevance score, ties broken by lower price. Test with 3 queries: `"vintage graphic tee", None, 30.0` (should hit lst_002/lst_006), `"leather trench", None, 20.0` (should return `[]`), and `"jeans", "W30", 50.0` (should hit lst_001 via size match).

- **suggest_outfit** — I'll give Claude Code the "Tool 2: suggest_outfit" block plus `data/wardrobe_schema.json` and the output of `get_example_wardrobe()`. Ask it to implement `tools/suggest_outfit.py` — score each wardrobe item by overlap of `colors` and `style_tags` with the `new_item`, pick 1–3 top items across `bottoms` / `shoes` / `outerwear`, and format a 2–4 sentence string that names items by their wardrobe `name`. Verification: (a) `wardrobe["items"] == []` returns generic advice keyed off `new_item["style_tags"]` instead of raising; (b) `new_item` missing `title` / `category` / `colors` / `style_tags` raises `ValueError` (not a silent empty string); (c) with a full wardrobe, output names at least one specific item. Test with `lst_006` + example wardrobe, `lst_006` + empty wardrobe, and a stripped-down `new_item` missing `style_tags`.

- **create_fit_card** — I'll give Claude Code the "Tool 3: create_fit_card" block plus a real `outfit` string produced by my suggest_outfit test above (paste it in verbatim so the input is realistic, not synthetic). Ask it to implement `tools/create_fit_card.py` that inserts `new_item["price"]` and `new_item["platform"]` and compresses `outfit` into casual social-media voice. Verification: (a) output ≤ 240 chars, (b) `price` and `platform` appear literally, (c) at most one emoji, (d) empty `outfit=""` or `new_item` missing `title`/`price`/`platform` returns the fallback caption instead of raising. Test with the real Step 2 output, `outfit=""`, and a `new_item` with `platform` deleted.

**Milestone 4 — Planning loop and state management:**

I'll use **Claude Code** again, this time seeded with more of the planning doc since the loop needs to reference every earlier decision.

- **Planning loop** — I'll give Claude Code the full "Planning Loop" section (with its pseudo-code branches), the "Architecture" ASCII diagram, and the "Error Handling" table from this planning.md, and ask it to implement `agent/planner.py`. The generated code must follow the exact B → C → D → E step order, initialize `session` with the six keys listed in the pseudo-code, and short-circuit on each `[ERROR: ...]` branch. Verification before I run it end-to-end: read the code and confirm (a) each error branch has an actual `return` and doesn't fall through to the next step, (b) `session["selected_item"]` is set from `results[0]` before `suggest_outfit` is invoked, (c) an empty wardrobe appends `"empty_wardrobe"` to `warnings` but does NOT skip Step C, (d) a `create_fit_card` failure still returns listing + outfit rather than an empty reply. Then I'll drive the full pipeline with the walkthrough query, and force each error branch by hand: `max_price=1.0` for `no_results`, a malformed `new_item` for `outfit_failed`, and a monkey-patched exception in `create_fit_card` for `fit_card_failed`.

- **State management** — I'll give Claude Code the "State Management" section plus the `session` dict shape from the planning loop pseudo-code, and ask it to add init + update helpers so state is only mutated through named functions (not scattered dict writes). Verification: grep the codebase for direct `session[` writes outside `agent/state.py` — there should be none — and confirm the same `session` reference is threaded through every tool call rather than reconstructed at each step.

---

## A Complete Interaction (Step by Step)

Write out what a full user interaction looks like from start to finish — tool call by tool call. Use a specific example query.

**Example user query:** "I'm looking for a vintage graphic tee under $30. I mostly wear baggy jeans and chunky sneakers. What's out there and how would I style it?"

**Step 1:**
<!-- What does the agent do first? Which tool is called? With what input? -->
The agent calls `search_listings(description="vintage graphic tee", size=None, max_price=30.0)`. The tool filters `data/listings.json` by matching "vintage" + "graphic tee" against `category`/`title`/`style_tags` and enforcing `price <= 30.0`. It returns a ranked list of matches (e.g. `lst_006` "Graphic Tee — 2003 Tour Bootleg Style" at $24, `lst_002` Y2K butterfly baby tee at $18). The agent picks the top result and stores it in session state as `new_item`.

**Step 2:**
<!-- What happens next? What was returned from step 1? What tool is called now? -->
Because Step 1 returned at least one listing, the agent calls `suggest_outfit(new_item=<lst_006 dict>, wardrobe=<example_wardrobe>)`. The tool cross-references the new item's `colors` and `style_tags` against the user's wardrobe (baggy jeans `w_001`, chunky sneakers `w_007`, black denim jacket `w_006`) and returns a styling string, e.g. "Pair the faded band tee with your baggy dark-wash jeans and chunky white sneakers, denim jacket on top for a 90s streetwear layered look." The agent stores this as `outfit`.

**Step 3:**
<!-- Continue until the full interaction is complete -->
The agent calls `create_fit_card(outfit=<string from step 2>, new_item=<lst_006 dict>)`. The tool combines the outfit description with the item's title, price, and platform to produce a short social-post caption, e.g. "scored this 2003 bootleg tour tee off depop for $24 — wearing it with my baggy jeans + chunkies, denim jacket on top. full fit in stories." If Step 1 had returned no matches, the agent stops here and instead tells the user how to loosen the query (raise price, drop size, try "band tee" or "y2k tee") without calling Steps 2 or 3.

**Final output to user:**
<!-- What does the user actually see at the end? -->
A three-part reply: (1) the picked listing — "Graphic Tee — 2003 Tour Bootleg Style, $24 on Depop, good condition"; (2) the styling suggestion from Step 2; (3) the fit card caption from Step 3, formatted as ready-to-post copy.
