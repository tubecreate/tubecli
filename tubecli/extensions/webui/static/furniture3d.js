/**
 * furniture3d.js — Shared HQ composite furniture builders for 3D Studio
 * Used by both studio.html (editor) and teams3d.js (viewer)
 * Requires THREE.js to be loaded before this script.
 */

const _fm = (c, opts = {}) => new THREE.MeshStandardMaterial({ color: c, roughness: opts.r || 0.5, metalness: opts.m || 0.1, ...opts });

// ── Desk (modern / wood) ─────────────────────────────────
function buildHQDesk(g, def) {
    const wood = _fm(def.color || '#f0ebe4');
    const metal = _fm('#444444', { r: 0.3, m: 0.6 });
    const accent = _fm('#333333', { r: 0.4, m: 0.3 });
    // Table top
    const top = new THREE.Mesh(new THREE.BoxGeometry(1.6, 0.06, 0.85), wood);
    top.position.y = 0.72; top.castShadow = true; top.receiveShadow = true; g.add(top);
    // Edge trim
    const trim = new THREE.Mesh(new THREE.BoxGeometry(1.62, 0.02, 0.02), accent);
    trim.position.set(0, 0.74, 0.42); g.add(trim);
    // 4 Metal legs with foot pads
    [[-0.72, -0.36], [-0.72, 0.36], [0.72, -0.36], [0.72, 0.36]].forEach(([lx, lz]) => {
        const leg = new THREE.Mesh(new THREE.CylinderGeometry(0.025, 0.025, 0.72, 6), metal);
        leg.position.set(lx, 0.36, lz); leg.castShadow = true; g.add(leg);
        const pad = new THREE.Mesh(new THREE.CylinderGeometry(0.04, 0.04, 0.02, 6), metal);
        pad.position.set(lx, 0.01, lz); g.add(pad);
    });
    // Drawer unit (right side)
    const drawer = _fm('#ddd5c8', { r: 0.6 });
    const dBox = new THREE.Mesh(new THREE.BoxGeometry(0.45, 0.3, 0.6), drawer);
    dBox.position.set(0.5, 0.55, 0); dBox.castShadow = true; g.add(dBox);
    // Drawer handles
    for (let dy of [0.48, 0.6]) {
        const handle = new THREE.Mesh(new THREE.BoxGeometry(0.12, 0.015, 0.02), metal);
        handle.position.set(0.5, dy, 0.31); g.add(handle);
    }
    // Cross support bar
    const bar = new THREE.Mesh(new THREE.BoxGeometry(1.3, 0.03, 0.03), metal);
    bar.position.set(0, 0.15, 0); g.add(bar);
}

// ── Round Table ──────────────────────────────────────────
function buildHQRoundTable(g, def) {
    const wood = _fm(def.color || '#d4c8b0');
    const metal = _fm('#555', { r: 0.3, m: 0.6 });
    // Table top (cylinder)
    const top = new THREE.Mesh(new THREE.CylinderGeometry(0.6, 0.6, 0.05, 16), wood);
    top.position.y = 0.72; top.castShadow = true; top.receiveShadow = true; g.add(top);
    // Edge rim
    const rim = new THREE.Mesh(new THREE.CylinderGeometry(0.62, 0.62, 0.02, 16), _fm('#b8a890'));
    rim.position.y = 0.73; g.add(rim);
    // Central pillar
    const pillar = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.08, 0.65, 8), metal);
    pillar.position.y = 0.37; g.add(pillar);
    // Base plate
    const base = new THREE.Mesh(new THREE.CylinderGeometry(0.3, 0.35, 0.04, 12), metal);
    base.position.y = 0.02; g.add(base);
    // 3 feet
    for (let i = 0; i < 3; i++) {
        const angle = (i / 3) * Math.PI * 2;
        const foot = new THREE.Mesh(new THREE.BoxGeometry(0.25, 0.025, 0.06), metal);
        foot.position.set(Math.sin(angle) * 0.2, 0.013, Math.cos(angle) * 0.2);
        foot.rotation.y = -angle;
        g.add(foot);
    }
}

