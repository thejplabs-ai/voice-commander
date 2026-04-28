#!/usr/bin/env node
// pre-edit-scope-detect.js -- PreToolUse Edit|Write|MultiEdit hook.
//
// Behavior:
//   1. Identifica sessao pelo cwd (findByCwd).
//   2. Se nao ha sessao: no-op (JP rodando solo em master = OK).
//   3. Se ha sessao com scope_paths vazio: AUTO-DETECT -- adiciona dir_pai/** ao scope.
//   4. Se path esta em scope de OUTRA sessao ativa: BLOCK com mensagem clara.
//
// ADR-047. VETO-PS-03 (scope declared), VETO-PS-05 (no overlap).

const path = require('path');
const fs = require('fs');

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

function globToRegex(pattern) {
  const normPattern = pattern.replace(/\\/g, '/');
  let re = '';
  let i = 0;
  while (i < normPattern.length) {
    const c = normPattern[i];
    if (c === '*') {
      if (normPattern[i + 1] === '*') { re += '.*'; i += 2; if (normPattern[i] === '/') i++; }
      else { re += '[^/]*'; i++; }
    } else if (c === '?') { re += '[^/]'; i++; }
    else if ('.+^${}()|[]\\'.indexOf(c) !== -1) { re += '\\' + c; i++; }
    else { re += c; i++; }
  }
  return new RegExp('^' + re + '$');
}

function matches(pattern, filePath) {
  return globToRegex(pattern).test(filePath.replace(/\\/g, '/'));
}

function toRepoRelative(filePath, projectDir) {
  const abs = path.resolve(filePath);
  const root = path.resolve(projectDir);
  if (abs.startsWith(root + path.sep)) return abs.slice(root.length + 1).replace(/\\/g, '/');
  // might be a worktree path outside repo -- then strip worktree root
  return abs.replace(/\\/g, '/');
}

let input = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', (c) => { input += c; });
process.stdin.on('end', () => {
  try {
    const data = input ? JSON.parse(input) : {};
    const filePath = data.tool_input?.file_path || '';
    const cwd = data.cwd || process.cwd();
    const projectDir = process.env.CLAUDE_PROJECT_DIR || cwd;

    if (!filePath) return process.exit(0);

    const reg = readRegistry(projectDir);
    if (!reg) return process.exit(0);

    const now = Date.now();
    const activeSessions = reg.sessions.filter((s) => now - Date.parse(s.last_heartbeat) < TIMEOUT_MS);
    if (activeSessions.length === 0) return process.exit(0);

    // Identify current session by cwd match
    const current = activeSessions.find((s) => {
      const wt = path.resolve(s.worktree_path);
      return path.resolve(cwd) === wt || path.resolve(cwd).startsWith(wt + path.sep);
    });

    // Translate file to session-relative view for scope check
    // If in a worktree, we want the path RELATIVE to the worktree root
    let scopeKey;
    if (current) {
      const wtRoot = path.resolve(current.worktree_path);
      const abs = path.resolve(filePath);
      if (abs.startsWith(wtRoot + path.sep)) {
        scopeKey = abs.slice(wtRoot.length + 1).replace(/\\/g, '/');
      } else {
        scopeKey = abs.replace(/\\/g, '/');
      }
    } else {
      scopeKey = toRepoRelative(filePath, projectDir);
    }

    // Check overlap with OTHER sessions
    const others = activeSessions.filter((s) => !current || s.session_id !== current.session_id);
    for (const other of others) {
      if (!other.scope_paths || other.scope_paths.length === 0) continue;
      for (const p of other.scope_paths) {
        if (matches(p, scopeKey)) {
          const out = {
            hookSpecificOutput: {
              hookEventName: 'PreToolUse',
              permissionDecision: 'deny',
              permissionDecisionReason:
                `VETO-PS-05: path "${scopeKey}" claimed by parallel session "${other.slug}" ` +
                `(scope: ${other.scope_paths.join(', ')}). ` +
                `Either wait/coordinate, close that session (/close-session), or work in a different path.`,
            },
          };
          process.stdout.write(JSON.stringify(out));
          return process.exit(0);
        }
      }
    }

    // Auto-detect scope for current session if empty
    if (current && (!current.scope_paths || current.scope_paths.length === 0)) {
      const dir = path.dirname(scopeKey);
      const autoScope = dir === '.' || dir === '' ? '**' : `${dir}/**`;
      current.scope_paths.push(autoScope);
      // Persist
      try {
        const regPath = path.join(projectDir, '.aios', 'operations', 'active-sessions.json');
        fs.writeFileSync(regPath, JSON.stringify(reg, null, 2));
      } catch (_) { /* best effort */ }
      // Emit context so JP sees it
      const out = {
        hookSpecificOutput: {
          hookEventName: 'PreToolUse',
          permissionDecision: 'allow',
          permissionDecisionReason: `[scope auto-detect] session "${current.slug}" scope -> ${autoScope}`,
        },
      };
      process.stdout.write(JSON.stringify(out));
    }
  } catch (_) { /* never block on error */ }
  process.exit(0);
});
