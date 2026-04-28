# /close-session — Fechar sessao paralela (cria PR + remove worktree)

> **ADR-047 (Parallel Sessions)**
> **Uso:** Finaliza a sessao da aba atual. Remove config links, cria PR via `gh`, remove worktree, desregistra. Branch sem commits e auto-deletada.

---

## Instrucoes

Ao receber `/close-session` (ou `/close-session --force` ou `/close-session --no-pr`):

1. **Verificar contexto:** Esta aba precisa estar DENTRO de um worktree de sessao. Se estiver no repo root, JP precisa passar `--session <id>` (pegar id via `/sessions`).

2. **Rodar (a partir do cwd atual):**
   ```bash
   node "$CLAUDE_PROJECT_DIR/scripts/sessions/close.js" [--force] [--no-pr] [--session <id>]
   ```

3. **Behavior:**
   - Se working tree dirty + sem `--force`: script bloqueia, pede commit ou --force. Reportar ao JP.
   - Se clean + has commits: `git push` + `gh pr create` (a menos de `--no-pr`).
   - Se sem commits: skip PR, deleta branch tambem (lixo).
   - Sempre: remove config links (.env hardlinks, node_modules junction) ANTES de `git worktree remove`.
   - Sempre tenta `git worktree remove` ao final + desregistra.

4. **Apos cleanup:**
   - Se cwd atual = worktree removido, instrua JP: `cd "$CLAUDE_PROJECT_DIR"` pra voltar ao repo root, ou fechar a aba.
   - Nao tentar cd automatico aqui (shell state nao persiste entre bash tool calls).

5. **Output esperado:**
   ```
   [close-session] DONE
   ```
   Reportar PR URL se gh criou.

## Default branch

Detectado automaticamente via `git symbolic-ref refs/remotes/origin/HEAD`. Override em `.aios/sessions.config.json -> default_branch` (ex: para projetos que usam `main` em vez de `master`, ou base diferente).

## Canon VETO-PS

- `VETO-PS-08`: working tree deve estar limpo OU `--force` explicito.
- `VETO-PS-04`: `git push` so ocorre se branch esta registrada (script so opera em sessoes ativas).

## Excecao autorizada a GAGE-only-push

Este comando **faz `git push` automaticamente** como parte do close. Isto e uma excecao explicita a regra "apenas GAGE faz push" porque:
- A branch e feature (nunca master)
- A operacao e unidirecional e auditavel (PR via gh)
- Fluxo e documentado em ADR-047
