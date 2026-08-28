/**
 * story_bubbles.js — 3D Speech Bubble System for Story Engine
 * Renders floating speech bubbles above characters using CSS overlay + THREE.js positions.
 */

class StoryBubbles {
    constructor() {
        this.container = null;  // DOM overlay container
        this.renderer = null;   // THREE.WebGLRenderer reference
        this.camera = null;     // THREE.Camera reference
        this.active = [];       // [{domEl, character, expiry, typewriterInterval}]
        this._boundUpdate = this.update.bind(this);
        this._rafId = null;
    }

    /**
     * Initialize. Call once the THREE scene is ready.
     * @param {HTMLElement} overlayContainer - positioned absolute div over the canvas
     * @param {THREE.Camera} camera
     * @param {THREE.WebGLRenderer} renderer
     */
    init(overlayContainer, camera, renderer) {
        this.container = overlayContainer;
        this.camera = camera;
        this.renderer = renderer;
        this._updateLoop();
    }

    _updateLoop() {
        this._rafId = requestAnimationFrame(() => {
            this.update();
            this._updateLoop();
        });
    }

    /**
     * Show a speech bubble over a character.
     * @param {Object} character - agentCharacter ref from teams3d.js
     * @param {string} text
     * @param {number} duration - seconds
     * @param {string} bubbleType - 'say', 'thought', 'code', 'test', 'drink', 'reboot', 'unlock', 'deploy'
     */
    show(character, text, duration = 3, bubbleType = 'say') {
        if (!this.container) return;

        // Limit active bubbles to at most 3 to avoid screen clutter/spam
        while (this.active.length >= 3) {
            const oldest = this.active.shift();
            if (oldest) {
                if (oldest.typewriterInterval) clearInterval(oldest.typewriterInterval);
                if (oldest.domEl) oldest.domEl.remove();
            }
        }

        // Remove existing bubble for this character
        this._removeForChar(character);

        const el = document.createElement('div');
        
        if (bubbleType === 'thought') {
            el.className = 'story-bubble thought-bubble';
            el.innerHTML = `
                <div class="bubble-content">
                    <span class="bubble-name">${this._charName(character)}</span>
                    <span class="bubble-text"></span>
                </div>
                <div class="thought-tail-circle-1"></div>
                <div class="thought-tail-circle-2"></div>
            `;
        } else if (['code', 'test', 'drink', 'reboot', 'unlock', 'deploy'].includes(bubbleType)) {
            let filename = 'terminal';
            let subClass = 'code-terminal';
            if (bubbleType === 'code') {
                const role = character.role || '';
                const charName = this._charName(character).replace(/\s+/g, '_');
                const ext = (role.toLowerCase().includes('lead') || role.toLowerCase().includes('specialist') || role.toLowerCase().includes('qa')) ? 'py' : 'js';
                filename = `${charName}.${ext}`;
                subClass = 'code-terminal';
            } else if (bubbleType === 'test') {
                filename = 'npm_test.sh';
                subClass = 'test-terminal';
            } else if (bubbleType === 'drink') {
                filename = 'caffeine_monitor.log';
                subClass = 'drink-terminal';
            } else if (bubbleType === 'reboot') {
                filename = 'system_recovery.sh';
                subClass = 'reboot-terminal';
            } else if (bubbleType === 'unlock') {
                filename = 'door_access.log';
                subClass = 'unlock-terminal';
            } else if (bubbleType === 'deploy') {
                filename = 'deploy_prod.sh';
                subClass = 'deploy-terminal';
            }

            el.className = `story-bubble terminal-bubble ${subClass}`;
            el.innerHTML = `
                <div class="bubble-header">
                    <span class="terminal-dots">
                        <span class="dot-red"></span>
                        <span class="dot-yellow"></span>
                        <span class="dot-green"></span>
                    </span>
                    <span class="terminal-filename">${filename}</span>
                </div>
                <div class="bubble-content">
                    <span class="bubble-name">${this._charName(character)}</span>
                    <span class="bubble-text"></span>
                </div>
                <div class="bubble-tail"></div>
            `;
        } else {
            // default 'say' / 'whisper'
            el.className = 'story-bubble chat-bubble';
            el.innerHTML = `
                <div class="bubble-content">
                    <span class="bubble-name">${this._charName(character)}</span>
                    <span class="bubble-text"></span>
                </div>
                <div class="bubble-tail"></div>
            `;
        }

        this.container.appendChild(el);

        const textSpan = el.querySelector('.bubble-text');

        // Typewriter effect with blinking cursor
        let charIdx = 0;
        const chars = [...text]; // handles emoji correctly
        const interval = setInterval(() => {
            if (charIdx < chars.length) {
                textSpan.textContent = chars.slice(0, charIdx + 1).join('') + '▋';
                charIdx++;
            } else {
                textSpan.textContent = text; // remove cursor at the end
                clearInterval(interval);
            }
        }, Math.min(30, (duration * 700) / Math.max(chars.length, 1)));

        const entry = {
            domEl: el,
            character,
            expiry: performance.now() + duration * 1000,
            typewriterInterval: interval,
        };
        this.active.push(entry);

        // Fade-in
        el.style.opacity = '0';
        requestAnimationFrame(() => { el.style.opacity = '1'; });
    }

