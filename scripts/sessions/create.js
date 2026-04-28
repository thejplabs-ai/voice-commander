#!/usr/bin/env node
/**
 * create.js -- Cria worktree + branch + registra sessao + symlinks de configs.
 *
 * Usage: node scripts/sessions/create.js <slug> [--scope <glob>,<glob>...]
 *
 * ADR-047. Implementa VETO-PS-01, VETO-PS-02, VETO-PS-07.
 *
 * Worktree path:
 *   - Default: sibling do repo (<parent>/<repo-name>-worktrees/<slug>-<ts>/)
 *   - Override: .aios/sessions.config.json -> worktree_base_dir
 *
 * Symlinks de configs (apos git worktree add):
 *   - Lidos de .aios/sessions.config.json -> symlinks: [...]
 *   - Files: hardlink (funciona Windows sem admin)
 *   - Directories: junction (funciona Windows sem admin)
 *   - Skip silencioso se path nao existe no principal
 */

const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const registry = require('./registry');

const SLUG_RE = /^[a-z0-9][a-z0-9-]{1,39}$/;

function fail(msg, code = 1) {
  console.error(`[new-session] ${msg}`);
  process.exit(code);
}

function parseArgs(argv) {
  const args = { slug: null, scope: [] };
  let i = 0;
  while (i < argv.length) {
    const a = argv[i];
    if (a === '--scope') {
      const v = argv[i + 1] || '';
      args.scope = v.split(',').map((s) => s.trim()).filter(Boolean);
      i += 2;
    } else if (!args.slug) {
      args.slug = a;
      i++;
    } else {
      i++;
    }
  }
  return args;
}

function tsCompact(date = new Date()) {
  const pad = (n) => String(n).padStart(2, '0');
  return (
    date.getUTCFullYear().toString() +
    pad(date.getUTCMonth() + 1) +
    pad(date.getUTCDate()) +
    pad(date.getUTCHours()) +
    pad(date.getUTCMinutes()) +
    pad(date.getUTCSeconds())
  );
}

function sh(cmd, opts = {}) {
  return execSync(cmd, { stdio: ['ignore', 'pipe', 'pipe'], encoding: 'utf8', ...opts }).trim();
}

function readConfig(repoRoot) {
  const p = path.join(repoRoot, '.aios', 'sessions.config.json');
  if (!fs.existsSync(p)) return {};
  try {
    return JSON.parse(fs.readFileSync(p, 'utf8'));
  } catch (e) {
    console.warn(`[new-session] WARN: invalid sessions.config.json (${e.message}). Using defaults.`);
    return {};
  }
}

function defaultWorktreeBaseDir(repoRoot) {
  const parent = path.dirname(repoRoot);
  const name = path.basename(repoRoot);
  return path.join(parent, `${name}-worktrees`);
}

/**
 * Cria link de config do principal -> worktree.
 * - File: hardlink (no Windows nao precisa admin)
 * - Directory: junction (no Windows nao precisa admin)
 * Cross-platform: hardlink + junction sao suportados em POSIX e Windows.
 */
