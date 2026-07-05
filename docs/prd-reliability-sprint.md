# PRD: Sprint de Confiabilidade (Bug Bounty 2026-07-05)

> Origem: auditoria de arquitetura + bug bounty de 2026-07-05, decisões fechadas em sessão de grill.
> Este PRD é um documento de destino, não um manual de implementação. Deletar após o merge do sprint.

## Problem Statement

O JP usa o Voice Commander o dia inteiro como ferramenta principal de ditado e enfrenta dois problemas que destroem a confiança no app:

1. **O app "delira".** Ele pede uma transcrição e recebe outra coisa: lixo de alucinação do Whisper ("Legendas pela comunidade Amara.org", loops de repetição) colado na janela ativa, ou a camada de correção respondendo ao conteúdo ditado em vez de corrigi-lo (caso real: ditou o pedido de uma descrição de vaga e recebeu "Entendo! Vamos construir a descrição da vaga juntos..."). Foram 9 alucinações coladas registradas no histórico de produção, 3 delas na semana do bug report.

2. **O hotkey morre.** De tempos em tempos o atalho de gravação para de responder e a única saída é encerrar pelo tray e abrir de novo. Causa raiz: a lib `keyboard` (arquivada upstream em 2026-02) tem uma thread de processamento que morre silenciosamente com qualquer exceção de callback e não tem recovery possível, além de estado de teclas corrompido após lock/sleep do Windows.

Agravante estrutural: o executável instalado estava 3 meses defasado do source. Fixes feitos no repo nunca chegaram ao binário usado no dia-a-dia porque o processo de release é manual e sem verificação.

## Solution

Um Voice Commander confiável no nível "Superflow pessoal":

- Gravar silêncio nunca cola lixo: o app avisa "não detectei fala" e pronto.
- A correção nunca responde, resume ou traduz por conta própria: ou corrige, ou entrega o texto cru.
- O hotkey funciona sempre: sobrevive lock/sleep, exceções internas e uso prolongado. Se um combo não puder ser registrado (conflito com outro app), o usuário fica sabendo no startup, com som e log, em vez de descobrir por silêncio.
- Trocar de aba no browser nunca mais troca o modo do app escondido, e um ciclo de modo acidental morre sozinho no próximo restart.
- Um comando builda, versiona e instala o release. A versão fica visível no banner e no tooltip do tray, então defasagem entre source e binário instalado nunca mais passa despercebida.

## User Stories

1. Como usuário ditando, eu quero que uma gravação sem fala detectável resulte em aviso sonoro e visual e nenhum paste, para nunca mais ver "Amara.org" ou "Thank you for watching" colado no meu texto.
2. Como usuário ditando, eu quero que a correção preserve o sentido literal do que falei, para que perguntas e instruções ditadas sejam transcritas, nunca respondidas ou executadas.
3. Como usuário ditando, eu quero que, se a correção produzir algo desproporcional ao que falei, o app cole a transcrição crua em vez do output suspeito, para que o pior caso seja "sem pontuação", nunca "texto inventado".
4. Como usuário ditando em PT com termos EN, eu quero que o texto corrigido continue no idioma em que falei, para nunca receber uma tradução não pedida.
5. Como usuário que dita várias vezes em sequência rápida, eu quero que cada ditado seja processado normalmente, para nunca receber texto sem correção ou a pergunta no lugar da resposta por causa de um cooldown invisível.
6. Como usuário, eu quero que o hotkey de gravação continue funcionando após bloquear e desbloquear o Windows (Win+L) ou após sleep, para não ter que reiniciar o app depois de cada pausa.
7. Como usuário, eu quero que uma falha interna em qualquer callback de hotkey afete no máximo aquela ação, para que um erro isolado nunca mate todos os atalhos do app.
8. Como usuário, eu quero ser avisado no startup (som + log) se algum hotkey não pôde ser registrado porque outro app já usa o combo, para poder trocar o combo em vez de achar que o app quebrou.
9. Como usuário que troca hotkeys nas Configurações, eu quero que o novo combo funcione imediatamente após salvar, sem esperar minutos nem reiniciar.
10. Como usuário de browser e VS Code, eu quero que os atalhos default do app não colidam com "aba anterior" (ctrl+shift+tab) nem "replace in files" (ctrl+shift+h), para que meu fluxo normal de trabalho nunca acione o app por acidente.
11. Como usuário que já tem os combos antigos gravados no .env, eu quero que a atualização migre automaticamente os defaults colidentes para os novos, para não precisar editar configuração na mão.
12. Como usuário que cicla modos por hotkey, eu quero que o ciclo valha só para a sessão atual, para que um toque acidental nunca mude o modo com que o app inicia amanhã.
13. Como usuário que escolhe modo pelo menu do tray ou pelas Configurações, eu quero que essa escolha deliberada persista entre sessões.
14. Como usuário, eu quero ver claramente o modo ativo (overlay ao ciclar, tooltip do tray), para saber sempre em que modo a próxima gravação vai rodar.
15. Como usuário com snippets configurados no futuro, eu quero que um snippet só dispare quando eu ditar exatamente o trigger, para que uma ditação longa que contenha a palavra do trigger nunca seja substituída pelo snippet.
16. Como usuário, eu quero parar de gravar e ter a transcrição processada mesmo em condições de erro interno, para que o app nunca fique preso em "aguardando transcrição anterior" até o restart.
17. Como mantenedor, eu quero rodar um único comando que testa, sincroniza versão, builda e instala o release, para que o binário instalado nunca mais fique meses atrás do source.
18. Como mantenedor, eu quero ver a versão no banner de startup e no tooltip do tray, para detectar defasagem de versão de relance.
19. Como mantenedor, eu quero que a suite de testes rode isolada dos arquivos reais de histórico, log e .env, para que rodar testes nunca contamine meus dados de uso.
20. Como mantenedor, eu quero que o CLAUDE.md reflita a estrutura real dos módulos e os gotchas vigentes, para que futuras sessões de agente não trabalhem com mapa desatualizado.
21. Como mantenedor, eu quero configuração morta removida (chaves que o código não lê), para que o .env descreva apenas o que existe.