    /**
     * Show a floating emoji above character (emote).
     */
    showEmote(character, emoji, duration = 2) {
        if (!this.container) return;
        const el = document.createElement('div');
        el.className = 'story-emote';
        el.textContent = emoji;
        this.container.appendChild(el);

        const entry = {
            domEl: el,
            character,
            expiry: performance.now() + duration * 1000,
            typewriterInterval: null,
            isEmote: true,
        };
        this.active.push(entry);
    }

    /**
     * Remove all bubbles for a character.
     */
    _removeForChar(character) {
        this.active = this.active.filter(e => {
            if (e.character === character) {
                this._destroyEntry(e);
                return false;
            }
            return true;
        });
    }

    _destroyEntry(entry) {
        if (entry.typewriterInterval) clearInterval(entry.typewriterInterval);
        entry.domEl.style.opacity = '0';
        setTimeout(() => { entry.domEl.remove(); }, 300);
    }

    clearAll() {
        this.active.forEach(e => this._destroyEntry(e));
        this.active = [];
    }

    _charName(ch) {
        if (ch.agentName) return ch.agentName;
        // Try to find the actor name from current story script
        try {
            const actor = storyPlayer?.script?.actors?.find(a => a.agent_id === ch.agentId);
            if (actor) return actor.name;
        } catch (e) {}
        return ch.agentId?.substring(0, 10) || '?';
    }

    /**
     * update() — project 3D positions to screen, reposition bubbles.
     * Called every frame.
     */
    update() {
        if (!this.camera || !this.renderer) return;
        const now = performance.now();
        const canvas = this.renderer.domElement;
        const rect = canvas.getBoundingClientRect();

        // Use THREE.Vector3 to project
        let toRemove = [];

        this.active.forEach(entry => {
            // Check expiry
            if (now > entry.expiry) {
                toRemove.push(entry);
                return;
            }

            const ch = entry.character;
            if (!ch || !ch.group) return;

            // World position = character head position
            const worldPos = new THREE.Vector3();
            // Head is ~1.15 units above group.position, plus a bit more for bubble
            worldPos.copy(ch.group.position);
            worldPos.y += (entry.isEmote ? 2.2 : 2.4);

            // Project to screen
            const projected = worldPos.clone().project(this.camera);

            const x = ((projected.x + 1) / 2) * rect.width;
            const y = ((-projected.y + 1) / 2) * rect.height;

            // If behind camera, hide
            if (projected.z > 1) {
                entry.domEl.style.display = 'none';
                return;
            }

            entry.domEl.style.display = '';
            entry.domEl.style.left = `${x}px`;
            entry.domEl.style.top  = `${y}px`;
        });

        // Clean up expired
        toRemove.forEach(e => {
            this._destroyEntry(e);
            const idx = this.active.indexOf(e);
            if (idx >= 0) this.active.splice(idx, 1);
        });
    }

    destroy() {
        if (this._rafId) cancelAnimationFrame(this._rafId);
        this.clearAll();
    }
}

// Global singleton
const storyBubbles = new StoryBubbles();

