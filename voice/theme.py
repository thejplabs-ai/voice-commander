# voice/theme.py — JP Labs Brand Design Tokens (Quiet Luxury 2026)
# Zero imports from other voice modules (leaf node in DAG)

# ── COLORS: background layers (warm neutrals) ────────────────────────────────
BG_ABYSS    = "#0F0F0F"   # window backgrounds (near-black, no blue tint)
BG_DEEP     = "#1A1A1E"   # cards, sidebar, headers
BG_ELEVATED = "#242428"   # hover on cards/sidebar
BG_NIGHT    = "#2C2C30"   # selected/active items

# ── COLORS: borders ───────────────────────────────────────────────────────────
BORDER_DEFAULT = "#2A2A2E"  # at-rest
BORDER_HOVER   = "#3A3A3E"  # on hover
BORDER_ACTIVE  = "#C4956A"  # selected/focused (warm amber)

# ── COLORS: text ──────────────────────────────────────────────────────────────
TEXT_PRIMARY   = "#F5F5F0"   # cream-white (not pure white)
TEXT_SECONDARY = "#B3B0AA"   # warm grey ~70%
TEXT_MUTED     = "#807E7A"   # warm grey ~50%
TEXT_DISABLED  = "#4D4C4A"   # warm grey ~30%

# ── COLORS: accents ───────────────────────────────────────────────────────────
PURPLE         = "#C4956A"   # warm amber (primary accent)
PURPLE_HOVER   = "#D4A87A"   # amber hover
PURPLE_DARK    = "#B4855A"   # amber pressed
BLUE_NEO       = "#6B8EBF"   # steel blue (secondary)

# ── COLORS: status ────────────────────────────────────────────────────────────
SUCCESS        = "#7EC89B"   # muted sage green
ERROR          = "#D4626E"   # muted rose
WARNING        = "#D4A24E"   # warm amber

# ── COLORS: tray states ──────────────────────────────────────────────────────
TRAY_IDLE       = "#C4956A"  # warm amber
TRAY_RECORDING  = "#D4626E"  # muted rose
TRAY_PROCESSING = "#6B8EBF"  # steel blue

# ── TYPOGRAPHY ────────────────────────────────────────────────────────────────
_HEAD = "Figtree"
_BODY = "Inter"
_MONO = "JetBrains Mono"
_SERIF = "Georgia"

_FALLBACK = {_HEAD: "Segoe UI", _BODY: "Segoe UI", _MONO: "Consolas", _SERIF: "Times New Roman"}

_cached_families: set | None = None


def _font(family: str, size: int, bold: bool = False) -> tuple:
    """Returns CTkFont-compatible tuple. Auto-fallback if family not installed."""
    global _cached_families
    if _cached_families is None:
        try:
            import tkinter as tk
            import tkinter.font as tkfont
            r = tk.Tk()
            r.withdraw()
            _cached_families = set(tkfont.families(r))
            r.destroy()
        except Exception:
            _cached_families = set()
    fam = family if family in _cached_families else _FALLBACK.get(family, "Segoe UI")
    weight = "bold" if bold else "normal"
    return (fam, size, weight)


# Font presets (callable so tkinter is initialized before first call)
def FONT_EDITORIAL():  return _font(_SERIF, 32, bold=True)    # hero headings
def FONT_EDITORIAL_SM(): return _font(_SERIF, 20, bold=True)  # subtitle editorial
def FONT_DISPLAY():    return _font(_HEAD, 28, bold=True)
def FONT_HEADING():    return _font(_HEAD, 18, bold=True)
def FONT_HEADING_SM(): return _font(_HEAD, 14, bold=True)
def FONT_BODY():       return _font(_BODY, 14)
def FONT_BODY_BOLD():  return _font(_BODY, 14, bold=True)
def FONT_CAPTION():    return _font(_BODY, 12)
def FONT_OVERLINE():   return _font(_BODY, 12, bold=True)
def FONT_MONO():       return _font(_MONO, 12)
def FONT_MONO_SM():    return _font(_MONO, 11)

# ── COMPONENT SIZES ───────────────────────────────────────────────────────────
CORNER_SM  = 8    # badges, tags
CORNER_MD  = 12   # buttons, inputs, nav items (default)
CORNER_LG  = 16   # cards, section containers
CORNER_XL  = 20   # large cards
CORNER_PILL = 999  # pill shapes

BTN_HEIGHT   = 40
INPUT_HEIGHT = 40

SIDEBAR_WIDTH = 200

# ── SPACING SCALE ─────────────────────────────────────────────────────────────
SPACE_2XS = 2
SPACE_XS  = 4
SPACE_SM  = 8
SPACE_MD  = 16
SPACE_LG  = 24
SPACE_XL  = 32
SPACE_2XL = 48

# ── ANIMATION DURATIONS (ms) ─────────────────────────────────────────────────
ANIM_FAST     = 100   # hover, press
ANIM_NORMAL   = 200   # transitions
ANIM_SLOW     = 350   # entrance/exit
ANIM_ENTRANCE = 400   # modal/overlay entrance
FPS_30        = 33    # ms per frame at 30fps
