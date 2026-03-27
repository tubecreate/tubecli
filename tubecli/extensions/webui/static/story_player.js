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
                if (typeof target === 'string') target = this.waypointMap[target] || null;
                if (ch && target) this._walkTo(ch, target.x, target.z);
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
    }

    _setSitState(ch) {
        ch.state = 'story_sit';
        ch.storyStateEnd = Infinity;
    }

    _setStandState(ch) {
        if (ch.state === 'story_sit') {
            ch.state = 'working';
            ch.stateTimer = 2;
        }
    }
}

// ── Story Animation Updates (integrated with teams3d.js animate loop) ──

/**
 * Call this from the animate3d() loop in teams3d.js
 * OR call storyAnimateUpdate(dt, t) in your own RAF loop.
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
                    ac.group.rotation.y = Math.atan2(dx, dz);
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

            case 'story_idle':
                // Stand in place, slight bob
                p.y = ac.homeY + Math.sin(t * 0.8 + ac.bobPhase) * 0.02;
                break;

            case 'story_chat': {
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
                // Hold book up, head tilted down
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
                // Right arm extended, writing
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
                // Arm extended forward for handshake
                ac.limbs.armR.rotation.x = -Math.PI / 2;
                ac.limbs.armR.rotation.z = 0;
                ac.group.position.y = ac.homeY + Math.sin(t * 6) * 0.04;
                if (player.currentTime >= ac.storyStateEnd) {
                    resetLimbs(ac); ac.state = 'story_idle';
                }
                break;
            }

            case 'story_cheer': {
                // Both arms up
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
                // Hand on chin
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
                // Squat effect (lower body)
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

// Global story player instance (used by story.html)
const storyPlayer = new StoryPlayer();