// ── Chair (office swivel) ────────────────────────────────
function buildHQChair(g, def) {
    const fabric = _fm(def.color || '#2d3250');
    const metal = _fm('#555555', { r: 0.3, m: 0.7 });
    const darkFab = _fm('#1a1e35');
    // Seat cushion
    const seat = new THREE.Mesh(new THREE.BoxGeometry(0.48, 0.07, 0.46), fabric);
    seat.position.y = 0.46; seat.castShadow = true; g.add(seat);
    // Backrest
    const back = new THREE.Mesh(new THREE.BoxGeometry(0.46, 0.5, 0.05), fabric);
    back.position.set(0, 0.74, -0.22); g.add(back);
    // Backrest top curve
    const topCurve = new THREE.Mesh(new THREE.BoxGeometry(0.46, 0.04, 0.06), darkFab);
    topCurve.position.set(0, 0.99, -0.22); g.add(topCurve);
    // Armrests (both sides)
    for (let side of [-0.26, 0.26]) {
        const arm = new THREE.Mesh(new THREE.BoxGeometry(0.04, 0.03, 0.3), metal);
        arm.position.set(side, 0.56, -0.04); g.add(arm);
        const armV = new THREE.Mesh(new THREE.CylinderGeometry(0.015, 0.015, 0.12, 6), metal);
        armV.position.set(side, 0.50, 0.1); g.add(armV);
    }
    // Central pillar
    const pillar = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.04, 0.35, 8), metal);
    pillar.position.set(0, 0.25, 0); g.add(pillar);
    // Star base (5-point) with wheels
    for (let i = 0; i < 5; i++) {
        const angle = (i / 5) * Math.PI * 2;
        const spoke = new THREE.Mesh(new THREE.BoxGeometry(0.28, 0.025, 0.035), metal);
        spoke.position.set(Math.sin(angle) * 0.13, 0.06, Math.cos(angle) * 0.13);
        spoke.rotation.y = -angle; g.add(spoke);
        const wheel = new THREE.Mesh(new THREE.SphereGeometry(0.025, 6, 4), _fm('#222'));
        wheel.position.set(Math.sin(angle) * 0.26, 0.025, Math.cos(angle) * 0.26);
        g.add(wheel);
    }
}

// ── Sofa ─────────────────────────────────────────────────
function buildHQSofa(g, def) {
    const fabric = _fm(def.color || '#3d4a8a', { r: 0.7 });
    const darkFab = _fm('#2a3570', { r: 0.7 });
    const legM = _fm('#333', { m: 0.5 });
    // Base frame
    const base = new THREE.Mesh(new THREE.BoxGeometry(1.8, 0.12, 0.75), darkFab);
    base.position.y = 0.18; base.castShadow = true; g.add(base);
    // Seat cushions (2 pieces)
    for (let cx of [-0.42, 0.42]) {
        const cush = new THREE.Mesh(new THREE.BoxGeometry(0.82, 0.12, 0.65), fabric);
        cush.position.set(cx, 0.3, 0.02); cush.castShadow = true; g.add(cush);
    }
    // Backrest
    const backR = new THREE.Mesh(new THREE.BoxGeometry(1.7, 0.4, 0.12), fabric);
    backR.position.set(0, 0.5, -0.32); backR.castShadow = true; g.add(backR);
    // Armrests
    for (let side of [-0.88, 0.88]) {
        const arm = new THREE.Mesh(new THREE.BoxGeometry(0.1, 0.25, 0.7), darkFab);
        arm.position.set(side, 0.35, 0); arm.castShadow = true; g.add(arm);
    }
    // Legs
    [[-0.82, -0.3], [-0.82, 0.3], [0.82, -0.3], [0.82, 0.3]].forEach(([lx, lz]) => {
        const leg = new THREE.Mesh(new THREE.CylinderGeometry(0.025, 0.02, 0.12, 6), legM);
        leg.position.set(lx, 0.06, lz); g.add(leg);
    });
}

