#!/usr/bin/env node
/**
 * registry.js -- Atomic CRUD para sessoes paralelas Claude Code.
 *
 * ADR-046 (Parallel Sessions). Canon VETO-PS-01..08.
 *
 * Storage: .aios/operations/active-sessions.json
 * Locking: sidecar lockfile `.aios/operations/active-sessions.json.lock`
 *          (fs.openSync wx -- atomico em Windows + POSIX).
 *
 * Consumed by: create.js, close.js, status.js, heartbeat.js, hooks/*
 */

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const REPO_ROOT = path.resolve(__dirname, '..', '..');
const REGISTRY_PATH = path.join(REPO_ROOT, '.aios', 'operations', 'active-sessions.json');
const LOCK_PATH = REGISTRY_PATH + '.lock';
const LOCK_RETRY_MS = 25;
const LOCK_MAX_WAIT_MS = 5000;
const IDLE_TIMEOUT_MS = 10 * 60 * 1000;
const MAX_SESSIONS = 6;

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

function isLockStale() {
  try {
    const st = fs.statSync(LOCK_PATH);
    return Date.now() - st.mtimeMs > 30_000;
  } catch (_) {
    return false;
  }
}

async function acquireLock() {
  const deadline = Date.now() + LOCK_MAX_WAIT_MS;
  while (Date.now() < deadline) {
    try {
      const fd = fs.openSync(LOCK_PATH, 'wx');
      fs.writeSync(fd, String(process.pid));
      fs.closeSync(fd);
      return;
    } catch (e) {
      if (e.code !== 'EEXIST') throw e;
      if (isLockStale()) {
        try { fs.unlinkSync(LOCK_PATH); } catch (_) { /* race */ }
        continue;
      }
      await sleep(LOCK_RETRY_MS);
    }
  }
  throw new Error(`registry lock timeout after ${LOCK_MAX_WAIT_MS}ms (stale lock?)`);
}

function releaseLock() {
  try { fs.unlinkSync(LOCK_PATH); } catch (_) { /* ignore */ }
}

function emptyRegistry() {
  return { version: 1, sessions: [] };
}

function readRegistry() {
  if (!fs.existsSync(REGISTRY_PATH)) return emptyRegistry();
  try {
    const raw = fs.readFileSync(REGISTRY_PATH, 'utf8');
    const parsed = JSON.parse(raw);
    if (!parsed || !Array.isArray(parsed.sessions)) return emptyRegistry();
    return parsed;
  } catch (_) {
    return emptyRegistry();
  }
}

function writeRegistry(registry) {
  fs.mkdirSync(path.dirname(REGISTRY_PATH), { recursive: true });
  const tmp = REGISTRY_PATH + '.tmp';
  fs.writeFileSync(tmp, JSON.stringify(registry, null, 2));
  fs.renameSync(tmp, REGISTRY_PATH);
}

async function withLock(fn) {
  await acquireLock();
  try {
    return await fn();
  } finally {
    releaseLock();
  }
}

function generateSessionId(timestamp) {
  const ts = timestamp.replace(/[:\-TZ.]/g, '').slice(0, 14);
  const rand = crypto.randomBytes(2).toString('hex');
  return `ps-${ts}-${rand}`;
}

function globMatch(pattern, filePath) {
  const normalized = filePath.replace(/\\/g, '/');
  const normPattern = pattern.replace(/\\/g, '/');
  let re = '';
  let i = 0;
  while (i < normPattern.length) {
    const c = normPattern[i];
    if (c === '*') {
      if (normPattern[i + 1] === '*') {
        re += '.*';
        i += 2;
        if (normPattern[i] === '/') i++;
      } else {
        re += '[^/]*';
        i++;
      }
    } else if (c === '?') {
      re += '[^/]';
      i++;
    } else if ('.+^${}()|[]\\'.indexOf(c) !== -1) {
      re += '\\' + c;
      i++;
    } else {
      re += c;
      i++;
    }
  }
  return new RegExp('^' + re + '$').test(normalized);
}

