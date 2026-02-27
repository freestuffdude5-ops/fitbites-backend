"""
YouTube Recipe Extraction API v2
Extracts recipe data from YouTube videos using auto-captions
Production-ready wrapper around yt-dlp

Changes in v2:
- Added thumbnail_url and channel_name extraction
- Improved carbs/fat regex patterns
- Parses recipe title from transcript
- Detects and SKIPS multi-recipe videos
"""

import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, Optional, Tuple

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, HttpUrl


router = APIRouter(prefix="/api/v1/youtube", tags=["youtube-extraction"])


class YouTubeExtractRequest(BaseModel):
    video_url: HttpUrl
    
class RecipeNutrition(BaseModel):
    calories: Optional[int] = None
    protein_grams: Optional[float] = None
    carbs_grams: Optional[float] = None
    fat_grams: Optional[float] = None

class ExtractedRecipe(BaseModel):
    title: str
    source_url: str
    thumbnail_url: Optional[str] = None  # NEW
    channel_name: Optional[str] = None   # NEW
    nutrition: RecipeNutrition
    ingredients_raw: Optional[str] = None
    success_rate: float  # 0.0 to 1.0 (fraction of fields extracted)
    source_type: str = "youtube"


class YouTubeExtractResponse(BaseModel):
    success: bool
    recipe: Optional[ExtractedRecipe] = None
    error: Optional[str] = None


def detect_multi_recipe_video(title: str, text: str) -> Tuple[bool, Optional[str]]:
    """
    Detect if video contains multiple recipes.
    Returns (is_multi_recipe, error_message)
    
    Detection patterns:
    - Title: "4 meals", "3 recipes", "X ways"
    - Caption: "Recipe 1:", "Meal 2:", numbered lists, "first recipe", "second recipe"
    """
    # Check title for multi-recipe indicators
    multi_recipe_title_patterns = [
        r'\d+\s+.*?\b(?:meals?|recipes?|dishes?|ways?|ideas?|options?)\b',  # "4 High Protein Meals"
        r'(?:meals?|recipes?)\s+prep',
        r'multiple|various|several',
    ]
    
    for pattern in multi_recipe_title_patterns:
        if re.search(pattern, title, re.IGNORECASE):
            return True, "Multi-recipe video detected (title indicates multiple recipes)"
    
    # Check transcript for multi-recipe structure
    multi_recipe_text_patterns = [
        r'(?:recipe|meal)\s*(?:#|number|num)?\s*[12345]',  # "Recipe 1", "Meal #2"
        r'(?:first|second|third|fourth|fifth)\s+(?:recipe|meal|option|dish)',
        r'(?:next|another)\s+(?:recipe|meal)',
        r'recipe\s+(?:one|two|three|four|five)',
        r'our\s+(?:first|second|third)\s+recipe',  # "Our first recipe"
    ]
    
    matches = 0
    for pattern in multi_recipe_text_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            matches += 1
            if matches >= 1:  # Lower threshold - even 1 match is strong signal
                return True, "Multi-recipe video detected (transcript contains multiple recipe segments)"
    
    return False, None


def extract_recipe_title_from_text(video_title: str, text: str) -> str:
    """
    Parse individual recipe title from transcript.
    Falls back to video title if no specific recipe title found.
    
    Patterns:
    - "Today we're making [Recipe Name]"
    - "[Recipe Name] recipe"
    - Capitalized dish names
    
    Conservative approach: only extract if high confidence, otherwise use video title.
    """
    # Pattern 1: "making/cooking [Capitalized Recipe Name]"
    # Only match if followed by proper punctuation or end
    making_patterns = [
        r'(?:making|cooking|preparing)\s+(?:a|an|my|this)?\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*(?:\s+[A-Z][a-z]+)?)\s*[,\.\!]',
    ]
    
    for pattern in making_patterns:
        match = re.search(pattern, text[:1000], re.IGNORECASE)
        if match:
            potential_title = match.group(1).strip()
            # Must be at least 2 words and not contain generic terms
            words = potential_title.split()
            if len(words) >= 2 and not re.search(r'\b(video|today|here|sure|easy|simple|quick|recipe|spray|oil|bit)\b', potential_title, re.IGNORECASE):
                return potential_title
    
    # Pattern 2: Look for recipe name in first 200 chars (intro)
    # "This [Dish Name] is..."
    intro_patterns = [
        r'^.{0,50}([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\s+(?:is|recipe|has)',
    ]
    
    for pattern in intro_patterns:
        match = re.search(pattern, text[:200])
        if match:
            potential_title = match.group(1).strip()
            if not re.search(r'\b(This|Today|Here|Welcome)\b', potential_title):
                return potential_title
    
    # Fallback: use video title (most reliable)
    return video_title


