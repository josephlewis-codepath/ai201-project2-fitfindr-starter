"""
tools.py

The three required FitFindr tools. Each tool is a standalone function that
can be called and tested independently before being wired into the agent loop.

Complete and test each tool before moving to agent.py.

Tools:
    search_listings(description, size, max_price)  → list[dict]
    suggest_outfit(new_item, wardrobe)              → str
    create_fit_card(outfit, new_item)               → str
"""

import os
import re

from dotenv import load_dotenv
from groq import Groq

from utils.data_loader import load_listings

load_dotenv()

_GROQ_MODEL = "openai/gpt-oss-120b"


# ── Groq client ───────────────────────────────────────────────────────────────

def _get_groq_client():
    """Initialize and return a Groq client using GROQ_API_KEY from .env."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY not set. Add it to a .env file in the project root."
        )
    return Groq(api_key=api_key)


# ── Tool 1: search_listings ───────────────────────────────────────────────────

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
        Returns an empty list if nothing matches — does NOT raise an exception.

    Each listing dict has the following fields:
        id, title, description, category, style_tags (list), size,
        condition, price (float), colors (list), brand, platform

    TODO:
        1. Load all listings with load_listings().
        2. Filter by max_price and size (if provided).
        3. Score each remaining listing by keyword overlap with `description`.
        4. Drop any listings with a score of 0 (no relevant matches).
        5. Sort by score, highest first, and return the listing dicts.

    Before writing code, fill in the Tool 1 section of planning.md.
    """
    listings = load_listings()

    if max_price is not None:
        listings = [item for item in listings if item["price"] <= max_price]

    if size is not None:
        size_needle = size.lower()
        listings = [item for item in listings if size_needle in item["size"].lower()]

    tokens = [t for t in re.findall(r"[a-z0-9]+", description.lower()) if len(t) > 1]

    scored: list[tuple[int, float, dict]] = []
    for item in listings:
        blob_parts = [
            item.get("title", ""),
            item.get("category", ""),
            " ".join(item.get("style_tags", [])),
        ]
        blob = " ".join(blob_parts).lower()
        score = sum(1 for t in set(tokens) if t in blob)
        if score > 0:
            scored.append((score, item["price"], item))

    scored.sort(key=lambda row: (-row[0], row[1]))
    return [row[2] for row in scored]


# ── Tool 2: suggest_outfit ────────────────────────────────────────────────────

def suggest_outfit(new_item: dict, wardrobe: dict) -> str:
    """
    Given a thrifted item and the user's wardrobe, suggest 1–2 complete outfits.

    Args:
        new_item: A listing dict (the item the user is considering buying).
        wardrobe: A wardrobe dict with an 'items' key containing a list of
                  wardrobe item dicts. May be empty — handle this gracefully.

    Returns:
        A non-empty string with outfit suggestions.
        If the wardrobe is empty, offer general styling advice for the item
        rather than raising an exception or returning an empty string.

    TODO:
        1. Check whether wardrobe['items'] is empty.
        2. If empty: call the LLM with a prompt for general styling ideas
           (what kinds of items pair well, what vibe it suits, etc.).
        3. If not empty: format the wardrobe items into a prompt and ask
           the LLM to suggest specific outfit combinations using the new item
           and named pieces from the wardrobe.
        4. Return the LLM's response as a string.

    Before writing code, fill in the Tool 2 section of planning.md.
    """
    item_line = (
        f"{new_item.get('title', 'a thrifted piece')} "
        f"(category: {new_item.get('category', 'unknown')}, "
        f"colors: {', '.join(new_item.get('colors', [])) or 'unspecified'}, "
        f"style tags: {', '.join(new_item.get('style_tags', [])) or 'none'})"
    )

    items = wardrobe.get("items", []) if wardrobe else []

    if not items:
        user_prompt = (
            f"A user is considering thrifting this piece: {item_line}.\n"
            "They have not entered any wardrobe items yet, so give general styling "
            "advice: what kinds of bottoms, shoes, and layers would pair well, and "
            "what overall vibe the piece suits. Keep it to 2-4 sentences and do "
            "not name specific items the user hasn't mentioned."
        )
    else:
        wardrobe_lines = []
        for w in items:
            wardrobe_lines.append(
                f"- {w.get('name', 'unnamed item')} "
                f"[{w.get('category', 'uncategorized')}; "
                f"colors: {', '.join(w.get('colors', [])) or 'n/a'}; "
                f"tags: {', '.join(w.get('style_tags', [])) or 'n/a'}]"
            )
        wardrobe_block = "\n".join(wardrobe_lines)
        user_prompt = (
            f"A user is considering thrifting this piece: {item_line}.\n\n"
            f"Their wardrobe contains:\n{wardrobe_block}\n\n"
            "Suggest 1-2 specific outfit combinations that pair the new piece "
            "with named items from the wardrobe above. Reference wardrobe items "
            "by their exact name. Include a concrete styling tip (tucking, "
            "cuffing, layering). Keep it to 2-4 sentences total."
        )

    client = _get_groq_client()
    response = client.chat.completions.create(
        model=_GROQ_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are FitFindr, a stylist for secondhand fashion shoppers. "
                    "Speak casually and give concrete, wearable outfit advice."
                ),
            },
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.7,
    )
    return response.choices[0].message.content.strip()


# ── Tool 3: create_fit_card ───────────────────────────────────────────────────

def create_fit_card(outfit: str, new_item: dict) -> str:
    """
    Generate a short, shareable outfit caption for the thrifted find.

    Args:
        outfit:   The outfit suggestion string from suggest_outfit().
        new_item: The listing dict for the thrifted item.

    Returns:
        A 2–4 sentence string usable as an Instagram/TikTok caption.
        If outfit is empty or missing, return a descriptive error message
        string — do NOT raise an exception.

    The caption should:
    - Feel casual and authentic (like a real OOTD post, not a product description)
    - Mention the item name, price, and platform naturally (once each)
    - Capture the outfit vibe in specific terms
    - Sound different each time for different inputs (use higher LLM temperature)

    TODO:
        1. Guard against an empty or whitespace-only outfit string.
        2. Build a prompt that gives the LLM the item details and the outfit,
           and asks for a caption matching the style guidelines above.
        3. Call the LLM and return the response.

    Before writing code, fill in the Tool 3 section of planning.md.
    """
    if not outfit or not outfit.strip():
        return (
            "[fit_card_error] Cannot generate a caption without an outfit "
            "suggestion — call suggest_outfit first and pass its output in."
        )

    title = new_item.get("title", "a thrifted find")
    price = new_item.get("price")
    platform = new_item.get("platform", "resale")
    price_str = f"${price:.0f}" if isinstance(price, (int, float)) else "a steal"

    user_prompt = (
        f"Write a 2-4 sentence Instagram/TikTok caption for an outfit-of-the-day "
        f"post. The thrifted piece is: {title}, {price_str}, from {platform}. "
        f"The outfit is: {outfit.strip()}\n\n"
        "Rules: casual, first-person, lowercase-social-media voice. Mention the "
        f"item name, {price_str}, and {platform} naturally (each exactly once). "
        "Use at most one emoji. Do not sound like a product listing."
    )

    client = _get_groq_client()
    response = client.chat.completions.create(
        model=_GROQ_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You write short, authentic-sounding outfit captions for a "
                    "secondhand fashion app. Vary phrasing between calls."
                ),
            },
            {"role": "user", "content": user_prompt},
        ],
        temperature=1.0,
    )
    return response.choices[0].message.content.strip()
