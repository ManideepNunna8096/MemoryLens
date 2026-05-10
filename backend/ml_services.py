import sys
from functools import lru_cache
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ML_DIR = PROJECT_ROOT / 'ml'

if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))


@lru_cache(maxsize=1)
def get_scene_classifier():
    from scene_classifier import classify_scene

    return classify_scene


@lru_cache(maxsize=1)
def get_clip_embedding_fn():
    from clip_search import get_clip_embedding

    return get_clip_embedding


@lru_cache(maxsize=1)
def get_text_embedding_fn():
    from clip_search import get_text_embedding

    return get_text_embedding


@lru_cache(maxsize=1)
def get_event_grouping_fn():
    from event_organizer import group_photos_into_events

    return group_photos_into_events
