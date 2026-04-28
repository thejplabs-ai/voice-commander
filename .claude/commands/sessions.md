# /sessions — Listar sessoes paralelas ativas

> **ADR-047 (Parallel Sessions)**
> **Uso:** Mostra todas as sessoes Claude Code ativas em paralelo no repo.

---

## Instrucoes

Ao receber `/sessions`:

1. **Rodar:**
   ```bash
   cd "$CLAUDE_PROJECT_DIR"
   node scripts/sessions/status.js
   ```

2. **Apresentar output ao JP tal qual:** tabela com SLUG, PID, AGE, IDLE, BRANCH, SCOPE + lista de worktrees.

3. **Se argumento `--json`:** passar flag adiante:
   ```bash
   node scripts/sessions/status.js --json
   ```

4. **Se nenhuma sessao ativa:** script imprime `[sessions] nenhuma sessao ativa`. Nao adicionar narracao.

## Side effect

`status.js` chama `cleanupIdle()` antes de listar, entao sessoes >10min idle sao auto-removidas (VETO-PS-06).
