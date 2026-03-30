/**
 * story_player.js — Core engine for 3D Story Script playback
 * Reads a JSON script and controls agentCharacters over timeline.
 * 
 * Depends on: teams3d.js (agentCharacters, animate3d global vars)
 */

class StoryPlayer {
    constructor() {
        this.script = null;
        this.isPlaying = false;
        this.currentTime = 0;
        this.speed = 1.0;
        this.duration = 0;
        this.dispatchedEvents = new Set(); // event indices already fired
        this.actorMap = {};   // key -> agentCharacter ref
        this.waypointMap = {}; // id -> {x, z}
        this._raf = null;
        this._lastTs = null;
        this.onTimeUpdate = null; // callback(currentTime, duration)
        this.onFinish = null;     // callback()
        this.onEventFired = null; // callback(event)
    }

    // ── Load script ────────────────────────────────────────────────────
    load(script) {
        this.script = script;
        this.currentTime = 0;
        this.dispatchedEvents = new Set();
        this.isPlaying = false;
        this._lastTs = null;
        this._waypointOccupants = {};

        // Build waypoint map
        this.waypointMap = {};
        (script.waypoints || []).forEach(wp => {
            this.waypointMap[wp.id] = { x: wp.x, z: wp.z, label: wp.label };
        });

        // Compute total duration
        const times = (script.timeline || []).map(e => (e.time || 0) + (e.duration || 2));
        this.duration = times.length > 0 ? Math.max(...times) + 3 : 30;

        // Re-build actorMap from agentCharacters (global from teams3d.js)
        this._rebuildActorMap();

        if (this.onTimeUpdate) this.onTimeUpdate(0, this.duration);
    }

    _rebuildActorMap() {
        this.actorMap = {};
        if (!this.script) return;
        (this.script.actors || []).forEach(actor => {
            // Find matching agentCharacter by agent_id
            const ch = (typeof agentCharacters !== 'undefined' ? agentCharacters : [])
                .find(c => c.agentId === actor.agent_id);
            if (ch) this.actorMap[actor.key] = ch;
        });
    }

    // ── Playback controls ──────────────────────────────────────────────
    play() {
        if (!this.script) return;
        if (this.currentTime >= this.duration) {
            this.seek(0);
        }
        this.isPlaying = true;
        this._lastTs = null;
        this._tick();
    }

    pause() {
        this.isPlaying = false;
        if (this._raf) { cancelAnimationFrame(this._raf); this._raf = null; }
    }

    stop() {
        this.pause();
        this.seek(0);
        this._returnAllToDesk();
        this._waypointOccupants = {};
        if (typeof storyBubbles !== 'undefined') storyBubbles.clearAll();
    }

    seek(timeSeconds) {
        this.currentTime = Math.max(0, Math.min(timeSeconds, this.duration));
        // Re-dispatch only events before currentTime
        this.dispatchedEvents = new Set();
        (this.script?.timeline || []).forEach((evt, idx) => {
            if (evt.time < this.currentTime) this.dispatchedEvents.add(idx);
        });
        if (this.onTimeUpdate) this.onTimeUpdate(this.currentTime, this.duration);
    }

    setSpeed(x) { this.speed = x; }

    // ── Main tick ──────────────────────────────────────────────────────
    _tick() {
        if (!this.isPlaying) return;
        this._raf = requestAnimationFrame((ts) => {
            if (this._lastTs === null) this._lastTs = ts;
            const dt = ((ts - this._lastTs) / 1000) * this.speed;
            this._lastTs = ts;

            this.currentTime += dt;

            // Dispatch new events
            (this.script?.timeline || []).forEach((evt, idx) => {
                if (!this.dispatchedEvents.has(idx) && evt.time <= this.currentTime) {
                    this.dispatchedEvents.add(idx);
                    this._fireEvent(evt);
                }
            });

            if (this.onTimeUpdate) this.onTimeUpdate(this.currentTime, this.duration);

            if (this.currentTime >= this.duration) {
                this.isPlaying = false;
                this._returnAllToDesk();
                if (this.onFinish) this.onFinish();
                return;
            }

            this._tick();
        });
    }

