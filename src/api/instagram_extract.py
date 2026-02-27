"""
Instagram Recipe Extraction API v1.0
Extracts recipe data from Instagram posts using multi-strategy approach:
1. oEmbed API (public, no auth)
2. GraphQL endpoint (public posts)
3. Browser automation (Playwright) + caption parsing

Production-ready wrapper modeled after YouTube extraction API.
"""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, HttpUrl

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/instagram", tags=["instagram-extraction"])


# ── Request / Response Models ─────────────────────────────────

class InstagramExtractRequest(BaseModel):
    post_url: HttpUrl


class RecipeNutrition(BaseModel):
    calories: Optional[int] = None
    protein_grams: Optional[float] = None
    carbs_grams: Optional[float] = None
    fat_grams: Optional[float] = None


class RecipeInstruction(BaseModel):
    step: int
    text: str


class ExtractedRecipe(BaseModel):
    title: str
    source_url: str
    thumbnail_url: Optional[str] = None
    creator_username: Optional[str] = None
    nutrition: RecipeNutrition
    ingredients: List[str] = []
    instructions: List[RecipeInstruction] = []
    description: Optional[str] = None
    success_rate: float  # 0.0-1.0
    source_type: str = "instagram"
    extraction_methods: List[str] = []


class InstagramExtractResponse(BaseModel):
    success: bool
    recipe: Optional[ExtractedRecipe] = None
    error: Optional[str] = None


# ── Extraction Helpers ─────────────────────────────────────────

SHORTCODE_RE = re.compile(
    r"(?:instagram\.com|instagr\.am)/(?:p|reel|tv)/([A-Za-z0-9_-]+)"
)


def _extract_shortcode(url: str) -> str | None:
    m = SHORTCODE_RE.search(url)
    return m.group(1) if m else None


async def _extract_via_oembed(url: str) -> dict:
    """Use Instagram oEmbed (no auth, works for public posts)."""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"https://api.instagram.com/oembed/?url={url}",
                headers={"User-Agent": "Mozilla/5.0"},
            )
            if resp.status_code == 200:
                return resp.json()
    except Exception as e:
        logger.debug(f"oEmbed failed: {e}")
    return {}


async def _extract_via_graphql(url: str) -> str:
    """Try Instagram's public GraphQL endpoint for caption text."""
    import httpx

    shortcode = _extract_shortcode(url)
    if not shortcode:
        return ""

    graphql_url = f"https://www.instagram.com/p/{shortcode}/?__a=1&__d=dis"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                graphql_url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "X-IG-App-ID": "936619743392459",
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("items", [])
                if items:
                    caption = items[0].get("caption", {})
                    if caption:
                        return caption.get("text", "")
    except Exception as e:
        logger.debug(f"GraphQL failed: {e}")
    return ""


async def _extract_via_browser(url: str) -> dict:
    """Use Playwright to load the post and extract content."""
    result = {"caption": "", "screenshot_path": "", "meta_title": "", "meta_description": ""}

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.warning("Playwright not installed, skipping browser extraction")
        return result

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport={"width": 430, "height": 932},
                user_agent=(
                    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                    "Version/17.0 Mobile/15E148 Safari/604.1"
                ),
            )
            page = await context.new_page()

            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)

            # Dismiss login popups
            for selector in [
                'button:text("Not Now")',
                'button:text("Decline")',
                '[aria-label="Close"]',
            ]:
                try:
                    btn = page.locator(selector).first
                    if await btn.is_visible(timeout=1000):
                        await btn.click()
                        await page.wait_for_timeout(500)
                except Exception:
                    pass

            # Extract meta tags
            for tag, key in [
                ('meta[property="og:description"]', "meta_description"),
                ('meta[property="og:title"]', "meta_title"),
            ]:
                try:
                    el = await page.query_selector(tag)
                    if el:
                        content = await el.get_attribute("content")
                        if content:
                            result[key] = content
                except Exception:
                    pass

            # Extract caption spans
            caption_parts: list[str] = []
            try:
                captions = await page.query_selector_all(
                    'span[class*="x1lliihq"], div[class*="x1lliihq"]'
                )
                for cap in captions[:10]:
                    text = await cap.inner_text()
                    if text and len(text) > 20:
                        caption_parts.append(text)
            except Exception:
                pass

            if not caption_parts:
                try:
                    body_text = await page.inner_text("body")
                    if body_text:
                        caption_parts.append(body_text[:5000])
                except Exception:
                    pass

            result["caption"] = "\n".join(caption_parts)

            # Screenshot for potential Vision AI
            ss_dir = tempfile.mkdtemp(prefix="ig_extract_")
            ss_path = os.path.join(ss_dir, "screenshot.png")
            await page.screenshot(path=ss_path, full_page=False)
            result["screenshot_path"] = ss_path

            await browser.close()
    except Exception as e:
        logger.warning(f"Browser extraction error: {e}")

    return result