function pathInScope(filePath, scopePaths) {
  if (!scopePaths || scopePaths.length === 0) return false;
  const normalized = filePath.replace(/\\/g, '/');
  return scopePaths.some((p) => globMatch(p, normalized));
}

async function register({ slug, pid, branch, worktreePath, scopePaths }) {
  return withLock(async () => {
    const reg = readRegistry();

    if (reg.sessions.length >= MAX_SESSIONS) {
      throw new Error(`VETO-PS-07: max ${MAX_SESSIONS} concurrent sessions (got ${reg.sessions.length})`);
    }

    if (reg.sessions.some((s) => s.branch === branch)) {
      throw new Error(`VETO-PS-01: branch already registered: ${branch}`);
    }

    const normalizedWt = path.resolve(worktreePath);
    const repoReal = path.resolve(REPO_ROOT);
    if (normalizedWt === repoReal || normalizedWt.startsWith(repoReal + path.sep)) {
      throw new Error(`VETO-PS-02: worktree must be outside repo root (got ${normalizedWt})`);
    }

    const now = new Date().toISOString();
    const session = {
      session_id: generateSessionId(now),
      slug,
      pid,
      started_at: now,
      branch,
      worktree_path: normalizedWt,
      scope_paths: Array.isArray(scopePaths) ? scopePaths.slice() : [],
      last_heartbeat: now,
    };

    reg.sessions.push(session);
    writeRegistry(reg);
    return session;
  });
}

async function unregister(sessionId) {
  return withLock(async () => {
    const reg = readRegistry();
    const before = reg.sessions.length;
    reg.sessions = reg.sessions.filter((s) => s.session_id !== sessionId);
    writeRegistry(reg);
    return before !== reg.sessions.length;
  });
}

function list() {
  return readRegistry().sessions;
}

function findByBranch(branch) {
  return readRegistry().sessions.find((s) => s.branch === branch) || null;
}

function findByWorktreePath(worktreePath) {
  const target = path.resolve(worktreePath);
  return readRegistry().sessions.find((s) => s.worktree_path === target) || null;
}

function findByCwd(cwd) {
  const target = path.resolve(cwd);
  return readRegistry().sessions.find(
    (s) => target === s.worktree_path || target.startsWith(s.worktree_path + path.sep)
  ) || null;
}

function findOverlap(filePath, excludeSessionId = null) {
  const sessions = readRegistry().sessions;
  for (const s of sessions) {
    if (s.session_id === excludeSessionId) continue;
    if (pathInScope(filePath, s.scope_paths)) return s;
  }
  return null;
}

async function addScopePath(sessionId, scopePath) {
  return withLock(async () => {
    const reg = readRegistry();
    const s = reg.sessions.find((x) => x.session_id === sessionId);
    if (!s) return false;
    if (!s.scope_paths.includes(scopePath)) {
      s.scope_paths.push(scopePath);
      writeRegistry(reg);
    }
    return true;
  });
}

async function heartbeat(sessionId) {
  return withLock(async () => {
    const reg = readRegistry();
    const s = reg.sessions.find((x) => x.session_id === sessionId);
    if (!s) return false;
    s.last_heartbeat = new Date().toISOString();
    writeRegistry(reg);
    return true;
  });
}

async function cleanupIdle(now = Date.now()) {
  return withLock(async () => {
    const reg = readRegistry();
    const before = reg.sessions.length;
    reg.sessions = reg.sessions.filter((s) => {
      const hb = Date.parse(s.last_heartbeat);
      return now - hb < IDLE_TIMEOUT_MS;
    });
    const removed = before - reg.sessions.length;
    if (removed > 0) writeRegistry(reg);
    return removed;
  });
}

module.exports = {
  REGISTRY_PATH,
  REPO_ROOT,
  MAX_SESSIONS,
  IDLE_TIMEOUT_MS,
  register,
  unregister,
  list,
  findByBranch,
  findByWorktreePath,
  findByCwd,
  findOverlap,
  addScopePath,
  heartbeat,
  cleanupIdle,
  pathInScope,
  globMatch,
  readRegistry,
  writeRegistry,
  generateSessionId,
  withLock,
};