    // ── Fire a single event ────────────────────────────────────────────
    _fireEvent(evt) {
        const ch = this.actorMap[evt.actor];
        if (this.onEventFired) this.onEventFired(evt);

        switch (evt.action) {
            case 'walk_to': {
                let target = evt.target;
                const waypointId = (typeof target === 'string') ? target : null;
                if (typeof target === 'string') target = this.waypointMap[target] || null;
                if (ch && target) {
                    // Apply offset so multiple characters don't stack
                    const offset = this._getFormationOffset(waypointId || `${target.x}_${target.z}`, ch);
                    this._walkTo(ch, target.x + offset.x, target.z + offset.z);
                }
                break;
            }
            case 'return_desk':
                if (ch) this._returnToDesk(ch);
                break;
            case 'chat':
                if (ch) {
                    const duration = evt.duration || 3;
                    if (typeof storyBubbles !== 'undefined') {
                        storyBubbles.show(ch, evt.dialog || '', duration);
                    }
                    this._setChatState(ch, duration);
                }
                break;
            case 'animate':
                if (ch) this._triggerAnimation(ch, evt.anim || 'think');
                break;
            case 'sit':
                if (ch) this._setSitState(ch);
                break;
            case 'stand':
                if (ch) this._setStandState(ch);
                break;
            case 'emote':
                if (ch && typeof storyBubbles !== 'undefined') {
                    storyBubbles.showEmote(ch, evt.emoji || '✨', 2);
                }
                break;
            default:
                break;
        }
    }

    // ── Action implementations ─────────────────────────────────────────

    _walkTo(ch, tx, tz) {
        ch.state = 'story_walking';
        ch.storyTarget = { x: tx, z: tz };
        ch.stateTimer = 0;
        // Face target will be set dynamically during walk
    }

    _returnToDesk(ch) {
        ch.state = 'story_walking';
        ch.storyTarget = { x: ch.homePos.x, z: ch.homePos.z };
        ch.stateTimer = 0;
        ch._returnAfterWalk = true;
    }

    _returnAllToDesk() {
        Object.values(this.actorMap).forEach(ch => this._returnToDesk(ch));
    }

    _setChatState(ch, duration) {
        ch.state = 'story_chat';
        ch.storyStateEnd = this.currentTime + duration;
        // Face nearest other actor that's also chatting or nearby
        ch.storyFaceTarget = this._findNearestOtherActor(ch);
    }

    _triggerAnimation(ch, anim) {
        const animMap = {
            read:         'story_read',
            write_board:  'story_write',
            shake_hand:   'story_shake',
            cheer:        'story_cheer',
            think:        'story_think',
        };
        ch.state = animMap[anim] || 'story_think';
        ch.storyStateEnd = this.currentTime + 4;

        // Set face target based on animation type
        if (anim === 'write_board') {
            // Face the whiteboard waypoint
            const board = this.waypointMap['board'] || this.waypointMap['whiteboard'];
            if (board) ch.storyFaceTarget = { x: board.x, z: board.z };
        } else if (anim === 'read') {
            // Face nearest bookshelf or keep current face
            const shelf = this.waypointMap['bookshelf'];
            if (shelf) ch.storyFaceTarget = { x: shelf.x, z: shelf.z };
        } else if (anim === 'shake_hand') {
            // Face nearest other actor
            ch.storyFaceTarget = this._findNearestOtherActor(ch);
        } else {
            // think, cheer etc. — face nearest actor or keep
            ch.storyFaceTarget = this._findNearestOtherActor(ch);
        }
    }

    _setSitState(ch) {
        ch.state = 'story_sit';
        ch.storyStateEnd = Infinity;
        // Face center of room
        ch.storyFaceTarget = { x: 0, z: 0 };
    }

    _setStandState(ch) {
        if (ch.state === 'story_sit') {
            ch.state = 'working';
            ch.stateTimer = 2;
        }
    }

    // ── Helpers ────────────────────────────────────────────────────────

    _findNearestOtherActor(ch) {
        const chars = (typeof agentCharacters !== 'undefined') ? agentCharacters : [];
        let nearest = null;
        let minDist = Infinity;
        const px = ch.group.position.x;
        const pz = ch.group.position.z;
        for (const other of chars) {
            if (other === ch || !other.hasAgent) continue;
            const dx = other.group.position.x - px;
            const dz = other.group.position.z - pz;
            const dist = Math.sqrt(dx * dx + dz * dz);
            if (dist < minDist) {
                minDist = dist;
                nearest = { x: other.group.position.x, z: other.group.position.z };
            }
        }
        return nearest;
    }

