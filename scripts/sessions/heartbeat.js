#!/usr/bin/env node
/**
 * heartbeat.js -- Atualiza last_heartbeat da sessao correspondente ao cwd.
 *
 * Usage:
 *   node scripts/sessions/heartbeat.js          # updates current session
 *   node scripts/sessions/heartbeat.js --cleanup-only
 *
 * Called by hooks periodically (PostToolUse / UserPromptSubmit).
 * Silent on success (exit 0). Exit 0 mesmo quando nao ha sessao (hook seguro).
 *
 * ADR-046. VETO-PS-06 (idle cleanup).
 */

const registry = require('./registry');

async function main() {
  const cleanupOnly = process.argv.includes('--cleanup-only');
  const removed = await registry.cleanupIdle();
  if (cleanupOnly) {
    if (removed > 0) console.log(`[heartbeat] cleaned ${removed} idle session(s)`);
    return;
  }

  const s = registry.findByCwd(process.cwd());
  if (!s) {
    if (process.argv.includes('--verbose')) {
      console.error('[heartbeat] no session for cwd (ok)');
    }
    return;
  }

  await registry.heartbeat(s.session_id);
  if (process.argv.includes('--verbose')) {
    console.log(`[heartbeat] ${s.slug} updated`);
  }
}

main().catch((e) => {
  console.error('[heartbeat] ' + (e.message || e));
  process.exit(0); // non-blocking in hooks
});
