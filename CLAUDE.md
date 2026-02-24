# CLAUDE.md — Voice Commander

Configuração do Claude Code para o projeto `voice-commander`.

---

## Projeto

Voice Commander é uma ferramenta voice-to-text pessoal para Windows. Captura áudio via hotkey global, transcreve com Whisper local e processa com Gemini, colando o resultado na janela ativa via ctypes SendInput.

- **Versão:** source única em `__version__` em `voice.py` (atualmente `1.0.11`)
- **Plataforma:** Windows 10/11 exclusivo — usa `ctypes.windll`, `winsound`, Named Mutex Win32, `SendInput`
- **Sem suporte macOS/Linux por design** — não escopo até Epic 5+

---

## Stack e Dependências

| Pacote | Versão Pinada | Propósito |
|--------|--------------|-----------|
| `faster-whisper` | 1.2.1 | Transcrição local (small model, CPU/int8) |
| `google-genai` | 1.63.0 | Gemini 2.0 Flash (correção, prompts, query) |
| `keyboard` | 0.13.5 | Registro de hotkeys globais |
| `sounddevice` | 0.5.5 | Captura de áudio do microfone |
| `numpy` | 2.4.2 | Processamento de frames de áudio |
| `pystray` | 0.19.5 | System tray icon (3 estados visuais) |
| `Pillow` | 11.1.0 | Geração de ícones para o tray |
| `customtkinter` | 5.2.2 | Dialog de onboarding (janela de licença) |

Versões em `requirements.txt`. Atualizar somente com intenção explícita e novo pin.

---

## Comandos Essenciais

```bash
# Desenvolvimento (com console)
python voice.py

# Produção (sem console — comportamento real)
pythonw.exe voice.py

# Instalar dependências
pip install -r requirements.txt

# Verificar sintaxe antes de qualquer commit
python -m py_compile voice.py

# Build PyInstaller + Inno Setup
cd build && build.bat

# Gerar chave de licença
python scripts/generate_license_key.py

# Listar dispositivos de áudio disponíveis
python -c "import sounddevice; print(sounddevice.query_devices())"
```

---

## Estrutura do Projeto

```
voice-commander/
├── voice.py                    ← Arquivo principal — TODO o app (monólito intencional por ora)
├── requirements.txt            ← Dependências pinadas (Python 3.13)
├── .env.example                ← Template de configuração
├── .env                        ← Configuração local (NUNCA commitar)
├── .gitignore                  ← history.jsonl + logs excluídos
├── README.md                   ← Documentação de usuário
├── ROADMAP.md                  ← Sprints 1-3 (feito) + Epic 4-5 (planejado)
├── launch_voice.vbs            ← Launcher silencioso (único canônico)
├── voice-run.bat               ← Launcher de debug
├── voice-setup.bat             ← Setup inicial do ambiente
├── setup_voice_task.ps1        ← Registra no Task Scheduler do Windows
├── voice_watchdog.ps1          ← Watchdog para restart automático
├── build/
│   ├── build.bat               ← PyInstaller + Inno Setup
│   ├── installer.iss           ← Script Inno Setup (AppVersion hardcoded — sync manual)
│   └── create_icon.py          ← Gera icon.ico para o build
├── dist/                       ← Builds gerados (não commitar)
├── scripts/
│   └── generate_license_key.py ← Geração de chaves HMAC locais
├── docs/
│   ├── PRD.md                  ← PRD formal (Epics 1-5)
│   └── n8n-license-workflow.md ← Fluxo do workflow n8n de licenças
└── .claude/
    └── agent-memory/dev/MEMORY.md  ← Memória persistente do DEX
```

---

## Agentes Responsáveis

| Tarefa | Agente |
|--------|--------|
| Código Python (`voice.py`, scripts) | `@dev` (DEX) |
| PRD, planejamento, stories, roadmap | `@pm` (MORGAN) |
| Git commits e push | `@devops` (GAGE) |
| Arquitetura, refactoring design | `@architect` |
| Security review | `@security` |

**⚠️ FORGE nunca toca neste projeto** — FORGE é exclusivo para Next.js/React. Todo código aqui é Python puro.

---

## 4 Modos de Operação

| Hotkey | Modo | Comportamento |
|--------|------|---------------|
| `Ctrl+Shift+Space` | Transcrição pura | Whisper → correção ortográfica Gemini → cola |
| `Ctrl+Alt+Space` | Prompt simples | Whisper → Gemini (bullet points) → cola |
| `Ctrl+CapsLock+Space` | Prompt COSTAR | Whisper → Gemini (estrutura XML COSTAR) → cola |
| `Ctrl+Shift+Alt+Space` | Query direta | Whisper → Gemini responde à pergunta → cola resposta |

