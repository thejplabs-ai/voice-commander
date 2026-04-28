#!/usr/bin/env node
/**
 * close.js -- Fecha sessao: valida clean tree, remove symlinks de config,
 *             cria PR via gh, remove worktree, desregistra.
 *
 * Usage: node scripts/sessions/close.js [--force] [--no-pr] [--session <id>]
 *
 * Deve ser executado DE DENTRO do worktree da sessao (detecta via cwd).
 * Se rodado do repo root, usa --session <id>.
 *
 * ADR-047. Implementa VETO-PS-08 (clean tree required).
 *
 * Default branch: lido de .aios/sessions.config.json -> default_branch,
 *                 ou detectado via 'git symbolic-ref refs/remotes/origin/HEAD',
 *                 ou fallback 'master'.
 */

const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const registry = require('./registry');

function fail(msg, code = 1) {
  console.error(`[close-session] ${msg}`);
  process.exit(code);
}

function parseArgs(argv) {
  const args = { force: false, noPr: false, sessionId: null };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--force') args.force = true;
    else if (a === '--no-pr') args.noPr = true;
    else if (a === '--session') args.sessionId = argv[++i];
  }
  return args;
}

function sh(cmd, opts = {}) {
  return execSync(cmd, { stdio: ['ignore', 'pipe', 'pipe'], encoding: 'utf8', ...opts }).trim();
}

function shInherit(cmd, opts = {}) {
  return execSync(cmd, { stdio: 'inherit', ...opts });
}

function readConfig(repoRoot) {
  const p = path.join(repoRoot, '.aios', 'sessions.config.json');
  if (!fs.existsSync(p)) return {};
  try {
    return JSON.parse(fs.readFileSync(p, 'utf8'));
  } catch (_) {
    return {};
  }
}

