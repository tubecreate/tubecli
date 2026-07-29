/**
 * tubecli-scripts — central store for browser-automation scripts.
 *
 * Clones the contract t2login's launcher already speaks (/api/scripts,
 * /api/script-stats, /api/script-outcome) so an existing client only has to
 * change its base URL, and adds what that contract was missing: delta sync,
 * a raw outcome log, and an admin surface to read both.
 *
 * Bindings: DB (D1). Secrets: ADMIN_TOKEN, CLIENT_KEY (optional).
 */

import DASHBOARD from './dashboard.html';

const JSON_COLUMNS = ['tags', 'steps', 'variables', 'function_inputs', 'function_outputs'];

const SCRIPT_COLUMNS = [
  'slug', 'name', 'description', 'category', 'target_url', 'tags', 'steps',
  'variables', 'is_function', 'function_inputs', 'function_outputs', 'engine',
  'min_client', 'enabled', 'created_at', 'updated_at',
];

// ── helpers ──────────────────────────────────────────────────────────────────

const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET,POST,PUT,DELETE,OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type,X-Admin-Token,X-Client-Key',
  'Access-Control-Max-Age': '86400',
};

function json(data, status = 200, extra = {}) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json; charset=utf-8', ...CORS, ...extra },
  });
}

function fail(message, status = 400, code = '') {
  return json({ success: false, error: message, code }, status);
}

function nowIso() {
  // "YYYY-MM-DD HH:MM:SS" — the shape t2login stores, so the two datasets
  // remain directly comparable and sortable as plain strings.
  return new Date().toISOString().replace('T', ' ').slice(0, 19);
}

/** Constant-time-ish string compare, so a wrong token leaks no timing signal. */
function tokensMatch(given, want) {
  if (typeof given !== 'string' || typeof want !== 'string') return false;
  if (given.length !== want.length || want.length === 0) return false;
  let diff = 0;
  for (let i = 0; i < given.length; i++) diff |= given.charCodeAt(i) ^ want.charCodeAt(i);
  return diff === 0;
}

function isAdmin(request, env) {
  return tokensMatch(request.headers.get('X-Admin-Token') || '', env.ADMIN_TOKEN || '');
}

/**
 * Client writes are gated only when CLIENT_KEY is configured. A key shipped
 * inside a desktop app is not a real secret — it exists to stop drive-by
 * posting from poisoning the success rates, nothing more.
 */
function clientAllowed(request, env) {
  if (!env.CLIENT_KEY) return true;
  return tokensMatch(request.headers.get('X-Client-Key') || '', env.CLIENT_KEY);
}

function parseJsonColumn(value, fallback) {
  if (value === null || value === undefined || value === '') return fallback;
  if (typeof value !== 'string') return value;
  try {
    return JSON.parse(value);
  } catch {
    return fallback;
  }
}

/** DB row -> API shape (JSON columns decoded, flags as booleans). */
function hydrate(row) {
  const out = { ...row };
  for (const col of JSON_COLUMNS) out[col] = parseJsonColumn(row[col], []);
  out.is_function = !!row.is_function;
  out.enabled = !!row.enabled;
  return out;
}

/**
 * A slug becomes a filename on every client that syncs, so it is folded to a
 * safe character set. Underscores are left exactly where the author put them —
 * trimming them would quietly rename '__draft__' to 'draft' and the author
 * would then be unable to find what they just saved.
 */
function normaliseSlug(value) {
  const folded = String(value || '').trim().toLowerCase().replace(/[^a-z0-9_.-]+/g, '_');
  // A slug of pure punctuation folds to "_" — and so does every other one, so
  // "!!!" and "@@@" would collide on a single row and overwrite each other.
  // Demand at least one letter or digit, which is what the error text promises.
  return /[a-z0-9]/.test(folded) ? folded : '';
}

/** decodeURIComponent throws on a malformed escape; a bad URL is a 400, not a 500. */
function safeDecode(segment) {
  try {
    return decodeURIComponent(segment);
  } catch {
    return null;
  }
}

