"""
TikTok Recipe Extraction API v1.0
Extracts recipe data from TikTok videos using yt-dlp + browser automation.

Based on PROTO's proto3_tiktok.py, productionized for FitBites.
Mirrors structure of youtube_extract.py.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, HttpUrl

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/tiktok", tags=["tiktok-extraction"])

YTDLP_PATH = "/home/user/.local/bin/yt-dlp"


# ── Request / Response models ──────────────────────────────────────────────

class TikTokExtractRequest(BaseModel):
    video_url: HttpUrl


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
    creator_name: Optional[str] = None
    creator_url: Optional[str] = None
    nutrition: RecipeNutrition
    ingredients: List[str] = []
    instructions: List[RecipeInstruction] = []
    ingredients_raw: Optional[str] = None
    success_rate: float  # 0.0 to 1.0
    source_type: str = "tiktok"
    caption: Optional[str] = None
    has_subtitles: bool = False
    view_count: Optional[int] = None
    like_count: Optional[int] = None


class TikTokExtractResponse(BaseModel):
    success: bool
    recipe: Optional[ExtractedRecipe] = None
    error: Optional[str] = None


# ── Extraction logic ───────────────────────────────────────────────────────

def _clean_subtitle_text(raw: str) -> str:
    """Parse VTT/SRT subtitle content into clean text."""
    lines = []
    for line in raw.split("\n"):
        line = line.strip()
        if (
            not line
            or re.match(r"^\d{2}:\d{2}", line)
            or line.startswith("WEBVTT")
            or re.match(r"^\d+$", line)
            or "-->" in line
            or line.startswith("NOTE")
            or line.startswith("Kind")
        ):
            continue
        line = re.sub(r"<[^>]+>", "", line)
        line = re.sub(r"\s+", " ", line).strip()
        if line and line not in lines[-1:]:
            lines.append(line)
    return " ".join(lines)


def extract_via_ytdlp(url: str) -> dict:
    """Use yt-dlp to get TikTok metadata, description, and subtitles."""
    result = {
        "title": "",
        "description": "",
        "subtitles": "",
        "thumbnail_url": None,
        "creator": "",
        "creator_url": "",
        "view_count": None,
        "like_count": None,
        "duration": 0,
    }

    try:
        cmd = [
            YTDLP_PATH, "--no-download", "--print-json",
            "--no-warnings", "--no-check-certificates",
            url,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if proc.returncode == 0 and proc.stdout.strip():
            data = json.loads(proc.stdout.strip().split("\n")[0])
            result["title"] = data.get("title", "") or data.get("fulltitle", "")
            result["description"] = data.get("description", "")
            result["thumbnail_url"] = data.get("thumbnail")
            result["duration"] = data.get("duration", 0) or 0
            result["view_count"] = data.get("view_count")
            result["like_count"] = data.get("like_count")

            uploader = data.get("uploader", "") or data.get("creator", "")
            result["creator"] = uploader
            result["creator_url"] = data.get("uploader_url", "") or (
                f"https://www.tiktok.com/@{uploader}" if uploader else ""
            )

            # Subtitles
            all_subs = {**data.get("subtitles", {}), **data.get("automatic_captions", {})}
            if all_subs:
                for lang in ("en", "en-US", "eng"):
                    if lang in all_subs:
                        result["subtitles"] = _fetch_subtitle_text(all_subs[lang])
                        break
                if not result["subtitles"] and all_subs:
                    first = list(all_subs.keys())[0]
                    result["subtitles"] = _fetch_subtitle_text(all_subs[first])

    except subprocess.TimeoutExpired:
        logger.warning(f"[tiktok] yt-dlp timeout for {url}")
    except Exception as e:
        logger.warning(f"[tiktok] yt-dlp error: {e}")

    # Fallback: download subs separately
    if not result["subtitles"]:
        result["subtitles"] = _download_subtitles(url)

    return result


def _fetch_subtitle_text(sub_entries: list) -> str:
    """Fetch subtitle text from yt-dlp subtitle entries."""
    import requests

    for entry in sub_entries:
        url = entry.get("url", "")
        if url:
            try:
                resp = requests.get(url, timeout=10)
                if resp.status_code == 200:
                    return _clean_subtitle_text(resp.text)
            except Exception:
                pass
    return ""


def _download_subtitles(url: str) -> str:
    """Download subtitles via yt-dlp as fallback."""
    with tempfile.TemporaryDirectory() as sub_dir:
        try:
            cmd = [
                YTDLP_PATH, "--write-auto-sub", "--write-sub",
                "--sub-lang", "en", "--skip-download",
                "--no-warnings", "--no-check-certificates",
                "-o", os.path.join(sub_dir, "%(id)s"),
                url,
            ]
            subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            for f in os.listdir(sub_dir):
                if f.endswith((".vtt", ".srt")):
                    with open(os.path.join(sub_dir, f)) as fh:
                        return _clean_subtitle_text(fh.read())
        except Exception:
            pass
    return ""


def extract_nutrition(text: str) -> RecipeNutrition:
    """Extract macro information from combined text."""
    nutrition = RecipeNutrition()

    # Calories
    for pat in [r"(\d{2,4})\s*(?:calories|kcal|cal)\b", r"calories?\s*[:\-]?\s*(\d{2,4})"]:
        m = re.search(pat, text, re.I)
        if m:
            val = int(m.group(1))
            if 50 <= val <= 5000:
                nutrition.calories = val
                break

    # Protein
    for pat in [
        r"(\d+(?:\.\d+)?)\s*(?:g|grams?)?\s*(?:of\s+)?protein",
        r"protein\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*(?:g|grams?)?",
    ]:
        m = re.search(pat, text, re.I)
        if m:
            nutrition.protein_grams = float(m.group(1))
            break

    # Carbs
    for pat in [
        r"(\d+(?:\.\d+)?)\s*(?:g|grams?)?\s*(?:of\s+)?(?:carbs?|carbohydrates?)",
        r"(?:carbs?|carbohydrates?)\s*[:\-]?\s*(\d+(?:\.\d+)?)",
    ]:
        m = re.search(pat, text, re.I)
        if m:
            nutrition.carbs_grams = float(m.group(1))
            break

    # Fat
    for pat in [
        r"(\d+(?:\.\d+)?)\s*(?:g|grams?)?\s*(?:of\s+)?fat\b",
        r"\bfat\s*[:\-]?\s*(\d+(?:\.\d+)?)",
    ]:
        m = re.search(pat, text, re.I)
        if m:
            nutrition.fat_grams = float(m.group(1))
            break

    return nutrition


def extract_ingredients(text: str) -> List[str]:
    """Extract ingredient mentions from text."""
    ingredients: list[str] = []
    seen: set[str] = set()

    quantity_pat = (
        r"(\d+(?:\.\d+)?(?:/\d+)?)\s*"
        r"(?:cups?|tbsp|tablespoons?|tsp|teaspoons?|oz|ounces?|lbs?|pounds?|g|grams?|ml|kg|"
        r"scoops?|servings?|slices?|pieces?|cans?|pkg|packages?)\s+"
        r"(?:of\s+)?([a-zA-Z][a-zA-Z\s]{2,30})"
    )

    for m in re.finditer(quantity_pat, text, re.I):
        item = f"{m.group(1)} {m.group(2).strip()}".strip().lower()
        if item not in seen:
            seen.add(item)
            ingredients.append(item)

    return ingredients[:25]


def extract_instructions(text: str) -> List[RecipeInstruction]:
    """Extract cooking steps from text."""
    instructions: list[RecipeInstruction] = []

    # Numbered steps
    for m in re.finditer(r"(?:step\s*)?(\d+)[\.\)]\s*([^.]{10,150})", text, re.I):
        instructions.append(RecipeInstruction(step=int(m.group(1)), text=m.group(2).strip()))

    if instructions:
        return instructions[:15]

    # Action-verb sentences
    action_verbs = [
        "add", "mix", "stir", "combine", "heat", "cook", "bake", "preheat",
        "slice", "cut", "chop", "pour", "blend", "whisk", "simmer", "boil",
        "season", "marinate", "sauté", "fry", "grill", "roast", "dice",
    ]
    step = 1
    for sentence in re.split(r"[.!?]+", text):
        sentence = sentence.strip()
        if any(v in sentence.lower() for v in action_verbs) and 15 < len(sentence) < 200:
            instructions.append(RecipeInstruction(step=step, text=sentence))
            step += 1
            if step > 15:
                break

    return instructions


def calculate_success_rate(
    nutrition: RecipeNutrition,
    has_title: bool,
    has_creator: bool,
    has_thumbnail: bool,
    has_ingredients: bool,
    has_instructions: bool,
    has_caption: bool,
) -> float:
    """Calculate extraction completeness (7 fields)."""
    fields = [
        nutrition.calories is not None,
        nutrition.protein_grams is not None,
        has_title,
        has_creator,
        has_thumbnail,
        has_ingredients,
        has_instructions,
    ]
    return sum(1 for f in fields if f) / len(fields)


def extract_recipe_from_tiktok(video_url: str) -> ExtractedRecipe:
    """
    Full extraction pipeline for a single TikTok video.
    Uses yt-dlp for metadata + subtitles.
    """
    if not Path(YTDLP_PATH).exists():
        raise HTTPException(status_code=500, detail="yt-dlp not installed")

    yt_data = extract_via_ytdlp(video_url)

    # Combine all text sources
    all_text = " ".join(
        filter(None, [yt_data["title"], yt_data["description"], yt_data["subtitles"]])
    )

    if not all_text.strip():
        raise HTTPException(status_code=404, detail="No text content extracted from video")

    # Parse recipe components
    nutrition = extract_nutrition(all_text)
    ingredients = extract_ingredients(all_text)
    instructions = extract_instructions(all_text)

    title = yt_data["title"] or "Untitled TikTok Recipe"

    success_rate = calculate_success_rate(
        nutrition,
        has_title=bool(yt_data["title"]),
        has_creator=bool(yt_data["creator"]),
        has_thumbnail=bool(yt_data["thumbnail_url"]),
        has_ingredients=bool(ingredients),
        has_instructions=bool(instructions),
        has_caption=bool(yt_data["description"]),
    )

    return ExtractedRecipe(
        title=title,
        source_url=video_url,
        thumbnail_url=yt_data["thumbnail_url"],
        creator_name=yt_data["creator"],
        creator_url=yt_data["creator_url"],
        nutrition=nutrition,
        ingredients=ingredients,
        instructions=instructions,
        ingredients_raw=", ".join(ingredients[:10]) if ingredients else None,
        success_rate=success_rate,
        source_type="tiktok",
        caption=yt_data["description"][:500] if yt_data["description"] else None,
        has_subtitles=bool(yt_data["subtitles"]),
        view_count=yt_data["view_count"],
        like_count=yt_data["like_count"],
    )


# ── API Routes ─────────────────────────────────────────────────────────────

@router.post("/extract", response_model=TikTokExtractResponse)
async def extract_tiktok_recipe(request: TikTokExtractRequest):
    """
    Extract recipe data from a TikTok video URL.

    Uses yt-dlp for metadata, description, and auto-captions.
    Returns nutrition, ingredients, instructions, and creator info.
    """
    try:
        recipe = await asyncio.get_event_loop().run_in_executor(
            None, extract_recipe_from_tiktok, str(request.video_url)
        )
        return TikTokExtractResponse(success=True, recipe=recipe)
    except HTTPException as e:
        return TikTokExtractResponse(success=False, error=e.detail)
    except Exception as e:
        logger.error(f"[tiktok] Extraction failed: {e}", exc_info=True)
        return TikTokExtractResponse(success=False, error=f"Extraction failed: {str(e)}")


@router.post("/extract/batch", response_model=list[TikTokExtractResponse])
async def extract_tiktok_batch(urls: list[HttpUrl]):
    """Extract recipes from multiple TikTok URLs (max 10 per request)."""
    if len(urls) > 10:
        raise HTTPException(status_code=400, detail="Max 10 URLs per batch request")

    results = []
    for url in urls:
        try:
            recipe = await asyncio.get_event_loop().run_in_executor(
                None, extract_recipe_from_tiktok, str(url)
            )
            results.append(TikTokExtractResponse(success=True, recipe=recipe))
        except Exception as e:
            results.append(TikTokExtractResponse(success=False, error=str(e)))
        await asyncio.sleep(1)  # Rate limit

    return results


@router.get("/health")
async def tiktok_extractor_health():
    """Check if TikTok extraction service is available."""
    ytdlp_installed = Path(YTDLP_PATH).exists()
    return {
        "status": "healthy" if ytdlp_installed else "degraded",
        "ytdlp_installed": ytdlp_installed,
        "version": "v1.0",
        "features": [
            "yt-dlp_metadata",
            "subtitle_extraction",
            "nutrition_parsing",
            "ingredient_extraction",
            "instruction_extraction",
            "batch_extraction",
            "creator_info",
        ],
    }
