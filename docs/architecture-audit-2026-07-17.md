# Architecture Audit — 2026-07-17 (escopado: pipeline de transcrição)

Escopo: `voice/transcription.py` + pontos de contato `ai_provider.py`/`gemini_prompts.py`, pós-fixes da wave bug bounty 2. Skill: /improve-codebase-architecture (Ousterhout deep modules).

## Candidate 1: montagem do texto STT (APLICADO nesta wave)

**Current shape:** `_join_segments()` é o ponto único declarado de montagem do raw_text (caminho normal + fallback sem VAD), carregando a defesa `strip_hallucinated_tail`. Mas os 3 fallbacks de infra (`_transcribe_no_vad_fallback`, `_transcribe_cpu_fallback`, `_transcribe_model_fallback`) duplicam o join inline (`" ".join(s.text ...)`) — 3 cópias do mesmo bloco, todas SEM a defesa de cauda.

**Why coupled:** mesmo conceito de domínio (segments do Whisper → texto final). A duplicação nasceu antes da defesa existir; hoje é um furo real: alucinação em caminho de fallback de infra chega ao paste sem filtro.

**Proposed deep module:** `_join_segments(segments) -> str` vira a ÚNICA saída de texto da transcrição — os 3 fallbacks passam a chamá-lo. Interface inalterada; encapsulado: join + defesa de cauda + futuras camadas de higiene. Test boundary único: testar `_join_segments` cobre todos os 5 caminhos.

**Expected gain:** 3 blocos duplicados removidos; gap de defesa fechado; qualquer filtro futuro pós-STT plugado num lugar só.

**Risk:** baixíssimo (3 linhas + 1 teste). Delta comportamental deliberado e desejado: os fallbacks raros de infra passam a ter o mesmo tail-strip dos caminhos principais (fecha Minor do review da Task 3).

## Candidate 2: lazy-lookup via facade `voice.audio` (NÃO aplicado)

**Current shape:** todo símbolo cross-module resolve em runtime via `from voice import audio as _audio` para honrar monkeypatch dos testes (documentado no header do arquivo). Interface de teste larga: testes patcham 10+ símbolos internos da facade.

**Proposal futura:** injetar dependências pela borda (um objeto de contexto da pipeline) e testar por comportamento na borda `transcribe()`. Ganho alto de robustez de teste, mas custo alto (toca dezenas de testes). Wave própria; não fazer junto de fixes.

## Candidate 3: unificar higiene de texto (NÃO aplicado)

`sanitize_llm_output` (pós-LLM, gemini_prompts) e `strip_hallucinated_tail` (pós-STT, transcription) são domínios distintos (lixo de modelo de chat vs alucinação de STT). Unificar criaria god module sem ganho de interface. Manter separados.

## Decisão

Aplicado apenas o Candidate 1 (commit `refactor:` próprio). Candidates 2-3 registrados para waves futuras.