/** API shape -> DB row. Unknown keys are dropped rather than trusted. */
function dehydrate(body, existing = null) {
  const pick = (key, dflt) => (body[key] === undefined
    ? (existing ? existing[key] : dflt)
    : body[key]);

  const encode = (key) => {
    const v = pick(key, undefined);
    if (v === undefined) return '[]';
    if (typeof v === 'string') {
      try { JSON.parse(v); return v; } catch { return '[]'; }
    }
    return JSON.stringify(v);
  };

  const truthy = (v) => v === true || v === 1 || v === '1' || v === 'true';
  const slug = normaliseSlug(pick('slug', ''));

  return {
    slug,
    name: String(pick('name', slug) || slug),
    description: String(pick('description', '') || ''),
    category: String(pick('category', 'general') || 'general').trim().toLowerCase(),
    target_url: String(pick('target_url', '') || ''),
    tags: encode('tags'),
    steps: encode('steps'),
    variables: encode('variables'),
    is_function: truthy(pick('is_function', false)) ? 1 : 0,
    function_inputs: encode('function_inputs'),
    function_outputs: encode('function_outputs'),
    engine: ['any', 'shardx', 'bas'].includes(String(pick('engine', 'any')))
      ? String(pick('engine', 'any')) : 'any',
    min_client: String(pick('min_client', '') || ''),
    enabled: truthy(pick('enabled', true)) ? 1 : 0,
    created_at: String(pick('created_at', '') || nowIso()),
    updated_at: nowIso(),
  };
}

async function readJson(request) {
  try {
    const body = await request.json();
    return (body && typeof body === 'object' && !Array.isArray(body)) ? body : null;
  } catch {
    return null;
  }
}

function clip(value, max) {
  if (value === null || value === undefined) return '';
  // Every field routed through here is meant to be text. Coercing a container
  // instead of rejecting it is a denial of service: Array.prototype.toString
  // recurses per nesting level, so a deeply nested array blows the stack before
  // any length check can run.
  if (typeof value === 'object') return '';
  return String(value).slice(0, max);
}

// ── public API ───────────────────────────────────────────────────────────────

/**
 * GET /api/scripts — the full catalogue, or everything touched since a
 * timestamp. Disabled scripts are withheld from clients but a deletion still
 * has to reach them, which is what `deleted` carries.
 */
async function listScripts(request, env) {
  const url = new URL(request.url);
  const since = (url.searchParams.get('since') || '').trim();
  const category = (url.searchParams.get('category') || '').trim().toLowerCase();
  const engine = (url.searchParams.get('engine') || '').trim().toLowerCase();

  const where = ['enabled = 1'];
  const params = [];
  // `>=`, not `>`. Timestamps have one-second resolution, so a script saved in
  // the same second the client last synced would sit forever on the wrong side
  // of a strict comparison and never reach it. Re-sending one script the client
  // already has costs nothing — its own updated_at check drops it.
  if (since) { where.push('updated_at >= ?'); params.push(since); }
  if (category) { where.push('LOWER(category) = ?'); params.push(category); }
  if (engine && engine !== 'any') { where.push("(engine = 'any' OR engine = ?)"); params.push(engine); }

  const sql = `SELECT ${SCRIPT_COLUMNS.join(',')} FROM scripts
               WHERE ${where.join(' AND ')} ORDER BY slug`;
  const { results } = await env.DB.prepare(sql).bind(...params).all();

  const payload = {
    scripts: (results || []).map(hydrate),
    server_time: nowIso(),
  };
  payload.count = payload.scripts.length;

  if (since) {
    const disabled = await env.DB.prepare(
      'SELECT slug FROM scripts WHERE enabled = 0 AND updated_at >= ? ORDER BY slug',
    ).bind(since).all();
    payload.deleted = (disabled.results || []).map((r) => r.slug);
  }
  return json(payload);
}

/**
 * The public single read must honour `enabled` exactly like the list does —
 * otherwise disabling a script withdraws it from the catalogue while leaving it
 * fully fetchable by anyone who knows its name, which is not what "tắt" means.
 */
async function getScript(env, slug) {
  const row = await env.DB.prepare(
    `SELECT ${SCRIPT_COLUMNS.join(',')} FROM scripts WHERE slug = ? AND enabled = 1`,
  ).bind(slug).first();
  if (!row) return fail('script not found', 404, 'NOT_FOUND');
  return json({ script: hydrate(row) });
}

/** GET /api/script-stats — the numbers both the client selector and the board read. */
async function getStats(env) {
  const { results } = await env.DB.prepare(
    'SELECT slug, attempts, successes, last_success_at, last_failure_at, last_error FROM script_stats',
  ).all();
  const stats = {};
  for (const r of results || []) {
    stats[r.slug] = {
      attempts: r.attempts,
      successes: r.successes,
      last_success_at: r.last_success_at || '',
      last_failure_at: r.last_failure_at || '',
      last_error: r.last_error || '',
    };
  }
  return json({ stats });
}