# ── Caption Parsing (macro/nutrition extraction) ───────────────

def _parse_macros_from_text(text: str) -> RecipeNutrition:
    """Extract macro numbers from caption text."""
    cal = _find_number(text, r"(\d{2,4})\s*(?:cal(?:ories?)?|kcal)")
    protein = _find_number(text, r"(\d{1,3})\s*g?\s*(?:protein|prot)")
    carbs = _find_number(text, r"(\d{1,3})\s*g?\s*(?:carbs?|carbohydrates?)")
    fat = _find_number(text, r"(\d{1,3})\s*g?\s*(?:fat|fats)")

    return RecipeNutrition(
        calories=int(cal) if cal else None,
        protein_grams=float(protein) if protein else None,
        carbs_grams=float(carbs) if carbs else None,
        fat_grams=float(fat) if fat else None,
    )


def _find_number(text: str, pattern: str) -> str | None:
    m = re.search(pattern, text, re.IGNORECASE)
    return m.group(1) if m else None


def _parse_ingredients_from_text(text: str) -> list[str]:
    """Extract ingredient lines from caption text."""
    ingredients: list[str] = []
    lines = text.split("\n")
    in_section = False

    for line in lines:
        stripped = line.strip()
        lower = stripped.lower()

        if re.match(r"(?:ingredients?|what you.?ll need|you.?ll need)", lower):
            in_section = True
            continue

        if in_section:
            if re.match(r"(?:instructions?|directions?|steps?|method|how to)", lower):
                break
            # Lines starting with - or • or numbers, or containing measurements
            if stripped and (
                stripped[0] in "-•·▪️" or
                re.match(r"^\d", stripped) or
                re.search(r"\b(?:cup|tbsp|tsp|oz|g|ml|lb)\b", lower)
            ):
                clean = re.sub(r"^[-•·▪️\d.)\s]+", "", stripped).strip()
                if clean:
                    ingredients.append(clean)

    # Fallback: look for measurement patterns anywhere
    if not ingredients:
        for line in lines:
            stripped = line.strip()
            if re.search(
                r"\b\d+(?:\.\d+)?\s*(?:cups?|tbsp|tsp|oz|g|grams?|ml|lb|lbs?)\b",
                stripped,
                re.IGNORECASE,
            ):
                clean = re.sub(r"^[-•·▪️\d.)\s]+", "", stripped).strip()
                if clean and len(clean) < 200:
                    ingredients.append(clean)

    return ingredients[:30]  # Cap at 30


def _parse_instructions_from_text(text: str) -> list[RecipeInstruction]:
    """Extract cooking instructions from caption text."""
    instructions: list[RecipeInstruction] = []
    lines = text.split("\n")
    in_section = False

    for line in lines:
        stripped = line.strip()
        lower = stripped.lower()

        if re.match(r"(?:instructions?|directions?|steps?|method|how to)", lower):
            in_section = True
            continue

        if in_section:
            if not stripped:
                continue
            if re.match(r"(?:nutrition|macros|calories|tags|tip[s:])", lower):
                break
            clean = re.sub(r"^(?:step\s*)?\d+[.):\s-]*", "", stripped, flags=re.IGNORECASE).strip()
            if clean and len(clean) > 10:
                instructions.append(
                    RecipeInstruction(step=len(instructions) + 1, text=clean)
                )

    return instructions[:20]


