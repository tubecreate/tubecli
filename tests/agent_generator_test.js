/**
 * Generating an agent with AI must produce an agent that can actually talk.
 *
 * Run:  node tests/agent_generator_test.js     (exit 0 = pass)
 *
 * Two defects, one visible and one not.
 *
 * The visible one: the provider dropdown was assigned 'ollama' outright, so a
 * user whose global default is Gemini opened the dialog pointed at a local
 * model they may never have pulled, and the first Generate failed on a
 * connection error that looked like a broken feature.
 *
 * The silent one: system_prompt was in neither half of the flow. The schema
 * sent to the model never asked for it, and applyGeneratedAgent() would not
 * have copied it across if it had. So every AI-generated agent reached the
 * create form still holding "You are a helpful AI assistant." — traits,
 * interests and focus areas were all produced and all landed in persona/routine,
 * where only the scheduled keyword routine reads them. In conversation the
 * agent knew nothing about itself. That is exactly what the VietLaw agent on
 * the live server looks like today.
 *
 * The functions are EXTRACTED FROM app.js AND EXECUTED here. Checking that the
 * string "system_prompt" appears somewhere in the file would have passed
 * against a version that reads the field and throws it away.
 */
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');

// Read with the line endings normalised. These files are CRLF in the working
// tree on Windows, and every \n\n in a pattern below would otherwise fail to
// match \r\n\r\n — silently, by reporting the code as missing rather than as
// wrong. That mistake has already been made twice in this repo.
const read = (p) => fs.readFileSync(path.join(ROOT, p), 'utf8').replace(/\r\n/g, '\n');

const APP = read('tubecli/extensions/webui/static/app.js');
const GEN = read('tubecli/core/ai_generator.py');
const HTML = read('tubecli/extensions/webui/static/index.html');

let checks = 0;
const failures = [];
function check(label, ok, detail = '') {
    checks++;
    if (!ok) failures.push(`${label}: ${detail}`);
}

function extract(name) {
    // Anchor on the declaration and take up to the closing brace at column 0.
    const re = new RegExp(`^(?:async )?function ${name}\\([\\s\\S]*?\\n\\}`, 'm');
    const m = APP.match(re);
    if (!m) throw new Error(`could not find function ${name} in app.js`);
    return m[0];
}

console.log('='.repeat(70));
console.log('AGENT GENERATOR');
console.log('='.repeat(70));

// ── 1. the schema asks for a system prompt ─────────────────────────────────
const promptFn = GEN.match(/def build_ai_prompt[\s\S]*?\n\ndef /);
check('build_ai_prompt found', !!promptFn, 'not in ai_generator.py');
if (promptFn) {
    const body = promptFn[0];
    check('schema requests system_prompt', /"system_prompt"\s*:/.test(body),
          'the model is never asked for one, so it never returns one');
    check('schema still requests persona', /"persona"\s*:/.test(body), 'persona lost');
    check('schema still requests routine', /"routine"\s*:/.test(body), 'routine lost');
    check('system_prompt is described, not just named',
          /system_prompt[\s\S]{0,400}(instructions|Instructions)/.test(body),
          'an unexplained key produces a one-line placeholder');
}

// ── 2. provider follows the global default ────────────────────────────────
const showFn = extract('showGenerateAgent');
check('showGenerateAgent reads the global setting', /api\/v1\/settings/.test(showFn),
      'still opens on a hardcoded provider');

