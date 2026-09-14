"""
style_memory.py

Style Profile Memory (stretch feature). Persists the wardrobe the user last
used to a local JSON file so a later run of the app can load it back without
the user re-entering or re-selecting it. This is real persistence across
separate runs of the app (survives restarting `python app.py`), unlike the
`session` dict in agent.py, which lives only for one run_agent() call.

See planning.md -> Stretch Features -> Style Profile Memory for the design
rationale.
"""

import json
import os

_PROFILE_PATH = os.path.join(os.path.dirname(__file__), "style_profile.json")


def save_style_profile(wardrobe: dict) -> None:
    """
    Persist the given wardrobe to disk as the user's remembered style profile.

    Args:
        wardrobe: A wardrobe dict with an 'items' key. An empty wardrobe is
                  not worth remembering, so this is a no-op if items is empty.
    """
    if not wardrobe.get("items"):
        return
    with open(_PROFILE_PATH, "w", encoding="utf-8") as f:
        json.dump(wardrobe, f, indent=2)


def load_style_profile() -> dict | None:
    """
    Load the previously saved style profile, if one exists.

    Returns:
        The saved wardrobe dict, or None if no profile has been saved yet.
        Never raises -- a corrupted or missing file is treated as "no profile."
    """
    if not os.path.exists(_PROFILE_PATH):
        return None
    try:
        with open(_PROFILE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