def _extract_title(text: str, meta_title: str = "") -> str:
    """Extract a recipe title from text."""
    if meta_title:
        # Instagram meta titles: "Username on Instagram: 'caption...'"
        m = re.search(r'[""](.*?)["""]', meta_title)
        if m:
            title = m.group(1).strip()
            if len(title) > 10:
                return title[:120]

    # First line of caption often is the title
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if lines:
        first = lines[0]
        # Remove hashtags and emojis from title
        title = re.sub(r"#\w+", "", first).strip()
        title = re.sub(r"[^\w\s',!.()-]", "", title).strip()
        if 5 < len(title) < 150:
            return title

    return "Instagram Recipe"


def _compute_success_rate(recipe: ExtractedRecipe) -> float:
    """Compute extraction success rate (fraction of fields populated)."""
    fields = [
        recipe.title != "Instagram Recipe",
        recipe.nutrition.calories is not None,
        recipe.nutrition.protein_grams is not None,
        recipe.nutrition.carbs_grams is not None,
        recipe.nutrition.fat_grams is not None,
        len(recipe.ingredients) > 0,
        len(recipe.instructions) > 0,
        recipe.description is not None and len(recipe.description) > 20,
    ]
    return sum(fields) / len(fields)


# ── Main Extraction Pipeline ──────────────────────────────────

async def extract_recipe_from_instagram(url: str) -> ExtractedRecipe:
    """Multi-strategy extraction pipeline for Instagram posts."""
    methods_used: list[str] = []
    all_text_parts: list[str] = []
    meta_title = ""
    creator = ""
    thumbnail = ""

    # Strategy 1: oEmbed
    oembed = await _extract_via_oembed(url)
    if oembed:
        methods_used.append("oembed")
        if oembed.get("title"):
            all_text_parts.append(oembed["title"])
        creator = oembed.get("author_name", "")
        thumbnail = oembed.get("thumbnail_url", "")

    # Strategy 2: GraphQL
    graphql_caption = await _extract_via_graphql(url)
    if graphql_caption:
        methods_used.append("graphql")
        all_text_parts.append(graphql_caption)

    # Strategy 3: Browser automation
    browser_data = await _extract_via_browser(url)
    if browser_data["caption"]:
        methods_used.append("browser")
        all_text_parts.append(browser_data["caption"])
    meta_title = meta_title or browser_data.get("meta_title", "")
    if browser_data.get("meta_description"):
        all_text_parts.append(browser_data["meta_description"])

    combined_text = "\n\n".join(all_text_parts)

    if not combined_text.strip():
        raise ValueError("Could not extract any content from Instagram post")

    # Parse structured data from combined text
    nutrition = _parse_macros_from_text(combined_text)
    ingredients = _parse_ingredients_from_text(combined_text)
    instructions = _parse_instructions_from_text(combined_text)
    title = _extract_title(combined_text, meta_title)

    # Build description from first ~200 chars of caption
    desc_text = combined_text.strip()[:300]
    desc_text = re.sub(r"#\w+", "", desc_text).strip()

    recipe = ExtractedRecipe(
        title=title,
        source_url=str(url),
        thumbnail_url=thumbnail or None,
        creator_username=creator or None,
        nutrition=nutrition,
        ingredients=ingredients,
        instructions=instructions,
        description=desc_text if len(desc_text) > 10 else None,
        success_rate=0.0,
        extraction_methods=methods_used,
    )
    recipe.success_rate = _compute_success_rate(recipe)

    return recipe


# ── API Endpoints ──────────────────────────────────────────────

@router.post("/extract", response_model=InstagramExtractResponse)
async def extract_instagram_recipe(req: InstagramExtractRequest):
    """Extract recipe data from an Instagram post URL.

    Tries oEmbed → GraphQL → Browser automation in sequence.
    Returns structured recipe with macros, ingredients, and instructions.
    """
    url = str(req.post_url)
    shortcode = _extract_shortcode(url)
    if not shortcode:
        raise HTTPException(
            status_code=400,
            detail="Invalid Instagram URL. Expected format: instagram.com/p/SHORTCODE/",
        )

    try:
        recipe = await extract_recipe_from_instagram(url)
        return InstagramExtractResponse(success=True, recipe=recipe)
    except Exception as e:
        logger.error(f"Instagram extraction failed for {url}: {e}")
        return InstagramExtractResponse(success=False, error=str(e))


@router.get("/health")
async def health():
    return {"status": "ok", "service": "instagram-extraction", "version": "1.0.0"}
