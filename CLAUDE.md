# CLAUDE.md — Voice Commander

Configuracao do Claude Code para o projeto `voice-commander`.

---

## Projeto

Voice Commander e uma ferramenta voice-to-text pessoal para Windows. Captura audio via hotkey global, transcreve com Whisper local e processa com Gemini, colando o resultado na janela ativa via ctypes SendInput.

- **Versao:** source unica em `__version__` em `voice/__init__.py` (atualmente `1.0.15`)
- **Plataforma:** Windows 10/11 exclusivo — usa `ctypes.windll`, `winsound`, Named Mutex Win32, `SendInput`
- **Sem suporte macOS/Linux por design**

---

## Stack e Dependencias

| Pacote | Versao Pinada | Proposito |
|--------|--------------|-----------|
| `faster-whisper` | 1.2.1 | Transcricao local (small model, CPU/int8) |
| `google-genai` | 1.63.0 | Gemini 2.5 Flash (correcao, prompts, query) |
| `keyboard` | 0.13.5 | Registro de hotkeys globais |
| `sounddevice` | 0.5.5 | Captura de audio do microfone |
| `numpy` | 2.4.2 | Processamento de frames de audio |
| `pystray` | 0.19.5 | System tray icon (3 estados visuais) |
| `Pillow` | 11.1.0 | Geracao de icones para o tray |
| `customtkinter` | 5.2.2 | Dialog de onboarding (janela de licenca) |

Versoes em `requirements.txt`. Atualizar somente com intencao explicita e novo pin.

---

## Comandos Essenciais

```bash
# Desenvolvimento (com console)
python -m voice

# Producao (sem console — comportamento real)
pythonw.exe -m voice

# Instalar dependencias
pip install -r requirements.txt

# Verificar sintaxe antes de qualquer commit
python -m py_compile voice/*.py

# Build PyInstaller + Inno Setup
cd build && build.bat

# Gerar chave de licenca
python scripts/generate_license_key.py

# Listar dispositivos de audio disponiveis
python -c "import sounddevice; print(sounddevice.query_devices())"
```

---

## Estrutura do Projeto

```
voice-commander/
├── voice/                      <- Pacote principal (17 modulos)
│   ├── app.py                  <- Entry point — main(), hotkey loop, startup
│   ├── config.py               <- load_config(), _save_env(), _reload_config(), license validation
│   ├── state.py                <- Estado global (recording, mode, buffers)
│   ├── audio.py                <- Gravacao sounddevice, toggle, beeps
│   ├── gemini.py               <- Cliente Gemini, modos de processamento
│   ├── ai_provider.py          <- Facade routing + retry utils (OpenRouter > Gemini > OpenAI)
│   ├── openrouter.py           <- OpenRouter gateway (OpenAI-compatible, smart routing)
│   ├── openai_.py              <- Implementacao OpenAI (provider legacy)
│   ├── modes.py                <- Nomes, labels e acoes centralizados de todos os modos
│   ├── tray.py                 <- System tray, 3 estados visuais, menu
│   ├── ui.py                   <- Settings dialog (customtkinter) com sidebar lateral
│   ├── overlay.py              <- Toast/feedback visual (tkinter puro)
│   ├── history_search.py       <- Busca em history.jsonl (overlay)
│   ├── clipboard.py            <- Leitura/escrita de clipboard via ctypes
│   ├── paths.py                <- Resolucao de paths (_BASE_DIR)
│   ├── mutex.py                <- Named Mutex Win32 (instancia unica)
│   ├── logging_.py             <- Setup de log e rotacao de sessao
│   ├── shutdown.py             <- graceful_shutdown, release mutex
│   ├── theme.py                <- Design tokens JP Labs (cores, fontes, espacamento)
│   └── __init__.py             <- __version__ = "1.0.15"
├── tests/                      <- 250 testes em 19 arquivos
├── requirements.txt            <- Dependencias pinadas (Python 3.13)
├── .env.example                <- Template de configuracao
├── .env                        <- Configuracao local (NUNCA commitar)
├── .gitignore                  <- history.jsonl + logs excluidos
├── README.md                   <- Documentacao de usuario
├── ROADMAP.md                  <- Epic 4-5 + status atual
├── launch_voice.vbs            <- Launcher silencioso (unico canonico)
├── voice-run.bat               <- Launcher de debug
├── voice-setup.bat             <- Setup inicial do ambiente
├── setup_voice_task.ps1        <- Registra no Task Scheduler do Windows
├── voice_watchdog.ps1          <- Watchdog para restart automatico
├── build/
│   ├── build.bat               <- PyInstaller + Inno Setup
│   ├── installer.iss           <- Script Inno Setup (AppVersion hardcoded — sync manual)
│   └── create_icon.py          <- Gera icon.ico para o build
├── dist/                       <- Builds gerados (nao commitar)
├── scripts/
│   └── generate_license_key.py <- Geracao de chaves HMAC locais
├── docs/
│   ├── PRD.md                  <- PRD formal (Epics 1-5)
│   ├── audit-features.md       <- Feature Discovery & Waste Audit (2026-04-03)
│   ├── audit-quality.md        <- Code Quality & Performance Audit (2026-04-03)
│   ├── audit-architecture.md   <- Architecture Review (2026-04-03)
│   └── n8n-license-workflow.md <- Fluxo do workflow n8n de licencas
└── .claude/
    ├── agent-memory/dev/MEMORY.md  <- Memoria persistente do DEX
    └── agent-memory/pm/MEMORY.md   <- Memoria persistente do MORGAN
```

