# Voice Commander — Roadmap de Melhorias

**Versão:** 1.0.11
**Data:** 2026-02-24
**Status:** Sprints 1-3 entregues | Sprint 4 planejada

---

## Contexto

Ferramenta voice-to-text pessoal do JP. 4 modos via hotkey global:
- `Ctrl+Shift+Space` — transcrição pura (Whisper + correção Gemini)
- `Ctrl+Alt+Space` — prompt simples (bullet points Gemini)
- `Ctrl+CapsLock+Space` — prompt estruturado COSTAR (XML tags Gemini)
- `Ctrl+Shift+Alt+Space` — query direta Gemini (responde à pergunta via voz, cola resposta)

Stack: Python 3.13, faster-whisper (small/CPU/int8), google-genai (Gemini 2.0 Flash), keyboard, sounddevice, ctypes, winsound, pystray, Pillow, customtkinter.

**Nota de nomenclatura:** Sprints 1-3 são retroativamente mapeados como Epics 1-3 no PRD formal (`docs/PRD.md`). A nomenclatura "Epic" substitui "Sprint" a partir do Epic 4.

---

## Sprint 1 — Fundação Estável

**Objetivo:** Eliminar dívida técnica de risco imediato.
**Agente:** DEX
**Estimativa:** 2.5 dias

### Story 1.1 — Pin de versões no requirements.txt

**AC:**
- Versão exata de cada pacote (via `pip freeze` do ambiente atual)
- Comentário com data do pin e versão Python testada
- README atualizado

### Story 1.2 — Cache da API key + configuração via .env

**AC:**
- `load_gemini_key()` executada **uma vez** no `main()` → variável de módulo `_GEMINI_API_KEY`
- Funções `correct_with_gemini()`, `simplify_as_prompt()`, `structure_as_prompt()` usam a variável de módulo (sem releitura de disco)
- `.env.example` atualizado com novas variáveis:
  - `GEMINI_API_KEY` (já existia)
  - `WHISPER_MODEL` (default: `small`, aceita `tiny`, `base`, `medium`)
  - `MAX_RECORD_SECONDS` (default: `120`)
  - `AUDIO_DEVICE_INDEX` (default: vazio = dispositivo padrão do SO)
- Log de startup exibe configs ativas (sem expor key completa — mostrar só últimos 4 chars)

### Story 1.3 — Timeout de gravação MAX_RECORD_SECONDS

**AC:**
- `MAX_RECORD_SECONDS` lido do `.env`, default 120s
- `record()` encerra automaticamente ao atingir o limite
- Log: `[WARN] Timeout de gravação atingido (Xs)`
- Bip de aviso 5s antes do timeout (frequência distinta)
- Após timeout: fluxo normal de transcrição (não aborta)

### Story 1.4 — Consolidação dos launchers VBS

**AC:**
- `voice-silent.vbs` e `voice-startup.vbs` **deletados**
- `launch_voice.vbs` é o único launcher canônico
- `setup_voice_task.ps1` referencia apenas `launch_voice.vbs`
- README atualizado

---

## Sprint 2 — Visibilidade e UX

**Objetivo:** System tray + Modo 4 (Query Direta).
**Agente:** DEX
**Estimativa:** 4 dias
**Pré-requisito:** Sprint 1 concluída

### Story 2.1 — System Tray com estado (pystray)

**AC:**
- Ícone na system tray com 3 estados visuais: Idle / Gravando / Processando
- Tooltip: nome do app + estado atual + último modo usado
- Menu direito: "Status" (info) + "Encerrar" (shutdown gracioso)
- Ícone removido corretamente ao encerrar (sem fantasma)
- ⚠️ **RISCO:** Testar proof of concept no Windows 11 com `pythonw.exe` no DIA 1 da sprint antes de implementar completo. Se `pystray` falhar → testar `infi.systray`. Se ambos falharem → log apenas, escalar para JP.

### Story 2.2 — Modo 4: Query Direta Gemini

