---
name: wave-runner
description: "Pipeline para multi-wave migrations/refactors com validation gate mandatorio por wave. Le wave-plan.yaml, executa waves em ordem topologica, bloqueia progressao sem teste verde, gera handoff ao final. Reusa /sprint-parallel quando waves paralelizaveis. Portable cross-project (AIOS, CBA, Arquiva, jp-labs-website, blueprint-ai, voice-commander)."
---

# /wave-runner — Multi-Wave Migration Pipeline

**Status:** ACTIVE
**Authority:** Verification Standards (`~/.claude/rules/verification-standards.md`)
**Canon:** VETO-WR-01..08 (mirrored em spec + validation logic)

---

## Problema que resolve

Migrations/refactors longos viram serie de "waves" dependentes (ex: W1 envelope auth -> W2 client migration -> W3 routes rollout). Historico mostra failure mode repetido: agente declara wave complete sem rodar smoke/E2E, avanca pra proxima, bug vaza downstream, retrabalho.

`/wave-runner` forca validation gate mandatorio entre waves e gera evidencia capturada de teste antes de proceder.

---

## Quando usar

- Multi-file migration com 3+ waves dependentes (auth refactor, data model change, API versioning)
- Sprint sequencial onde cada step depende do anterior estar verde
- Processo com pattern "implementa -> valida -> commit -> proxima fase"

**Nao usar para:**
- Single-file fix (usar direto)
- Stories paralelas independentes (usar `/sprint-parallel` direto)
- Bug diagnosis (usar `/tech-debt *diagnose`)

---

## Pipeline

```
JP: /wave-runner <path/to/wave-plan.yaml>
  |
  v
PARSE: le yaml, valida schema (VETO-WR-01)
  |
  v
DAG: detecta depends_on, topological sort (VETO-WR-02)
  |
  v
PLAN: mostra waves ordenadas + custo estimado + paralelismo detectado
  |
  v
CHECKPOINT 1: JP aprova plan (VETO-WR-04)
  |
  v
LOOP por wave em ordem topologica:
  |
  +-- Se wave.parallel=true E ambiente tem /sprint-parallel disponivel:
  |      -> delega para /sprint-parallel com stories = files da wave
  |
  +-- Senao (default, sequencial):
  |      -> spawn subagent (Task tool) com wave.brief + wave.files
  |      -> subagent implementa (escopo restrito aos files declarados)
  |
  v
  VALIDATION GATE (mandatorio, VETO-WR-03):
    1. Rodar validate.smoke (Bash tool, captura output completo)
    2. Rodar validate.e2e se definido (captura output)
    3. Rodar validate.extras[] se definido
    4. Parse exit code:
       - All PASS -> proceed
       - Any FAIL -> BLOCK + escrever wave-failure-{wave-id}.log + retry task
       - Max 3 retries (VETO-WR-08) -> BLOCK dura, pedir JP
  |
  v
  SCOPE CHECK (VETO-WR-06):
    diff tocou paths fora de wave.files? -> BLOCK, reverter, perguntar JP
  |
  v
  COMMIT: git commit com wave.id + wave.title + evidencia teste
  |
  v
  LESSONS: append wave-lessons.md (aprendizado/falha/retry count)
  |
  v
  PROCEED proxima wave
  |
  v
HANDOFF FINAL (VETO-WR-07):
  -> gera .aios/plans/waves/{wave-plan-id}/handoff.md
  -> inclui waves concluidas, evidencias, logs, next steps
  -> final_gate opcional do yaml roda aqui (ex: QUINN em AIOS)
```

---

## Commands

### `/wave-runner <wave-plan.yaml>`
Default. Parse -> Checkpoint 1 -> executa todas waves em ordem -> handoff.

### `/wave-runner --dry-run <wave-plan.yaml>`
Parse + valida schema + mostra DAG + custo estimado. Nao spawna subagents nao muda arquivo.

### `/wave-runner --resume <wave-plan-id>`
Retoma wave plan interrompido. Le `.aios/plans/waves/{id}/state.json`, continua da wave pendente.

### `/wave-runner --status <wave-plan-id>`
Mostra waves completed / pending / blocked.

---

## Schema wave-plan.yaml