---

## Agentes Responsaveis

| Tarefa | Agente |
|--------|--------|
| Codigo Python (`voice/`, scripts) | `@dev` (DEX) |
| PRD, planejamento, stories, roadmap | `@pm` (MORGAN) |
| Git commits e push | `@devops` (GAGE) |
| Arquitetura, refactoring design | `@architect` |
| Security review | `@security` |

**FORGE nunca toca neste projeto** — FORGE e exclusivo para Next.js/React. Todo codigo aqui e Python puro.

---

## Modos de Operacao

### Ciclo de modos (via `RECORD_HOTKEY` + `CYCLE_HOTKEY`)

O modo ativo e exibido no tooltip do tray. Trocar modo: `CYCLE_HOTKEY` (default: `Ctrl+Shift+Tab`).

| Modo (id) | Nome PT | Comportamento |
|-----------|---------|---------------|
| `transcribe` | Transcrever | Whisper -> correcao ortografica Gemini -> cola |
| `email` | Email | Whisper -> Gemini formata como email profissional -> cola |
| `simple` | Prompt Simples | Whisper -> Gemini organiza em bullet points -> cola |
| `prompt` | Prompt COSTAR | Whisper -> Gemini estrutura em XML COSTAR (SYSTEM + USER) -> cola |
| `query` | Perguntar ao Gemini | Whisper -> Gemini responde a pergunta -> cola resposta |
| `bullet` | Bullet Dump | Whisper -> Gemini gera lista de bullets -> cola |
| `translate` | Traduzir | Whisper -> Gemini traduz para `TRANSLATE_TARGET_LANG` (default: `en`) -> cola |

Todos usam `RECORD_HOTKEY` (default: `Ctrl+Shift+Space`) para iniciar/parar gravacao.
`CYCLE_MODES` no `.env` controla quais modos entram no ciclo (default: 5 primeiros).

Todos os hotkeys usam `suppress=False` (ver Gotchas).

---

## AI Provider Routing

Prioridade: `OPENROUTER_API_KEY` > `GEMINI_API_KEY` > `OPENAI_API_KEY`

Via OpenRouter (recomendado), smart routing automatico:
- Modos rapidos (transcribe, email, bullet, translate) -> Llama 4 Scout
- Modos complexos (simple, prompt, query) -> Gemini 2.5 Flash

---

## Variaveis de `.env`

Fonte da verdade: `voice/config.py` (`load_config()`). Defaults abaixo refletem o estado real do codigo.

### Essenciais

