/**
 * story_editor.js — Timeline Script Editor UI for 3D Story Engine
 * Manages: actor list, timeline tracks, event CRUD, waypoint placement, Save/Load/AI
 */

const ACTION_COLORS = {
    walk_to:      '#3b82f6',
    chat:         '#22c55e',
    animate:      '#a855f7',
    return_desk:  '#f59e0b',
    sit:          '#14b8a6',
    stand:        '#f97316',
    emote:        '#ec4899',
};

const ACTION_ICONS = {
    walk_to: '🚶', chat: '💬', animate: '🎭',
    return_desk: '🏃', sit: '🪑', stand: '⬆️', emote: '✨',
};

const ANIM_OPTIONS = ['read', 'write_board', 'shake_hand', 'cheer', 'think'];

class StoryEditor {
    constructor() {
        this.script = this._emptyScript();
        this.selectedEventIdx = null;
        this.timelineScale = 60; // px per second
        this.isDragging = false;
        this.dragEvt = null;
        this.waypointMode = false;  // clicking 3D map creates waypoint
        this._agents = [];
        this._onWaypointPlace = null; // callback(x, z)
    }

    // ── Init ────────────────────────────────────────────────────────────
    async init() {
        // Actors now come from team selection (doSelectTeam in story.html)
        this._renderActors();
        this._renderTimeline();
        this._renderWaypoints();
        this._bindControls();
    }

    _emptyScript() {
        return {
            id: null,
            title: 'Kịch bản mới',
            scene_id: 'team_trieudionh',
            actors: [],
            waypoints: [],
            timeline: [],
        };
    }

    // ── Agent Loader ─────────────────────────────────────────────────────
    async _loadAgents() {
        try {
            const res = await fetch('/api/v1/agents');
            const data = await res.json();
            this._agents = data.agents || data || [];
        } catch (e) { this._agents = []; }
    }

    // ── Actors Panel (read-only, populated from team) ──────────────────
    _renderActors() {
        const container = document.getElementById('se-actors');
        if (!container) return;
        container.innerHTML = '';

        if (this.script.actors.length === 0) {
            container.innerHTML = '<span style="color:var(--muted);font-size:12px">Chọn Team ở trên để load nhân vật</span>';
            return;
        }

        this.script.actors.forEach((actor) => {
            const div = document.createElement('div');
            div.className = 'se-actor-row';
            div.innerHTML = `
                <span class="se-actor-color" style="background:${actor.color}"></span>
                <span style="font-size:15px;flex-shrink:0">${actor.emoji || '🤖'}</span>
                <div style="flex:1;min-width:0;overflow:hidden">
                    <div class="se-actor-name" style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${actor.name}</div>
                    <div style="font-size:10px;color:var(--muted)">${actor.role || ''} <span style="color:#475569">[${actor.key}]</span></div>
                </div>
            `;
            container.appendChild(div);
        });
    }

    _showAddActorModal() {
        const agentOptions = this._agents.map(a =>
            `<option value="${a.id}">${a.name || a.id}</option>`
        ).join('');

        showModal('Thêm nhân vật', `
            <div class="se-form">
                <label>Nhân vật key (VD: nam, lan):</label>
                <input id="se-actor-key" class="se-input" placeholder="key" value="actor${this.script.actors.length + 1}">
                <label>Tên hiển thị:</label>
                <input id="se-actor-name" class="se-input" placeholder="Tên">
                <label>Agent:</label>
                <select id="se-actor-agent" class="se-input">${agentOptions}</select>
                <label>Màu:</label>
                <input id="se-actor-color" type="color" class="se-input-color" value="${this._randomColor()}">
            </div>
        `, () => {
            const key   = document.getElementById('se-actor-key').value.trim();
            const name  = document.getElementById('se-actor-name').value.trim();
            const agent_id = document.getElementById('se-actor-agent').value;
            const color = document.getElementById('se-actor-color').value;
            if (!key || !name) return;
            this.script.actors.push({ key, name, agent_id, color });
            this._renderActors();
            this._renderTimeline();
            // Re-sync actor map in player
            storyPlayer.script = this.script;
            storyPlayer._rebuildActorMap();
        });
    }

    _removeActor(i) {
        const key = this.script.actors[i]?.key;
        this.script.actors.splice(i, 1);
        // Remove their events too
        if (key) this.script.timeline = this.script.timeline.filter(e => e.actor !== key);
        this._renderActors();
        this._renderTimeline();
    }