**AC:**
- Novo hotkey: `Ctrl+Win+Space` (testar conflito com Windows 11 antes de implementar)
- Alternativa se conflito: `Ctrl+Shift+Alt+Space`
- Hotkey configurável via `.env`: `QUERY_HOTKEY`
- Fluxo: gravar → Whisper → Gemini responde → clipboard → colar
- `QUERY_SYSTEM_PROMPT` configurável via `.env`
- Fallback sem Gemini: cola transcrição pura com prefixo `[SEM RESPOSTA GEMINI] `
- Bip início: 1 bip longo + 1 bip curto (padrão distinto)
- README + startup display atualizados

### Story 2.3 — Validação de microfone no startup

**AC:**
- `sd.InputStream` testado na inicialização com dispositivo configurado
- OK: `[OK] Microfone validado (dispositivo: X)`
- FAIL: `[WARN] Microfone não acessível` (app continua, não encerra)
- Timeout da validação: 3 segundos

---

## Sprint 3 — Observabilidade e Resiliência

**Objetivo:** Histórico persistente, rotação de log, graceful shutdown.
**Agente:** DEX
**Estimativa:** 2.5 dias
**Pré-requisito:** Sprint 2 concluída

### Story 3.1 — Histórico de transcrições (history.jsonl)

**AC:**
- `history.jsonl` na raiz (append-only, nunca sobrescreve)
- Campos: `timestamp`, `mode`, `raw_text`, `processed_text`, `duration_seconds`, `chars`
- Erros de transcrição: `"error": true, "processed_text": null`
- `.gitignore` atualizado (dado pessoal)
- `HISTORY_MAX_ENTRIES` via `.env` (default: 500)

### Story 3.2 — Log com rotação por sessão

**AC:**
- Ao iniciar: renomear `voice.log` → `voice.YYYY-MM-DD_HH-MM-SS.log`
- `LOG_KEEP_SESSIONS` via `.env` (default: 5 sessões)
- Logs antigos deletados automaticamente
- Rotação silenciosa (sem output ao usuário)

### Story 3.3 — Graceful shutdown com gravação ativa

**AC:**
- Se gravando no shutdown: `stop_event.set()` + aguardar `record_thread` (até 5s)
- Se frames capturados: transcrever e colar antes de encerrar
- Se transcrição > 10s: abortar com `[WARN] Shutdown forçado — transcrição abortada`
- Mutex liberado em qualquer cenário (try/finally)
- Log: `[OK] Shutdown gracioso concluído`

---

## Quick Wins — 2026-02-24

Melhorias pontuais executadas fora de sprint, antes do Epic 4:

| Item | Descrição |
|------|-----------|
| `.gitignore` | `history.jsonl` e `voice.*.log` adicionados (dados pessoais fora do VCS) |
| Singleton Gemini | `_get_gemini_client()` — lazy init, reutiliza conexão entre chamadas |
| `__version__` | Versão canônica em `voice.py` (`__version__ = "1.0.11"`) — source única |
| Clipboard ctypes | `_paste_via_sendinput()` via ctypes puro — remove dependência de `keyboard` no paste |

---

## Backlog

| Item | Motivo do adiamento |
|------|---------------------|
| BOM UTF-16 no clipboard | Nenhum problema reportado em produção com apps modernos |
| Dois modelos Whisper (tiny + small) | Complexidade de 2 instâncias em memória — aguardar feedback de latência |
| Seleção de dispositivo de áudio via .env | Coberto parcialmente pela Story 1.2 |

---

## Definition of Done (todas as stories)

- [ ] Código commitado no branch `feature/{story-id}` e mergeado em `master`
- [ ] `python -m py_compile voice.py` sem erros
- [ ] 3 modos existentes sem regressão (testado manualmente)
- [ ] Testado com `pythonw.exe` (sem console)
- [ ] `.env.example` atualizado se nova variável adicionada
- [ ] `README.md` atualizado se feature visível ao usuário
- [ ] Prefixos de log: `[OK]`, `[...]`, `[WARN]`, `[ERRO]`, `[REC]`, `[STOP]`, `[SKIP]`, `[INFO]`

---

*Voice Commander — JP Labs*
*Gerado por: ATLAS (análise) + MORGAN (roadmap) em 2026-02-24*