```yaml
wave_plan:
  id: <slug-unico>              # required. ex: auth-migration-2026-05
  project: <nome>                # required. ex: cba | arquiva | aios
  description: <texto>           # required. motivo da migration em 1-2 frases

  waves:
    - id: <slug>                 # required. ex: W1-envelope
      title: <frase curta>       # required
      brief: |                   # required. briefing do que fazer. vira prompt do subagent.
        ...
      files:                     # required. paths afetados (wildcards OK)
        - src/path/...
      depends_on: []             # required (pode ser array vazio)
      assignee: <agente|none>    # opcional. default none = general-purpose. AIOS accepts agent names.
      validate:                  # required
        smoke: <comando shell>   # required. ex: "npm run smoke" | "pytest -k smoke"
        e2e: <comando> | null    # opcional
        extras:                  # opcional. ex: typecheck, lint
          - <comando>
      parallel: false            # opcional. true permite /sprint-parallel se disponivel
      max_retries: 3             # opcional. default 3

checkpoints:
  require_approval_at:           # opcional
    - after_parse                # Checkpoint 1 default ON
    - before_final_merge         # Checkpoint 2 opcional

final_gate:                      # opcional. roda apos todas waves concluidas
  command: <comando>             # ex: "npm run quality:gate" | AIOS pode ser "quinn *gate"
  optional: true                 # se false e falhar, pipeline BLOCK
```

---

## Canon VETO-WR-NN

| Veto | Trigger | Acao |
|------|---------|------|
| **VETO-WR-01** | yaml schema invalido (campo obrigatorio ausente) | BLOCK. Mostra campo faltante, pede JP corrigir. |
| **VETO-WR-02** | DAG tem ciclo em depends_on | BLOCK. Mostra ciclo. |
| **VETO-WR-03** | validation gate falhou (smoke/e2e exit code != 0) | BLOCK. Escreve wave-failure-{id}.log. Cria retry task. Nunca pular. |
| **VETO-WR-04** | JP nao aprovou plan no Checkpoint 1 | PAUSE. Nenhuma wave executada. |
| **VETO-WR-05** | Tentativa de marcar wave done sem evidencia de teste capturado | BLOCK. Proibido "looks fine", "should work". |
| **VETO-WR-06** | Subagent tocou paths fora de wave.files | BLOCK. Reverter edits extras. Perguntar JP se expandir escopo. |
| **VETO-WR-07** | Pipeline terminou sem gerar handoff.md | BLOCK commit final. Gerar handoff antes de fechar. |
| **VETO-WR-08** | max_retries excedido (default 3) | BLOCK dura. Pipeline pausa. JP decide continuar/abortar/revisar plan. |

---

## State tracking

Cada wave plan persistido em `.aios/plans/waves/{wave-plan-id}/`:

- `state.json` — waves[] + status (pending/running/completed/failed) + retry counts
- `wave-lessons.md` — append-only. 1 entry por wave. Ex:
  ```
  ## W1-envelope (2026-05-01)
  Status: completed (1 retry)
  Retry reason: smoke falhou — cookie header case-sensitive. Fix: lowercase normalize.
  Evidencia: wave-logs/W1-envelope-smoke-attempt2.log (PASS, 14 tests)
  Lesson: middleware deve normalizar headers antes de comparar.
  ```
- `wave-logs/` — stdout capturado de cada smoke/e2e/extras run
- `wave-failures/` — se VETO-WR-03 disparou, log completo
- `handoff.md` — gerado ao final

---

## Integration com rules globais

Este pipeline e a implementacao operacional de `~/.claude/rules/verification-standards.md`. As regras dizem "rode smoke/E2E antes de declarar done". `/wave-runner` codifica isso como VETO-WR-03 + VETO-WR-05 executaveis.

Agente rodando `/wave-runner` deve ler a rule e respeitar checklist dela. Output do validation gate deve mostrar comando rodado + output capturado, nao resumo.

---

## Portability (cross-project)

Skill e portable. Zero dependencia de agente AIOS-specifico. Runtime detection:

| Recurso | Se disponivel | Se ausente |
|---------|---------------|------------|
| `/sprint-parallel` | wave.parallel=true delega | fallback sequencial |
| QUINN agent | final_gate pode usar | usar comando do yaml |
| SENTINEL | baseline check opcional | skip |
| Task tool com subagent_type | usa assignee do yaml | fallback general-purpose |

Default sem nenhum desses: executa sequencial, usa comandos do yaml, subagent general-purpose. Funciona em qualquer projeto.

---

## Execution mode

Default: **Interactive** — JP aprova Checkpoint 1. Validation gates sao automaticos (BLOCK em falha, nao pede aprovacao).

**YOLO disponivel** via `--yolo` flag — pula Checkpoint 1. Validation gates permanecem mandatorios (VETO-WR-03 nunca degrada).

---

## Example

Ver `examples/wave-plan.example.yaml` neste mesmo diretorio. Cenario: auth migration 3 waves (envelope -> client -> routes).

---

*Source of truth: este SKILL.md*
*Rules dependentes: `~/.claude/rules/verification-standards.md`*
*Canon: VETO-WR-01..08*