    _randomColor() {
        const colors = ['#f43f5e','#22d3ee','#a855f7','#22c55e','#f59e0b','#3b82f6','#ec4899','#14b8a6'];
        return colors[this.script.actors.length % colors.length];
    }

    // ── Waypoints ─────────────────────────────────────────────────────────
    _renderWaypoints() {
        const container = document.getElementById('se-waypoints');
        if (!container) return;
        container.innerHTML = '';
        this.script.waypoints.forEach((wp, i) => {
            const div = document.createElement('div');
            div.className = 'se-waypoint-row';
            div.innerHTML = `
                <span class="se-wp-icon">📍</span>
                <span class="se-wp-label">${wp.label} <small>(${wp.id})</small></span>
                <span class="se-wp-pos">${wp.x.toFixed(1)}, ${wp.z.toFixed(1)}</span>
                <button class="se-btn-icon" onclick="storyEditor._removeWaypoint(${i})">✕</button>
            `;
            container.appendChild(div);
        });

        const addBtn = document.createElement('div');
        addBtn.innerHTML = `
            <button class="se-btn-secondary ${this.waypointMode ? 'active' : ''}" 
                onclick="storyEditor._toggleWaypointMode()">
                ${this.waypointMode ? '✓ Đang chờ click 3D map...' : '📍 Đặt waypoint'}
            </button>
        `;
        container.appendChild(addBtn);
    }

    _toggleWaypointMode() {
        this.waypointMode = !this.waypointMode;
        this._renderWaypoints();
        // Show instruction
        const msg = document.getElementById('se-status');
        if (msg) msg.textContent = this.waypointMode ? '↗ Click vào bản đồ 3D để đặt waypoint' : '';
    }

    addWaypointAt(x, z) {
        if (!this.waypointMode) return false;
        // Ask for name
        const label = prompt('Tên waypoint (VD: Whiteboard, Sofa):', `WP${this.script.waypoints.length + 1}`);
        if (!label) { this.waypointMode = false; this._renderWaypoints(); return false; }
        const id = label.toLowerCase().replace(/\s+/g, '_').replace(/[^a-z0-9_]/g, '');
        this.script.waypoints.push({ id, label, x: parseFloat(x.toFixed(2)), z: parseFloat(z.toFixed(2)) });
        this.waypointMode = false;
        this._renderWaypoints();
        storyPlayer.waypointMap[id] = { x, z, label };
        // Draw waypoint marker on 3D scene
        this._draw3DWaypointMarker(id, label, x, z);
        return true;
    }

