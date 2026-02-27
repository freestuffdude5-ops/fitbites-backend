"""
YouTube Recipe Extraction API v2.1 - Full Transcript Edition
Extracts recipe data from YouTube videos using auto-captions with ffmpeg support
Production-ready wrapper around yt-dlp

Changes in v2.1:
- Full VTT transcript extraction with segment parsing
- Structured ingredients list (not just raw text)
- Structured cooking instructions (step-by-step)
- Better ingredient section detection
- Better instruction section detection
- Improved success rate calculation (8 fields now)

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
from typing import Dict, Optional, Tuple, List

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

class RecipeInstruction(BaseModel):
    step: int
    text: str

class ExtractedRecipe(BaseModel):
    title: str
    source_url: str
    thumbnail_url: Optional[str] = None
    channel_name: Optional[str] = None
    nutrition: RecipeNutrition
    ingredients: List[str] = []  # NEW v2.1: structured list
    instructions: List[RecipeInstruction] = []  # NEW v2.1: structured steps
    ingredients_raw: Optional[str] = None  # DEPRECATED: kept for compatibility
    success_rate: float  # 0.0 to 1.0 (fraction of fields extracted)
    source_type: str = "youtube"
    transcript_segments: Optional[int] = None  # NEW v2.1


class YouTubeExtractResponse(BaseModel):
    success: bool
    recipe: Optional[ExtractedRecipe] = None
    error: Optional[str] = None


def detect_multi_recipe_video(title: str, text: str) -> Tuple[bool, Optional[str]]:
    """
    Detect if video contains multiple recipes.
    Returns (is_multi_recipe, error_message)
    """
    multi_recipe_title_patterns = [
        r'\d+\s+.*?\b(?:meals?|recipes?|dishes?|ways?|ideas?|options?)\b',
        r'(?:meals?|recipes?)\s+prep',
        r'multiple|various|several',
    ]
    
    for pattern in multi_recipe_title_patterns:
        if re.search(pattern, title, re.IGNORECASE):
            return True, "Multi-recipe video detected (title indicates multiple recipes)"
    
    multi_recipe_text_patterns = [
        r'(?:recipe|meal)\s*(?:#|number|num)?\s*[12345]',
        r'(?:first|second|third|fourth|fifth)\s+(?:recipe|meal|option|dish)',
        r'(?:next|another)\s+(?:recipe|meal)',
        r'recipe\s+(?:one|two|three|four|five)',
        r'our\s+(?:first|second|third)\s+recipe',
    ]
    
    matches = 0
    for pattern in multi_recipe_text_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            matches += 1
            if matches >= 1:
                return True, "Multi-recipe video detected (transcript contains multiple recipe segments)"
    
    return False, None


def parse_vtt_to_segments(vtt_content: str) -> Tuple[str, List[Dict]]:
    """
    Parse VTT subtitle file into clean text and timestamped segments.
    Returns (full_text, segments_list)
    """
    lines = vtt_content.split('\n')
    segments = []
    full_text = ''
    last_timestamp = ''
    
    for line in lines:
        line = line.strip()
        
        # Skip header and empty
        if not line or line.startswith('WEBVTT') or line.startswith('NOTE') or line.startswith('Kind'):
            continue
        
        # Capture timestamp
        if '-->' in line:
            parts = line.split('-->')
            last_timestamp = parts[0].strip()
            continue
        
        # Skip segment numbers
        if re.match(r'^\d+$', line):
            continue
        
        # Clean the line - remove VTT timing tags
        cleaned = re.sub(r'<\d{2}:\d{2}:\d{2}\.\d{3}>', '', line)
        cleaned = re.sub(r'<c>[^<]*</c>', '', cleaned)
        cleaned = re.sub(r'\s*align:start\s+position:\d+%\s*', ' ', cleaned)
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        
        # Only add if we have meaningful text
        if len(cleaned) > 3 and not re.match(r'^\d+$', cleaned):
            segments.append({'start': last_timestamp, 'text': cleaned})
            full_text += cleaned + ' '
    
    # Deduplicate segments (YouTube includes duplicate text)
    unique_segments = []
    last_text = ''
    for seg in segments:
        if seg['text'] != last_text and len(seg['text']) > 5:
            unique_segments.append(seg)
            last_text = seg['text']
    
    return full_text.strip(), unique_segments


def extract_ingredients_from_transcript(segments: List[Dict], full_text: str) -> List[str]:
    """
    Extract ingredients list from transcript segments.
    Returns structured list of ingredients.
    """
    ingredients = []
    seen = set()
    
    # Look for explicit ingredients section
    ingredient_section = find_ingredient_section(segments)
    if ingredient_section:
        for item in ingredient_section:
            if item not in seen:
                ingredients.append(item)
                seen.add(item)
    
    # Extract quantity-based ingredients
    quantity_pattern = r'(\d+(?:\.\d+)?(?:/\d+)?)\s*(?:cups?|tbsp|tablespoons?|tsp|teaspoons?|oz|ounces?|lbs?|pounds?|g|grams?|ml|mls?|kg|pkg|package|can|cans?|slice|slices|piece|pieces|pinch|dash|clove|cloves?)\s+(?:of\s+)?([a-zA-Z\s]+?)(?=\s+(?:and|,|\.|or|with|for)|$)'
    
    for match in re.finditer(quantity_pattern, full_text, re.I):
        ingredient = f"{match.group(1)} {match.group(2).strip()}".lower()
        if len(ingredient) > 3 and ingredient not in seen:
            ingredients.append(ingredient)
            seen.add(ingredient)
    
    return ingredients[:30]  # Limit to 30


def find_ingredient_section(segments: List[Dict]) -> Optional[List[str]]:
    """Find explicit ingredient section in transcript segments."""
    ingredients = []
    in_ingredient_section = False
    found_count = 0
    
    for segment in segments:
        text = segment['text'].lower()
        
        # Start of ingredients section
        if 'ingredients' in text and not in_ingredient_section:
            in_ingredient_section = True
            continue
        
        # End markers
        if in_ingredient_section:
            if any(marker in text for marker in ['instructions', 'directions', 'steps', 'method', 'now', 'first', 'preheat']):
                break
            
            # Skip timestamps and numbers
            if re.match(r'^\d{2}:', segment['text']) or re.match(r'^\d+$', segment['text']):
                continue
            
            # Clean and add ingredient
            cleaned = segment['text']
            cleaned = re.sub(r'^\d+[\.\)]\s*', '', cleaned)
            cleaned = re.sub(r'^[•\-\*]\s*', '', cleaned)
            cleaned = re.sub(r'\s+', ' ', cleaned).strip()
            
            if 5 < len(cleaned) < 100:
                ingredients.append(cleaned)
                found_count += 1
            
            if found_count >= 15:
                break
    
    return ingredients if ingredients else None


def extract_instructions_from_transcript(segments: List[Dict], full_text: str) -> List[RecipeInstruction]:
    """Extract cooking instructions from transcript."""
    instructions = []
    
    # Look for instruction section
    instruction_section = find_instruction_section(segments)
    if instruction_section:
        return instruction_section
    
    # Fallback: extract numbered steps
    step_pattern = r'(?:step\s*)?(\d+)[\.\)]\s*([^.]+(?:\. [^.]+){0,2})'
    for match in re.finditer(step_pattern, full_text, re.I):
        step_num = int(match.group(1))
        step_text = match.group(2).strip()
        
        if 10 < len(step_text) < 200:
            instructions.append(RecipeInstruction(step=step_num, text=step_text))
    
    # If no numbered steps, extract sentences with action verbs
    if not instructions:
        action_verbs = ['add', 'mix', 'stir', 'combine', 'heat', 'cook', 'bake', 'preheat', 
                       'slice', 'cut', 'chop', 'pour', 'blend', 'whisk', 'simmer', 'boil']
        
        sentences = re.split(r'[.!?]+', full_text)
        for sentence in sentences:
            lower = sentence.lower()
            if any(verb in lower for verb in action_verbs) and 20 < len(sentence) < 150:
                instructions.append(RecipeInstruction(step=len(instructions) + 1, text=sentence.strip()))
    
    return instructions[:15]  # Limit to 15


def find_instruction_section(segments: List[Dict]) -> Optional[List[RecipeInstruction]]:
    """Find explicit instruction section in transcript."""
    instructions = []
    in_instruction_section = False
    step_num = 1
    
    for segment in segments:
        text = segment['text']
        lower = text.lower()
        
        # Start of instructions section
        if any(marker in lower for marker in ['instructions', 'directions', 'steps', 'method', 'how to make', 'recipe']):
            in_instruction_section = True
            continue
        
        if in_instruction_section:
            # Skip timestamps and short segments
            if re.match(r'^\d{2}:', text) or len(text) < 10:
                continue
            
            # Clean step
            cleaned = text
            cleaned = re.sub(r'^\d+[\.\)]\s*', '', cleaned)
            cleaned = re.sub(r'^[•\-\*]\s*', '', cleaned)
            cleaned = cleaned.strip()
            
            if 10 < len(cleaned) < 200:
                instructions.append(RecipeInstruction(step=step_num, text=cleaned))
                step_num += 1
            
            if step_num > 15:
                break
    
    return instructions if instructions else None


def extract_recipe_title_from_text(video_title: str, text: str) -> str:
    """Parse individual recipe title from transcript."""
    intro_text = text[:1000]
    
    patterns = [
        r"(?:today|here(?:'s| is)|let'?s?\s*(?:make|do)|i'?m\s*(?:making|doing))\s+(?:a\s+)?(?:my\s+)?(?:the\s+)?([^.]+)",
        r"(?:this\s+is\s+(?:a\s+)?(?:my\s+)?)?(?:the\s+)?([^.]+?)\s+recipe",
        r"recipe\s+(?:for|is|called)\s+([^.]+)",
        r"(?:welcome\s+to\s+)?(?:my\s+)?(?:healthy\s+)?(\d+\s*(?:gram|protein)\s+\w+)",
    ]
    
    for pattern in patterns:
        match = re.search(pattern, intro_text, re.I)
        if match and match.group(1):
            extracted_title = match.group(1).strip()
            extracted_title = re.sub(r'\s*[-|]\s*.*$', '', extracted_title)
            extracted_title = re.sub(r'\s*recipe\s*$', '', extracted_title, flags=re.I)
            extracted_title = extracted_title.strip()
            
            if 3 < len(extracted_title) < 100:
                return extracted_title
    
    # Fallback
    clean_title = video_title
    clean_title = re.sub(r'\s*\|.*$', '', clean_title)
    clean_title = re.sub(r'\s*-.*recipe.*$', '', clean_title, flags=re.I)
    clean_title = re.sub(r'^\d+\s*(calorie|protein|macro)s?\s*', '', clean_title, flags=re.I)
    clean_title = re.sub(r'\s*\(\d+\)\s*$', '', clean_title)
    return clean_title.strip()


def extract_nutrition_from_text(text: str) -> Dict:
    """Extract nutrition information from text."""
    nutrition = {
        "calories": None,
        "protein_grams": None,
        "carbs_grams": None,
        "fat_grams": None
    }
    
    # Calories
    cal_patterns = [
        r'(\d+)\s*(?:calories|kcal|cal)\b',
        r'calories?\s*[:\-]?\s*(\d+)',
    ]
    for pattern in cal_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            nutrition["calories"] = int(match.group(1))
            break
    
    # Protein
    protein_patterns = [
        r'(\d+(?:\.\d+)?)\s*(?:g|grams?)\s*(?:of\s+)?protein',
        r'protein\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*(?:g|grams?)?',
    ]
    for pattern in protein_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            nutrition["protein_grams"] = float(match.group(1))
            break
    
    # Carbs
    carb_patterns = [
        r'(\d+(?:\.\d+)?)\s*(?:g|grams?)?\s*(?:of\s+)?(?:carbs?|carbohydrates?)\b',
        r'(?:carbs?|carbohydrates?)\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*(?:g|grams?)?',
    ]
    for pattern in carb_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            nutrition["carbs_grams"] = float(match.group(1))
            break
    
    # Fat
    fat_patterns = [
        r'(\d+(?:\.\d+)?)\s*(?:g|grams?)?\s*(?:of\s+)?fat\b',
        r'\bfat\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*(?:g|grams?)?',
    ]
    for pattern in fat_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            nutrition["fat_grams"] = float(match.group(1))
            break
    
    return nutrition


def calculate_success_rate(nutrition: Dict, has_thumbnail: bool, has_channel: bool,
                          has_ingredients: bool, has_instructions: bool) -> float:
    """
    Calculate what percentage of key fields were extracted.
    v2.1 fields (8 total): calories, protein, fat, carbs, thumbnail, channel, ingredients, instructions
    """
    fields = [
        nutrition.get("calories"),
        nutrition.get("protein_grams"),
        nutrition.get("fat_grams"),
        nutrition.get("carbs_grams"),
        has_thumbnail,
        has_channel,
        has_ingredients,
        has_instructions,
    ]
    extracted = sum(1 for f in fields if f is not None and f is not False)
    return extracted / len(fields)


def extract_recipe_from_youtube(video_url: str) -> ExtractedRecipe:
    """
    Extract recipe data from YouTube video using yt-dlp and auto-captions.
    v2.1: Full transcript parsing with ingredients and instructions.
    """
    ytdlp_path = "/home/user/.local/bin/yt-dlp"
    
    if not Path(ytdlp_path).exists():
        raise HTTPException(
            status_code=500,
            detail="yt-dlp not installed. Run: pip install yt-dlp"
        )
    
    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            # Get video metadata
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
            
            # Parse VTT to segments
            vtt_content = vtt_files[0].read_text(encoding='utf-8')
            full_text, segments = parse_vtt_to_segments(vtt_content)
            
            # Check for multi-recipe video
            is_multi_recipe, multi_recipe_error = detect_multi_recipe_video(video_title, full_text)
            if is_multi_recipe:
                raise HTTPException(
                    status_code=400,
                    detail=f"Multi-recipe video detected. {multi_recipe_error}"
                )
            
            # Extract recipe components
            recipe_title = extract_recipe_title_from_text(video_title, full_text)
            nutrition = extract_nutrition_from_text(full_text)
            
            # v2.1: Extract structured ingredients and instructions
            ingredients = extract_ingredients_from_transcript(segments, full_text)
            instructions = extract_instructions_from_transcript(segments, full_text)
            
            # Legacy raw ingredients for compatibility
            ingredients_raw = None
            if ingredients:
                ingredients_raw = ", ".join(ingredients[:10])  # First 10 for summary
            
            success_rate = calculate_success_rate(
                nutrition, 
                bool(thumbnail_url), 
                bool(channel_name),
                bool(ingredients),
                bool(instructions)
            )
            
            return ExtractedRecipe(
                title=recipe_title,
                source_url=str(video_url),
                thumbnail_url=thumbnail_url,
                channel_name=channel_name,
                nutrition=RecipeNutrition(**nutrition),
                ingredients=ingredients,
                instructions=instructions,
                ingredients_raw=ingredients_raw,
                success_rate=success_rate,
                source_type="youtube",
                transcript_segments=len(segments)
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
    
    v2.1 features:
    - Structured ingredients list
    - Step-by-step instructions
    - Full transcript parsing with segment detection
    - 8-field success rate (calories, protein, carbs, fat, thumbnail, channel, ingredients, instructions)
    
    Returns nutrition, structured ingredients/instructions, thumbnail, and channel name.
    Multi-recipe videos will return an error.
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
    
    # Check ffmpeg
    try:
        ffmpeg_result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            timeout=5
        )
        ffmpeg_available = ffmpeg_result.returncode == 0
    except:
        ffmpeg_available = False
    
    return {
        "status": "healthy" if (ytdlp_installed and ffmpeg_available) else "degraded",
        "ytdlp_installed": ytdlp_installed,
        "ffmpeg_available": ffmpeg_available,
        "version": "v2.1",
        "features": [
            "thumbnail_extraction",
            "channel_name_extraction",
            "structured_ingredients_list",
            "structured_instructions",
            "full_transcript_parsing",
            "segment_detection",
            "improved_carbs_fat_regex",
            "recipe_title_parsing",
            "multi_recipe_detection"
        ]
    }