/**
 * POST /api/script-outcome — one run, reported by a client.
 * The raw row and the rollup are written in one batch so the two can never
 * disagree about how many times a script has run.
 */
async function recordOutcome(request, env) {
  if (!clientAllowed(request, env)) return fail('client key required', 401, 'CLIENT_KEY_REQUIRED');

  const body = await readJson(request);
  if (!body) return fail('body must be a JSON object');

  const slug = clip(body.slug, 120).trim();
  if (!slug) return fail('slug is required');

  const known = await env.DB.prepare('SELECT 1 AS ok FROM scripts WHERE slug = ?').bind(slug).first();
  if (!known) return fail(`unknown script '${slug}'`, 404, 'NOT_FOUND');

  const success = body.success === true || body.success === 1 || body.success === 'true' ? 1 : 0;
  const ts = nowIso();
  // Trimmed, like /api/register does it. Without this a padded id upserts under
  // a different primary key and one physical machine is counted as two.
  const machineId = clip(body.machine_id, 100).trim();
  const failedIndex = Number.isInteger(body.failed_step_index) ? body.failed_step_index : null;
  const error = clip(body.error, 500);
  const duration = Number.isFinite(body.duration_ms) ? Math.trunc(body.duration_ms) : null;

  const statements = [
    env.DB.prepare(
      `INSERT INTO script_outcomes
         (slug, machine_id, client_version, engine, success,
          failed_step_index, failed_step_label, error, duration_ms, created_at)
       VALUES (?,?,?,?,?,?,?,?,?,?)`,
    ).bind(
      slug, machineId, clip(body.client_version, 40), clip(body.engine, 40), success,
      failedIndex, clip(body.failed_step_label, 200), error, duration, ts,
    ),
    env.DB.prepare(
      `INSERT INTO script_stats (slug, attempts, successes, last_success_at, last_failure_at, last_error)
       VALUES (?, 1, ?, ?, ?, ?)
       ON CONFLICT(slug) DO UPDATE SET
         attempts        = attempts + 1,
         successes       = successes + excluded.successes,
         last_success_at = CASE WHEN excluded.successes = 1 THEN excluded.last_success_at ELSE script_stats.last_success_at END,
         last_failure_at = CASE WHEN excluded.successes = 0 THEN excluded.last_failure_at ELSE script_stats.last_failure_at END,
         last_error      = CASE WHEN excluded.successes = 0 THEN excluded.last_error ELSE script_stats.last_error END`,
    ).bind(slug, success, success ? ts : '', success ? '' : ts, success ? '' : error),
  ];

  if (machineId) {
    statements.push(env.DB.prepare(
      `INSERT INTO clients (machine_id, hostname, version, platform, first_seen, last_seen, runs)
       VALUES (?,?,?,?,?,?,1)
       ON CONFLICT(machine_id) DO UPDATE SET
         hostname  = excluded.hostname,
         version   = excluded.version,
         platform  = excluded.platform,
         last_seen = excluded.last_seen,
         runs      = clients.runs + 1`,
    ).bind(machineId, clip(body.hostname, 100), clip(body.client_version, 40),
      clip(body.platform, 40), ts, ts));
  }

  await env.DB.batch(statements);
  return json({ success: true, slug, recorded_at: ts });
}

/** POST /api/register — heartbeat, so the board can show who is actually running. */
async function registerClient(request, env) {
  if (!clientAllowed(request, env)) return fail('client key required', 401, 'CLIENT_KEY_REQUIRED');
  const body = await readJson(request);
  if (!body) return fail('body must be a JSON object');
  const machineId = clip(body.machine_id, 100).trim();
  if (!machineId) return fail('machine_id is required');
  const ts = nowIso();
  await env.DB.prepare(
    `INSERT INTO clients (machine_id, hostname, version, platform, first_seen, last_seen, runs)
     VALUES (?,?,?,?,?,?,0)
     ON CONFLICT(machine_id) DO UPDATE SET
       hostname = excluded.hostname, version = excluded.version,
       platform = excluded.platform, last_seen = excluded.last_seen`,
  ).bind(machineId, clip(body.hostname, 100), clip(body.version, 40),
    clip(body.platform, 40), ts, ts).run();
  return json({ success: true, machine_id: machineId, server_time: ts });
}

