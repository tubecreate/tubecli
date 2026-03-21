/**
 * Teams AI Dashboard — Client-side application logic
 * Connects to /api/v1/multi-agents/ endpoints
 */

const API_BASE = '/api/v1/multi-agents';
const AGENTS_API = '/api/v1/agents';

let allTeams = [];
let allAgents = [];
let templates = [];
let currentTeamId = null;
let selectedTemplateId = null;

// ── Init ──────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
    await Promise.all([loadTeams(), loadAgents(), loadTemplates()]);
    renderTeamsList();
});

// ── API helpers ───────────────────────────────────────────
async function api(path, opts = {}) {
    const url = path.startsWith('http') ? path : `${API_BASE}${path}`;
    const res = await fetch(url, {
        headers: { 'Content-Type': 'application/json', ...opts.headers },
        ...opts,
    });
    if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || err.message || 'API error');
    }
    return res.json();
}

async function loadTeams() {
    try {
        const data = await api('/teams');
        allTeams = data.teams || [];
    } catch (e) {
        console.error('Failed to load teams:', e);
        allTeams = [];
    }
}

async function loadAgents() {
    try {
        const res = await fetch(`${AGENTS_API}`);
        const data = await res.json();
        allAgents = data.agents || data || [];
    } catch (e) {
        console.error('Failed to load agents:', e);
        allAgents = [];
    }
}

async function loadTemplates() {
    try {
        const data = await api('/templates');
        templates = data.templates || [];
    } catch (e) {
        console.error('Failed to load templates:', e);
        templates = [];
    }
}

async function loadTaskLog() {
    try {
        const data = await api('/log');
        renderTaskLog(data.log || []);
    } catch (e) {
        console.error('Failed to load task log:', e);
    }
}

// ── Render: Teams List ────────────────────────────────────
function renderTeamsList() {
    const container = document.getElementById('teams-list');
    if (allTeams.length === 0) {
        container.innerHTML = '<div class="empty-state">No teams yet. Click + to create one.</div>';
        return;
    }
    container.innerHTML = allTeams.map(t => `
        <div class="team-card ${currentTeamId === t.id ? 'active' : ''}" onclick="selectTeam('${t.id}')">
            <div class="team-card-name">${escHtml(t.name)}</div>
            <div class="team-card-meta">
                ${t.template !== 'custom' ? `<span class="tag" style="font-size:10px">${escHtml(t.template)}</span> ` : ''}
                ${(t.nodes || []).length} roles · ${(t.agent_ids || []).length} agents
            </div>
        </div>
    `).join('');

    loadTaskLog();
}

// ── Render: Task Log ──────────────────────────────────────
function renderTaskLog(log) {
    const container = document.getElementById('task-log');
    if (log.length === 0) {
        container.innerHTML = '<div class="empty-state">No tasks yet</div>';
        return;
    }
    container.innerHTML = log.slice(-10).reverse().map(entry => `
        <div class="log-entry">
            <div class="log-entry-task">${escHtml(entry.task || '').substring(0, 60)}...</div>
            <div class="log-entry-meta">${escHtml(entry.team_name)} · ${entry.agent_count} agents · ${formatTime(entry.timestamp)}</div>
        </div>
    `).join('');
}

// ── Select Team ───────────────────────────────────────────
async function selectTeam(teamId) {
    currentTeamId = teamId;
    renderTeamsList();

    document.getElementById('empty-main').style.display = 'none';
    document.getElementById('team-detail').style.display = 'block';

    try {
        const team = await api(`/teams/${teamId}`);
        renderTeamDetail(team);
    } catch (e) {
        toast('Failed to load team: ' + e.message, 'error');
    }
}

function renderTeamDetail(team) {
    document.getElementById('detail-name').textContent = team.name;
    document.getElementById('detail-template').textContent = team.template || 'custom';
    document.getElementById('detail-strategy').textContent = team.strategy || 'sequential';
    document.getElementById('detail-desc').textContent = team.description || 'No description';

    // Hide delegation results when switching teams
    document.getElementById('delegation-results').style.display = 'none';

    // Render org chart
    renderOrgChart(team);
}