| Variavel | Default | Tipo | Descricao |
|----------|---------|------|-----------|
| `LICENSE_KEY` | — | string | Chave HMAC local. Formato: `vc-{expiry_base64}-{hmac}` |
| `OPENROUTER_API_KEY` | *(vazio)* | string | Gateway unico (recomendado). Obter em openrouter.ai/keys |
| `GEMINI_API_KEY` | — | string | Fallback direto. Obter em aistudio.google.com/apikey |
| `GEMINI_MODEL` | `gemini-2.5-flash` | string | Modelo Gemini para correcao/estruturacao |
| `OPENAI_API_KEY` | *(vazio)* | string | Legacy fallback |
| `OPENAI_MODEL` | `gpt-4o-mini` | string | Modelo OpenAI |

### Transcricao (Whisper)

| Variavel | Default | Tipo | Descricao |
|----------|---------|------|-----------|
| `WHISPER_MODEL` | `tiny` | string | Modelo fallback global |
| `WHISPER_MODEL_FAST` | `tiny` | string | Modelo para modos rapidos (transcribe, email, bullet, translate) |
| `WHISPER_MODEL_QUALITY` | `small` | string | Modelo para modos que exigem precisao (simple, prompt, query) |
| `WHISPER_DEVICE` | `cpu` | string | `cpu` \| `cuda` (GPU, se disponivel) |
| `WHISPER_BEAM_SIZE` | `1` | int | Trade-off velocidade/precisao. 1=rapido, 5=preciso |
| `WHISPER_LANGUAGE` | *(vazio)* | string | Vazio = auto-detect PT+EN \| `pt` \| `en` |
| `WHISPER_INITIAL_PROMPT` | *(vazio)* | string | Contexto de vocabulario para o Whisper. Vazio = padrao PT-BR |
| `STT_PROVIDER` | `whisper` | string | `whisper` (local, offline) \| `gemini` (cloud, melhor PT-BR) |
| `GEMINI_CORRECT` | `true` | string | `true` = Gemini corrige raw Whisper; `false` = retorna texto cru |
| `VAD_THRESHOLD` | `0.3` | float | Sensibilidade VAD: 0.1 (muito sensivel) a 0.9 (pouco sensivel) |

### Gravacao e Audio

| Variavel | Default | Tipo | Descricao |
|----------|---------|------|-----------|
| `MAX_RECORD_SECONDS` | `120` | int | Timeout de gravacao. Bip de aviso 5s antes |
| `AUDIO_DEVICE_INDEX` | *(vazio)* | int | Indice do microfone. Vazio = padrao do SO |
| `PASTE_DELAY_MS` | `50` | int | Delay adicional antes de colar (ms) |
| `SOUND_START` | *(vazio)* | string | Path para som customizado de inicio. Vazio = beep padrao |
| `SOUND_SUCCESS` | *(vazio)* | string | Path para som de sucesso |
| `SOUND_ERROR` | *(vazio)* | string | Path para som de erro |
| `SOUND_WARNING` | *(vazio)* | string | Path para som de aviso |
| `SOUND_SKIP` | *(vazio)* | string | Path para som de skip |

### Hotkeys

| Variavel | Default | Tipo | Descricao |
|----------|---------|------|-----------|
| `RECORD_HOTKEY` | `ctrl+shift+space` | string | Iniciar/parar gravacao |
| `CYCLE_HOTKEY` | `ctrl+shift+tab` | string | Ciclar entre modos do ciclo |
| `CYCLE_MODES` | `transcribe,email,simple,prompt,query` | string | Modos no ciclo (separados por virgula) |
| `QUERY_SYSTEM_PROMPT` | *(vazio)* | string | System prompt customizado para modo query |
| `HISTORY_HOTKEY` | `ctrl+shift+h` | string | Abrir busca no historico |

### Features

| Variavel | Default | Tipo | Descricao |
|----------|---------|------|-----------|
| `SELECTED_MODE` | `transcribe` | string | Modo ativo ao iniciar |
| `OVERLAY_ENABLED` | `true` | string | Toast de feedback visual. `false` = desativar |
| `CLIPBOARD_CONTEXT_ENABLED` | `true` | string | Injetar clipboard como contexto no modo query |
| `CLIPBOARD_CONTEXT_MAX_CHARS` | `2000` | int | Maximo de chars do clipboard enviados ao Gemini |
| `TRANSLATE_TARGET_LANG` | `en` | string | Idioma alvo do modo translate |
| `DEBUG_PERF` | `false` | string | Imprimir `[PERF]` no log com breakdown de latencia por fase |

