"""Carousel factory core: harvest, typography, LLM, batch, captions."""

from .usage_meter import get_meter
from .batch_factory import run_batch
from .caption_engine import generate_caption
from .color_matcher import get_color_profile, get_harmony_score, rank_by_harmony
from .harvester import (
    CandidateImage,
    HarvestProgress,
    PinterestHarvester,
    finalize_photo_query,
)
from .llm_engine import (
    GeminiApiKeyMissing,
    GeminiGenerator,
    OllamaGenerator,
    OllamaUnavailable,
    UGC_QUERY_MARKERS,
)
from .preference_learner import PreferenceLearner
from .renderer import (
    SlideRenderMeta,
    find_optimal_text_position,
    render_preview,
    render_slide,
)

__all__ = [
    "CandidateImage",
    "HarvestProgress",
    "GeminiApiKeyMissing",
    "GeminiGenerator",
    "OllamaGenerator",
    "OllamaUnavailable",
    "PreferenceLearner",
    "PinterestHarvester",
    "SlideRenderMeta",
    "UGC_QUERY_MARKERS",
    "finalize_photo_query",
    "find_optimal_text_position",
    "generate_caption",
    "get_meter",
    "get_color_profile",
    "get_harmony_score",
    "rank_by_harmony",
    "render_preview",
    "render_slide",
    "run_batch",
]