    /**
     * Get a circular offset for a character going to a shared waypoint.
     * First character goes to center, others spread in a circle around it.
     * Radius grows slightly as more characters join.
     */
    _getFormationOffset(waypointKey, ch) {
        if (!this._waypointOccupants) this._waypointOccupants = {};

        if (!this._waypointOccupants[waypointKey]) {
            this._waypointOccupants[waypointKey] = [];
        }

        const occupants = this._waypointOccupants[waypointKey];

        // Remove this character from any previous waypoint
        for (const key in this._waypointOccupants) {
            this._waypointOccupants[key] = this._waypointOccupants[key].filter(c => c !== ch);
            if (this._waypointOccupants[key].length === 0 && key !== waypointKey) {
                delete this._waypointOccupants[key];
            }
        }

        // Add to this waypoint
        if (!occupants.includes(ch)) occupants.push(ch);

        const idx = occupants.indexOf(ch);
        const total = occupants.length;

        // First character: no offset (center)
        if (total <= 1) return { x: 0, z: 0 };

        // Circle formation: spread around the center
        const RADIUS = 0.6 + Math.floor(total / 6) * 0.4; // grow radius for large groups
        const angle = (idx / total) * Math.PI * 2;
        return {
            x: Math.cos(angle) * RADIUS,
            z: Math.sin(angle) * RADIUS,
        };
    }
}

// ── Story Animation Updates (integrated with teams3d.js animate loop) ──

/**
 * Smoothly rotate character to face target position.
 * Uses lerp on Y rotation for natural-looking turns.
 */
function _faceTowards(ac, targetX, targetZ, dt, lerpSpeed) {
    const dx = targetX - ac.group.position.x;
    const dz = targetZ - ac.group.position.z;
    if (Math.abs(dx) < 0.01 && Math.abs(dz) < 0.01) return; // too close, skip
    const targetAngle = Math.atan2(dx, dz);
    // Lerp rotation (shortest path around circle)
    let diff = targetAngle - ac.group.rotation.y;
    // Normalize to [-PI, PI]
    while (diff > Math.PI) diff -= Math.PI * 2;
    while (diff < -Math.PI) diff += Math.PI * 2;
    ac.group.rotation.y += diff * Math.min(1, (lerpSpeed || 5) * dt);
}

/**
 * Call this from the animate3d() loop in teams3d.js
 */