// Run it. A presence check for "/api/v1/settings" passes just as happily
// against a version that fetches the setting and then ignores it — which is
// what the first draft of this test actually asserted.
async function openWith(defaultModel, providerModels) {
    const el = {};
    const make = (id) => ({
        id, value: '', textContent: '', style: {}, options: [],
        classList: { remove() {}, add() {} },
        addEventListener() {},
        cloneNode() { return make(id); },
        parentNode: { replaceChild(nu, old) { el[old.id] = nu; } },
    });
    const doc = { getElementById: (id) => (el[id] = el[id] || make(id)) };

    // The provider <select> carries the real option list from index.html, so
    // a provider id the markup does not offer is rejected here exactly as the
    // browser would reject it.
    doc.getElementById('agent-gen-provider').options = [...optionValues].map(v => ({ value: v }));

    // Stands in for onGenProviderChange, which repopulates the model list.
    const onChange = async () => {
        const p = doc.getElementById('agent-gen-provider').value;
        doc.getElementById('agent-gen-model').options = (providerModels[p] || []).map(v => ({ value: v }));
    };

    const impl = new Function(
        'document', 'apiGet', 'onGenProviderChange', 'providerIdForModel',
        showFn.replace(/^(async )?function/, 'return async function')
    )(doc,
      async (p) => (p === '/api/v1/settings' ? { default_model: defaultModel } : {}),
      onChange, providerIdForModelRef);

    await impl();
    // The settings call is fire-and-forget inside the function, so drain the
    // microtask queue before reading what it did.
    for (let i = 0; i < 5; i++) await new Promise(r => setImmediate(r));
    return el;
}

const providerIdForModelRef = new Function(extract('providerIdForModel') + '\nreturn providerIdForModel;')();

const MODELS = {
    ollama: ['qwen:latest', 'deepseek-r1:latest'],
    gemini: ['gemini-2.5-flash', 'gemini-1.5-pro'],
    chatgpt: ['gpt-4o'],
};

async function runProviderDefaultChecks() {
    let el = await openWith('gemini-2.5-flash', MODELS);
    check('opening on a Gemini default selects Gemini',
          el['agent-gen-provider'].value === 'gemini',
          `select is '${el['agent-gen-provider'].value}' — the global setting was read and ignored`);
    check('and selects the exact global model',
          el['agent-gen-model'].value === 'gemini-2.5-flash', el['agent-gen-model'].value);

    el = await openWith('qwen:latest', MODELS);
    check('an Ollama default still selects Ollama', el['agent-gen-provider'].value === 'ollama',
          el['agent-gen-provider'].value);

    // The global model belongs to a provider whose list does not offer it.
    // Assigning it would blank the <select>, so the provider changes and the
    // model is left on whatever that provider does have.
    el = await openWith('gemini-3-unreleased', MODELS);
    check('an unknown model still switches provider', el['agent-gen-provider'].value === 'gemini',
          el['agent-gen-provider'].value);
    check('an unknown model does not blank the model select',
          el['agent-gen-model'].value !== 'gemini-3-unreleased', el['agent-gen-model'].value);

    // No setting saved yet: leave the dialog on its own default rather than
    // clearing the provider.
    el = await openWith('', MODELS);
    check('no global default leaves a usable provider',
          !!el['agent-gen-provider'].value, 'provider was blanked');
}

// providerIdForModel, executed against the model names that actually occur.
const providerIdForModel = providerIdForModelRef;

const cases = [
    ['gemini-2.5-flash', 'gemini'],
    ['gemini-1.5-pro', 'gemini'],
    ['gemma2', 'gemini'],
    ['gpt-4o', 'chatgpt'],
    ['o3-mini', 'chatgpt'],
    ['claude-sonnet-4', 'claude'],
    ['grok-2', 'grok'],
    ['deepseek-chat', 'deepseek'],
    ['qwen:latest', 'ollama'],
    ['llama3.2:3b', 'ollama'],
    // The one that decides the whole ordering: an Ollama TAG for a DeepSeek
    // model. It is served locally, not by DeepSeek's cloud, so the colon has
    // to win over the vendor name. This is the model the dialog was showing.
    ['deepseek-r1:latest', 'ollama'],
    ['cx/some-model', '9router'],
    ['ag/other', '9router'],
    ['', ''],
];
for (const [model, expected] of cases) {
    const got = providerIdForModel(model);
    check(`providerIdForModel(${JSON.stringify(model)})`, got === expected, `got ${JSON.stringify(got)}`);
}

