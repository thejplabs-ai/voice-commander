#!/usr/bin/env node
// pre-push-session-guard.js -- PreToolUse Bash hook.
//
// Quando o comando contem "git push", valida:
//   1. cwd dentro de worktree de sessao registrada (se houver)
//   2. cross-session overlap via merge-guard-cross.js
//
// Se OK: allow. Se NOT: deny com mensagem.
//
// ADR-047. VETO-PS-04 (registered branch), VETO-PS-05 (overlap).

const path = require('path');
const fs = require('fs');
const { execSync } = require('child_process');

const TIMEOUT_MS = 10 * 60 * 1000;

function readRegistry(projectDir) {
  const p = path.join(projectDir, '.aios', 'operations', 'active-sessions.json');
  if (!fs.existsSync(p)) return null;
  try {
    const raw = fs.readFileSync(p, 'utf8');
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed.sessions) ? parsed : null;
  } catch (_) {
    return null;
  }
}

function isPushCommand(cmd) {
  return /(^|[;&|\s])git\s+push\b/.test(cmd);
}

let input = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', (c) => { input += c; });
process.stdin.on('end', () => {
  try {
    const data = input ? JSON.parse(input) : {};
    const cmd = data.tool_input?.command || '';
    if (!isPushCommand(cmd)) return process.exit(0);

    const cwd = data.cwd || process.cwd();
    const projectDir = process.env.CLAUDE_PROJECT_DIR || cwd;
    const reg = readRegistry(projectDir);
    if (!reg) return process.exit(0);

    const now = Date.now();
    const activeSessions = reg.sessions.filter((s) => now - Date.parse(s.last_heartbeat) < TIMEOUT_MS);
    if (activeSessions.length === 0) return process.exit(0);

    // Identify which session (if any) corresponds to cwd
    const current = activeSessions.find((s) => {
      const wt = path.resolve(s.worktree_path);
      return path.resolve(cwd) === wt || path.resolve(cwd).startsWith(wt + path.sep);
    });

    // Case 1: cwd is a session worktree -> run cross-session merge-guard
    if (current) {
      try {
        const guardPath = path.join(projectDir, 'scripts', 'sessions', 'merge-guard-cross.js');
        execSync(`node "${guardPath}"`, {
          cwd: current.worktree_path,
          stdio: ['ignore', 'pipe', 'pipe'],
          encoding: 'utf8',
        });
      } catch (e) {
        const code = e.status;
        if (code === 2) {
          const reason = (e.stderr || e.stdout || '').toString().trim();
          const out = {
            hookSpecificOutput: {
              hookEventName: 'PreToolUse',
              permissionDecision: 'deny',
              permissionDecisionReason: `VETO-PS-05 (merge-guard):\n${reason}`,
            },
          };
          process.stdout.write(JSON.stringify(out));
          return process.exit(0);
        }
        // other errors (e.g. network, git) -> let through; this hook is not about runtime push errors
      }
      return process.exit(0);
    }

    // Case 2: not in a session worktree. If sessions ARE active, warn (but don't block -- user may be
    // pushing legitimate master work from repo root).
    if (activeSessions.length > 0) {
      // Allow but add context
      const out = {
        hookSpecificOutput: {
          hookEventName: 'PreToolUse',
          permissionDecision: 'allow',
          permissionDecisionReason:
            `[sessions] ${activeSessions.length} active session(s) in parallel. ` +
            `Pushing from repo root (not a session worktree) -- verify this isn't a session branch.`,
        },
      };
      process.stdout.write(JSON.stringify(out));
    }
  } catch (_) { /* never block on error */ }
  process.exit(0);
});
