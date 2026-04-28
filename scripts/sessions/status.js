#!/usr/bin/env node
/**
 * status.js -- Lista sessoes ativas.
 *
 * Usage: node scripts/sessions/status.js [--json]
 *
 * ADR-046.
 */

const registry = require('./registry');

function ageMin(iso) {
  const ms = Date.now() - Date.parse(iso);
  return Math.floor(ms / 60000);
}

function truncate(str, n) {
  if (!str) return '';
  if (str.length <= n) return str;
  return str.slice(0, n - 1) + '...';
}

async function main() {
  await registry.cleanupIdle();
  const sessions = registry.list();
  const json = process.argv.includes('--json');

  if (json) {
    process.stdout.write(JSON.stringify({ sessions, count: sessions.length }, null, 2) + '\n');
    return;
  }

  if (sessions.length === 0) {
    console.log('[sessions] nenhuma sessao ativa');
    return;
  }

  console.log(`[sessions] ${sessions.length} sessao(oes) ativa(s):`);
  console.log('');
  const header = ['SLUG', 'PID', 'AGE', 'IDLE', 'BRANCH', 'SCOPE'];
  const rows = sessions.map((s) => [
    s.slug,
    String(s.pid),
    `${ageMin(s.started_at)}m`,
    `${ageMin(s.last_heartbeat)}m`,
    truncate(s.branch, 44),
    s.scope_paths.length === 0 ? '(auto)' : truncate(s.scope_paths.join(','), 40),
  ]);

  const widths = header.map((h, i) =>
    Math.max(h.length, ...rows.map((r) => r[i].length))
  );

  const fmt = (r) => r.map((c, i) => c.padEnd(widths[i])).join('  ');
  console.log(fmt(header));
  console.log(widths.map((w) => '-'.repeat(w)).join('  '));
  for (const r of rows) console.log(fmt(r));
  console.log('');
  console.log('Worktrees:');
  for (const s of sessions) {
    console.log(`  ${s.slug} -> ${s.worktree_path}`);
  }
}

main().catch((e) => {
  console.error('[sessions] ' + (e.stack || e.message));
  process.exit(1);
});