def extract_nutrition_from_text(text: str) -> Dict:
    """
    Extract nutrition information from caption text using improved regex patterns.
    
    Handles various formats:
    - "650 calories"
    - "64g of protein" / "64 grams protein"
    - "11g fat" / "11 grams of fat"
    - "50 carbs" / "50g carbohydrates"
    - Decimal values: "64.5g protein"
    """
    nutrition = {
        "calories": None,
        "protein_grams": None,
        "carbs_grams": None,
        "fat_grams": None
    }
    
    # Calories: matches "650 calories", "650kcal", "650 cal"
    cal_patterns = [
        r'(\d+)\s*(?:calories|kcal|cal)\b',
        r'(\d+)\s*(?:cals?)\b',
        r'calories?\s*[:\-]?\s*(\d+)',
    ]
    for pattern in cal_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            nutrition["calories"] = int(match.group(1))
            break
    
    # Protein: matches "64g protein", "64.5 grams of protein", "protein 64g"
    protein_patterns = [
        r'(\d+(?:\.\d+)?)\s*(?:g|grams?)\s*(?:of\s+)?protein',
        r'protein\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*(?:g|grams?)?',
        r'(\d+(?:\.\d+)?)\s*(?:g|grams?)\s+protein',
    ]
    for pattern in protein_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            nutrition["protein_grams"] = float(match.group(1))
            break
    
    # Carbs: IMPROVED - more patterns, handles decimals
    carb_patterns = [
        r'(\d+(?:\.\d+)?)\s*(?:g|grams?)?\s*(?:of\s+)?(?:carbs?|carbohydrates?)\b',
        r'(?:carbs?|carbohydrates?)\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*(?:g|grams?)?',
        r'(\d+(?:\.\d+)?)\s*(?:g|grams?)\s+(?:carbs?|carbohydrates?)',
        r'\b(\d+(?:\.\d+)?)\s+(?:g\s+)?carbs?\b',  # "45 carbs" or "45 g carbs"
        r'\bcarbs?\s*(\d+(?:\.\d+)?)\b',  # "carbs 45"
    ]
    for pattern in carb_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            nutrition["carbs_grams"] = float(match.group(1))
            break
    
    # Fat: IMPROVED - more patterns, handles decimals
    fat_patterns = [
        r'(\d+(?:\.\d+)?)\s*(?:g|grams?)?\s*(?:of\s+)?fat\b',
        r'\bfat\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*(?:g|grams?)?',
        r'(\d+(?:\.\d+)?)\s*(?:g|grams?)\s+fat\b',
        r'\b(\d+(?:\.\d+)?)\s+(?:g\s+)?fat\b',  # "11 fat" or "11 g fat"
        r'\bfat\s*(\d+(?:\.\d+)?)\b',  # "fat 11"
    ]
    for pattern in fat_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            nutrition["fat_grams"] = float(match.group(1))
            break
    
    return nutrition


