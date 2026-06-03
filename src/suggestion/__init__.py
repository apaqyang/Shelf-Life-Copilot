"""LLM-backed suggestion generation."""

from src.suggestion.engine import SuggestionEngine, SuggestionEngineError
from src.suggestion.prompt import SYSTEM_PROMPT, build_user_prompt, format_actions_block
from src.suggestion.providers import (
    ANTHROPIC_DEFAULT_MODEL,
    MOONSHOT_DEFAULT_MODEL,
    OFFLINE_MODEL_NAME,
    AnthropicProvider,
    LLMProvider,
    LLMProviderError,
    MoonshotProvider,
    OfflineLLMProvider,
    build_anthropic_provider,
    build_moonshot_provider,
    build_offline_provider,
)
from src.suggestion.schema import TOOL_NAME, build_suggestion_tool

__all__ = [
    "ANTHROPIC_DEFAULT_MODEL",
    "MOONSHOT_DEFAULT_MODEL",
    "OFFLINE_MODEL_NAME",
    "SYSTEM_PROMPT",
    "TOOL_NAME",
    "AnthropicProvider",
    "LLMProvider",
    "LLMProviderError",
    "MoonshotProvider",
    "OfflineLLMProvider",
    "SuggestionEngine",
    "SuggestionEngineError",
    "build_anthropic_provider",
    "build_moonshot_provider",
    "build_offline_provider",
    "build_suggestion_tool",
    "build_user_prompt",
    "format_actions_block",
]