// ── Render: Org Chart ─────────────────────────────────────
function renderOrgChart(team) {
    const container = document.getElementById('org-chart');
    const nodes = team.nodes || [];

    if (nodes.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                No hierarchy defined. This team uses <strong>${team.strategy}</strong> strategy.
                <br><br>Agents: ${(team.agent_ids || []).map(id => {
                    const a = allAgents.find(ag => ag.id === id);
                    return a ? `<span class="tag tag-cyan">${escHtml(a.name)}</span>` : id;
                }).join(' ')}
            </div>`;
        return;
    }

    // Group nodes by layer
    const layers = {};
    nodes.forEach(n => {
        const layer = n.layer || 0;
        if (!layers[layer]) layers[layer] = [];
        layers[layer].push(n);
    });

    const sortedLayers = Object.keys(layers).sort((a, b) => a - b);

    let html = '';
    sortedLayers.forEach((layerKey, idx) => {
        if (idx > 0) {
            html += '<div class="org-connector"></div>';
        }
        html += '<div class="org-layer">';
        layers[layerKey].forEach(node => {
            const agent = node.agent_id ? allAgents.find(a => a.id === node.agent_id) : null;
            html += `
                <div class="org-node ${agent ? 'assigned' : ''}" title="${escHtml(node.description || '')}">
                    <span class="org-node-emoji">${node.emoji || '🤖'}</span>
                    <div class="org-node-role">${escHtml(node.role || node.role_id)}</div>
                    ${agent
                        ? `<div class="org-node-agent">${escHtml(agent.name)}</div>`
                        : `<div class="org-node-empty">unassigned</div>`
                    }
                </div>`;
        });
        html += '</div>';
    });

    container.innerHTML = html;
}

// ── Create Team Modal ─────────────────────────────────────
function showCreateModal() {
    document.getElementById('create-modal').classList.add('open');
    document.getElementById('step-template').style.display = 'block';
    document.getElementById('step-configure').style.display = 'none';
    selectedTemplateId = null;
    renderTemplatesGrid();
}

function closeCreateModal() {
    document.getElementById('create-modal').classList.remove('open');
}

function renderTemplatesGrid() {
    const grid = document.getElementById('templates-grid');

    // Add custom template option
    let html = `
        <div class="template-card" onclick="selectTemplate('custom')">
            <div class="template-card-name">🛠️ Custom Team</div>
            <div class="template-card-desc">Create a flat team without hierarchy</div>
            <div class="template-card-roles">No predefined roles</div>
        </div>`;

    templates.forEach(t => {
        const roleEmojis = (t.roles || []).slice(0, 6).map(r => r.emoji).join(' ');
        html += `
            <div class="template-card" onclick="selectTemplate('${t.id}')">
                <div class="template-card-name">${escHtml(t.name)}</div>
                <div class="template-card-desc">${escHtml(t.description)}</div>
                <div class="template-card-roles">${roleEmojis} · ${t.node_count} roles</div>
            </div>`;
    });

    grid.innerHTML = html;
}

async function selectTemplate(templateId) {
    selectedTemplateId = templateId;

    if (templateId === 'custom') {
        // Quick create: just name + agents
        document.getElementById('step-template').style.display = 'none';
        document.getElementById('step-configure').style.display = 'block';
        document.getElementById('team-name-input').value = '';
        document.getElementById('role-assignments').innerHTML =
            '<div class="empty-state">Custom teams have no roles. Agents will work in sequential order.</div>';
        return;
    }

    // Fetch full template details
    try {
        const tmpl = await api(`/templates/${templateId}`);
        document.getElementById('step-template').style.display = 'none';
        document.getElementById('step-configure').style.display = 'block';
        document.getElementById('team-name-input').value = tmpl.name || '';

        renderRoleAssignments(tmpl.nodes || []);
    } catch (e) {
        toast('Failed to load template: ' + e.message, 'error');
    }
}

function renderRoleAssignments(nodes) {
    const container = document.getElementById('role-assignments');
    container.innerHTML = nodes.map(node => `
        <div class="role-row">
            <span class="role-row-emoji">${node.emoji}</span>
            <div class="role-row-info">
                <div class="role-row-name">${escHtml(node.role)}</div>
                <div class="role-row-desc">${escHtml(node.description || '')}</div>
            </div>
            <select data-role-id="${node.role_id}">
                <option value="">-- None --</option>
                ${allAgents.map(a => `<option value="${a.id}">${escHtml(a.name)}</option>`).join('')}
            </select>
        </div>
    `).join('');
}

function backToTemplates() {
    document.getElementById('step-template').style.display = 'block';
    document.getElementById('step-configure').style.display = 'none';
}

async function createTeamFromTemplate() {
    const name = document.getElementById('team-name-input').value.trim();
    if (!name) {
        toast('Please enter a team name', 'error');
        return;
    }

    try {
        if (selectedTemplateId === 'custom') {
            await api('/teams', {
                method: 'POST',
                body: JSON.stringify({ name, strategy: 'sequential', description: 'Custom team' }),
            });
        } else {
            // Gather agent assignments
            const assignments = {};
            document.querySelectorAll('#role-assignments select').forEach(sel => {
                if (sel.value) {
                    assignments[sel.dataset.roleId] = sel.value;
                }
            });

            await api('/teams/from-template', {
                method: 'POST',
                body: JSON.stringify({
                    template_id: selectedTemplateId,
                    name,
                    agent_assignments: assignments,
                }),
            });
        }

        toast('Team created successfully!', 'success');
        closeCreateModal();
        await loadTeams();
        renderTeamsList();

        // Auto-select the latest team
        if (allTeams.length > 0) {
            selectTeam(allTeams[allTeams.length - 1].id);
        }
    } catch (e) {
        toast('Failed to create team: ' + e.message, 'error');
    }
}

// ── Delete Team ───────────────────────────────────────────
async function deleteCurrentTeam() {
    if (!currentTeamId) return;
    if (!confirm('Are you sure you want to delete this team?')) return;

    try {
        await api(`/teams/${currentTeamId}`, { method: 'DELETE' });
        toast('Team deleted', 'success');
        currentTeamId = null;
        document.getElementById('team-detail').style.display = 'none';
        document.getElementById('empty-main').style.display = 'flex';
        await loadTeams();
        renderTeamsList();
    } catch (e) {
        toast('Failed to delete team: ' + e.message, 'error');
    }
}

// ── Delegate Task ─────────────────────────────────────────
function showDelegatePanel() {
    document.getElementById('delegate-modal').classList.add('open');
    document.getElementById('delegate-task-input').value = '';
    document.getElementById('delegate-task-input').focus();
}

function closeDelegatePanel() {
    document.getElementById('delegate-modal').classList.remove('open');
}

async function delegateTask() {
    if (!currentTeamId) return;
    const task = document.getElementById('delegate-task-input').value.trim();
    if (!task) {
        toast('Please describe the task', 'error');
        return;
    }

    const btn = document.getElementById('btn-delegate');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Delegating...';

    try {
        const result = await api(`/teams/${currentTeamId}/delegate`, {
            method: 'POST',
            body: JSON.stringify({ task }),
        });

        closeDelegatePanel();
        renderDelegationResults(result);
        await loadTaskLog();
        toast('Task delegated successfully!', 'success');
    } catch (e) {
        toast('Delegation failed: ' + e.message, 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '🚀 Delegate';
    }
}

function renderDelegationResults(result) {
    const container = document.getElementById('delegation-results');
    const content = document.getElementById('results-content');
    container.style.display = 'block';

    const results = result.results || [];
    if (results.length === 0) {
        content.innerHTML = '<div class="empty-state">No results returned.</div>';
        return;
    }

    content.innerHTML = results.map(r => {
        const indent = (r.depth || 0) * 20;
        const isSkipped = r.status === 'skipped';
        return `
            <div class="result-card ${isSkipped ? 'skipped' : ''}" style="margin-left: ${indent}px">
                <div class="result-card-header">
                    <span>${r.emoji || '🤖'}</span>
                    <span>${escHtml(r.role || r.agent_name || r.agent_id || 'Unknown')}</span>
                    ${r.agent_name ? `<span class="tag tag-cyan" style="font-size:10px">${escHtml(r.agent_name)}</span>` : ''}
                </div>
                <div class="result-card-reply">${escHtml(r.reply || 'No response')}</div>
            </div>`;
    }).join('');
}

// ── Utilities ─────────────────────────────────────────────
function escHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function formatTime(iso) {
    if (!iso) return '';
    try {
        const d = new Date(iso);
        return d.toLocaleString('vi-VN', { hour: '2-digit', minute: '2-digit', day: '2-digit', month: '2-digit' });
    } catch { return iso; }
}

function toast(msg, type = 'success') {
    const container = document.getElementById('toast-container');
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.textContent = msg;
    container.appendChild(el);
    setTimeout(() => { el.style.opacity = '0'; setTimeout(() => el.remove(), 300); }, 3000);
}
