"""Recipe validation system - strict quality enforcement for FitBites."""
from typing import Optional, Dict, List, Any
import re
from dataclasses import dataclass


@dataclass
class ValidationResult:
    """Result of recipe validation."""
    is_valid: bool
    rejection_reason: Optional[str] = None
    warnings: List[str] = None
    
    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


class RecipeValidator:
    """
    Strict recipe validator - enforces complete data requirements.
    
    Rules:
    1. All 4 macros required (calories, protein, carbs, fat)
    2. Minimum 3 ingredients
    3. Minimum 3 cooking steps
    4. Valid thumbnail URL
    5. Valid source URL
    6. NOT a multi-recipe compilation
    """
    
    # Multi-recipe compilation patterns (case-insensitive)
    MULTI_RECIPE_PATTERNS = [
        r"day\s+in\s+the\s+life",
        r"full\s+day\s+of\s+eating",
        r"what\s+i\s+eat\s+in\s+a\s+day",
        r"\d+\s+recipes",  # "5 recipes", "10 recipes"
        r"meal\s+prep\s+for\s+the\s+week",
        r"everything\s+i\s+ate",
        r"24\s+hours?\s+of\s+eating",
        r"meal\s+prep\s+sunday",
        r"weekly\s+meal\s+prep",
        r"recipe\s+compilation",
        r"easy\s+recipes",  # Often compilations
        r"\d+\s+meals",  # "5 meals in one day"
    ]
    
    def __init__(self):
        self.multi_recipe_regex = re.compile(
            '|'.join(self.MULTI_RECIPE_PATTERNS),
            re.IGNORECASE
        )
    
    def validate(self, recipe_data: Dict[str, Any]) -> ValidationResult:
        """
        Validate a recipe against strict quality requirements.
        
        Args:
            recipe_data: Dict with recipe fields (title, ingredients, steps, etc.)
            
        Returns:
            ValidationResult indicating pass/fail and reason
        """
        title = recipe_data.get("title", "")
        description = recipe_data.get("description", "")
        
        # 1. Check for multi-recipe compilation
        if self._is_compilation(title, description):
            return ValidationResult(
                is_valid=False,
                rejection_reason=f"Multi-recipe compilation detected: '{title[:100]}'"
            )
        
        # 2. Validate macros (ALL 4 REQUIRED)
        macros_result = self._validate_macros(recipe_data)
        if not macros_result.is_valid:
            return macros_result
        
        # 3. Validate ingredients
        ingredients_result = self._validate_ingredients(recipe_data)
        if not ingredients_result.is_valid:
            return ingredients_result
        
        # 4. Validate steps
        steps_result = self._validate_steps(recipe_data)
        if not steps_result.is_valid:
            return steps_result
        
        # 5. Validate URLs
        urls_result = self._validate_urls(recipe_data)
        if not urls_result.is_valid:
            return urls_result
        
        # 6. Quality checks (warnings only)
        warnings = []
        if len(title) < 10:
            warnings.append("Title is very short")
        if len(recipe_data.get("ingredients", [])) > 20:
            warnings.append("Unusually high ingredient count")
        
        return ValidationResult(
            is_valid=True,
            warnings=warnings
        )
    
    def _is_compilation(self, title: str, description: str) -> bool:
        """Check if title or description indicates a multi-recipe compilation."""
        combined_text = f"{title} {description or ''}"
        return bool(self.multi_recipe_regex.search(combined_text))
    
    def _validate_macros(self, recipe_data: Dict[str, Any]) -> ValidationResult:
        """Validate all 4 macros are present and valid."""
        calories = recipe_data.get("calories")
        protein_g = recipe_data.get("protein_g")
        carbs_g = recipe_data.get("carbs_g")
        fat_g = recipe_data.get("fat_g")
        
        missing_macros = []
        if calories is None or calories <= 0:
            missing_macros.append("calories")
        if protein_g is None or protein_g < 0:
            missing_macros.append("protein")
        if carbs_g is None or carbs_g < 0:
            missing_macros.append("carbs")
        if fat_g is None or fat_g < 0:
            missing_macros.append("fat")
        
        if missing_macros:
            return ValidationResult(
                is_valid=False,
                rejection_reason=f"Missing/invalid macros: {', '.join(missing_macros)}"
            )
        
        # Sanity check: macros should roughly add up (with some tolerance)
        # Protein & Carbs: 4 cal/g, Fat: 9 cal/g
        calculated_cals = (protein_g * 4) + (carbs_g * 4) + (fat_g * 9)
        if abs(calculated_cals - calories) > calories * 0.5:  # 50% tolerance
            return ValidationResult(
                is_valid=False,
                rejection_reason=f"Macro math doesn't add up: {calories} cal reported vs {calculated_cals:.0f} calculated"
            )
        
        return ValidationResult(is_valid=True)
    
    def _validate_ingredients(self, recipe_data: Dict[str, Any]) -> ValidationResult:
        """Validate ingredients list is present and reasonable."""
        ingredients = recipe_data.get("ingredients", [])
        
        if not ingredients:
            return ValidationResult(
                is_valid=False,
                rejection_reason="No ingredients provided"
            )
        
        if len(ingredients) < 3:
            return ValidationResult(
                is_valid=False,
                rejection_reason=f"Too few ingredients ({len(ingredients)} < 3 minimum)"
            )
        
        # Check ingredient quality (not just transcript noise)
        for i, ing in enumerate(ingredients[:5]):  # Check first 5
            if isinstance(ing, dict):
                name = ing.get("name", "")
            elif isinstance(ing, str):
                name = ing
            else:
                return ValidationResult(
                    is_valid=False,
                    rejection_reason=f"Invalid ingredient format: {type(ing)}"
                )
            
            if len(name) < 2:
                return ValidationResult(
                    is_valid=False,
                    rejection_reason=f"Ingredient {i+1} is too short: '{name}'"
                )
            
            # Check for common transcript noise patterns
            noise_patterns = ["watch", "video", "subscribe", "link", "recipe"]
            if any(pattern in name.lower() for pattern in noise_patterns):
                return ValidationResult(
                    is_valid=False,
                    rejection_reason=f"Ingredient appears to be transcript noise: '{name[:50]}'"
                )
        
        return ValidationResult(is_valid=True)
    
    def _validate_steps(self, recipe_data: Dict[str, Any]) -> ValidationResult:
        """Validate cooking steps are present and reasonable."""
        steps = recipe_data.get("steps", [])
        
        if not steps:
            return ValidationResult(
                is_valid=False,
                rejection_reason="No cooking steps provided"
            )
        
        if len(steps) < 3:
            return ValidationResult(
                is_valid=False,
                rejection_reason=f"Too few steps ({len(steps)} < 3 minimum)"
            )
        
        # Check step quality
        for i, step in enumerate(steps[:3]):  # Check first 3
            if isinstance(step, str):
                if len(step) < 10:
                    return ValidationResult(
                        is_valid=False,
                        rejection_reason=f"Step {i+1} is too short: '{step}'"
                    )
            else:
                return ValidationResult(
                    is_valid=False,
                    rejection_reason=f"Invalid step format: {type(step)}"
                )
        
        return ValidationResult(is_valid=True)
    
    def _validate_urls(self, recipe_data: Dict[str, Any]) -> ValidationResult:
        """Validate source and thumbnail URLs are present and valid."""
        source_url = recipe_data.get("source_url", "")
        thumbnail_url = recipe_data.get("thumbnail_url", "")
        
        if not source_url or len(source_url) < 10:
            return ValidationResult(
                is_valid=False,
                rejection_reason="Missing or invalid source URL"
            )
        
        if not source_url.startswith(("http://", "https://")):
            return ValidationResult(
                is_valid=False,
                rejection_reason=f"Invalid source URL format: {source_url[:50]}"
            )
        
        if not thumbnail_url or len(thumbnail_url) < 10:
            return ValidationResult(
                is_valid=False,
                rejection_reason="Missing or invalid thumbnail URL"
            )
        
        if not thumbnail_url.startswith(("http://", "https://")):
            return ValidationResult(
                is_valid=False,
                rejection_reason=f"Invalid thumbnail URL format: {thumbnail_url[:50]}"
            )
        
        return ValidationResult(is_valid=True)


# Global validator instance
validator = RecipeValidator()


def validate_recipe(recipe_data: Dict[str, Any]) -> ValidationResult:
    """
    Validate a recipe for quality and completeness.
    
    Args:
        recipe_data: Recipe dictionary to validate
        
    Returns:
        ValidationResult with pass/fail status and reason
    """
    return validator.validate(recipe_data)
