# /new-session — Criar nova sessao paralela isolada

> **ADR-047 (Parallel Sessions)**
> **Uso:** Isola esta aba Claude Code em worktree proprio + branch dedicada. Previne conflitos cross-session. Configs gitignored (.env, .claude/settings.local.json, node_modules) sao hardlink/junction do principal -> mesmas contas/MCPs/credentials.

---

## Instrucoes

Ao receber `/new-session {slug}` (ou `/new-session {slug} --scope "glob1,glob2"`):

1. **Validar argumento:**
   - `{slug}` obrigatorio (a-z 0-9 -, 2-40 chars)
   - `--scope` opcional (se omitido, scope sera auto-detectado no primeiro Edit/Write)

2. **Rodar:**
   ```bash
   cd "$CLAUDE_PROJECT_DIR"
   node scripts/sessions/create.js {slug} [--scope "..."]
   ```

3. **Output esperado:**
   - Path do worktree em `<repo-parent>/<repo-name>-worktrees/{slug}-{ts}/`
     (ex: `C:\Users\joaop\AIOS JP Labs-worktrees\{slug}-{ts}`)
   - Branch criada (`feature/session-{ts}-{slug}`)
   - Lista de config links criados (`.env`, `.env.local`, `.claude/settings.local.json`, `node_modules`)

4. **Instruir JP a migrar:**
   > Esta aba permanece no repo root. Para trabalhar na sessao isolada:
   > 1. Abra nova aba Claude Code
   > 2. `cd "{worktree_path}" && claude`
   > 3. Todo trabalho ocorre nesse worktree; commits vao para `feature/session-*` automaticamente
   > 4. `.env`, MCPs, credentials e node_modules estao acessiveis (hardlink/junction do principal)

5. **Nao cd automatico:** Esta aba continua onde esta. Se o JP quiser migrar a aba atual, ele fecha e reabre no worktree.

## Configuracao por projeto

`.aios/sessions.config.json` controla:
- `worktree_base_dir` (null = sibling automatico)
- `default_branch` (null = detect via origin/HEAD)
- `symlinks` (paths para hardlink/junction)

Editar para incluir/excluir paths gitignored adicionais (ex: `credentials.json`, `.vercel`).

## Canon VETO-PS

- `VETO-PS-01`: branch unica por sessao (reject duplicate)
- `VETO-PS-02`: worktree FORA do repo root (sibling = OK)
- `VETO-PS-07`: max 6 sessoes concorrentes

Se qualquer violacao: script sai com codigo != 0 e mensagem de erro clara. Reporte ao JP.