    _draw3DWaypointMarker(id, label, x, z) {
        if (typeof scene3d === 'undefined' || typeof THREE === 'undefined') return;
        // Remove old marker with same id
        const old = scene3d.getObjectByName('wp_' + id);
        if (old) scene3d.remove(old);

        const g = new THREE.Group();
        g.name = 'wp_' + id;
        g.position.set(x, 0, z);

        // Pin pole
        const pole = new THREE.Mesh(
            new THREE.CylinderGeometry(0.03, 0.03, 0.8, 6),
            new THREE.MeshBasicMaterial({ color: 0xf59e0b })
        );
        pole.position.y = 0.4;
        g.add(pole);

        // Pin head
        const head = new THREE.Mesh(
            new THREE.SphereGeometry(0.1, 8, 6),
            new THREE.MeshBasicMaterial({ color: 0xf59e0b })
        );
        head.position.y = 0.85;
        g.add(head);

        // Label sprite
        if (typeof makeText === 'function') {
            const tex = makeText(label, '#f59e0b', 28, 256, 40);
            const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: false }));
            sprite.scale.set(1.5, 0.28, 1);
            sprite.position.y = 1.15;
            g.add(sprite);
        }

        scene3d.add(g);
    }

    _removeWaypoint(i) {
        const wp = this.script.waypoints[i];
        if (wp && typeof scene3d !== 'undefined') {
            const m = scene3d.getObjectByName('wp_' + wp.id);
            if (m) scene3d.remove(m);
        }
        this.script.waypoints.splice(i, 1);
        this._renderWaypoints();
    }

    // Redraw all waypoints on 3D scene (e.g., after loading a script)
    _drawAllWaypoints() {
        (this.script.waypoints || []).forEach(wp =>
            this._draw3DWaypointMarker(wp.id, wp.label, wp.x, wp.z)
        );
    }

    // ── Timeline ──────────────────────────────────────────────────────────
    _renderTimeline() {
        const tl = document.getElementById('se-timeline');
        if (!tl) return;
        tl.innerHTML = '';

        const maxTime = Math.max(30, ...this.script.timeline.map(e => (e.time || 0) + (e.duration || 2))) + 5;

        // Time ruler
        const ruler = document.createElement('div');
        ruler.className = 'se-ruler';
        ruler.style.width = `${maxTime * this.timelineScale + 80}px`;
        for (let s = 0; s <= maxTime; s += 5) {
            const tick = document.createElement('span');
            tick.className = 'se-ruler-tick';
            tick.style.left = `${s * this.timelineScale}px`;
            tick.textContent = `${s}s`;
            ruler.appendChild(tick);
        }
        tl.appendChild(ruler);

        // Actor tracks
        this.script.actors.forEach(actor => {
            const track = document.createElement('div');
            track.className = 'se-track';
            track.style.width = `${maxTime * this.timelineScale + 80}px`;

            const label = document.createElement('div');
            label.className = 'se-track-label';
            label.innerHTML = `<span style="background:${actor.color}" class="se-dot"></span><span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${actor.name}</span>`;
            track.appendChild(label);

            const lane = document.createElement('div');
            lane.className = 'se-track-lane';
            lane.style.width = `${maxTime * this.timelineScale}px`;

            // Events for this actor
            this.script.timeline.forEach((evt, idx) => {
                if (evt.actor !== actor.key) return;
                const block = this._makeEventBlock(evt, idx, actor.color);
                lane.appendChild(block);
            });

            // Click lane to add event
            lane.addEventListener('click', (e) => {
                if (e.target !== lane) return;
                const laneRect = lane.getBoundingClientRect();
                const timeClicked = (e.clientX - laneRect.left) / this.timelineScale;
                this._showAddEventModal(actor.key, Math.round(timeClicked));
            });

            track.appendChild(lane);
            tl.appendChild(track);
        });
    }

    _makeEventBlock(evt, idx, actorColor) {
        const duration = evt.duration || (evt.action === 'walk_to' ? 3 : evt.action === 'chat' ? 3 : 2);
        const w = Math.max(30, duration * this.timelineScale);
        const left = (evt.time || 0) * this.timelineScale;
        const color = ACTION_COLORS[evt.action] || '#555';

        const block = document.createElement('div');
        block.className = 'se-event-block';
        block.style.cssText = `left:${left}px; width:${w}px; background:${color}22; border-left:3px solid ${color}`;
        block.innerHTML = `
            <span class="se-evt-icon">${ACTION_ICONS[evt.action] || '•'}</span>
            <span class="se-evt-label">${this._eventLabel(evt)}</span>
        `;
        block.title = `${evt.action} @ ${evt.time}s`;

        // Click = edit
        block.addEventListener('click', (e) => {
            e.stopPropagation();
            this._showEditEventModal(idx);
        });

        // Drag to move time
        block.addEventListener('mousedown', (e) => {
            if (e.button !== 0) return;
            e.stopPropagation();
            const startX = e.clientX;
            const startTime = evt.time || 0;
            const onMove = (ev) => {
                const dx = ev.clientX - startX;
                evt.time = Math.max(0, Math.round(startTime + dx / this.timelineScale));
                block.style.left = `${evt.time * this.timelineScale}px`;
            };
            const onUp = () => {
                document.removeEventListener('mousemove', onMove);
                document.removeEventListener('mouseup', onUp);
                this._renderTimeline();
            };
            document.addEventListener('mousemove', onMove);
            document.addEventListener('mouseup', onUp);
        });

        return block;
    }

    _eventLabel(evt) {
        if (evt.action === 'chat') return evt.dialog?.substring(0, 18) || 'chat';
        if (evt.action === 'walk_to') return typeof evt.target === 'string' ? evt.target : `(${evt.target?.x},${evt.target?.z})`;
        if (evt.action === 'animate') return evt.anim || 'anim';
        if (evt.action === 'emote') return evt.emoji || '✨';
        return evt.action;
    }

    // ── Event Modals ─────────────────────────────────────────────────────
    _showAddEventModal(actorKey, time) {
        const wpOptions = this.script.waypoints.map(wp =>
            `<option value="${wp.id}">${wp.label} (${wp.id})</option>`
        ).join('');

        showModal('Thêm sự kiện', `
            <div class="se-form">
                <label>Thời gian (giây):</label>
                <input id="se-evt-time" class="se-input" type="number" value="${time}" min="0">
                <label>Hành động:</label>
                <select id="se-evt-action" class="se-input" onchange="storyEditor._onActionChange()">
                    ${Object.keys(ACTION_COLORS).map(a => `<option value="${a}">${ACTION_ICONS[a]} ${a}</option>`).join('')}
                </select>
                <div id="se-evt-extra"></div>
            </div>
        `, () => {
            const action = document.getElementById('se-evt-action').value;
            const time_ = parseInt(document.getElementById('se-evt-time').value) || 0;
            const evt = { time: time_, actor: actorKey, action };

            if (action === 'chat') {
                evt.dialog = document.getElementById('se-evt-dialog')?.value || '';
                evt.duration = parseFloat(document.getElementById('se-evt-duration')?.value) || 3;
            } else if (action === 'walk_to') {
                const wpSel = document.getElementById('se-evt-wp-sel')?.value;
                const cx = document.getElementById('se-evt-cx')?.value;
                const cz = document.getElementById('se-evt-cz')?.value;
                evt.target = wpSel ? wpSel : { x: parseFloat(cx) || 0, z: parseFloat(cz) || 0 };
            } else if (action === 'animate') {
                evt.anim = document.getElementById('se-evt-anim')?.value || 'think';
            } else if (action === 'emote') {
                evt.emoji = document.getElementById('se-evt-emoji')?.value || '✨';
            }

            this.script.timeline.push(evt);
            this.script.timeline.sort((a, b) => (a.time || 0) - (b.time || 0));
            this._renderTimeline();
        });

        // Trigger initial extra-fields render
        setTimeout(() => this._onActionChange(), 50);
    }

    _onActionChange() {
        const action = document.getElementById('se-evt-action')?.value;
        const extra = document.getElementById('se-evt-extra');
        if (!extra) return;
        const wpOptions = this.script.waypoints.map(wp =>
            `<option value="${wp.id}">${wp.label}</option>`
        ).join('');

        if (action === 'chat') {
            extra.innerHTML = `
                <label>Nội dung dialog:</label>
                <textarea id="se-evt-dialog" class="se-input se-textarea" rows="2" placeholder="Nhập câu thoại..."></textarea>
                <label>Thời gian hiển thị (giây):</label>
                <input id="se-evt-duration" class="se-input" type="number" value="3" min="1" max="15">
            `;
        } else if (action === 'walk_to') {
            extra.innerHTML = `
                <label>Waypoint:</label>
                <select id="se-evt-wp-sel" class="se-input">
                    <option value="">-- Tọa độ tùy chỉnh --</option>
                    ${wpOptions}
                </select>
                <label>Hoặc nhập tọa độ X, Z:</label>
                <div style="display:flex;gap:8px">
                    <input id="se-evt-cx" class="se-input" type="number" placeholder="X" step="0.5">
                    <input id="se-evt-cz" class="se-input" type="number" placeholder="Z" step="0.5">
                </div>
            `;
        } else if (action === 'animate') {
            extra.innerHTML = `
                <label>Animation:</label>
                <select id="se-evt-anim" class="se-input">
                    ${ANIM_OPTIONS.map(a => `<option value="${a}">${a}</option>`).join('')}
                </select>
            `;
        } else if (action === 'emote') {
            extra.innerHTML = `
                <label>Emoji:</label>
                <input id="se-evt-emoji" class="se-input" value="✨" style="font-size:1.5em;width:80px">
            `;
        } else {
            extra.innerHTML = '';
        }
    }

    _showEditEventModal(idx) {
        const evt = this.script.timeline[idx];
        if (!evt) return;

        const existingActionEl = `<select id="se-edit-action" class="se-input">
            ${Object.keys(ACTION_COLORS).map(a =>
                `<option value="${a}" ${a === evt.action ? 'selected' : ''}>${ACTION_ICONS[a]} ${a}</option>`
            ).join('')}
        </select>`;

        let extraFields = '';
        if (evt.action === 'chat') {
            extraFields = `
                <label>Dialog:</label>
                <textarea id="se-edit-dialog" class="se-input se-textarea" rows="2">${evt.dialog || ''}</textarea>
                <label>Duration (s):</label>
                <input id="se-edit-dur" class="se-input" type="number" value="${evt.duration || 3}">
            `;
        } else if (evt.action === 'walk_to') {
            const t = typeof evt.target === 'string' ? evt.target : '';
            const cx = typeof evt.target === 'object' ? (evt.target?.x || 0) : '';
            const cz = typeof evt.target === 'object' ? (evt.target?.z || 0) : '';
            const wpOptions = ['', ...this.script.waypoints.map(wp => wp.id)].map(id =>
                `<option value="${id}" ${id === t ? 'selected' : ''}>${id || '-- Tọa độ --'}</option>`
            ).join('');
            extraFields = `
                <label>Waypoint:</label>
                <select id="se-edit-wp" class="se-input">${wpOptions}</select>
                <label>X, Z:</label>
                <div style="display:flex;gap:8px">
                    <input id="se-edit-cx" class="se-input" type="number" value="${cx}" step="0.5">
                    <input id="se-edit-cz" class="se-input" type="number" value="${cz}" step="0.5">
                </div>
            `;
        } else if (evt.action === 'animate') {
            extraFields = `
                <label>Anim:</label>
                <select id="se-edit-anim" class="se-input">
                    ${ANIM_OPTIONS.map(a => `<option value="${a}" ${a === evt.anim ? 'selected' : ''}>${a}</option>`).join('')}
                </select>
            `;
        } else if (evt.action === 'emote') {
            extraFields = `<label>Emoji:</label><input id="se-edit-emoji" class="se-input" value="${evt.emoji || '✨'}" style="font-size:1.5em;width:80px">`;
        }

        showModal('Sửa sự kiện', `
            <div class="se-form">
                <label>Thời gian (s):</label>
                <input id="se-edit-time" class="se-input" type="number" value="${evt.time || 0}">
                <label>Hành động:</label>
                ${existingActionEl}
                ${extraFields}
                <button class="se-btn-danger" onclick="storyEditor._deleteEvent(${idx}); closeModal();">🗑 Xóa event</button>
            </div>
        `, () => {
            evt.time = parseInt(document.getElementById('se-edit-time').value) || 0;
            if (evt.action === 'chat') {
                evt.dialog = document.getElementById('se-edit-dialog')?.value || '';
                evt.duration = parseFloat(document.getElementById('se-edit-dur')?.value) || 3;
            } else if (evt.action === 'walk_to') {
                const wp = document.getElementById('se-edit-wp')?.value;
                const cx_ = document.getElementById('se-edit-cx')?.value;
                const cz_ = document.getElementById('se-edit-cz')?.value;
                evt.target = wp ? wp : { x: parseFloat(cx_) || 0, z: parseFloat(cz_) || 0 };
            } else if (evt.action === 'animate') {
                evt.anim = document.getElementById('se-edit-anim')?.value || 'think';
            } else if (evt.action === 'emote') {
                evt.emoji = document.getElementById('se-edit-emoji')?.value || '✨';
            }
            this.script.timeline.sort((a, b) => (a.time || 0) - (b.time || 0));
            this._renderTimeline();
        });
    }

    _deleteEvent(idx) {
        this.script.timeline.splice(idx, 1);
        this._renderTimeline();
    }

    // ── Save / Load ───────────────────────────────────────────────────────
    async save() {
        const isNew = !this.script.id;
        const url = isNew ? '/api/v1/story/scripts' : `/api/v1/story/scripts/${this.script.id}`;
        const method = isNew ? 'POST' : 'PUT';
        try {
            const res = await fetch(url, {
                method,
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(this.script),
            });
            const data = await res.json();
            if (isNew && data.id) this.script.id = data.id;
            showToast('✅ Đã lưu kịch bản!', 'success');
        } catch (e) {
            showToast('❌ Lưu thất bại: ' + e.message, 'error');
        }
    }

    async loadList() {
        const res = await fetch('/api/v1/story/scripts');
        const data = await res.json();
        return data.scripts || [];
    }

    async loadScript(id) {
        const res = await fetch(`/api/v1/story/scripts/${id}`);
        const data = await res.json();
        this.script = data.script;
        this._renderActors();
        this._renderTimeline();
        this._renderWaypoints();
        this._drawAllWaypoints();
        // Sync to player
        storyPlayer.load(this.script);
        showToast('📂 Đã tải kịch bản: ' + this.script.title, 'success');
    }

    newScript() {
        // Keep team actors, reset timeline, waypoints, title
        const savedActors = [...this.script.actors];
        const savedSceneId = this.script.scene_id;
        this.script = this._emptyScript();
        this.script.actors = savedActors;
        this.script.scene_id = savedSceneId;
        this._renderActors();
        this._renderTimeline();
        this._renderWaypoints();
        // Clear 3D waypoint markers
        if (typeof scene3d !== 'undefined') {
            const toRemove = [];
            scene3d.traverse(o => { if (o.name && o.name.startsWith('wp_')) toRemove.push(o); });
            toRemove.forEach(o => scene3d.remove(o));
        }
    }

    // ── AI Generate ───────────────────────────────────────────────────────
    async aiGenerate(prompt) {
        const btn = document.getElementById('btn-ai-gen');
        if (btn) { btn.disabled = true; btn.textContent = '⏳ Đang tạo...'; }
        try {
            const res = await fetch('/api/v1/story/ai-generate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    prompt,
                    scene_id: this.script.scene_id,
                    actors: this.script.actors,
                }),
            });
            const data = await res.json();
            if (data.ok && data.script) {
                // Merge waypoints & timeline, keep existing actors if populated
                if (this.script.actors.length === 0) this.script.actors = data.script.actors || [];
                this.script.waypoints = data.script.waypoints || [];
                this.script.timeline = data.script.timeline || [];
                if (!this.script.title || this.script.title === 'Kịch bản mới') {
                    this.script.title = data.script.title || this.script.title;
                    const titleEl = document.getElementById('se-title');
                    if (titleEl) titleEl.value = this.script.title;
                }
                this._renderActors();
                this._renderTimeline();
                this._renderWaypoints();
                this._drawAllWaypoints();
                storyPlayer.load(this.script);
                const note = data.note === 'demo_fallback' ? ' (demo template - Ollama chưa chạy)' : '';
                showToast(`🤖 AI đã tạo kịch bản!${note}`, 'success');
            }
        } catch (e) {
            showToast('❌ AI generate lỗi: ' + e.message, 'error');
        } finally {
            if (btn) { btn.disabled = false; btn.textContent = '🤖 AI Generate'; }
        }
    }

    // ── Controls binding ──────────────────────────────────────────────────
    _bindControls() {
        // Title input
        const titleEl = document.getElementById('se-title');
        if (titleEl) {
            titleEl.value = this.script.title;
            titleEl.addEventListener('input', () => { this.script.title = titleEl.value; });
        }

        // Timeline zoom
        const zoomIn  = document.getElementById('btn-zoom-in');
        const zoomOut = document.getElementById('btn-zoom-out');
        if (zoomIn)  zoomIn.addEventListener('click',  () => { this.timelineScale = Math.min(120, this.timelineScale + 10); this._renderTimeline(); });
        if (zoomOut) zoomOut.addEventListener('click', () => { this.timelineScale = Math.max(20, this.timelineScale - 10); this._renderTimeline(); });
    }
}

