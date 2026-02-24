# Voice Commander

Voice-to-text com 3 modos de hotkey para Windows. Grava sua voz, transcreve com Whisper local e cola o resultado onde o cursor estiver — sem janela, sem distração.

Optionalmente usa Gemini para corrigir transcrição e estruturar prompts.

---

## O que faz cada hotkey

| Hotkey | Modo | O que acontece |
|--------|------|----------------|
| `Ctrl+Shift+Space` | Transcrição pura | Transcreve e corrige erros de pronúncia via Gemini |
| `Ctrl+Alt+Space` | Prompt simples | Transcreve e organiza em bullet points (para usar em qualquer LLM) |
| `Ctrl+CapsLock+Space` | Prompt estruturado | Transcreve e formata em SYSTEM + USER prompt com XML tags (framework COSTAR) |
| `Ctrl+Shift+Alt+Space` | Query direta Gemini | Transcreve e envia como pergunta ao Gemini — cola a resposta diretamente |

Todos os modos: pressione o hotkey para iniciar a gravação, pressione novamente para parar. O texto é colado automaticamente onde o cursor estiver.

O hotkey do modo 4 é configurável via `.env` (`QUERY_HOTKEY`). O default `ctrl+shift+alt+space` é seguro no Windows 11 — evita conflito com `ctrl+win+space` (Input Method do sistema).

Idiomas suportados: PT-BR e EN (detecção automática, pode misturar os dois).

---

## Pré-requisitos

- Windows 10 ou 11
- Python 3.10 ou superior
- Microfone funcionando
- Chave de API do Google Gemini (opcional — sem ela, o modo de transcrição pura ainda funciona, mas sem correção)

---

## Instalação

### 1. Clonar o repositório

```
git clone https://github.com/thejplabs/voice-commander.git
cd voice-commander
```

### 2. Instalar dependências Python

```
pip install -r requirements.txt
```

Na primeira execução o Whisper vai baixar o modelo `small` (~244 MB). Isso acontece uma vez só.

Dependências incluídas: `sounddevice`, `numpy`, `faster-whisper`, `keyboard`, `google-genai`, `pystray`, `Pillow`.

> As versões das dependências estão fixadas no `requirements.txt`. Para atualizar intencionalmente, veja as instruções no topo do arquivo.

### 3. Configurar o .env

Copie o arquivo de exemplo e configure:

```
copy .env.example .env
```

Edite `.env` e preencha os valores desejados:

- `GEMINI_API_KEY` — chave obtida em https://aistudio.google.com/apikey (obrigatória para os modos de prompt)
- `WHISPER_MODEL` — modelo a usar: `tiny`, `base`, `small` (default), `medium`, `large-v2`, `large-v3`
- `MAX_RECORD_SECONDS` — limite de gravação em segundos (default: 120). Um bip de aviso soa 5s antes do timeout.
- `AUDIO_DEVICE_INDEX` — índice do microfone (deixe em branco para usar o padrão do sistema)
- `QUERY_HOTKEY` — hotkey para o modo Query Direta Gemini (default: `ctrl+shift+alt+space`)
- `QUERY_SYSTEM_PROMPT` — prompt de sistema customizado para o modo query (deixe em branco para usar o padrão)
- `HISTORY_MAX_ENTRIES` — número máximo de entradas em `history.jsonl` (default: 500). Entradas mais antigas são removidas automaticamente ao ultrapassar o limite.
- `LOG_KEEP_SESSIONS` — número de arquivos de sessão de log a manter (default: 5). Logs mais antigos são deletados automaticamente no startup.

Sem a chave Gemini, `Ctrl+Shift+Space` ainda funciona (transcrição sem correção). Os outros modos precisam da chave; o modo Query Direta retorna `[SEM RESPOSTA GEMINI] <transcrição>` como fallback.

### 4. Testar manualmente

```
python voice.py
```

O terminal vai mostrar os hotkeys registrados. Pressione `Ctrl+C` para encerrar.

### 5. Configurar para iniciar automaticamente no login (opcional)

Execute o setup uma vez como Administrador:

