/**
 * "Auto-scrape" is a switch the user turns on, not a suggestion to a model.
 *
 * Run:  node tests/scrape_trigger_test.js     (exit 0 = pass)
 *
 * The Psychology agent visited 43 pages and harvested 2 articles. Not a crash,
 * not a selector break — the system asked for exactly that:
 *
 *   6. PRIORITIZE browsing and exploring content (click_result, browse, watch)
 *      over extract_content.
 *
 * That line sat in the prompt the model uses to pick every action. And the
 * deterministic rule that WOULD have saved it — "content page detected,
 * auto-trigger extract_content" in _getContentBasedAction — is only reached
 * when generateAIAction returns nothing at all. With a model that answers, the
 * branch never runs, so the safety net was hanging under a floor nobody walks
 * on.
 *
 * Two changes, and this file guards both:
 *   - the rule is inverted: on an unharvested content page, extract first
 *   - _ensureScrapeFirst prepends the action when the model omits it anyway
 *
 * The method is extracted from session_manager.js and EXECUTED against stub
 * state. A regex confirming the method exists would pass against a body that
 * returns its input unchanged.
 */
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const SRC = fs.readFileSync(
    path.join(ROOT, 'tubecli/extensions/browser/session_manager.js'), 'utf8'
).replace(/\r\n/g, '\n');

let checks = 0;
const failures = [];
function check(label, ok, detail = '') {
    checks++;
    if (!ok) failures.push(`${label}: ${detail}`);
}

console.log('='.repeat(70));
console.log('SCRAPE TRIGGER');
console.log('='.repeat(70));

// ── 1. the instruction no longer ranks browsing above harvesting ───────────
check('the old "prioritise browsing over extract_content" rule is gone',
      !/PRIORITIZE browsing[^\n]*over extract_content/i.test(SRC),
      'the prompt still tells the model to skip harvesting');
check('the prompt now demands extraction on an unharvested content page',
      /isContentPage[^\n]*alreadyScraped[^\n]*extract_content MUST be the FIRST action/i.test(SRC),
      'no positive instruction to harvest');
check('extract_content is still offered only when scraping is enabled',
      /\$\{context\.enable_scraping \? '- extract_content/.test(SRC),
      'the action list no longer respects the switch');

// ── 2. the net is on the path the model actually takes ────────────────────
check('_ensureScrapeFirst runs on the AI chain',
      /const finalChain = this\._ensureScrapeFirst\(actionChain, pageContent\);[\s\S]{0,200}return finalChain;/.test(SRC),
      'defined but never called on the returned chain');

const m = SRC.match(/^  _ensureScrapeFirst\(actionChain, pageContent\) \{[\s\S]*?\n  \}/m);
check('_ensureScrapeFirst found', !!m, 'not in session_manager.js');
if (!m) { report(); }

// Rebuild it as a standalone function bound to a stub `this`.
const impl = new Function('return function ' + m[0].trim().replace(/^_ensureScrapeFirst/, '_ensureScrapeFirst'))();

function run({ enabled = true, isContentPage = true, url = 'https://altius.au/news/resilience',
               scraped = [], history = [], chain = [{ action: 'browse', params: { iterations: 5 } }] } = {}) {
    const ctx = {
        agentContext: { enable_scraping: enabled },
        currentContext: { url },
        scrapedUrls: new Set(scraped),
        actionHistory: history,
    };
    return impl.call(ctx, chain, { isContentPage });
}

const BROWSE = [{ action: 'browse', params: { iterations: 5 } }];

// The case from the live corpus: a real article, model chose to browse past it.
let out = run({ chain: BROWSE });
check('an unharvested article gets extract_content prepended',
      out.length === 2 && out[0].action === 'extract_content',
      JSON.stringify(out));
check('the model\'s own actions are kept, in order',
      out[1] && out[1].action === 'browse' && out[1].params.iterations === 5,
      JSON.stringify(out));

// ── 3. and does not fire when it should not ───────────────────────────────
check('the user switch is respected',
      run({ enabled: false, chain: BROWSE }).length === 1, 'scraped with the switch off');
check('a non-article page is left alone',
      run({ isContentPage: false, chain: BROWSE }).length === 1, 'harvested a listing page');
check('a page already scraped in an earlier session is left alone',
      run({ scraped: ['https://altius.au/news/resilience'], chain: BROWSE }).length === 1,
      're-scraped a known URL');
check('a page already scraped in THIS session is left alone',
      run({ history: [{ action: 'extract_content', url: 'https://altius.au/news/resilience', status: 'success' }],
            chain: BROWSE }).length === 1,
      're-scraped within the session');
// A failed attempt is not a completed one — it must be allowed to retry.
check('a FAILED earlier attempt does not block a retry',
      run({ history: [{ action: 'extract_content', url: 'https://altius.au/news/resilience', status: 'error' }],
            chain: BROWSE })[0].action === 'extract_content',
      'a single failure permanently skipped the article');
check('the model already choosing extraction is not duplicated',
      run({ chain: [{ action: 'extract_content', params: {} }, ...BROWSE] }).length === 2,
      'extract_content added twice');

// Domains extract_content refuses anyway — prepending only adds a step that
// logs "skipping commercial/service domain" and returns null.
for (const url of ['https://www.google.com/search?q=x', 'https://www.youtube.com/watch?v=1']) {
    check(`skip-listed ${new URL(url).hostname} is not prepended`,
          run({ url, chain: BROWSE }).length === 1, 'wasted an action on a refused domain');
}
check('an empty url is left alone', run({ url: '', chain: BROWSE }).length === 1, 'acted with no url');

// Junk in the chain must not throw — a null action from a bad model reply is
// the kind of thing that would take the whole session down.
let threw = false;
try { run({ chain: [null, { action: 'browse' }] }); } catch (e) { threw = true; }
check('a null action in the chain does not throw', !threw, 'crashed on malformed model output');

function report() {
    console.log(`\n${checks - failures.length}/${checks} PASS`);
    failures.forEach(x => console.log('  FAIL ' + x));
    process.exit(failures.length ? 1 : 0);
}
report();