// ── admin API ────────────────────────────────────────────────────────────────

async function adminOverview(env) {
  const [scripts, stats, outcomes, clients, totals] = await Promise.all([
    env.DB.prepare(
      `SELECT slug, name, category, target_url, engine, enabled, is_function,
              updated_at, json_array_length(steps) AS step_count
         FROM scripts ORDER BY slug`,
    ).all(),
    env.DB.prepare('SELECT * FROM script_stats').all(),
    env.DB.prepare(
      `SELECT COUNT(*) AS total,
              SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) AS ok,
              MAX(created_at) AS latest
         FROM script_outcomes`,
    ).first(),
    env.DB.prepare('SELECT COUNT(*) AS total, MAX(last_seen) AS latest FROM clients').first(),
    // Summed here, over every rollup row, rather than in the page. Adding it up
    // client-side from the script list drops any row whose script has been
    // deleted, so the headline rate would move the moment you delete a script
    // while keeping its history — the opposite of what "giữ lịch sử" promises.
    env.DB.prepare(
      `SELECT COALESCE(SUM(attempts), 0)  AS attempts,
              COALESCE(SUM(successes), 0) AS successes,
              COALESCE(SUM(seed_attempts), 0) AS seed_attempts
         FROM script_stats`,
    ).first(),
  ]);

  const byslug = {};
  for (const s of stats.results || []) byslug[s.slug] = s;

  return json({
    scripts: (scripts.results || []).map((s) => ({ ...s, stats: byslug[s.slug] || null })),
    totals: {
      scripts: (scripts.results || []).length,
      // Every attempt on record, inherited history included.
      attempts: (totals && totals.attempts) || 0,
      successes: (totals && totals.successes) || 0,
      // The subset this store actually witnessed and can show step detail for.
      logged_runs: (outcomes && outcomes.total) || 0,
      inherited: (totals && totals.seed_attempts) || 0,
      last_run: (outcomes && outcomes.latest) || '',
      clients: (clients && clients.total) || 0,
      last_seen: (clients && clients.latest) || '',
    },
    server_time: nowIso(),
  });
}

async function adminGetScript(env, slug) {
  const row = await env.DB.prepare('SELECT * FROM scripts WHERE slug = ?').bind(slug).first();
  if (!row) return fail('script not found', 404, 'NOT_FOUND');
  const stats = await env.DB.prepare('SELECT * FROM script_stats WHERE slug = ?').bind(slug).first();
  const outcomes = await env.DB.prepare(
    `SELECT id, machine_id, client_version, engine, success, failed_step_index,
            failed_step_label, error, duration_ms, created_at
       FROM script_outcomes WHERE slug = ? ORDER BY created_at DESC, id DESC LIMIT 50`,
  ).bind(slug).all();
  return json({
    script: hydrate(row),
    stats: stats || null,
    outcomes: outcomes.results || [],
  });
}

async function adminSaveScript(request, env, slugFromPath) {
  const body = await readJson(request);
  if (!body) return fail('body must be a JSON object');

  // The path identifies the resource. A slug in the body never overrides it,
  // otherwise PUT /scripts/foo with {"slug":"bar"} would leave foo untouched
  // and silently create a second script instead of updating the one addressed.
  const slug = normaliseSlug(slugFromPath || body.slug || '');
  if (!slug) return fail('slug is required and must contain a letter or digit');
  body.slug = slug;

  // Reject bad JSON instead of coercing it. Quietly turning an unparseable
  // `steps` into [] stores a script that runs nothing and still reports
  // success — the worst possible outcome for an automation catalogue.
  for (const key of JSON_COLUMNS) {
    if (body[key] === undefined) continue;
    let value = body[key];
    if (typeof value === 'string') {
      try {
        value = JSON.parse(value);
      } catch {
        return fail(`${key} must be valid JSON`);
      }
    }
    if (!Array.isArray(value)) return fail(`${key} must be a JSON array`);
    body[key] = value;
  }

  const existing = await env.DB.prepare('SELECT * FROM scripts WHERE slug = ?')
    .bind(slug).first();

  // POST to the collection means "create". If the slug is taken, say so instead
  // of replacing a live script wholesale: the create form pre-fills every field
  // with blanks, so an accidental collision would silently wipe a 36-step flow
  // and still report success.
  if (!slugFromPath && existing && new URL(request.url).searchParams.get('overwrite') !== '1') {
    return fail(`script '${slug}' already exists — edit it, or repeat with ?overwrite=1`,
      409, 'SLUG_EXISTS');
  }

  const row = dehydrate(body, existing);

  await env.DB.prepare(
    `INSERT OR REPLACE INTO scripts (${SCRIPT_COLUMNS.join(',')})
     VALUES (${SCRIPT_COLUMNS.map(() => '?').join(',')})`,
  ).bind(...SCRIPT_COLUMNS.map((c) => row[c])).run();

  return json({ success: true, slug: row.slug, created: !existing, updated_at: row.updated_at });
}