function createConfigLink(targetAbs, linkAbs) {
  if (!fs.existsSync(targetAbs)) return { skipped: true, reason: 'target_missing' };
  if (fs.existsSync(linkAbs) || fs.lstatSync(linkAbs, { throwIfNoEntry: false })) {
    return { skipped: true, reason: 'link_exists' };
  }

  const stat = fs.statSync(targetAbs);
  const isDir = stat.isDirectory();

  fs.mkdirSync(path.dirname(linkAbs), { recursive: true });

  try {
    if (isDir) {
      fs.symlinkSync(targetAbs, linkAbs, 'junction');
      return { ok: true, type: 'junction' };
    } else {
      fs.linkSync(targetAbs, linkAbs);
      return { ok: true, type: 'hardlink' };
    }
  } catch (e) {
    return { error: `${e.code || 'ERR'}: ${e.message.split('\n')[0]}` };
  }
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (!args.slug) fail('usage: new-session <slug> [--scope "glob1,glob2"]');
  if (!SLUG_RE.test(args.slug)) {
    fail(`invalid slug "${args.slug}" (must match ${SLUG_RE}, a-z 0-9 -, 2-40 chars)`);
  }

  // Cleanup idle sessions first
  const removed = await registry.cleanupIdle();
  if (removed > 0) console.log(`[new-session] cleaned ${removed} idle session(s)`);

  // Cap check pre-flight
  const active = registry.list();
  if (active.length >= registry.MAX_SESSIONS) {
    fail(
      `VETO-PS-07: max ${registry.MAX_SESSIONS} concurrent sessions already active. Close one with /close-session.`
    );
  }

  // Ensure no duplicate slug active
  const dup = active.find((s) => s.slug === args.slug);
  if (dup) {
    fail(`slug "${args.slug}" already in use by PID ${dup.pid} (${dup.branch}). Pick another or close the other.`);
  }

  // Ensure we are in repo root with git
  const cwd = process.cwd();
  const repoRoot = registry.REPO_ROOT;
  if (path.resolve(cwd) !== path.resolve(repoRoot)) {
    console.warn(`[new-session] WARN: cwd != repo root. repo=${repoRoot} cwd=${cwd}`);
  }

  const config = readConfig(repoRoot);

  // Base branch: config override > origin/HEAD detect > master fallback
  let baseBranch = config.default_branch || null;
  if (!baseBranch) {
    try {
      baseBranch = sh('git symbolic-ref --short refs/remotes/origin/HEAD', { cwd: repoRoot })
        .replace(/^origin\//, '');
    } catch (_) { /* fallback below */ }
  }
  if (!baseBranch) baseBranch = 'master';

  const ts = tsCompact();
  const branch = `feature/session-${ts}-${args.slug}`;

  // Worktree base: config override > sibling default
  const worktreeRoot = config.worktree_base_dir
    ? path.resolve(config.worktree_base_dir)
    : defaultWorktreeBaseDir(repoRoot);
  const worktreePath = path.join(worktreeRoot, `${args.slug}-${ts}`);

  if (fs.existsSync(worktreePath)) {
    fail(`worktree path already exists: ${worktreePath}`);
  }

  fs.mkdirSync(worktreeRoot, { recursive: true });

  console.log(`[new-session] base branch:   ${baseBranch}`);
  console.log(`[new-session] new branch:    ${branch}`);
  console.log(`[new-session] worktree base: ${worktreeRoot}`);
  console.log(`[new-session] worktree:      ${worktreePath}`);

  // Fetch latest to avoid stale base
  try {
    sh('git fetch origin --quiet', { cwd: repoRoot });
  } catch (e) {
    console.warn(`[new-session] WARN: git fetch failed (${e.message.split('\n')[0]}). Continuing with local ${baseBranch}.`);
  }

  // Resolve base ref (prefer remote-tracking)
  let baseRef = `origin/${baseBranch}`;
  try {
    sh(`git rev-parse --verify ${baseRef}`, { cwd: repoRoot });
  } catch (_) {
    baseRef = baseBranch;
  }

  // Create worktree
  try {
    sh(`git worktree add -b ${branch} "${worktreePath}" ${baseRef}`, { cwd: repoRoot });
  } catch (e) {
    fail(`git worktree add failed:\n${e.stderr || e.message}`);
  }

  // Register session
  let session;
  try {
    session = await registry.register({
      slug: args.slug,
      pid: process.ppid || process.pid,
      branch,
      worktreePath,
      scopePaths: args.scope,
    });
  } catch (e) {
    // Rollback worktree if registry rejected
    try { sh(`git worktree remove --force "${worktreePath}"`, { cwd: repoRoot }); } catch (_) {}
    try { sh(`git branch -D ${branch}`, { cwd: repoRoot }); } catch (_) {}
    fail(`register failed: ${e.message}`);
  }

  // Create config symlinks/hardlinks (after worktree exists)
  const symlinkPaths = Array.isArray(config.symlinks) ? config.symlinks : [];
  const linkResults = [];
  for (const relPath of symlinkPaths) {
    const targetAbs = path.join(repoRoot, relPath);
    const linkAbs = path.join(worktreePath, relPath);
    const r = createConfigLink(targetAbs, linkAbs);
    linkResults.push({ path: relPath, ...r });
  }

  console.log('');
  console.log('[new-session] OK');
  console.log(`  session_id: ${session.session_id}`);
  console.log(`  slug:       ${session.slug}`);
  console.log(`  branch:     ${session.branch}`);
  console.log(`  worktree:   ${session.worktree_path}`);
  console.log(`  scope:      ${session.scope_paths.length > 0 ? session.scope_paths.join(', ') : '(auto-detect on first Edit)'}`);

  if (linkResults.length > 0) {
    console.log('');
    console.log('[new-session] config links:');
    for (const r of linkResults) {
      if (r.ok) console.log(`  + ${r.path} (${r.type})`);
      else if (r.skipped) console.log(`  - ${r.path} (skipped: ${r.reason})`);
      else if (r.error) console.log(`  ! ${r.path} (FAIL: ${r.error})`);
    }
  }

  console.log('');
  console.log('Next step: abra nova aba Claude Code em:');
  console.log(`  cd "${session.worktree_path}" && claude`);
  console.log('');
}

main().catch((e) => fail(e.stack || e.message, 1));
