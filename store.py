"""
store.py — small JSON-backed store for recently used repo paths.

Lives outside the project folder (in the user's home config dir) so it
persists across Termux sessions and isn't tied to any single repo.
"""
import json
import os
import time

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".config", "git-ui")
RECENTS_FILE = os.path.join(CONFIG_DIR, "recents.json")
MAX_RECENTS = 10


def _ensure_dir():
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        return True
    except OSError:
        return False


def load_recents():
    if not os.path.isfile(RECENTS_FILE):
        return []
    try:
        with open(RECENTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [r for r in data if isinstance(r, dict) and r.get("path")]
    except (OSError, ValueError):
        pass
    return []


def _save(recents):
    if not _ensure_dir():
        return False
    try:
        with open(RECENTS_FILE, "w", encoding="utf-8") as f:
            json.dump(recents, f, indent=2)
        return True
    except OSError:
        return False


def add_recent(path):
    if not path:
        return load_recents()
    recents = [r for r in load_recents() if r.get("path") != path]
    recents.insert(0, {"path": path, "last_opened": time.time()})
    recents = recents[:MAX_RECENTS]
    _save(recents)
    return recents


def remove_recent(path):
    recents = [r for r in load_recents() if r.get("path") != path]
    _save(recents)
    return recents


def last_repo():
    recents = load_recents()
    return recents[0]["path"] if recents else ""