// ── CSS for bubbles (injected once) ───────────────────────────────────
(function injectBubbleCSS() {
    if (document.getElementById('story-bubble-styles')) return;
    const s = document.createElement('style');
    s.id = 'story-bubble-styles';
    s.textContent = `
/* Bubble tokens. Dark values are the original literals; the light blocks
   mirror the dashboard light palette (white glass, ink #1e293b, accent
   #5276EB, purple #7c5ce7). Terminal bubbles are NOT tokenised: a terminal is
   content and keeps its dark look in both themes.
   KEEP THE TWO LIGHT BLOCKS IDENTICAL - CSS cannot share them. */
:root {
    --sb-bg: rgba(15,17,30,0.92);
    --sb-line: rgba(34,211,238,0.4);
    --sb-ink: #f0f4ff;
    --sb-name: #22d3ee;
    --sb-shadow: 0 6px 28px rgba(0,0,0,0.55), 0 0 0 1px rgba(34,211,238,0.1);
    --sb-emote-shadow: 0 2px 6px rgba(0,0,0,0.6);
    --sb-th-bg: linear-gradient(135deg, rgba(23, 15, 38, 0.95), rgba(13, 8, 24, 0.98));
    --sb-th-line: rgba(216, 180, 254, 0.5);
    --sb-th-ink: #e9d5ff;
    --sb-th-name: #c084fc;
    --sb-th-shadow: 0 8px 32px rgba(168, 85, 247, 0.25), 0 0 0 1px rgba(216, 180, 254, 0.15);
    --sb-th-dot-bg: rgba(13, 8, 24, 0.98);
    --sb-th-dot-line: rgba(216, 180, 254, 0.4);
    --sb-th-dot-line2: rgba(216, 180, 254, 0.3);
    --sb-chat-bg: linear-gradient(135deg, rgba(14, 20, 42, 0.95), rgba(8, 12, 28, 0.98));
    --sb-chat-tail: rgba(8, 12, 28, 0.98);
    --sb-chat-line: rgba(56, 189, 248, 0.45);
    --sb-chat-name: #38bdf8;
    --sb-chat-shadow: 0 8px 32px rgba(56, 189, 248, 0.2), 0 0 0 1px rgba(56, 189, 248, 0.1);
}
:root[data-theme="light"] {
    --sb-bg: rgba(255,255,255,0.94);
    --sb-line: rgba(82,118,235,0.45);
    --sb-ink: #1e293b;
    --sb-name: #5276EB;
    --sb-shadow: 0 6px 28px rgba(15,23,42,0.22), 0 0 0 1px rgba(82,118,235,0.12);
    --sb-emote-shadow: 0 2px 6px rgba(15,23,42,0.35);
    --sb-th-bg: linear-gradient(135deg, rgba(250,245,255,0.96), rgba(243,232,255,0.98));
    --sb-th-line: rgba(124,92,231,0.5);
    --sb-th-ink: #6d28d9;
    --sb-th-name: #7c5ce7;
    --sb-th-shadow: 0 8px 32px rgba(124,92,231,0.2), 0 0 0 1px rgba(124,92,231,0.12);
    --sb-th-dot-bg: rgba(243,232,255,0.98);
    --sb-th-dot-line: rgba(124,92,231,0.4);
    --sb-th-dot-line2: rgba(124,92,231,0.3);
    --sb-chat-bg: linear-gradient(135deg, rgba(255,255,255,0.96), rgba(239,244,255,0.98));
    --sb-chat-tail: rgba(239,244,255,0.98);
    --sb-chat-line: rgba(82,118,235,0.45);
    --sb-chat-name: #5276EB;
    --sb-chat-shadow: 0 8px 32px rgba(82,118,235,0.18), 0 0 0 1px rgba(82,118,235,0.1);
}
@media (prefers-color-scheme: light) {
    :root:not([data-theme="dark"]) {
        --sb-bg: rgba(255,255,255,0.94);
        --sb-line: rgba(82,118,235,0.45);
        --sb-ink: #1e293b;
        --sb-name: #5276EB;
        --sb-shadow: 0 6px 28px rgba(15,23,42,0.22), 0 0 0 1px rgba(82,118,235,0.12);
        --sb-emote-shadow: 0 2px 6px rgba(15,23,42,0.35);
        --sb-th-bg: linear-gradient(135deg, rgba(250,245,255,0.96), rgba(243,232,255,0.98));
        --sb-th-line: rgba(124,92,231,0.5);
        --sb-th-ink: #6d28d9;
        --sb-th-name: #7c5ce7;
        --sb-th-shadow: 0 8px 32px rgba(124,92,231,0.2), 0 0 0 1px rgba(124,92,231,0.12);
        --sb-th-dot-bg: rgba(243,232,255,0.98);
        --sb-th-dot-line: rgba(124,92,231,0.4);
        --sb-th-dot-line2: rgba(124,92,231,0.3);
        --sb-chat-bg: linear-gradient(135deg, rgba(255,255,255,0.96), rgba(239,244,255,0.98));
        --sb-chat-tail: rgba(239,244,255,0.98);
        --sb-chat-line: rgba(82,118,235,0.45);
        --sb-chat-name: #5276EB;
        --sb-chat-shadow: 0 8px 32px rgba(82,118,235,0.18), 0 0 0 1px rgba(82,118,235,0.1);
    }
}
.story-bubble-overlay {
    position: absolute;
    top: 0; left: 0; width: 100%; height: 100%;
    pointer-events: none;
    overflow: hidden;
}
.story-bubble {
    position: absolute;
    transform: translate(-50%, -100%);
    background: var(--sb-bg);
    border: 1px solid var(--sb-line);
    border-radius: 14px;
    padding: 8px 14px;
    min-width: 120px;
    max-width: 280px;
    color: var(--sb-ink);
    font-size: 13px;
    line-height: 1.45;
    box-shadow: var(--sb-shadow);
    transition: opacity 0.25s ease, transform 0.2s ease-out;
    z-index: 1000;
    text-align: left;
    backdrop-filter: blur(8px);
    -webkit-backdrop-filter: blur(8px);
}
.bubble-name {
    display: block;
    font-size: 11px;
    font-weight: 700;
    color: var(--sb-name);
    margin-bottom: 3px;
    letter-spacing: 0.5px;
    text-transform: uppercase;
}
.bubble-text {
    display: block;
    word-break: break-word;
}
.bubble-tail {
    position: absolute;
    bottom: -8px;
    left: 50%;
    transform: translateX(-50%);
    width: 0; height: 0;
    border-left: 8px solid transparent;
    border-right: 8px solid transparent;
    border-top: 9px solid var(--sb-bg);
}
.story-emote {
    position: absolute;
    transform: translate(-50%, -100%);
    font-size: 32px;
    pointer-events: none;
    animation: emoteFloat 0.4s ease-out;
    z-index: 1001;
    filter: drop-shadow(var(--sb-emote-shadow));
    transition: opacity 0.3s;
}

/* --- Thought Bubble --- */
.story-bubble.thought-bubble {
    background: var(--sb-th-bg);
    border: 1.5px dashed var(--sb-th-line);
    border-radius: 20px;
    box-shadow: var(--sb-th-shadow);
    font-style: italic;
    color: var(--sb-th-ink);
}
.story-bubble.thought-bubble .bubble-name {
    color: var(--sb-th-name);
}
.story-bubble.thought-bubble .bubble-tail {
    display: none;
}
.story-bubble.thought-bubble .thought-tail-circle-1 {
    position: absolute;
    bottom: -6px;
    left: 48%;
    width: 8px;
    height: 8px;
    background: var(--sb-th-dot-bg);
    border: 1px solid var(--sb-th-dot-line);
    border-radius: 50%;
}
.story-bubble.thought-bubble .thought-tail-circle-2 {
    position: absolute;
    bottom: -12px;
    left: 45%;
    width: 5px;
    height: 5px;
    background: var(--sb-th-dot-bg);
    border: 1px solid var(--sb-th-dot-line2);
    border-radius: 50%;
}

/* --- Terminal IDE Bubble --- */
/* Intentionally theme-invariant: a terminal is content, not chrome, and
   keeps its dark ground in the light theme too. */
.story-bubble.terminal-bubble {
    background: rgba(10, 12, 16, 0.96);
    border: 1px solid rgba(52, 211, 153, 0.45);
    border-radius: 8px;
    padding: 0;
    min-width: 210px;
    max-width: 320px;
    box-shadow: 0 10px 40px rgba(0, 0, 0, 0.75), 0 0 12px rgba(52, 211, 153, 0.15);
    font-family: 'Consolas', 'Fira Code', 'Cascadia Code', 'Courier New', monospace;
    overflow: hidden;
}
.story-bubble.terminal-bubble .bubble-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    background: rgba(22, 27, 34, 0.95);
    padding: 6px 12px;
    border-bottom: 1px solid rgba(52, 211, 153, 0.2);
}
.story-bubble.terminal-bubble .terminal-dots {
    display: flex;
    gap: 5px;
}
.story-bubble.terminal-bubble .terminal-dots span {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    display: inline-block;
}
.story-bubble.terminal-bubble .terminal-dots span.dot-red { background: #ef4444; }
.story-bubble.terminal-bubble .terminal-dots span.dot-yellow { background: #eab308; }
.story-bubble.terminal-bubble .terminal-dots span.dot-green { background: #22c55e; }

.story-bubble.terminal-bubble .terminal-filename {
    font-size: 10px;
    font-weight: 600;
    color: #34d399;
    letter-spacing: 0.5px;
}
.story-bubble.terminal-bubble .bubble-content {
    padding: 10px 12px;
}
.story-bubble.terminal-bubble .bubble-name {
    color: #a7f3d0;
    margin-bottom: 5px;
}
.story-bubble.terminal-bubble .bubble-text {
    font-size: 11px;
    line-height: 1.5;
    white-space: pre;
    color: #10b981;
    text-shadow: 0 0 3px rgba(16, 185, 129, 0.35);
}
.story-bubble.terminal-bubble .bubble-tail {
    border-top-color: rgba(10, 12, 16, 0.96);
}

/* Custom terminal colors for different status */
.story-bubble.terminal-bubble.test-terminal {
    border-color: rgba(56, 189, 248, 0.45);
    box-shadow: 0 10px 40px rgba(0,0,0,0.7), 0 0 12px rgba(56, 189, 248, 0.15);
}
.story-bubble.terminal-bubble.test-terminal .bubble-header {
    border-bottom-color: rgba(56, 189, 248, 0.2);
}
.story-bubble.terminal-bubble.test-terminal .terminal-filename {
    color: #38bdf8;
}
.story-bubble.terminal-bubble.test-terminal .bubble-text {
    color: #38bdf8;
    text-shadow: 0 0 3px rgba(56, 189, 248, 0.35);
}

.story-bubble.terminal-bubble.drink-terminal {
    border-color: rgba(245, 158, 11, 0.45);
    box-shadow: 0 10px 40px rgba(0,0,0,0.7), 0 0 12px rgba(245, 158, 11, 0.15);
}
.story-bubble.terminal-bubble.drink-terminal .bubble-header {
    border-bottom-color: rgba(245, 158, 11, 0.2);
}
.story-bubble.terminal-bubble.drink-terminal .terminal-filename {
    color: #fbbf24;
}
.story-bubble.terminal-bubble.drink-terminal .bubble-text {
    color: #fbbf24;
    text-shadow: 0 0 3px rgba(251, 191, 36, 0.35);
}

.story-bubble.terminal-bubble.reboot-terminal {
    border-color: rgba(239, 68, 68, 0.45);
    box-shadow: 0 10px 40px rgba(0,0,0,0.7), 0 0 12px rgba(239, 68, 68, 0.15);
}
.story-bubble.terminal-bubble.reboot-terminal .bubble-header {
    border-bottom-color: rgba(239, 68, 68, 0.2);
}
.story-bubble.terminal-bubble.reboot-terminal .terminal-filename {
    color: #f87171;
}
.story-bubble.terminal-bubble.reboot-terminal .bubble-text {
    color: #f87171;
    text-shadow: 0 0 3px rgba(248, 113, 113, 0.35);
}

.story-bubble.terminal-bubble.unlock-terminal {
    border-color: rgba(168, 85, 247, 0.45);
    box-shadow: 0 10px 40px rgba(0,0,0,0.7), 0 0 12px rgba(168, 85, 247, 0.15);
}
.story-bubble.terminal-bubble.unlock-terminal .bubble-header {
    border-bottom-color: rgba(168, 85, 247, 0.2);
}
.story-bubble.terminal-bubble.unlock-terminal .terminal-filename {
    color: #c084fc;
}
.story-bubble.terminal-bubble.unlock-terminal .bubble-text {
    color: #c084fc;
    text-shadow: 0 0 3px rgba(192, 132, 252, 0.35);
}

.story-bubble.terminal-bubble.deploy-terminal {
    border-color: rgba(245, 158, 11, 0.5);
    box-shadow: 0 10px 40px rgba(0,0,0,0.7), 0 0 15px rgba(245, 158, 11, 0.25);
}
.story-bubble.terminal-bubble.deploy-terminal .bubble-header {
    border-bottom-color: rgba(245, 158, 11, 0.2);
}
.story-bubble.terminal-bubble.deploy-terminal .terminal-filename {
    color: #fbbf24;
}
.story-bubble.terminal-bubble.deploy-terminal .bubble-text {
    color: #fbbf24;
    text-shadow: 0 0 3px rgba(251, 191, 36, 0.35);
}

/* --- Say/Chat Bubble --- */
.story-bubble.chat-bubble {
    background: var(--sb-chat-bg);
    border: 1px solid var(--sb-chat-line);
    box-shadow: var(--sb-chat-shadow);
}
.story-bubble.chat-bubble .bubble-name {
    color: var(--sb-chat-name);
}
.story-bubble.chat-bubble .bubble-tail {
    border-top-color: var(--sb-chat-tail);
}

@keyframes emoteFloat {
    from { transform: translate(-50%, -80%) scale(0.5); opacity: 0; }
    to   { transform: translate(-50%, -100%) scale(1); opacity: 1; }
}
    `;
    document.head.appendChild(s);
})();

