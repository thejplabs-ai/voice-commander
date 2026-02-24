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

Todos os modos: pressione o hotkey para iniciar a gravação, pressione novamente para parar. O texto é colado automaticamente onde o cursor estiver.

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

### 3. Configurar a chave Gemini

Copie o arquivo de exemplo e adicione sua chave:

```
copy .env.example .env
```

Edite `.env` e substitua `your_gemini_api_key_here` pela sua chave obtida em https://aistudio.google.com/apikey.

Sem a chave, `Ctrl+Shift+Space` ainda funciona (transcrição sem correção). Os outros dois modos precisam da chave para funcionar.

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
2. Clique onde quer que o texto apareça (campo de texto, editor, terminal, etc.)
3. Pressione o hotkey desejado para iniciar a gravação — você vai ouvir um bip
4. Fale
5. Pressione o mesmo hotkey novamente para parar — você vai ouvir dois bips quando o texto for colado

O log fica em `voice.log` na pasta do projeto.

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
pip uninstall sounddevice numpy faster-whisper keyboard google-genai
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
Verifique se o microfone padrão do Windows está configurado corretamente em Configurações > Sistema > Som > Entrada.

---

## Arquitetura

```
voice-commander/
├── voice.py                # Script principal — hotkeys, gravação, transcrição, Gemini
├── voice_watchdog.ps1      # Watchdog PowerShell — mantém voice.py vivo
├── setup_voice_task.ps1    # Registra watchdog no Task Scheduler (rodar 1x como admin)
├── voice-run.bat           # Atalho para rodar voice.py com janela (debug)
├── voice-setup.bat         # Instala dependências via pip
├── voice-silent.vbs        # Inicia voice.py via python.exe sem janela
├── voice-startup.vbs       # Inicia voice.py via pythonw.exe sem janela
├── launch_voice.vbs        # Inicia voice.py via pythonw.exe (path absoluto com fallback)
├── requirements.txt        # Dependências Python
├── .env.example            # Template da chave Gemini
└── .gitignore
```

---

JP Labs — Voice Commander
