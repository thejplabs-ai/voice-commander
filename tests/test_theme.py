"""
Tests for voice/theme.py — _font() family resolution.

W4 hygiene: _font() must never instantiate a transient tk.Tk() to probe
installed font families. Tk-real tests aren't viable in this suite (no
display guaranteed) — test the mechanics via monkeypatched tkinter internals.
"""

import sys
import types

# tests/test_overlay.py replaces sys.modules["tkinter"] with a MagicMock stub
# (module-level, via setdefault) so it can test _OverlayThread headlessly.
# In a full-suite run test_overlay.py collects before this file alphabetically,
# so that stub can already be cached by the time we get here. This file needs
# the REAL stdlib tkinter to monkeypatch _default_root/Tk/families — force a
# genuine (re)import if the stub won the race.
if not isinstance(sys.modules.get("tkinter"), types.ModuleType):
    sys.modules.pop("tkinter", None)
    sys.modules.pop("tkinter.font", None)

import tkinter
import tkinter.font as tkfont

import pytest

from voice import theme


@pytest.fixture(autouse=True)
def _reset_font_cache(monkeypatch):
    """theme._cached_families is module-global state — isolate each test."""
    monkeypatch.setattr(theme, "_cached_families", None)


class TestFontNoDefaultRoot:
    def test_sem_default_root_nao_instancia_tk(self, monkeypatch):
        """No live Tk root -> _font() never calls tkinter.Tk()."""
        monkeypatch.setattr(tkinter, "_default_root", None)
        calls = []
        monkeypatch.setattr(tkinter, "Tk", lambda *a, **kw: calls.append((a, kw)))

        theme._font("Figtree", 18, bold=True)

        assert calls == []

    def test_sem_default_root_retorna_familia_preferida_sem_probing(self, monkeypatch):
        """No live Tk root -> returns the requested family untouched (no fallback lookup)."""
        monkeypatch.setattr(tkinter, "_default_root", None)

        result = theme._font("Figtree", 18, bold=True)

        assert result == ("Figtree", 18, "bold")

    def test_sem_default_root_normal_weight(self, monkeypatch):
        monkeypatch.setattr(tkinter, "_default_root", None)

        result = theme._font("Inter", 14)

        assert result == ("Inter", 14, "normal")


class TestFontWithDefaultRoot:
    def test_com_default_root_familia_ausente_cai_no_fallback(self, monkeypatch):
        """Live root + probed families that don't include the family -> _FALLBACK."""
        monkeypatch.setattr(tkinter, "_default_root", object())
        monkeypatch.setattr(tkfont, "families", lambda root=None: ("Segoe UI", "Consolas"))

        result = theme._font("Figtree", 18, bold=True)

        assert result == ("Segoe UI", 18, "bold")

    def test_com_default_root_familia_presente_e_usada(self, monkeypatch):
        """Live root + probed families that DO include the family -> keep it."""
        monkeypatch.setattr(tkinter, "_default_root", object())
        monkeypatch.setattr(tkfont, "families", lambda root=None: ("Figtree", "Segoe UI"))

        result = theme._font("Figtree", 14)

        assert result == ("Figtree", 14, "normal")

    def test_probing_falha_cai_no_fallback(self, monkeypatch):
        """If tkfont.families() raises, cache degrades to empty set -> fallback."""
        monkeypatch.setattr(tkinter, "_default_root", object())

        def _boom(root=None):
            raise RuntimeError("no display")

        monkeypatch.setattr(tkfont, "families", _boom)

        result = theme._font("Figtree", 18)

        assert result == ("Segoe UI", 18, "normal")