// ── Bookshelf ────────────────────────────────────────────
function buildHQBookshelf(g, def) {
    const wood = _fm(def.color || '#6b4226', { r: 0.7 });
    const darkW = _fm('#4a2e18', { r: 0.7 });
    // Back panel
    const back = new THREE.Mesh(new THREE.BoxGeometry(1.2, 2.0, 0.04), darkW);
    back.position.set(0, 1.0, -0.18); back.castShadow = true; g.add(back);
    // Side panels
    for (let sx of [-0.6, 0.6]) {
        const side = new THREE.Mesh(new THREE.BoxGeometry(0.04, 2.0, 0.4), wood);
        side.position.set(sx, 1.0, 0); side.castShadow = true; g.add(side);
    }
    // Shelves (5 levels)
    for (let sy of [0.02, 0.5, 1.0, 1.5, 1.98]) {
        const shelf = new THREE.Mesh(new THREE.BoxGeometry(1.16, 0.04, 0.38), wood);
        shelf.position.set(0, sy, 0); g.add(shelf);
    }
    // Books (random colors)
    const bookColors = [0xc0392b, 0x2980b9, 0x27ae60, 0xf39c12, 0x8e44ad, 0xe74c3c, 0x2c3e50, 0xd35400];
    for (let shelfY of [0.07, 0.55, 1.05, 1.55]) {
        const numBooks = 4 + Math.floor(Math.random() * 3);
        let bx = -0.48;
        for (let b = 0; b < numBooks && bx < 0.48; b++) {
            const bw = 0.06 + Math.random() * 0.08;
            const bh = 0.28 + Math.random() * 0.15;
            const bc = bookColors[Math.floor(Math.random() * bookColors.length)];
            const book = new THREE.Mesh(new THREE.BoxGeometry(bw, bh, 0.25), _fm(bc, { r: 0.8 }));
            book.position.set(bx + bw / 2, shelfY + bh / 2 + 0.02, 0.02);
            g.add(book);
            bx += bw + 0.01;
        }
    }
}

// ── Monitor ──────────────────────────────────────────────
function buildHQMonitor(g, def) {
    const black = _fm('#1a1a2e', { r: 0.2, m: 0.4 });
    // Screen panel
    const panel = new THREE.Mesh(new THREE.BoxGeometry(0.7, 0.48, 0.03), black);
    panel.position.set(0, 1.05, 0); panel.castShadow = true; g.add(panel);
    // Screen glow
    const scr = new THREE.Mesh(new THREE.PlaneGeometry(0.62, 0.38),
        new THREE.MeshBasicMaterial({ color: 0x1a3a5a, transparent: true, opacity: 0.6 }));
    scr.position.set(0, 1.05, 0.016); g.add(scr);
    // Bezel top
    const bTop = new THREE.Mesh(new THREE.BoxGeometry(0.72, 0.015, 0.035), _fm('#111'));
    bTop.position.set(0, 1.29, 0); g.add(bTop);
    // Stand neck + base
    const neck = new THREE.Mesh(new THREE.BoxGeometry(0.04, 0.22, 0.04), _fm('#333', { m: 0.5 }));
    neck.position.set(0, 0.89, 0); g.add(neck);
    const standBase = new THREE.Mesh(new THREE.BoxGeometry(0.25, 0.02, 0.15), _fm('#333', { m: 0.5 }));
    standBase.position.set(0, 0.77, 0.02); g.add(standBase);
    // Keyboard
    const kb = new THREE.Mesh(new THREE.BoxGeometry(0.4, 0.015, 0.14), _fm('#2a2a2a'));
    kb.position.set(0, 0.76, 0.3); g.add(kb);
    const keys = new THREE.Mesh(new THREE.PlaneGeometry(0.34, 0.1),
        new THREE.MeshBasicMaterial({ color: 0x444444, transparent: true, opacity: 0.5 }));
    keys.position.set(0, 0.77, 0.3); keys.rotation.x = -Math.PI / 2; g.add(keys);
    // Mouse
    const mouse = new THREE.Mesh(new THREE.BoxGeometry(0.05, 0.018, 0.08), _fm('#222'));
    mouse.position.set(0.3, 0.77, 0.32); g.add(mouse);
}