## Implementation Decisions

Decisões fechadas no grill (2026-07-05):

**Transcrição (W1)**
- VAD-gate estrito: quando o VAD não detecta fala, a gravação vira SKIP com beep de erro + overlay "Não detectei fala" + registro no histórico. O fallback de retranscrição sem VAD e seu blocklist são removidos por completo.
- Guarda anti-resposta nos prompts de correção (smart e minimal) e no prompt de STT via Gemini: o texto do usuário é sempre conteúdo a corrigir/transcrever, nunca instrução; texto do usuário passa a ser delimitado explicitamente no prompt.
- PromptSpec ganha um hook opcional de validação de output (output_guard). O modo transcribe usa um guard determinístico de razão de tamanho: output fora da faixa aceitável em relação ao input descarta a correção e cola o texto cru.
- Correção roda com temperatura 0 também no caminho Gemini direto (remove o uso de temperatura default do SDK no modo transcribe).
- Modelos: Gemini 3.1 Flash-Lite nos DOIS tiers (fast e quality) via OpenRouter. O plumbing de tiers é mantido; mudam os defaults. Preflight obrigatório: confirmar o slug exato no OpenRouter antes de pinnar; se indisponível, fallback documentado para a geração anterior de Flash-Lite.
- Cooldowns SEC-05 (2s entre chamadas AI) e QW-1 (2s pós-query) removidos, junto com seu estado global. Proteção contra double-fire fica com o debounce de hotkey e o gate de transcrição em andamento.
- Fix do estado preso: o flag de transcrição em andamento só é ativado quando existe de fato uma thread de gravação para finalizar; nenhum caminho pode ativá-lo e retornar sem agendar a transcrição.

**Hotkeys (W2)**
- Migração completa de todos os hotkeys (record, cycle, history, command) da lib `keyboard` para RegisterHotKey do Win32 via ctypes, com thread dedicada de message loop. A dependência `keyboard` sai do projeto.
- Callbacks são despachados para worker threads; a thread do message loop nunca executa trabalho do app.
- Falha de registro de combo é reportada no startup com beep + log de erro (e notificação de tray quando disponível).
- Rebind em runtime: salvar hotkeys nas Configurações re-registra imediatamente.
- Consequência aceita: combos registrados são consumidos pelo OS (não chegam ao app em foco). O gotcha histórico de suppress=False era específico do hook global da lib antiga e deixa de existir.

**Defaults e modo (W3)**
- Novos defaults: cycle = ctrl+alt+m, history = ctrl+alt+h. Record (ctrl+shift+space) e command (ctrl+alt+space) inalterados.
- Migração one-time no load de config: valor legado exatamente igual ao default colidente antigo é substituído pelo novo default (cobre o .env de produção existente).
- Ciclo de modo por hotkey muda o modo apenas em memória. Persistência no .env acontece somente via menu do tray ou Configurações. Reload de configurações não sobrescreve mais o modo ativo em memória quando o valor persistido não mudou.

**Higiene (W4)**
- Isolamento de testes: fixture global redireciona diretório base, log e histórico para diretório temporário. Nenhum teste escreve nos arquivos reais do repo.
- Snippets: matching passa a ser frase completa contra trigger (normalização de caixa/acentos/pontuação, fuzzy alto sobre a frase inteira). Matching por contenção e partial match são removidos.
- History search: reuso da janela singleton roteado pela thread dona do Tcl (fila), eliminando chamadas tkinter cross-thread a partir de callbacks de hotkey.
- Theme deixa de criar root Tk transiente para resolver fontes.
- Bridge das Configurações ganha guard server-side: valores de API key mascarados nunca são persistidos.
- Config morta removida do código e do .env.example (chave de provider não consumida, chaves de wake word inexistentes, chaves do provider OpenAI removido).
- CLAUDE.md atualizado: mapa real de módulos, defaults reais, gotchas da lib keyboard removidos, novos gotchas do RegisterHotKey documentados.