def extract_ingredients_section(text: str) -> Optional[str]:
    """
    Extract ingredients section from caption text.
    Returns raw text that can be parsed by frontend or reviewed by human.
    """
    # Look for "ingredients" keyword followed by content
    patterns = [
        r'ingredients?[:\s]+(.*?)(?=instructions?|steps?|method|directions?|\n\n)',
        r'(?:what you(?:\'ll)? need|you(?:\'ll)? need)[:\s]+(.*?)(?=instructions?|steps?|\n\n)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            ingredients_text = match.group(1).strip()
            # Clean up but preserve structure
            ingredients_text = re.sub(r'\s+', ' ', ingredients_text)
            return ingredients_text[:500]  # Limit length
    
    return None


def calculate_success_rate(nutrition: Dict, has_thumbnail: bool, has_channel: bool) -> float:
    """
    Calculate what percentage of key fields were extracted.
    Key fields: calories, protein, fat, carbs, thumbnail, channel (6 total)
    """
    fields = [
        nutrition.get("calories"),
        nutrition.get("protein_grams"),
        nutrition.get("fat_grams"),
        nutrition.get("carbs_grams"),
        has_thumbnail,
        has_channel,
    ]
    extracted = sum(1 for f in fields if f is not None and f is not False)
    return extracted / len(fields)


def extract_recipe_from_youtube(video_url: str) -> ExtractedRecipe:
    """
    Extract recipe data from YouTube video using yt-dlp and auto-captions.
    
    Raises:
        HTTPException: If extraction fails or video contains multiple recipes
    """
    ytdlp_path = "/home/user/.local/bin/yt-dlp"
    
    # Check if yt-dlp exists
    if not Path(ytdlp_path).exists():
        raise HTTPException(
            status_code=500,
            detail="yt-dlp not installed. Run: pip install yt-dlp"
        )
    
    # Create temp directory for caption files
    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            # Get video metadata (title, thumbnail, channel)
            metadata_cmd = [
                ytdlp_path,
                "--print", "%(title)s|||%(thumbnail)s|||%(uploader)s",
                video_url
            ]
            metadata_result = subprocess.run(
                metadata_cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if metadata_result.returncode != 0:
                raise HTTPException(
                    status_code=400,
                    detail=f"Failed to fetch video: {metadata_result.stderr}"
                )
            
            # Parse metadata
            metadata_parts = metadata_result.stdout.strip().split("|||")
            video_title = metadata_parts[0] if len(metadata_parts) > 0 else "Unknown"
            thumbnail_url = metadata_parts[1] if len(metadata_parts) > 1 else None
            channel_name = metadata_parts[2] if len(metadata_parts) > 2 else None
            
            # Download auto-captions
            caption_cmd = [
                ytdlp_path,
                "--write-auto-subs",
                "--sub-lang", "en",
                "--skip-download",
                "--output", f"{temp_dir}/%(title)s.%(ext)s",
                video_url
            ]
            
            caption_result = subprocess.run(
                caption_cmd,
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if caption_result.returncode != 0:
                raise HTTPException(
                    status_code=400,
                    detail=f"Failed to download captions: {caption_result.stderr}"
                )
            
            # Find VTT file
            vtt_files = list(Path(temp_dir).glob("*.en.vtt"))
            if not vtt_files:
                raise HTTPException(
                    status_code=404,
                    detail="No English auto-captions found for this video"
                )
            
            # Read and parse captions
            vtt_content = vtt_files[0].read_text(encoding='utf-8')
            
            # Clean VTT formatting
            text = re.sub(r'<[^>]+>', '', vtt_content)  # Remove HTML tags
            text = re.sub(r'\n[0-9:\.]+\s*-->', ' ', text)  # Remove timestamps
            text = re.sub(r'^WEBVTT.*\n', '', text)
            text = re.sub(r'^\s*\d+\s*$', '', text, flags=re.MULTILINE)
            text = text.strip()
            
            # CHECK FOR MULTI-RECIPE VIDEO (return error if detected)
            is_multi_recipe, multi_recipe_error = detect_multi_recipe_video(video_title, text)
            if is_multi_recipe:
                raise HTTPException(
                    status_code=400,
                    detail=f"Multi-recipe video detected. FitBites only extracts single-recipe videos. {multi_recipe_error}"
                )
            
            # Extract recipe title from transcript (not video title)
            recipe_title = extract_recipe_title_from_text(video_title, text)
            
            # Extract nutrition and ingredients
            nutrition = extract_nutrition_from_text(text)
            ingredients = extract_ingredients_section(text)
            success_rate = calculate_success_rate(nutrition, bool(thumbnail_url), bool(channel_name))
            
            return ExtractedRecipe(
                title=recipe_title,
                source_url=str(video_url),
                thumbnail_url=thumbnail_url,
                channel_name=channel_name,
                nutrition=RecipeNutrition(**nutrition),
                ingredients_raw=ingredients,
                success_rate=success_rate,
                source_type="youtube"
            )
            
        except subprocess.TimeoutExpired:
            raise HTTPException(
                status_code=504,
                detail="Video extraction timed out"
            )
        except Exception as e:
            if isinstance(e, HTTPException):
                raise
            raise HTTPException(
                status_code=500,
                detail=f"Extraction failed: {str(e)}"
            )


@router.post("/extract", response_model=YouTubeExtractResponse)
async def extract_youtube_recipe(request: YouTubeExtractRequest):
    """
    Extract recipe data from a YouTube video URL.
    
    Returns nutrition information (calories, protein, fat, carbs), thumbnail, 
    channel name, and ingredients extracted from auto-generated captions.
    
    **Success rate:** Indicates what fraction of fields were extracted (6 fields total).
    - 1.0 = All fields (calories, protein, fat, carbs, thumbnail, channel)
    - 0.83 = 5/6 fields
    - 0.67 = 4/6 fields
    
    **Multi-recipe videos:** Videos with multiple recipes will return an error.
    FitBites only extracts single-recipe videos to ensure thumbnail matches recipe.
    
    **Note:** Not all videos will have complete nutrition information in captions.
    """
    try:
        recipe = extract_recipe_from_youtube(str(request.video_url))
        return YouTubeExtractResponse(
            success=True,
            recipe=recipe
        )
    except HTTPException as e:
        return YouTubeExtractResponse(
            success=False,
            error=e.detail
        )
    except Exception as e:
        return YouTubeExtractResponse(
            success=False,
            error=f"Unexpected error: {str(e)}"
        )


@router.get("/health")
async def youtube_extractor_health():
    """Check if YouTube extraction service is available."""
    ytdlp_path = "/home/user/.local/bin/yt-dlp"
    ytdlp_installed = Path(ytdlp_path).exists()
    
    return {
        "status": "healthy" if ytdlp_installed else "degraded",
        "ytdlp_installed": ytdlp_installed,
        "ytdlp_path": ytdlp_path if ytdlp_installed else None,
        "version": "v2",
        "features": [
            "thumbnail_extraction",
            "channel_name_extraction",
            "improved_carbs_fat_regex",
            "recipe_title_parsing",
            "multi_recipe_detection"
        ]
    }
