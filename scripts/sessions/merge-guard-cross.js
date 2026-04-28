#!/usr/bin/env node
/**
 * merge-guard-cross.js -- Detecta overlap cross-session ANTES de git push.
 *
 * Dado: cwd dentro de um worktree session.
 * Checa: todos os arquivos modificados na branch desta sessao vs scope_paths
 *        de OUTRAS sessoes ativas.
 *
 * Se overlap: BLOCK + lista conflitos.
 *
 * Usage: node scripts/sessions/merge-guard-cross.js [--json]
 * Exit 0 = clean, 2 = overlap detected, 1 = error.
 *
 * ADR-046. VETO-PS-05 (scope overlap).
 */

const { execSync } = require('child_process');
const path = require('path');
const registry = require('./registry');

function sh(cmd, opts = {}) {
  return execSync(cmd, { stdio: ['ignore', 'pipe', 'pipe'], encoding: 'utf8', ...opts }).trim();
}

function diffFiles(worktreePath, baseRef = 'origin/master') {
  try {
    const out = sh(`git diff --name-only ${baseRef}...HEAD`, { cwd: worktreePath });
    return out ? out.split('\n').filter(Boolean) : [];
  } catch (_) {
    return [];
  }
}

async function main() {
  const current = registry.findByCwd(process.cwd());
  if (!current) {
    process.stdout.write('[merge-guard] no active session for cwd (ok, not a session branch)\n');
    process.exit(0);
  }

  const files = diffFiles(current.worktree_path);
  if (files.length === 0) {
    process.stdout.write('[merge-guard] no diff vs origin/master\n');
    process.exit(0);
  }

  const others = registry.list().filter((s) => s.session_id !== current.session_id);
  const conflicts = [];
  for (const f of files) {
    for (const other of others) {
      if (registry.pathInScope(f, other.scope_paths)) {
        conflicts.push({ file: f, otherSession: other.slug, otherScope: other.scope_paths });
      }
    }
  }

  if (process.argv.includes('--json')) {
    process.stdout.write(JSON.stringify({ current: current.slug, files, conflicts }, null, 2) + '\n');
    process.exit(conflicts.length > 0 ? 2 : 0);
  }

  if (conflicts.length === 0) {
    console.log(`[merge-guard] ${files.length} file(s) changed, no overlap with ${others.length} other session(s). OK.`);
    process.exit(0);
  }

  console.error(`[merge-guard] BLOCK: ${conflicts.length} overlap(s) with other active sessions (VETO-PS-05):`);
  for (const c of conflicts) {
    console.error(`  ${c.file}  ->  claimed by "${c.otherSession}" (scope: ${c.otherScope.join(', ')})`);
  }
  console.error('');
  console.error('Resolve: close the other session, OR rebase, OR narrow your scope.');
  process.exit(2);
}

main().catch((e) => {
  console.error('[merge-guard] ' + (e.message || e));
  process.exit(1);
});