**Release (W5)**
- Script único de release local: roda verificação de sintaxe + suite de testes, injeta a versão do pacote no instalador (mata o sync manual do Inno Setup), builda PyInstaller + instalador e instala silenciosamente.
- Bump para 1.1.0. Versão exibida no banner de startup e no tooltip do tray.

**Execução**
- 5 PRs sequenciais na ordem W1 → W2 → W3 → W4 → W5. Cada PR: suite verde + smoke manual com pythonw. Build + install imediatos após o último merge (sem período de soak).

## Testing Decisions

Bom teste neste contexto exercita comportamento externo observável (o que seria colado, o que seria registrado no histórico, o que o usuário ouviria/veria), não detalhes internos. O padrão de lazy-lookup via facade `voice.audio` deve ser respeitado: patches continuam mirando o facade, como os testes existentes fazem.

Módulos com testes obrigatórios (deep):
- Novo módulo de hotkeys Win32: parser de combo string → modifiers/VK (função pura, tabela de casos incluindo combos inválidos) e ciclo de vida register/rebind/unregister com ctypes mockado, incluindo o caso "registro falhou".
- VAD-gate: gravação com zero fala detectada resulta em skip + histórico de erro + nenhum paste (evoluir os testes de VAD existentes, que hoje validam o fallback que será removido).
- Guarda de correção: output_guard descarta output desproporcional e retorna cru; prompts mantêm a invariante de identidade byte a byte entre builders Gemini e SYSTEM/user do OpenRouter (padrão de teste já existente no repo).
- Snippets: novo matching exato de frase, incluindo casos que hoje seriam sequestrados por contenção/partial e passam a não disparar.
- Migração de config legada: .env com combo colidente antigo carrega com o novo default; combo custom do usuário é preservado.
- Isolamento de testes: fixture de diretório temporário validada por meta-teste simples (histórico real intocado após a suite).

Módulos shallow sem testes dedicados (validação manual no smoke): script de release, exibição de versão, ajustes de tray/overlay, guard de key mascarada no bridge (1 teste barato se o padrão de teste do bridge já existir).

Prior art no repo: suite de VAD, suite de snippets, suite de prompts (invariante de identidade), suite de command mode (padrão de patch no facade).

## Out of Scope

- Migrar para outra lib de STT ou trocar o Whisper local (large-v3/CUDA permanece como está).
- Mudanças no modo hands-free, wake word (feature inexistente; chaves mortas apenas removidas) e no modo visual.
- Refactor do split de ui_settings pendente do SENTINEL (segue como débito separado).
- Auto-update do app ou verificação de versão online; o release continua sendo disparado manualmente (agora com um comando).
- Consolidação dos múltiplos interpretadores Tk num único root/thread de UI; nesta wave apenas eliminamos as chamadas cross-thread. Consolidação total fica para sprint futuro se a instabilidade persistir.
- Filtro de eco do initial_prompt no output do Whisper (o VAD-gate elimina o vetor principal; reavaliar se reaparecer).
- Qualquer mudança de UI das Configurações além do guard de key mascarada.

## Further Notes

- **Preflight de integração (obrigatório antes do W1):** confirmar no OpenRouter o slug exato do Gemini 3.1 Flash-Lite e fazer uma chamada de teste com a key existente. Se o modelo não existir lá, decisão de fallback já acordada: geração anterior de Flash-Lite.
- **Risco W2:** RegisterHotKey falha se outro app já registrou o combo. Mitigação já decidida (falha visível + rebind fácil). Testar convivência com PowerToys/utilitários que o JP use.
- **Risco W2:** apps elevados (UAC) não recebem SendInput de processo não-elevado; o paste dentro de janelas admin continua limitado. Comportamento igual ao atual, documentar como limitação conhecida.
- **Dependência de ambiente:** validação final exige a máquina real do JP (CUDA, mic, instalador). O smoke de release inclui: ditar nos modos transcribe/simple, gravar silêncio (esperar skip), ciclo Win+L, trocar hotkey nas Configurações e reinstalar por cima da versão anterior.
- O `.env` de produção em APPDATA difere do `.env` do repo (dev usa STT via Gemini; produção usa Whisper local). Testes manuais de release devem rodar com o `.env` de produção.
- PRD deve ser deletado após o merge do sprint (convenção anti dock-rot do fluxo).
