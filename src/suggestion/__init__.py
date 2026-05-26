"""LLM-backed suggestion generation."""

from src.suggestion.engine import (
    DEFAULT_AVG_SAVINGS,
    DEFAULT_MODEL,
    SuggestionEngine,
    SuggestionEngineError,
)
from src.suggestion.prompt import SYSTEM_PROMPT, build_user_prompt, format_actions_block
from src.suggestion.schema import TOOL_NAME, build_suggestion_tool

__all__ = [
    "DEFAULT_AVG_SAVINGS",
    "DEFAULT_MODEL",
    "SYSTEM_PROMPT",
    "TOOL_NAME",
    "SuggestionEngine",
    "SuggestionEngineError",
    "build_suggestion_tool",
    "build_user_prompt",
    "format_actions_block",
]