### OpenRouter (modelos por modo)

| Variavel | Default | Tipo | Descricao |
|----------|---------|------|-----------|
| `OPENROUTER_MODEL_FAST` | `meta-llama/llama-4-scout-17b-16e-instruct` | string | Modelo para modos rapidos |
| `OPENROUTER_MODEL_QUALITY` | `google/gemini-2.5-flash` | string | Modelo para modos complexos |

### Observabilidade

| Variavel | Default | Tipo | Descricao |
|----------|---------|------|-----------|
| `HISTORY_MAX_ENTRIES` | `500` | int | Maximo de entradas em `history.jsonl` |
| `LOG_KEEP_SESSIONS` | `5` | int | Sessoes de log arquivadas a manter |

---

## Capabilities (o que voce PODE fazer neste projeto)

- **Docs lookup:** Context7 MCP (Python, faster-whisper, google-genai, pystray docs atualizadas)
- **Web search:** Exa MCP + WebSearch/WebFetch nativos (pesquisa tecnica)
- **Docs:** Google Docs + Drive MCP (documentacao, specs)

---

## Definition of Done

```
[ ] python -m py_compile voice/*.py   — zero erros de sintaxe
[ ] pytest                            — 250+ testes passando
[ ] Testado com pythonw.exe           — sem console, comportamento real
[ ] .env nao commitado
[ ] .env.example atualizado se nova variavel
[ ] Log prefixes respeitados ([OK], [...], [WARN], [ERRO], [REC], [STOP], [SKIP], [INFO])
[ ] CI green (ruff + pytest + py_compile)
```

---

## Auto-Documentacao de Falhas

Quando uma abordagem falhar (erro inesperado, Whisper ou Gemini com comportamento errado):
1. Resolver o problema
2. Propor um novo gotcha para a secao "Gotchas Conhecidos" deste CLAUDE.md
3. JP aprova antes de adicionar

---

## Seguranca

- API keys SEMPRE em .env (nunca hardcoded)
- NUNCA exibir, imprimir ou repetir API keys, tokens ou secrets no chat
- Auditar dependencias antes de pip install (verificar se pacote e legitimo)
- License key secret ofuscado via XOR em config.py (nao expor em plain text)

---

## Padroes de Codigo

### Prefixos de Log

Todo output deve usar prefixos padronizados:

```python
[OK]    # Operacao concluida com sucesso
[...]   # Operacao em andamento
[WARN]  # Aviso nao-fatal
[ERRO]  # Erro (pode ou nao encerrar)
[REC]   # Gravacao iniciada
[STOP]  # Gravacao encerrada
[SKIP]  # Operacao pulada (sem audio, licenca expirada, etc.)
[INFO]  # Informacao de startup ou estado
[PERF]  # Breakdown de latencia por fase (so se DEBUG_PERF=true)
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
        "NOVA_VAR": "default_value",  # <- sempre com default explicito
        ...
    }
```

Atualizar `.env.example` com comentario explicativo ao adicionar nova variavel.

### Gemini — Singleton

```python
# CORRETO — sempre via helper
client = _get_gemini_client()
response = client.models.generate_content(...)

# ERRADO — nunca instanciar direto
from google import genai
client = genai.Client(api_key=key)  # <- nao fazer isso
```

### Threading

- `_toggle_lock` (threading.RLock) protege estado de gravacao (`is_recording`, `frames_buf`, `current_mode`)
- Sempre copiar `frames_buf` e `current_mode` DENTRO do lock antes de usar fora
- Threads daemon=True para nao bloquear exit
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

### `suppress=False` nos hotkeys e INTENCIONAL

Nao alterar para `suppress=True`. Com suppress=True, ha delay perceptivel em Ctrl+C, Ctrl+V, Shift+seta, etc. em todo o sistema. O risco de re-entrada e mitigado por `_toggle_lock`.

### `pythonw.exe` nao tem stdout/stderr

`sys.stdout` e `sys.stderr` sao `None` ao rodar via `pythonw.exe`. O codigo ja trata isso com verificacoes `if sys.stdout is not None`. Nunca assumir que stdout existe.

### `os._exit(0)` no tray quit e NECESSARIO

