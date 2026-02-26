# voice/theme.py — JP Labs Brand Design Tokens
# Zero imports from other voice modules (leaf node in DAG)

# ── COLORS: background layers ─────────────────────────────────────────────────
BG_ABYSS    = "#01010D"   # window backgrounds
BG_DEEP     = "#0D0C25"   # cards, sidebar, headers
BG_ELEVATED = "#131340"   # hover on cards/sidebar
BG_NIGHT    = "#170433"   # selected/active items

# ── COLORS: borders ───────────────────────────────────────────────────────────
BORDER_DEFAULT = "#1C1C32"  # at-rest
BORDER_HOVER   = "#2A2A4A"  # on hover
BORDER_ACTIVE  = "#6B2FF8"  # selected/focused

# ── COLORS: text ──────────────────────────────────────────────────────────────
TEXT_PRIMARY   = "#FFFFFF"
TEXT_SECONDARY = "#B3B3CC"   # ~70% white
TEXT_MUTED     = "#808099"   # ~50% white
TEXT_DISABLED  = "#4D4D66"   # ~30% white

# ── COLORS: accents ───────────────────────────────────────────────────────────
PURPLE         = "#6B2FF8"   # primary brand
PURPLE_HOVER   = "#7B42FF"
PURPLE_DARK    = "#5620D4"
BLUE_NEO       = "#1E38F7"

# ── COLORS: status ────────────────────────────────────────────────────────────
SUCCESS        = "#00FF88"
ERROR          = "#FF3366"
WARNING        = "#FFAA00"

# ── COLORS: tray states (brand-compliant) ────────────────────────────────────
TRAY_IDLE       = "#6B2FF8"  # purple (era cinza #808080)
TRAY_RECORDING  = "#FF3366"  # error red (era #FF3333)
TRAY_PROCESSING = "#1E38F7"  # blue-neo (era amarelo #FFD700)

# ── TYPOGRAPHY ────────────────────────────────────────────────────────────────
_HEAD = "Poppins"
_BODY = "Inter"
_MONO = "JetBrains Mono"

_FALLBACK = {_HEAD: "Segoe UI", _BODY: "Segoe UI", _MONO: "Consolas"}


def _font(family: str, size: int, bold: bool = False) -> tuple:
    """Returns CTkFont-compatible tuple. Auto-fallback if family not installed."""
    try:
        import tkinter as tk
        import tkinter.font as tkfont
        r = tk.Tk()
        r.withdraw()
        families = tkfont.families(r)
        r.destroy()
        fam = family if family in families else _FALLBACK.get(family, "Segoe UI")
    except Exception:
        fam = _FALLBACK.get(family, "Segoe UI")
    weight = "bold" if bold else "normal"
    return (fam, size, weight)


# Font presets (callable so tkinter is initialized before first call)
def FONT_DISPLAY():    return _font(_HEAD, 28, bold=True)
def FONT_HEADING():    return _font(_HEAD, 18, bold=True)
def FONT_HEADING_SM(): return _font(_HEAD, 14, bold=True)
def FONT_BODY():       return _font(_BODY, 13)
def FONT_BODY_BOLD():  return _font(_BODY, 13, bold=True)
def FONT_CAPTION():    return _font(_BODY, 11)
def FONT_OVERLINE():   return _font(_BODY, 11, bold=True)
def FONT_MONO():       return _font(_MONO, 12)
def FONT_MONO_SM():    return _font(_MONO, 11)

# ── COMPONENT SIZES ───────────────────────────────────────────────────────────
CORNER_SM  = 6    # badges, tags
CORNER_MD  = 8    # buttons, inputs, nav items (default)
CORNER_LG  = 12   # cards, section containers
CORNER_XL  = 16   # large cards

BTN_HEIGHT   = 40
INPUT_HEIGHT = 40

SIDEBAR_WIDTH = 200
