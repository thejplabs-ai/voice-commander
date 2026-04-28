#!/usr/bin/env node
// session-start-notify.js -- SessionStart hook.
// Avisa JP se ha >=1 sessao ativa quando nova aba abre NO REPO ROOT.
// Nao bloqueia. Nao pergunta nada. Apenas informa.
// ADR-047 (Parallel Sessions).

const path = require('path');
const fs = require('fs');

let input = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', (c) => { input += c; });
process.stdin.on('end', () => {
  try {
    const data = input ? JSON.parse(input) : {};
    const cwd = data.cwd || process.cwd();
    const projectDir = process.env.CLAUDE_PROJECT_DIR || cwd;

    // Load registry directly (not via require of our lib, to avoid coupling hook runtime to repo layout)
    const registryPath = path.join(projectDir, '.aios', 'operations', 'active-sessions.json');
    if (!fs.existsSync(registryPath)) return process.exit(0);

    const raw = fs.readFileSync(registryPath, 'utf8');
    const parsed = JSON.parse(raw);
    const sessions = Array.isArray(parsed.sessions) ? parsed.sessions : [];

    // Filter idle (>10min)
    const now = Date.now();
    const active = sessions.filter((s) => now - Date.parse(s.last_heartbeat) < 10 * 60 * 1000);
    if (active.length === 0) return process.exit(0);

    // Check if current cwd is already a session worktree
    const current = active.find((s) => {
      const wt = path.resolve(s.worktree_path);
      return path.resolve(cwd) === wt || path.resolve(cwd).startsWith(wt + path.sep);
    });

    let msg;
    if (current) {
      msg = `[sessions] Voce esta na sessao "${current.slug}" (branch ${current.branch}).`;
      if (active.length > 1) {
        const others = active.filter((s) => s.session_id !== current.session_id).map((s) => s.slug);
        msg += ` ${others.length} outra(s) ativa(s): ${others.join(', ')}. /sessions pra listar.`;
      }
    } else {
      const slugs = active.map((s) => s.slug).join(', ');
      msg = `[sessions] AVISO: ${active.length} sessao(oes) ativa(s) em paralelo: ${slugs}. Se for trabalhar em algo separado, rode /new-session <slug> pra isolar. ADR-047.`;
    }

    const out = {
      hookSpecificOutput: {
        hookEventName: 'SessionStart',
        additionalContext: msg,
      },
    };
    process.stdout.write(JSON.stringify(out));
  } catch (_) {
    // never block on parse error
  }
  process.exit(0);
});