```
powershell -ExecutionPolicy Bypass -File setup_voice_task.ps1
```

Isso registra o watchdog no Task Scheduler. A partir do próximo login, o `voice.py` vai iniciar automaticamente em background e se manter vivo — sem janela, sem ícone na barra.

Para iniciar sem reiniciar o computador:

```
Start-ScheduledTask -TaskName "VoiceTranscription"
```

---

## Como usar

1. Inicie o `voice.py` (manualmente ou via Task Scheduler)
2. Um ícone cinza aparece na system tray (área de notificação do Windows) — indica que está ativo e aguardando
3. Clique onde quer que o texto apareça (campo de texto, editor, terminal, etc.)
4. Pressione o hotkey desejado para iniciar a gravação — você vai ouvir um bip e o ícone fica vermelho
5. Fale
6. Pressione o mesmo hotkey novamente para parar — o ícone fica amarelo durante o processamento, depois volta a cinza, e você vai ouvir dois bips quando o texto for colado

Para encerrar: clique com o botão direito no ícone da tray e selecione **Encerrar**, ou use `Ctrl+C` no terminal.

O log fica em `voice.log` na pasta do projeto. A cada inicialização o log anterior é renomeado para `voice.YYYY-MM-DD_HH-MM-SS.log` (rotação automática). O menu "Status" na tray exibe o estado atual, último modo usado e configurações ativas.

---

## Como desinstalar

### Remover do Task Scheduler

```
powershell -Command "Unregister-ScheduledTask -TaskName 'VoiceTranscription' -Confirm:$false"
```

### Matar o processo em background

```
powershell -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*voice.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId }"
```

### Remover dependências (opcional)

```
pip uninstall sounddevice numpy faster-whisper keyboard google-genai pystray Pillow
```

---

## Troubleshooting

**"Outra instância do voice.py já está rodando"**
O mutex garante instância única. Mate o processo anterior antes de iniciar:
```
powershell -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*voice.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId }"
```

**Hotkeys não respondem**
Verifique o `voice.log` para erros de import. Provavelmente alguma dependência não foi instalada corretamente. Rode `pip install -r requirements.txt` novamente.

**Gemini desativado (sem .env)**
Crie o arquivo `.env` com `GEMINI_API_KEY=sua_chave`. Sem ele, `Ctrl+Alt+Space` e `Ctrl+CapsLock+Space` retornam o texto bruto sem estruturação.

**Erro de áudio / microfone não encontrado**
Verifique se o microfone padrão do Windows está configurado corretamente em Configurações > Sistema > Som > Entrada. Para usar um microfone específico, liste os dispositivos disponíveis e configure `AUDIO_DEVICE_INDEX` no `.env`:
```
python -c "import sounddevice; print(sounddevice.query_devices())"
```

---

## Arquitetura

```
voice-commander/
├── voice.py                # Script principal — hotkeys, gravação, transcrição, Gemini
├── voice_watchdog.ps1      # Watchdog PowerShell — mantém voice.py vivo
├── setup_voice_task.ps1    # Registra watchdog no Task Scheduler (rodar 1x como admin)
├── voice-run.bat           # Atalho para rodar voice.py com janela (debug)
├── voice-setup.bat         # Instala dependências via pip
├── launch_voice.vbs        # Inicia voice.py via pythonw.exe (path absoluto com fallback)
├── requirements.txt        # Dependências Python com versões fixadas
├── .env.example            # Template de configuração (.env com GEMINI_API_KEY, WHISPER_MODEL, etc.)
├── .gitignore
├── history.jsonl           # Histórico de transcrições (append-only, ignorado pelo git — dado pessoal)
└── voice.YYYY-MM-DD_*.log  # Logs de sessões anteriores (rotação automática, N sessões conforme LOG_KEEP_SESSIONS)
```

O `history.jsonl` é gerado automaticamente e acumula todas as transcrições com campos `timestamp`, `mode`, `raw_text`, `processed_text`, `duration_seconds` e `chars`. Entradas com erro incluem `"error": true` e `processed_text: null`. O arquivo não é versionado (dado pessoal).

---

JP Labs — Voice Commander