Todos os hotkeys usam `suppress=False` (ver Gotchas). Hotkey do modo 4 configurável via `QUERY_HOTKEY` no `.env`.

---

## Variáveis de `.env`

| Variável | Default | Tipo | Descrição |
|----------|---------|------|-----------|
| `LICENSE_KEY` | — | string | Chave HMAC local. Formato: `vc-{expiry_base64}-{hmac}` |
| `GEMINI_API_KEY` | — | string | Obter em https://aistudio.google.com/apikey |
| `WHISPER_MODEL` | `small` | string | `tiny` \| `base` \| `small` \| `medium` \| `large-v2` \| `large-v3` |
| `MAX_RECORD_SECONDS` | `120` | int | Timeout de gravação. Bip de aviso 5s antes |
| `AUDIO_DEVICE_INDEX` | *(vazio)* | int | Índice do microfone. Vazio = padrão do SO |
| `QUERY_HOTKEY` | `ctrl+shift+alt+space` | string | Hotkey do modo 4 |
| `QUERY_SYSTEM_PROMPT` | *(vazio)* | string | System prompt customizado para modo 4 |
| `WHISPER_LANGUAGE` | *(vazio)* | string | Vazio = auto-detect PT+EN \| `pt` \| `en` |
| `HISTORY_MAX_ENTRIES` | `500` | int | Máximo de entradas em `history.jsonl` |
| `LOG_KEEP_SESSIONS` | `5` | int | Sessões de log arquivadas a manter |

**⚠️ `voice.jplabs.ai`** — domínio referenciado no `.env.example` como URL de compra. Placeholder — URL a definir antes do Epic 5 (server-side license).

---

## Padrões de Código

### Prefixos de Log

Todo output deve usar prefixos padronizados:

```python
[OK]    # Operação concluída com sucesso
[...]   # Operação em andamento
[WARN]  # Aviso não-fatal
[ERRO]  # Erro (pode ou não encerrar)
[REC]   # Gravação iniciada
[STOP]  # Gravação encerrada
[SKIP]  # Operação pulada (sem áudio, licença expirada, etc.)
[INFO]  # Informação de startup ou estado
```

### Paths — `_BASE_DIR`

```python
# dev:  _BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# .exe: _BASE_DIR = APPDATA/VoiceCommander (criado automaticamente)
if getattr(sys, 'frozen', False):
    _BASE_DIR = os.path.join(os.environ.get("APPDATA", ...), "VoiceCommander")
else:
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))
```

**SEMPRE** usar `_BASE_DIR` para qualquer path de arquivo de dados. Nunca usar `__file__` ou caminhos relativos diretamente.

### Adicionar Nova Config

```python
def load_config():
    cfg = {
        "NOVA_VAR": "default_value",  # ← sempre com default explícito
        ...
    }
    # Para int, usar bloco try separado:
    try:
        cfg["NOVA_INT_VAR"] = int(cfg["NOVA_INT_VAR"])
    except (ValueError, KeyError):
        cfg["NOVA_INT_VAR"] = 120  # fallback seguro
```

Atualizar `.env.example` com comentário explicativo ao adicionar nova variável.

### Gemini — Singleton

```python
# CORRETO — sempre via helper
client = _get_gemini_client()
response = client.models.generate_content(...)

# ERRADO — nunca instanciar direto
from google import genai
client = genai.Client(api_key=key)  # ← não fazer isso
```

### Threading

- `_toggle_lock` (threading.Lock) protege estado de gravação (`is_recording`, `frames_buf`, `current_mode`)
- Sempre copiar `frames_buf` e `current_mode` DENTRO do lock antes de usar fora
- Threads daemon=True para não bloquear exit
- `stop_event` (threading.Event) para sinalizar encerramento limpo

### Paste

```python
# CORRETO
_paste_via_sendinput()  # ctypes puro, bypass total de keyboard

# ERRADO
subprocess.run(["clip", ...])  # nunca subprocess
keyboard.send("ctrl+v")        # nunca keyboard para paste
```

---

## Gotchas Conhecidos

### `suppress=False` nos hotkeys é INTENCIONAL

Não alterar para `suppress=True`. Com suppress=True, há delay perceptível em Ctrl+C, Ctrl+V, Shift+seta, etc. em todo o sistema. O risco de re-entrada é mitigado por `_toggle_lock`.

### `pythonw.exe` não tem stdout/stderr

`sys.stdout` e `sys.stderr` são `None` ao rodar via `pythonw.exe`. O código já trata isso com verificações `if sys.stdout is not None`. Nunca assumir que stdout existe — sempre checar antes de qualquer operação de console.

### `os._exit(0)` no tray quit é NECESSÁRIO