// ── Plant Pot ────────────────────────────────────────────
function buildHQPlant(g, def) {
    const potColor = _fm('#8B4513', { r: 0.8 });
    const soilColor = _fm('#3e2723', { r: 0.9 });
    // Pot (tapered)
    const pot = new THREE.Mesh(new THREE.CylinderGeometry(0.16, 0.12, 0.22, 8), potColor);
    pot.position.y = 0.11; pot.castShadow = true; g.add(pot);
    // Pot rim
    const rim = new THREE.Mesh(new THREE.CylinderGeometry(0.17, 0.17, 0.025, 8), potColor);
    rim.position.y = 0.22; g.add(rim);
    // Soil
    const soil = new THREE.Mesh(new THREE.CylinderGeometry(0.14, 0.14, 0.03, 8), soilColor);
    soil.position.y = 0.2; g.add(soil);
    // Foliage (stacked spheres)
    const leafColors = [0x27ae60, 0x2ecc71, 0x1abc9c, 0x16a085];
    [[0, 0.45, 0, 0.14], [0.06, 0.55, 0.04, 0.11], [-0.05, 0.52, -0.04, 0.10],
     [0.03, 0.62, -0.02, 0.08], [-0.03, 0.58, 0.05, 0.09]].forEach(([x, y, z, r], i) => {
        const leaf = new THREE.Mesh(new THREE.SphereGeometry(r, 6, 5), _fm(leafColors[i % leafColors.length], { r: 0.8 }));
        leaf.position.set(x, y, z); leaf.castShadow = true; g.add(leaf);
    });
    // Stem
    const stem = new THREE.Mesh(new THREE.CylinderGeometry(0.012, 0.015, 0.25, 4), _fm('#2d5016'));
    stem.position.set(0, 0.32, 0); g.add(stem);
}

// ── Cabinet ──────────────────────────────────────────────
function buildHQCabinet(g, def) {
    const metal = _fm(def.color || '#8a8a8a', { r: 0.4, m: 0.3 });
    const dark = _fm('#666', { r: 0.4, m: 0.3 });
    // Main body
    const body = new THREE.Mesh(new THREE.BoxGeometry(0.58, 1.18, 0.48), metal);
    body.position.y = 0.59; body.castShadow = true; g.add(body);
    // Drawer lines (3 drawers)
    for (let dy of [0.22, 0.58, 0.94]) {
        const line = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.01, 0.01), dark);
        line.position.set(0, dy, 0.245); g.add(line);
        const handle = new THREE.Mesh(new THREE.BoxGeometry(0.1, 0.015, 0.02), _fm('#444', { m: 0.6 }));
        handle.position.set(0, dy + 0.15, 0.25); g.add(handle);
    }
}