// Every id it can return must be a real option in the dropdown, or the
// assignment silently does nothing and the dialog stays on Ollama.
const optionValues = new Set(
    [...HTML.matchAll(/<select id="agent-gen-provider"[\s\S]*?<\/select>/g)]
        .flatMap(m => [...m[0].matchAll(/<option value="([^"]+)"/g)].map(o => o[1]))
);
check('provider options were found in the markup', optionValues.size >= 5, [...optionValues].join(','));
for (const [model, expected] of cases) {
    if (!expected) continue;
    check(`'${expected}' is an option in the dropdown`, optionValues.has(expected),
          `providerIdForModel can return '${expected}' but the select has no such option`);
}

// ── 3. Apply carries the system prompt across ─────────────────────────────
const applySrc = extract('applyGeneratedAgent');
const fallbackSrc = extract('systemPromptFromGenerated');

// Execute Apply against a stubbed DOM and see what lands in each field.
function runApply(generated) {
    const fields = {};
    const doc = {
        getElementById: (id) => (fields[id] = fields[id] || { value: '' }),
    };
    const sandbox = new Function(
        'document', 'showCreateAgent', 'closeModal', 'window',
        fallbackSrc + '\n' + applySrc + '\nreturn applyGeneratedAgent;'
    )(doc, () => {}, () => {}, { _lastGen: generated });
    sandbox();
    return fields;
}

const full = {
    name: 'VietLaw Business Advisor',
    description: 'A legal and business advisory assistant for Vietnamese business law.',
    system_prompt: 'You are VietLaw Business Advisor. You advise on Vietnamese corporate law.',
    persona: { traits: ['precise', 'formal'], interests: ['Commercial Law', 'FDI'] },
    routine: { dailyRoutine: { morning: {} }, workHabits: { focusAreas: ['Corporate Law'], preferredSites: ['moj.gov.vn'] } },
};

let f = runApply(full);
check('Apply fills the name', f['agent-name'].value === full.name, f['agent-name'].value);
check('Apply fills the description', f['agent-desc'].value === full.description, f['agent-desc'].value);
check('Apply fills the system prompt', f['agent-prompt'].value === full.system_prompt,
      `agent-prompt got ${JSON.stringify(f['agent-prompt'].value)}`);
check('Apply still fills interests', f['agent-interests'].value === 'Commercial Law, FDI',
      f['agent-interests'].value);
check('Apply still fills behavior JSON', /workHabits/.test(f['agent-behavior'].value),
      f['agent-behavior'].value);

// The model omitted system_prompt — routine for smaller local models given a
// long schema. The persona must still reach conversation.
const without = JSON.parse(JSON.stringify(full));
delete without.system_prompt;
f = runApply(without);
const built = f['agent-prompt'].value;
check('a missing system_prompt is rebuilt, not left blank', built.trim().length > 60, JSON.stringify(built));
check('rebuilt prompt names the agent', built.includes('VietLaw Business Advisor'), built);
check('rebuilt prompt carries the interests', built.includes('Commercial Law') && built.includes('FDI'), built);
check('rebuilt prompt carries the focus areas', built.includes('Corporate Law'), built);
check('rebuilt prompt carries the preferred sources', built.includes('moj.gov.vn'), built);
check('rebuilt prompt is never the stock placeholder',
      !/^You are a helpful AI assistant\.?$/i.test(built.trim()),
      'fell back to the very default this change exists to remove');

// Whitespace-only counts as absent. A model that emits "system_prompt": " "
// would otherwise defeat the fallback and hand back a blank field.
const blank = JSON.parse(JSON.stringify(full));
blank.system_prompt = '   \n  ';
check('a blank system_prompt is treated as missing',
      runApply(blank)['agent-prompt'].value.includes('VietLaw'), 'blank string was accepted as a prompt');

// Nothing but a name: the fallback must still produce usable text rather than
// throwing on the absent persona/routine.
const bare = { name: 'Solo' };
const bareOut = runApply(bare)['agent-prompt'].value;
check('fallback survives a near-empty generation', bareOut.includes('Solo') && bareOut.length > 40, bareOut);

// The provider-default checks are the only async ones; everything above has
// already run. Report once they finish so the count is complete.
runProviderDefaultChecks().catch(e => {
    check('provider-default checks ran', false, String(e && e.message || e));
}).then(() => {
    console.log(`\n${checks - failures.length}/${checks} PASS`);
    failures.forEach(x => console.log('  FAIL ' + x));
    process.exit(failures.length ? 1 : 0);
});
