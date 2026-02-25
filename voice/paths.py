# voice/paths.py — base directory resolution and resource path helper
# Side-effect on import: populates state._BASE_DIR, state._log_path, state._history_path

import os
import sys
import pathlib

from voice import state


def _resource_path(relative: str) -> pathlib.Path:
    """Resolve caminho de recurso para dev e para PyInstaller (.exe)."""
    if getattr(sys, 'frozen', False):
        # sys._MEIPASS = pasta temporária onde o PyInstaller extrai os arquivos
        return pathlib.Path(sys._MEIPASS) / relative  # type: ignore[attr-defined]
    # __file__ is voice/paths.py — parent is voice/ — parent.parent is project root
    return pathlib.Path(__file__).parent.parent / relative


# Populate state on import
if getattr(sys, 'frozen', False):
    state._BASE_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "VoiceCommander")
    os.makedirs(state._BASE_DIR, exist_ok=True)
else:
    # __file__ is voice/paths.py — go two levels up to reach project root
    state._BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

state._log_path = os.path.join(state._BASE_DIR, "voice.log")
state._history_path = os.path.join(state._BASE_DIR, "history.jsonl")