function detectDefaultBranch(repoRoot, config) {
  if (config.default_branch) return config.default_branch;
  try {
    return sh('git symbolic-ref --short refs/remotes/origin/HEAD', { cwd: repoRoot })
      .replace(/^origin\//, '') || 'master';
  } catch (_) {
    return 'master';
  }
}

/**
 * Remove symlink/hardlink/junction. Tenta unlink (file) -> rmdir (junction).
 * Hardlink: unlink remove a entrada do worktree, NAO afeta o arquivo no principal.
 * Junction: rmdir remove a junction, NAO afeta o diretorio target.
 */
function removeConfigLink(linkAbs) {
  const lst = fs.lstatSync(linkAbs, { throwIfNoEntry: false });
  if (!lst) return { skipped: true, reason: 'not_found' };

  try {
    fs.unlinkSync(linkAbs);
    return { ok: true };
  } catch (e1) {
    try {
      fs.rmdirSync(linkAbs);
      return { ok: true };
    } catch (e2) {
      return { error: `${e1.code || 'ERR1'} / ${e2.code || 'ERR2'}: ${e2.message.split('\n')[0]}` };
    }
  }
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const cwd = process.cwd();

  let session = null;
  if (args.sessionId) {
    session = registry.list().find((s) => s.session_id === args.sessionId) || null;
  } else {
    session = registry.findByCwd(cwd);
  }

  if (!session) {
    fail('current cwd is not inside a registered session worktree. Use --session <id> or cd into the worktree.');
  }

  const repoRoot = registry.REPO_ROOT;
  const config = readConfig(repoRoot);
  const defaultBranch = detectDefaultBranch(repoRoot, config);

  console.log(`[close-session] session: ${session.slug} (${session.session_id})`);
  console.log(`[close-session] branch:  ${session.branch}`);
  console.log(`[close-session] worktree: ${session.worktree_path}`);
  console.log(`[close-session] base branch: ${defaultBranch}`);

  // 1. Check working tree (VETO-PS-08).
  //    Filter out paths that are config symlinks/hardlinks (criados pelo create.js,
  //    aparecem como untracked se nao estao no .gitignore do target).
  let dirty = '';
  try {
    dirty = sh('git status --porcelain', { cwd: session.worktree_path });
  } catch (e) {
    fail(`git status failed: ${e.message}`);
  }

  const symlinkPathsForFilter = (Array.isArray(config.symlinks) ? config.symlinks : [])
    .map((p) => p.replace(/\\/g, '/'));
  const allDirtyLines = dirty.split('\n').filter(Boolean);
  const realDirtyLines = allDirtyLines.filter((line) => {
    const m = line.match(/^.{2}\s+(.+)$/);
    if (!m) return true;
    let filePath = m[1].replace(/\\/g, '/');
    if (filePath.startsWith('"') && filePath.endsWith('"')) filePath = filePath.slice(1, -1);
    for (const sl of symlinkPathsForFilter) {
      if (filePath === sl || filePath.startsWith(sl + '/')) return false;
    }
    return true;
  });
  const realDirty = realDirtyLines.join('\n');
  const filteredCount = allDirtyLines.length - realDirtyLines.length;
  if (filteredCount > 0) {
    console.log(`[close-session] ignoring ${filteredCount} dirty path(s) that are config symlinks`);
  }

  if (realDirty && !args.force) {
    console.error('[close-session] working tree is dirty:');
    console.error(realDirty);
    fail('commit changes first or pass --force to discard them. VETO-PS-08.');
  }

  if (realDirty && args.force) {
    console.warn('[close-session] --force: discarding uncommitted changes');
    try { sh('git reset --hard', { cwd: session.worktree_path }); } catch (_) {}
    try { sh('git clean -fd', { cwd: session.worktree_path }); } catch (_) {}
  }

  // 2. Check if branch has commits beyond base
  let hasCommits = false;
  try {
    const ahead = sh(`git rev-list --count origin/${defaultBranch}..${session.branch}`, {
      cwd: session.worktree_path,
    });
    hasCommits = parseInt(ahead, 10) > 0;
  } catch (_) {
    hasCommits = false;
  }

  if (!hasCommits) {
    console.log('[close-session] no commits on branch -- skipping PR');
    args.noPr = true;
  }

  // 3. Push + PR if applicable
  if (!args.noPr && hasCommits) {
    console.log('[close-session] pushing branch...');
    try {
      shInherit(`git push -u origin ${session.branch}`, { cwd: session.worktree_path });
    } catch (e) {
      fail('git push failed. Fix and retry close, or pass --no-pr.');
    }

    const title = `session(${session.slug}): auto-close`;
    const body = `Auto-generated PR from /close-session.\n\n- session_id: \`${session.session_id}\`\n- slug: \`${session.slug}\`\n- started: ${session.started_at}\n- scope: ${session.scope_paths.length === 0 ? '(auto-detected)' : session.scope_paths.join(', ')}\n\nCanon: ADR-047 Parallel Sessions.`;

    console.log('[close-session] opening PR...');
    try {
      shInherit(`gh pr create --base ${defaultBranch} --head ${session.branch} --title "${title}" --body "${body.replace(/"/g, '\\"')}"`, {
        cwd: session.worktree_path,
      });
    } catch (e) {
      console.warn('[close-session] gh pr create failed (PR may already exist). Skipping.');
    }
  }

  // 4. Remove config symlinks BEFORE git worktree remove
  //    (junctions/hardlinks podem confundir git worktree remove em alguns cenarios)
  const symlinkPaths = Array.isArray(config.symlinks) ? config.symlinks : [];
  if (symlinkPaths.length > 0) {
    console.log('[close-session] removing config links...');
    for (const relPath of symlinkPaths) {
      const linkAbs = path.join(session.worktree_path, relPath);
      const r = removeConfigLink(linkAbs);
      if (r.ok) console.log(`  - ${relPath} (removed)`);
      else if (r.error) console.warn(`  ! ${relPath} (FAIL: ${r.error})`);
    }
  }

  // 5. Remove worktree (must run from repo root)
  const insideTarget = path.resolve(cwd) === session.worktree_path ||
    path.resolve(cwd).startsWith(session.worktree_path + path.sep);
  if (insideTarget) {
    console.warn('[close-session] NOTE: cwd is inside worktree being removed -- cd to repo root after this.');
  }

  console.log('[close-session] removing worktree...');
  try {
    sh(`git worktree remove "${session.worktree_path}"`, { cwd: repoRoot });
  } catch (e) {
    console.warn(`[close-session] worktree remove failed: ${e.message.split('\n')[0]}`);
    console.warn('[close-session] trying --force...');
    try {
      sh(`git worktree remove --force "${session.worktree_path}"`, { cwd: repoRoot });
    } catch (e2) {
      fail(`worktree remove failed even with --force: ${e2.message.split('\n')[0]}`);
    }
  }

  // 6. Deregister
  const removed = await registry.unregister(session.session_id);
  console.log(`[close-session] registry: ${removed ? 'deregistered' : 'already gone'}`);

  // 7. Prune any dangling worktree metadata
  try { sh('git worktree prune', { cwd: repoRoot }); } catch (_) {}

  // 8. Delete branch if it had no commits (no PR was created -- branch is dead weight)
  if (!hasCommits) {
    try {
      sh(`git branch -D ${session.branch}`, { cwd: repoRoot });
      console.log(`[close-session] branch ${session.branch} (empty) deleted`);
    } catch (_) { /* best effort */ }
  }

  console.log('');
  console.log('[close-session] DONE');
  if (insideTarget) {
    console.log(`  cd "${repoRoot}"`);
  }
}

main().catch((e) => fail(e.stack || e.message, 1));
