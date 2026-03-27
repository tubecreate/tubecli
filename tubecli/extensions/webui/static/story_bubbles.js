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
     */
    show(character, text, duration = 3) {
        if (!this.container) return;

        // Remove existing bubble for this character
        this._removeForChar(character);

        const el = document.createElement('div');
        el.className = 'story-bubble';
        el.innerHTML = `
            <div class="bubble-content">
                <span class="bubble-name">${this._charName(character)}</span>
                <span class="bubble-text"></span>
            </div>
            <div class="bubble-tail"></div>
        `;
        this.container.appendChild(el);

        const textSpan = el.querySelector('.bubble-text');

        // Typewriter effect
        let charIdx = 0;
        const chars = [...text]; // handles emoji correctly
        const interval = setInterval(() => {
            if (charIdx < chars.length) {
                textSpan.textContent += chars[charIdx++];
            } else {
                clearInterval(interval);
            }
        }, Math.min(60, (duration * 700) / Math.max(chars.length, 1)));

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
.story-bubble-overlay {
    position: absolute;
    top: 0; left: 0; width: 100%; height: 100%;
    pointer-events: none;
    overflow: hidden;
}
.story-bubble {
    position: absolute;
    transform: translate(-50%, -100%);
    background: rgba(15,17,30,0.92);
    border: 1px solid rgba(34,211,238,0.4);
    border-radius: 14px;
    padding: 8px 14px;
    min-width: 120px;
    max-width: 260px;
    color: #f0f4ff;
    font-size: 13px;
    line-height: 1.45;
    box-shadow: 0 4px 24px rgba(0,0,0,0.5), 0 0 0 1px rgba(34,211,238,0.1);
    transition: opacity 0.25s ease;
    z-index: 1000;
    text-align: left;
    backdrop-filter: blur(8px);
    -webkit-backdrop-filter: blur(8px);
}
.bubble-name {
    display: block;
    font-size: 11px;
    font-weight: 700;
    color: #22d3ee;
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
    border-top: 9px solid rgba(15,17,30,0.92);
}
.story-emote {
    position: absolute;
    transform: translate(-50%, -100%);
    font-size: 32px;
    pointer-events: none;
    animation: emoteFloat 0.4s ease-out;
    z-index: 1001;
    filter: drop-shadow(0 2px 6px rgba(0,0,0,0.6));
    transition: opacity 0.3s;
}
@keyframes emoteFloat {
    from { transform: translate(-50%, -80%) scale(0.5); opacity: 0; }
    to   { transform: translate(-50%, -100%) scale(1); opacity: 1; }
}
    `;
    document.head.appendChild(s);
})();
