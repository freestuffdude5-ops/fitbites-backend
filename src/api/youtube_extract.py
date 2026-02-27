"""
YouTube Recipe Extraction API
Extracts recipe data from YouTube videos using auto-captions
Production-ready wrapper around yt-dlp
"""

import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, HttpUrl


router = APIRouter(prefix="/api/v1/youtube", tags=["youtube-extraction"])


class YouTubeExtractRequest(BaseModel):
    video_url: HttpUrl
    
class RecipeNutrition(BaseModel):
    calories: Optional[int] = None
    protein_grams: Optional[int] = None
    carbs_grams: Optional[int] = None
    fat_grams: Optional[int] = None

class ExtractedRecipe(BaseModel):
    title: str
    source_url: str
    nutrition: RecipeNutrition
    ingredients_raw: Optional[str] = None
    success_rate: float  # 0.0 to 1.0 (fraction of fields extracted)
    source_type: str = "youtube"


class YouTubeExtractResponse(BaseModel):
    success: bool
    recipe: Optional[ExtractedRecipe] = None
    error: Optional[str] = None


def extract_nutrition_from_text(text: str) -> Dict:
    """
    Extract nutrition information from caption text using improved regex patterns.
    
    Handles various formats:
    - "650 calories"
    - "64g of protein" 
    - "64 grams protein"
    - "11g fat"
    - "50 carbs"
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
        r'(\d+)\s*(?:cals?)\b'
    ]
    for pattern in cal_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            nutrition["calories"] = int(match.group(1))
            break
    
    # Protein: matches "64g protein", "64 grams of protein", "protein 64g"
    protein_patterns = [
        r'(\d+)\s*(?:g|grams?)\s*(?:of\s+)?protein',
        r'protein\s*[:\-]?\s*(\d+)\s*(?:g|grams?)?',
        r'(\d+)\s*(?:g|grams?)\s+protein'
    ]
    for pattern in protein_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            nutrition["protein_grams"] = int(match.group(1))
            break
    
    # Carbs: matches "50g carbs", "50 carbohydrates", "carbs 50g"
    carb_patterns = [
        r'(\d+)\s*(?:g|grams?)?\s*(?:of\s+)?(?:carbs?|carbohydrates?)',
        r'(?:carbs?|carbohydrates?)\s*[:\-]?\s*(\d+)\s*(?:g|grams?)?',
        r'(\d+)\s*(?:g|grams?)\s+(?:carbs?|carbohydrates?)'
    ]
    for pattern in carb_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            nutrition["carbs_grams"] = int(match.group(1))
            break
    
    # Fat: matches "11g fat", "11 grams of fat", "fat 11g"
    fat_patterns = [
        r'(\d+)\s*(?:g|grams?)?\s*(?:of\s+)?fat\b',
        r'fat\s*[:\-]?\s*(\d+)\s*(?:g|grams?)?',
        r'(\d+)\s*(?:g|grams?)\s+fat\b'
    ]
    for pattern in fat_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            nutrition["fat_grams"] = int(match.group(1))
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


def calculate_success_rate(nutrition: Dict) -> float:
    """
    Calculate what percentage of key fields were extracted.
    Key fields: calories, protein, fat, carbs (4 total)
    """
    fields = [
        nutrition.get("calories"),
        nutrition.get("protein_grams"),
        nutrition.get("fat_grams"),
        nutrition.get("carbs_grams")
    ]
    extracted = sum(1 for f in fields if f is not None)
    return extracted / len(fields)


def extract_recipe_from_youtube(video_url: str) -> ExtractedRecipe:
    """
    Extract recipe data from YouTube video using yt-dlp and auto-captions.
    
    Raises:
        HTTPException: If extraction fails
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
            # Get video title
            title_cmd = [ytdlp_path, "--print", "title", video_url]
            title_result = subprocess.run(
                title_cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if title_result.returncode != 0:
                raise HTTPException(
                    status_code=400,
                    detail=f"Failed to fetch video: {title_result.stderr}"
                )
            
            title = title_result.stdout.strip()
            
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
            
            # Extract nutrition and ingredients
            nutrition = extract_nutrition_from_text(text)
            ingredients = extract_ingredients_section(text)
            success_rate = calculate_success_rate(nutrition)
            
            return ExtractedRecipe(
                title=title,
                source_url=str(video_url),
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
    
    Returns nutrition information (calories, protein, fat, carbs) and ingredients
    extracted from auto-generated captions.
    
    **Success rate:** Indicates what fraction of nutrition fields were extracted.
    - 1.0 = All fields (calories, protein, fat, carbs)
    - 0.75 = 3/4 fields (e.g., missing carbs)
    - 0.5 = 2/4 fields
    
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
        "ytdlp_path": ytdlp_path if ytdlp_installed else None
    }