`_tray_on_quit` chama `os._exit(0)` ao final. Isso e intencional: pystray cria threads daemon que travam o `sys.exit()` normal. A sequencia correta e:
```
icon.stop() -> graceful_shutdown() -> os._exit(0)
```

### `_release_named_mutex()` e idempotente

A funcao checa `if _mutex_handle` antes de agir. Pode ser chamada multiplas vezes sem double-free.

### `current_mode` salvo ao INICIAR gravacao

O modo e capturado no momento do toggle de inicio, nao no momento de parar a gravacao. Intencional: o usuario pode mudar modo durante a gravacao.

### Onboarding antes do mutex

O dialog de onboarding (customtkinter) e chamado antes de `_acquire_named_mutex()`. Nao mover esta ordem.

### `build/installer.iss` tem `AppVersion` hardcoded

A versao no script Inno Setup nao e lida automaticamente de `__version__`. Sync manual a cada release.

### Fork de `_BASE_DIR` em dev vs .exe

Em desenvolvimento, arquivos ficam na raiz do repositorio. Em producao, ficam em `APPDATA/VoiceCommander/`. Testes manuais de paths devem ser feitos com `pythonw.exe`.

### `theme._font()` cacheia `tkfont.families()`

O cache e criado na primeira chamada e reutilizado. Se fontes forem instaladas durante a sessao, o cache nao sera atualizado (reiniciar o app).

---

## Veto Conditions

- **NUNCA** importar dependencia nova sem adicionar a `requirements.txt` com versao pinada
- **NUNCA** commitar `.env` (contem `GEMINI_API_KEY` e `LICENSE_KEY`)
- **SEMPRE** testar com `pythonw.exe` (sem console) antes de fechar qualquer story
- **NUNCA** usar `subprocess` com `shell=True` (substituido por ctypes)
- **NUNCA** usar `keyboard.send()` para paste (substituido por `_paste_via_sendinput()`)
- **NUNCA** instanciar `genai.Client()` diretamente — sempre via `_get_gemini_client()`

---

## Como Testar Manualmente

### Setup inicial
```bash
copy .env.example .env
# Editar .env com GEMINI_API_KEY e LICENSE_KEY validos
pip install -r requirements.txt
```

### Testar os modos
1. `python -m voice` (ou `pythonw.exe -m voice` para simular producao)
2. Aguardar startup — icone aparece na system tray; tooltip exibe modo ativo
3. **Ciclar modos:** `Ctrl+Shift+Tab` -> overlay exibe o novo modo por 1.5s
4. **Transcribe:** `Ctrl+Shift+Space` -> falar -> parar -> conferir correcao ortografica
5. **Email:** ciclar para `email` -> ditar rascunho -> conferir email formatado
6. **Query:** ciclar para `query` -> fazer pergunta -> conferir resposta

### Testar graceful shutdown
- Menu tray -> Encerrar -> confirmar que icone some, processo encerra limpo
- `Ctrl+C` no console (dev mode) -> mesma verificacao

---

## Build e Distribuicao

### Processo
```bash
python -m py_compile voice/*.py  # verificar sintaxe de todos os modulos
cd build && build.bat            # PyInstaller -> dist\VoiceCommander\ + Inno Setup -> dist\VoiceCommanderSetup.exe
```

### Checklist pre-release
- [ ] `__version__` em `voice/__init__.py` atualizado
- [ ] `AppVersion` em `build/installer.iss` sincronizado manualmente
- [ ] `requirements.txt` atualizado se nova dependencia
- [ ] Testado com `pythonw.exe` (sem console)
- [ ] `.env` nao incluido no build

---

## Licenca

O sistema usa validacao HMAC local (sem servidor, sem network call):

- **Formato da chave:** `vc-{expiry_base64}-{hmac}`
- **Geracao:** `python scripts/generate_license_key.py`
- **Secret:** ofuscado em `voice/config.py` via XOR (evita extracao por grep no `.exe`)
- **Expiracao:** verificada localmente a cada inicializacao
- **n8n workflow:** `docs/n8n-license-workflow.md` descreve o fluxo de geracao via webhook

---

*Voice Commander — JP Labs*
*Windows-only | Python 3.13 | DEX e o agente responsavel*
