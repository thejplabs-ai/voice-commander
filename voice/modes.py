# voice/modes.py — Definições centralizadas dos modos de operação

"""Centraliza nomes e labels de modos para evitar duplicação entre módulos."""


# Nomes em português claro para tooltip/tray/overlay (ciclo de modo)
# Fonte original: voice/tray.py e voice/overlay.py (_MODE_NAMES_PT)
MODE_NAMES_PT: dict[str, str] = {
    "transcribe": "Transcrever",
    "email":      "Email",
    "simple":     "Prompt Simples",
    "prompt":     "Prompt COSTAR",
    "query":      "Perguntar ao Gemini",
    "bullet":     "Bullet Dump",
    "translate":  "Traduzir",
    "—":          "—",
}

# Labels de ação curtos para o overlay durante processamento
# Fonte original: voice/overlay.py (_MODE_LABELS) e voice/audio.py (_MODE_LABELS)
MODE_LABELS: dict[str, str] = {
    "transcribe": "Transcrevendo",
    "simple":     "Prompt Simples",
    "prompt":     "Prompt COSTAR",
    "query":      "Consultando IA",
    "bullet":     "Bullet Dump",
    "email":      "Email Draft",
    "translate":  "Traduzindo",
}

# Labels de ação para log de terminal (mais descritivos)
# Fonte original: voice/audio.py (_MODE_ACTIONS)
MODE_ACTIONS: dict[str, str] = {
    "transcribe": "Corrigindo",
    "simple":     "Simplificando prompt",
    "prompt":     "Estruturando prompt (COSTAR)",
    "query":      "Consultando AI (query direta)",
    "bullet":     "Gerando bullets",
    "email":      "Rascunhando email",
    "translate":  "Traduzindo",
}


def get_mode_name(mode_id: str) -> str:
    """Retorna nome em português do modo, ou o mode_id se não encontrado."""
    return MODE_NAMES_PT.get(mode_id, mode_id)


def get_mode_label(mode_id: str) -> str:
    """Retorna label curto de ação do modo (para overlay), ou o mode_id se não encontrado."""
    return MODE_LABELS.get(mode_id, mode_id)


def get_mode_action(mode_id: str) -> str:
    """Retorna label de ação descritivo (para log de terminal), ou 'Processando' se não encontrado."""
    return MODE_ACTIONS.get(mode_id, "Processando")