function storyAnimateUpdate(dt, t, player) {
    if (!player || !player.script) return;

    const chars = (typeof agentCharacters !== 'undefined') ? agentCharacters : [];
    chars.forEach(ac => {
        if (!ac.hasAgent) return;
        const p = ac.group.position;

        switch (ac.state) {
            case 'story_walking': {
                const tgt = ac.storyTarget;
                if (!tgt) break;
                const dx = tgt.x - p.x;
                const dz = tgt.z - p.z;
                const dist = Math.sqrt(dx*dx + dz*dz);
                if (dist > 0.15) {
                    p.x += dx * ac.walkSpeed * 60 * dt;
                    p.z += dz * ac.walkSpeed * 60 * dt;
                    // Smooth face towards walk target
                    _faceTowards(ac, tgt.x, tgt.z, dt, 8);
                    // Walk animation
                    ac.limbs.legL.rotation.x = Math.sin(t * 8) * 0.5;
                    ac.limbs.legR.rotation.x = Math.sin(t * 8 + Math.PI) * 0.5;
                    ac.limbs.armL.rotation.x = Math.sin(t * 8 + Math.PI) * 0.4;
                    ac.limbs.armR.rotation.x = Math.sin(t * 8) * 0.4;
                    ac.limbs.armL.rotation.z = 0;
                    ac.limbs.armR.rotation.z = 0;
                    p.y = ac.homeY + Math.abs(Math.sin(t * 8)) * 0.06;
                } else {
                    p.set(tgt.x, ac.homeY, tgt.z);
                    resetLimbs(ac);
                    if (ac._returnAfterWalk) {
                        ac._returnAfterWalk = false;
                        ac.state = 'working';
                        ac.stateTimer = 5;
                    } else {
                        ac.state = 'story_idle';
                    }
                }
                break;
            }

            case 'story_idle': {
                // Stand in place, slight bob + face nearest actor
                p.y = ac.homeY + Math.sin(t * 0.8 + ac.bobPhase) * 0.02;
                // Gently look around — find nearest other actor
                const nearIdle = _findNearestInScene(ac);
                if (nearIdle) _faceTowards(ac, nearIdle.x, nearIdle.z, dt, 2);
                break;
            }

            case 'story_chat': {
                // Face the chat partner (dynamically update)
                const chatTarget = ac.storyFaceTarget || _findNearestInScene(ac);
                if (chatTarget) _faceTowards(ac, chatTarget.x, chatTarget.z, dt, 6);
                // Wave arm while talking
                ac.limbs.armR.rotation.x = Math.sin(t * 3) * 0.5 - 0.4;
                ac.limbs.armR.rotation.z = -0.35;
                ac.limbs.armL.rotation.x = -0.15;
                ac.limbs.head.rotation.x = Math.sin(t * 2.5) * 0.12;
                ac.limbs.head.rotation.y = Math.sin(t * 0.8) * 0.15;
                if (player.currentTime >= ac.storyStateEnd) {
                    resetLimbs(ac);
                    ac.state = 'story_idle';
                }
                break;
            }

            case 'story_read': {
                // Face bookshelf/object
                if (ac.storyFaceTarget) _faceTowards(ac, ac.storyFaceTarget.x, ac.storyFaceTarget.z, dt, 4);
                ac.limbs.armL.rotation.x = -1.2;
                ac.limbs.armR.rotation.x = -1.0;
                ac.limbs.armL.rotation.z = 0.3;
                ac.limbs.armR.rotation.z = -0.3;
                ac.limbs.head.rotation.x = 0.4;
                if (player.currentTime >= ac.storyStateEnd) {
                    resetLimbs(ac); ac.state = 'story_idle';
                }
                break;
            }

            case 'story_write': {
                // Face the whiteboard
                if (ac.storyFaceTarget) _faceTowards(ac, ac.storyFaceTarget.x, ac.storyFaceTarget.z, dt, 4);
                ac.limbs.armR.rotation.x = -0.9 + Math.sin(t * 4 + ac.bobPhase) * 0.15;
                ac.limbs.armR.rotation.z = -0.2;
                ac.limbs.armL.rotation.x = -0.3;
                ac.limbs.head.rotation.x = -0.1;
                if (player.currentTime >= ac.storyStateEnd) {
                    resetLimbs(ac); ac.state = 'story_idle';
                }
                break;
            }

            case 'story_shake': {
                // Face the handshake partner
                const shakePartner = ac.storyFaceTarget || _findNearestInScene(ac);
                if (shakePartner) _faceTowards(ac, shakePartner.x, shakePartner.z, dt, 8);
                ac.limbs.armR.rotation.x = -Math.PI / 2;
                ac.limbs.armR.rotation.z = 0;
                ac.group.position.y = ac.homeY + Math.sin(t * 6) * 0.04;
                if (player.currentTime >= ac.storyStateEnd) {
                    resetLimbs(ac); ac.state = 'story_idle';
                }
                break;
            }

            case 'story_cheer': {
                // Face nearest actor or center
                const cheerTarget = ac.storyFaceTarget || _findNearestInScene(ac);
                if (cheerTarget) _faceTowards(ac, cheerTarget.x, cheerTarget.z, dt, 3);
                ac.limbs.armL.rotation.x = -2.2 + Math.sin(t * 4) * 0.2;
                ac.limbs.armR.rotation.x = -2.2 + Math.sin(t * 4 + 0.5) * 0.2;
                ac.limbs.armL.rotation.z = 0.4;
                ac.limbs.armR.rotation.z = -0.4;
                ac.group.position.y = ac.homeY + Math.abs(Math.sin(t * 4)) * 0.1;
                if (player.currentTime >= ac.storyStateEnd) {
                    resetLimbs(ac); ac.state = 'story_idle';
                }
                break;
            }

            case 'story_think': {
                // Gentle head rotation + face nearest actor
                const thinkTarget = ac.storyFaceTarget || _findNearestInScene(ac);
                if (thinkTarget) _faceTowards(ac, thinkTarget.x, thinkTarget.z, dt, 2);
                ac.limbs.armR.rotation.x = -0.6;
                ac.limbs.armR.rotation.z = -0.5;
                ac.limbs.head.rotation.y = Math.sin(t * 0.5) * 0.2;
                ac.limbs.head.rotation.x = -0.1;
                if (player.currentTime >= ac.storyStateEnd) {
                    resetLimbs(ac); ac.state = 'story_idle';
                }
                break;
            }

            case 'story_sit': {
                // Face center or stored target
                if (ac.storyFaceTarget) _faceTowards(ac, ac.storyFaceTarget.x, ac.storyFaceTarget.z, dt, 2);
                ac.limbs.legL.rotation.x = -0.7;
                ac.limbs.legR.rotation.x = -0.7;
                p.y = ac.homeY - 0.15;
                break;
            }

            default:
                break;
        }
    });
}

/** Helper: find nearest other agent character in scene */
function _findNearestInScene(ac) {
    const chars = (typeof agentCharacters !== 'undefined') ? agentCharacters : [];
    let nearest = null;
    let minDist = Infinity;
    for (const other of chars) {
        if (other === ac || !other.hasAgent) continue;
        const dx = other.group.position.x - ac.group.position.x;
        const dz = other.group.position.z - ac.group.position.z;
        const dist = dx * dx + dz * dz;
        if (dist < minDist) {
            minDist = dist;
            nearest = { x: other.group.position.x, z: other.group.position.z };
        }
    }
    return nearest;
}

// Global story player instance (used by story.html)
const storyPlayer = new StoryPlayer();