/**
 * Deleting drops the script but keeps its history by default — the outcome rows
 * are the only record of why a script was thrown away, and they cost nothing.
 * ?purge=1 forgets it completely, which is what you want for a script that was
 * only ever a test: otherwise its old attempts keep skewing the totals.
 */
async function adminDeleteScript(request, env, slug) {
  const purge = new URL(request.url).searchParams.get('purge') === '1';
  const existing = await env.DB.prepare('SELECT slug FROM scripts WHERE slug = ?').bind(slug).first();

  // A purge must work on history whose script is already gone — that orphaned
  // history is exactly what you are trying to forget. Only a plain delete needs
  // the script to still be there.
  if (!existing && !purge) return fail('script not found', 404, 'NOT_FOUND');

  const statements = [env.DB.prepare('DELETE FROM scripts WHERE slug = ?').bind(slug)];
  if (purge) {
    statements.push(env.DB.prepare('DELETE FROM script_stats WHERE slug = ?').bind(slug));
    statements.push(env.DB.prepare('DELETE FROM script_outcomes WHERE slug = ?').bind(slug));
  }
  await env.DB.batch(statements);
  return json({ success: true, slug, history_kept: !purge, script_existed: !!existing });
}

async function adminToggleScript(env, slug) {
  const row = await env.DB.prepare('SELECT enabled FROM scripts WHERE slug = ?').bind(slug).first();
  if (!row) return fail('script not found', 404, 'NOT_FOUND');
  const next = row.enabled ? 0 : 1;
  await env.DB.prepare('UPDATE scripts SET enabled = ?, updated_at = ? WHERE slug = ?')
    .bind(next, nowIso(), slug).run();
  return json({ success: true, slug, enabled: !!next });
}

async function adminOutcomes(request, env) {
  const url = new URL(request.url);
  const slug = (url.searchParams.get('slug') || '').trim();
  const onlyFailed = url.searchParams.get('failed') === '1';
  const limit = Math.min(Math.max(parseInt(url.searchParams.get('limit') || '100', 10) || 100, 1), 500);

  const where = [];
  const params = [];
  if (slug) { where.push('slug = ?'); params.push(slug); }
  if (onlyFailed) where.push('success = 0');

  const { results } = await env.DB.prepare(
    `SELECT id, slug, machine_id, client_version, engine, success, failed_step_index,
            failed_step_label, error, duration_ms, created_at
       FROM script_outcomes
       ${where.length ? `WHERE ${where.join(' AND ')}` : ''}
       ORDER BY created_at DESC, id DESC LIMIT ?`,
  ).bind(...params, limit).all();

  return json({ outcomes: results || [], count: (results || []).length });
}

/**
 * Rebuild the rollup from the raw log, ON TOP OF the inherited baseline.
 *
 * The 16 rows migrated from t2login carry 964 attempts that have no raw rows
 * behind them — this store never saw those runs. An earlier version assigned
 * the raw-log counts straight over the rollup, so the first real run of a
 * seeded script turned "114/196" into "0/1" and the migrated history was gone
 * from its only copy. seed_attempts / seed_successes hold that baseline
 * separately so a rebuild adds to it instead of replacing it.
 */
async function adminRecomputeStats(env) {
  const { results } = await env.DB.prepare(
    `SELECT slug,
            COUNT(*) AS attempts,
            SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) AS successes,
            COALESCE(MAX(CASE WHEN success = 1 THEN created_at END), '') AS last_success_at,
            COALESCE(MAX(CASE WHEN success = 0 THEN created_at END), '') AS last_failure_at
       FROM script_outcomes GROUP BY slug`,
  ).all();

  const rows = results || [];
  if (rows.length) {
    await env.DB.batch(rows.map((r) => env.DB.prepare(
      `INSERT INTO script_stats
         (slug, attempts, successes, last_success_at, last_failure_at, last_error,
          seed_attempts, seed_successes)
       VALUES (?,?,?,?,?,'',0,0)
       ON CONFLICT(slug) DO UPDATE SET
         attempts        = script_stats.seed_attempts  + excluded.attempts,
         successes       = script_stats.seed_successes + excluded.successes,
         last_success_at = MAX(script_stats.last_success_at, excluded.last_success_at),
         last_failure_at = MAX(script_stats.last_failure_at, excluded.last_failure_at)`,
    ).bind(r.slug, r.attempts, r.successes, r.last_success_at, r.last_failure_at)));
  }
  return json({
    success: true,
    recomputed: rows.length,
    note: 'raw-log counts were added to the inherited baseline; rows with no raw log are untouched',
  });
}