// ── Modal helpers ─────────────────────────────────────────────────────────
function showModal(title, bodyHtml, onConfirm) {
    let overlay = document.getElementById('se-modal-overlay');
    if (!overlay) {
        overlay = document.createElement('div');
        overlay.id = 'se-modal-overlay';
        overlay.className = 'se-modal-overlay';
        document.body.appendChild(overlay);
    }
    overlay.innerHTML = `
        <div class="se-modal">
            <div class="se-modal-header">
                <span>${title}</span>
                <button class="se-btn-icon" onclick="closeModal()">✕</button>
            </div>
            <div class="se-modal-body">${bodyHtml}</div>
            <div class="se-modal-foot">
                <button class="se-btn-secondary" onclick="closeModal()">Hủy</button>
                <button class="se-btn-primary" id="se-modal-confirm">Xác nhận</button>
            </div>
        </div>
    `;
    overlay.style.display = 'flex';
    document.getElementById('se-modal-confirm').onclick = async () => {
        if (onConfirm) await onConfirm();
        closeModal();
    };
}

function closeModal() {
    const overlay = document.getElementById('se-modal-overlay');
    if (overlay) overlay.style.display = 'none';
}

function showToast(msg, type = 'info') {
    let tc = document.getElementById('se-toast-container');
    if (!tc) {
        tc = document.createElement('div');
        tc.id = 'se-toast-container';
        tc.className = 'se-toast-container';
        document.body.appendChild(tc);
    }
    const t = document.createElement('div');
    t.className = `se-toast se-toast-${type}`;
    t.textContent = msg;
    tc.appendChild(t);
    setTimeout(() => { t.style.opacity = '0'; setTimeout(() => t.remove(), 400); }, 3000);
}

// Global singleton
const storyEditor = new StoryEditor();