// ── Whiteboard ───────────────────────────────────────────
function buildHQWhiteboard(g, def) {
    const frame = _fm('#666', { r: 0.3, m: 0.4 });
    const white = _fm('#f0f0f0', { r: 0.3 });
    // Board surface
    const board = new THREE.Mesh(new THREE.BoxGeometry(1.5, 1.0, 0.03), white);
    board.position.y = 1.5; board.castShadow = true; g.add(board);
    // Frame edges
    const fTop = new THREE.Mesh(new THREE.BoxGeometry(1.56, 0.04, 0.05), frame);
    fTop.position.set(0, 2.01, 0); g.add(fTop);
    const fBot = fTop.clone(); fBot.position.y = 0.99; g.add(fBot);
    const fLeft = new THREE.Mesh(new THREE.BoxGeometry(0.04, 1.06, 0.05), frame);
    fLeft.position.set(-0.76, 1.5, 0); g.add(fLeft);
    const fRight = fLeft.clone(); fRight.position.x = 0.76; g.add(fRight);
    // Marker tray
    const tray = new THREE.Mesh(new THREE.BoxGeometry(0.6, 0.03, 0.06), frame);
    tray.position.set(0, 0.97, 0.04); g.add(tray);
    // Markers (3 colored)
    [[-0.12, 0xff3333], [0, 0x3333ff], [0.12, 0x33cc33]].forEach(([mx, mc]) => {
        const marker = new THREE.Mesh(new THREE.CylinderGeometry(0.012, 0.012, 0.1, 6), _fm(mc));
        marker.position.set(mx, 0.99, 0.04); marker.rotation.z = Math.PI / 2; g.add(marker);
    });
}

// ── Lantern ──────────────────────────────────────────────
function buildHQLantern(g, def) {
    const red = _fm(def.color || '#cc3333', { r: 0.6 });
    // Lantern body (sphere)
    const body = new THREE.Mesh(new THREE.SphereGeometry(0.18, 8, 6), red);
    body.position.y = 2.5; body.castShadow = true; g.add(body);
    // Top cap
    const cap = new THREE.Mesh(new THREE.CylinderGeometry(0.08, 0.14, 0.06, 8), _fm('#8B0000'));
    cap.position.y = 2.68; g.add(cap);
    // Bottom cap
    const bCap = cap.clone(); bCap.position.y = 2.32; g.add(bCap);
    // String
    const string = new THREE.Mesh(new THREE.CylinderGeometry(0.008, 0.008, 0.3, 4), _fm('#333'));
    string.position.y = 2.84; g.add(string);
    // glow light
    const glow = new THREE.PointLight(0xff4444, 0.4, 5);
    glow.position.y = 2.5; g.add(glow);
    // Emissive
    body.material.emissive = new THREE.Color(def.color || '#cc3333');
    body.material.emissiveIntensity = 0.5;
}

// ── Pillar ───────────────────────────────────────────────
function buildHQPillar(g, def) {
    const pillarMat = _fm(def.color || '#c9302c', { r: 0.5 });
    // Main pillar
    const pillar = new THREE.Mesh(new THREE.CylinderGeometry(0.18, 0.2, 3.5, 8), pillarMat);
    pillar.position.y = 1.75; pillar.castShadow = true; g.add(pillar);
    // Top crown
    const crown = new THREE.Mesh(new THREE.CylinderGeometry(0.25, 0.22, 0.1, 8), _fm('#8B0000'));
    crown.position.y = 3.5; g.add(crown);
    // Base
    const base = new THREE.Mesh(new THREE.CylinderGeometry(0.22, 0.25, 0.1, 8), _fm('#8B0000'));
    base.position.y = 0.05; g.add(base);
}

// ── Master registry ──────────────────────────────────────
const HQ_BUILDERS = {
    desk_modern: buildHQDesk,
    desk_wood: buildHQDesk,
    table_round: buildHQRoundTable,
    chair_office: buildHQChair,
    sofa: buildHQSofa,
    bookshelf: buildHQBookshelf,
    monitor: buildHQMonitor,
    plant_pot: buildHQPlant,
    cabinet: buildHQCabinet,
    whiteboard: buildHQWhiteboard,
    lantern: buildHQLantern,
    pillar_red: buildHQPillar,
};

/**
 * Create an HQ furniture group, or return null if no builder exists.
 * @param {string} assetId - asset ID (e.g. 'desk_modern')
 * @param {object} def - asset definition with .color, .size etc.
 * @returns {THREE.Group|null}
 */
function createHQFurniture(assetId, def) {
    const builder = HQ_BUILDERS[assetId];
    if (!builder) return null;
    const g = new THREE.Group();
    builder(g, def);
    return g;
}