async function adminClients(env) {
  const { results } = await env.DB.prepare(
    'SELECT * FROM clients ORDER BY last_seen DESC LIMIT 200',
  ).all();
  return json({ clients: results || [] });
}

// ── router ───────────────────────────────────────────────────────────────────

export default {
  async fetch(request, env) {
    if (request.method === 'OPTIONS') return new Response(null, { status: 204, headers: CORS });

    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, '') || '/';
    const method = request.method.toUpperCase();

    try {
      // `await` is load-bearing. A bare `return handler(...)` settles after the
      // try block has already exited, so a rejection escapes the catch and the
      // caller gets Cloudflare's opaque "error code: 1101" page instead of a
      // JSON error naming the actual fault.
      return await route(request, env, path, method);
    } catch (err) {
      return fail(`server error: ${err && err.message ? err.message : String(err)}`, 500, 'SERVER_ERROR');
    }
  },
};

async function route(request, env, path, method) {
  if (path === '/' || path === '/admin') {
    return new Response(DASHBOARD, {
      headers: { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' },
    });
  }
  if (path === '/health') {
    const row = await env.DB.prepare('SELECT COUNT(*) AS c FROM scripts').first();
    return json({ ok: true, scripts: row.c, server_time: nowIso() });
  }

  // public
  if (path === '/api/scripts' && method === 'GET') return listScripts(request, env);
  if (path.startsWith('/api/scripts/') && method === 'GET') {
    const slug = safeDecode(path.slice('/api/scripts/'.length));
    if (slug === null) return fail('malformed percent-escape in path', 400, 'BAD_PATH');
    return getScript(env, slug);
  }
  if (path === '/api/script-stats' && method === 'GET') return getStats(env);
  if (path === '/api/script-outcome' && method === 'POST') return recordOutcome(request, env);
  if (path === '/api/register' && method === 'POST') return registerClient(request, env);

  // admin
  if (path.startsWith('/api/admin/')) {
    if (!env.ADMIN_TOKEN) return fail('admin API is disabled: ADMIN_TOKEN is not set', 503, 'NO_ADMIN_TOKEN');
    if (!isAdmin(request, env)) return fail('admin token required', 401, 'ADMIN_TOKEN_REQUIRED');

    if (path === '/api/admin/overview' && method === 'GET') return adminOverview(env);
    if (path === '/api/admin/outcomes' && method === 'GET') return adminOutcomes(request, env);
    if (path === '/api/admin/clients' && method === 'GET') return adminClients(env);
    if (path === '/api/admin/stats/recompute' && method === 'POST') return adminRecomputeStats(env);
    if (path === '/api/admin/scripts' && method === 'GET') return adminOverview(env);
    if (path === '/api/admin/scripts' && method === 'POST') return adminSaveScript(request, env, '');

    if (path.startsWith('/api/admin/scripts/')) {
      const rest = path.slice('/api/admin/scripts/'.length);
      const isToggle = rest.endsWith('/toggle');
      const slug = safeDecode(isToggle ? rest.slice(0, -'/toggle'.length) : rest);
      if (slug === null) return fail('malformed percent-escape in path', 400, 'BAD_PATH');
      if (isToggle) {
        return method === 'POST' ? adminToggleScript(env, slug)
          : fail('toggle requires POST', 405, 'METHOD_NOT_ALLOWED');
      }
      if (method === 'GET') return adminGetScript(env, slug);
      if (method === 'PUT' || method === 'POST') return adminSaveScript(request, env, slug);
      if (method === 'DELETE') return adminDeleteScript(request, env, slug);
    }
    return fail('unknown admin endpoint', 404, 'NOT_FOUND');
  }

  return fail(`no route for ${method} ${path}`, 404, 'NOT_FOUND');
}