`_tray_on_quit` chama `os._exit(0)` ao final. Isso é intencional: pystray cria threads daemon que travam o `sys.exit()` normal. A sequência correta é:
```
icon.stop() → graceful_shutdown() → os._exit(0)
```

### `_release_named_mutex()` é idempotente

A função checa `if _mutex_handle` antes de agir. Pode ser chamada múltiplas vezes sem double-free. O `try/finally` em `graceful_shutdown()` garante que o mutex é sempre liberado.

### `current_mode` salvo ao INICIAR gravação

O modo é capturado no momento do toggle de início, não no momento de parar a gravação. Isso é intencional: o usuário pode pressionar outro hotkey durante a gravação, e o modo correto deve ser o que estava ativo no início.

### Onboarding antes do mutex

O dialog de onboarding (customtkinter) é chamado antes de `_acquire_named_mutex()`. Não mover esta ordem — o mutex deve ser adquirido só após o usuário concluir o onboarding para evitar bloquear a instância durante a UI de setup.

### `build/installer.iss` tem `AppVersion` hardcoded

A versão no script Inno Setup (`AppVersion=1.0.x`) não é lida automaticamente de `__version__`. É sync manual a cada release. Lembrar de atualizar antes de gerar o instalador.

### Fork de `_BASE_DIR` em dev vs .exe

Em desenvolvimento (`python voice.py`), arquivos ficam na raiz do repositório. Em produção (`VoiceCommander.exe`), ficam em `APPDATA/VoiceCommander/`. Testes manuais de comportamento de paths devem ser feitos com `pythonw.exe`, não apenas `python voice.py`.

---

## Veto Conditions

- **NUNCA** importar dependência nova sem adicionar a `requirements.txt` com versão pinada
- **NUNCA** commitar `.env` (contém `GEMINI_API_KEY` e `LICENSE_KEY`)
- **SEMPRE** testar com `pythonw.exe` (sem console) antes de fechar qualquer story
- **NUNCA** usar `subprocess` com `shell=True` (substituído por ctypes)
- **NUNCA** usar `keyboard.send()` para paste (substituído por `_paste_via_sendinput()`)
- **NUNCA** instanciar `genai.Client()` diretamente — sempre via `_get_gemini_client()`

---

## Como Testar Manualmente

### Setup inicial
```bash
copy .env.example .env
# Editar .env com GEMINI_API_KEY e LICENSE_KEY válidos
pip install -r requirements.txt
```

### Testar os 4 modos
1. `python voice.py` (ou `pythonw.exe voice.py` para simular produção)
2. Aguardar startup — ícone aparece na system tray
3. **Modo 1:** `Ctrl+Shift+Space` → falar → `Ctrl+Shift+Space` → conferir clipboard
4. **Modo 2:** `Ctrl+Alt+Space` → falar → `Ctrl+Alt+Space` → conferir bullet points
5. **Modo 3:** `Ctrl+CapsLock+Space` → falar → `Ctrl+CapsLock+Space` → conferir estrutura COSTAR
6. **Modo 4:** `Ctrl+Shift+Alt+Space` → fazer pergunta → `Ctrl+Shift+Alt+Space` → conferir resposta Gemini

### Testar graceful shutdown
- Menu tray → Encerrar → confirmar que ícone some, processo encerra limpo
- `Ctrl+C` no console (dev mode) → mesma verificação

### Verificar logs
```bash
# Último log de sessão:
type voice.log
# Histórico de transcrições:
type history.jsonl
```

---

## Build e Distribuição

### Processo
```bash
python -m py_compile voice.py    # verificar sintaxe
cd build && build.bat            # PyInstaller → dist\VoiceCommander\ + Inno Setup → dist\VoiceCommanderSetup.exe
```

### Checklist pré-release
- [ ] `__version__` em `voice.py` atualizado
- [ ] `AppVersion` em `build/installer.iss` sincronizado manualmente
- [ ] `requirements.txt` atualizado se nova dependência
- [ ] Testado com `pythonw.exe` (sem console)
- [ ] `.env` não incluído no build

---

## Licença

O sistema usa validação HMAC local (sem servidor, sem network call):

- **Formato da chave:** `vc-{expiry_base64}-{hmac}`
- **Geração:** `python scripts/generate_license_key.py`
- **Secret:** ofuscado em `voice.py` via XOR (evita extração por grep no `.exe`)
- **Expiração:** verificada localmente a cada inicialização
- **Fallback atual:** 72 horas de período de graça para network issues (Epic 5 implementa server-side)
- **n8n workflow:** `docs/n8n-license-workflow.md` descreve o fluxo de geração via webhook

---

*Voice Commander — JP Labs*
*Windows-only | Python 3.13 | DEX é o agente responsável*
