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

// ── Classic Chair (wooden, no wheels) ────────────────────
function buildHQClassicChair(g, def) {
    const wood = _fm(def.color || '#5c3a1e', { r: 0.7 });
    const darkW = _fm('#3d2510', { r: 0.7 });
    // Seat
    const seat = new THREE.Mesh(new THREE.BoxGeometry(0.44, 0.04, 0.44), wood);
    seat.position.y = 0.45; seat.castShadow = true; g.add(seat);
    // 4 Legs (tapered)
    [[-0.18, -0.18], [-0.18, 0.18], [0.18, -0.18], [0.18, 0.18]].forEach(([lx, lz]) => {
        const leg = new THREE.Mesh(new THREE.CylinderGeometry(0.02, 0.025, 0.45, 6), darkW);
        leg.position.set(lx, 0.225, lz); leg.castShadow = true; g.add(leg);
    });
    // Backrest (curved slats)
    const backFrame = new THREE.Mesh(new THREE.BoxGeometry(0.44, 0.5, 0.03), wood);
    backFrame.position.set(0, 0.72, -0.2); g.add(backFrame);
    // Decorative slats
    for (let sx of [-0.12, 0, 0.12]) {
        const slat = new THREE.Mesh(new THREE.BoxGeometry(0.03, 0.35, 0.02), darkW);
        slat.position.set(sx, 0.7, -0.19); g.add(slat);
    }
    // Cross bars between legs
    const crossF = new THREE.Mesh(new THREE.BoxGeometry(0.36, 0.02, 0.02), darkW);
    crossF.position.set(0, 0.15, 0.18); g.add(crossF);
    const crossB = crossF.clone(); crossB.position.z = -0.18; g.add(crossB);
}

// ── Dining Chair ─────────────────────────────────────────
function buildHQDiningChair(g, def) {
    const fabric = _fm(def.color || '#8B4513', { r: 0.6 });
    const metal = _fm('#888', { r: 0.3, m: 0.5 });
    // Padded seat
    const seat = new THREE.Mesh(new THREE.BoxGeometry(0.44, 0.06, 0.42), fabric);
    seat.position.y = 0.46; seat.castShadow = true; g.add(seat);
    // Padded backrest
    const back = new THREE.Mesh(new THREE.BoxGeometry(0.42, 0.4, 0.04), fabric);
    back.position.set(0, 0.7, -0.2); g.add(back);
    // Metal legs (4, angled outward slightly)
    [[-0.2, -0.18, -0.03], [-0.2, 0.18, 0.03], [0.2, -0.18, -0.03], [0.2, 0.18, 0.03]].forEach(([lx, lz, tilt]) => {
        const leg = new THREE.Mesh(new THREE.CylinderGeometry(0.015, 0.015, 0.46, 6), metal);
        leg.position.set(lx, 0.23, lz); leg.rotation.x = tilt; leg.castShadow = true; g.add(leg);
    });
    // Back legs extend up to support backrest
    for (let sx of [-0.2, 0.2]) {
        const upright = new THREE.Mesh(new THREE.CylinderGeometry(0.015, 0.015, 0.5, 6), metal);
        upright.position.set(sx, 0.7, -0.2); g.add(upright);
    }
}

// ── Fridge ────────────────────────────────────────────────
function buildHQFridge(g, def) {
    const white = _fm(def.color || '#e8e8e8', { r: 0.3, m: 0.2 });
    const silver = _fm('#bbb', { r: 0.2, m: 0.5 });
    const dark = _fm('#333');
    // Main body
    const body = new THREE.Mesh(new THREE.BoxGeometry(0.7, 1.8, 0.65), white);
    body.position.y = 0.9; body.castShadow = true; g.add(body);
    // Top freezer door line
    const line1 = new THREE.Mesh(new THREE.BoxGeometry(0.66, 0.01, 0.01), dark);
    line1.position.set(0, 1.35, 0.33); g.add(line1);
    // Freezer handle
    const hTop = new THREE.Mesh(new THREE.BoxGeometry(0.02, 0.15, 0.03), silver);
    hTop.position.set(0.28, 1.55, 0.34); g.add(hTop);
    // Main door handle
    const hBot = new THREE.Mesh(new THREE.BoxGeometry(0.02, 0.2, 0.03), silver);
    hBot.position.set(0.28, 0.9, 0.34); g.add(hBot);
    // Brand logo area (small rectangle)
    const logo = new THREE.Mesh(new THREE.BoxGeometry(0.12, 0.04, 0.005), _fm('#22d3ee'));
    logo.position.set(0, 1.65, 0.33); g.add(logo);
    // Feet
    for (let fx of [-0.28, 0.28]) {
        const foot = new THREE.Mesh(new THREE.BoxGeometry(0.06, 0.03, 0.06), dark);
        foot.position.set(fx, 0.015, 0); g.add(foot);
    }
}

// ── Washing Machine ──────────────────────────────────────
function buildHQWashingMachine(g, def) {
    const white = _fm(def.color || '#e0e0e0', { r: 0.3, m: 0.15 });
    const silver = _fm('#aaa', { r: 0.2, m: 0.5 });
    const dark = _fm('#222');
    // Main body
    const body = new THREE.Mesh(new THREE.BoxGeometry(0.6, 0.85, 0.6), white);
    body.position.y = 0.425; body.castShadow = true; g.add(body);
    // Control panel (top front)
    const panel = new THREE.Mesh(new THREE.BoxGeometry(0.55, 0.08, 0.01), _fm('#ccc', { m: 0.3 }));
    panel.position.set(0, 0.8, 0.305); g.add(panel);
    // Dial knob
    const knob = new THREE.Mesh(new THREE.CylinderGeometry(0.025, 0.025, 0.02, 8), silver);
    knob.position.set(-0.15, 0.8, 0.32); knob.rotation.x = Math.PI / 2; g.add(knob);
    // Power button
    const btn = new THREE.Mesh(new THREE.CylinderGeometry(0.015, 0.015, 0.01, 8), _fm('#22c55e'));
    btn.position.set(0.15, 0.8, 0.32); btn.rotation.x = Math.PI / 2; g.add(btn);
    // Door (circular window)
    const doorRim = new THREE.Mesh(new THREE.TorusGeometry(0.15, 0.02, 8, 16), silver);
    doorRim.position.set(0, 0.4, 0.31); g.add(doorRim);
    const doorGlass = new THREE.Mesh(new THREE.CircleGeometry(0.13, 16),
        new THREE.MeshStandardMaterial({ color: 0x3a5a7a, transparent: true, opacity: 0.4, roughness: 0.1, metalness: 0.3 }));
    doorGlass.position.set(0, 0.4, 0.31); g.add(doorGlass);
    // Feet
    [[-0.25, -0.25], [-0.25, 0.25], [0.25, -0.25], [0.25, 0.25]].forEach(([fx, fz]) => {
        const foot = new THREE.Mesh(new THREE.CylinderGeometry(0.025, 0.025, 0.03, 6), dark);
        foot.position.set(fx, 0.015, fz); g.add(foot);
    });
}

// ── Bar Counter ──────────────────────────────────────────
function buildHQBarCounter(g, def) {
    const wood = _fm(def.color || '#3a2518', { r: 0.6 });
    const darkW = _fm('#2a1a10', { r: 0.7 });
    const metal = _fm('#666', { r: 0.3, m: 0.5 });
    // Counter top (long)
    const top = new THREE.Mesh(new THREE.BoxGeometry(2.4, 0.06, 0.6), wood);
    top.position.y = 1.05; top.castShadow = true; top.receiveShadow = true; g.add(top);
    // Top edge trim
    const trim = new THREE.Mesh(new THREE.BoxGeometry(2.42, 0.03, 0.02), _fm('#1a0f08'));
    trim.position.set(0, 1.07, 0.3); g.add(trim);
    // Front panel
    const front = new THREE.Mesh(new THREE.BoxGeometry(2.36, 0.95, 0.04), darkW);
    front.position.set(0, 0.53, 0.28); front.castShadow = true; g.add(front);
    // Back panel (shorter)
    const backP = new THREE.Mesh(new THREE.BoxGeometry(2.36, 0.7, 0.04), darkW);
    backP.position.set(0, 0.38, -0.28); g.add(backP);
    // Shelves inside (2 levels)
    for (let sy of [0.3, 0.65]) {
        const shelf = new THREE.Mesh(new THREE.BoxGeometry(2.3, 0.03, 0.5), darkW);
        shelf.position.set(0, sy, 0); g.add(shelf);
    }
    // Foot rail (brass)
    const rail = new THREE.Mesh(new THREE.CylinderGeometry(0.02, 0.02, 2.3, 8), _fm('#b8860b', { m: 0.6 }));
    rail.position.set(0, 0.2, 0.32); rail.rotation.z = Math.PI / 2; g.add(rail);
    // Bottles on top shelf
    const bottleColors = [0x2ecc71, 0x9b59b6, 0xe74c3c, 0xf39c12, 0x3498db];
    for (let i = 0; i < 5; i++) {
        const bx = -0.9 + i * 0.4;
        const bottle = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.035, 0.25, 6),
            _fm(bottleColors[i], { r: 0.3, m: 0.2 }));
        bottle.position.set(bx, 0.78, 0); g.add(bottle);
        // Bottle neck
        const neck = new THREE.Mesh(new THREE.CylinderGeometry(0.015, 0.02, 0.08, 6),
            _fm(bottleColors[i], { r: 0.3 }));
        neck.position.set(bx, 0.94, 0); g.add(neck);
    }
}

// ── Coffee Machine ───────────────────────────────────────
function buildHQCoffeeMachine(g, def) {
    const body = _fm(def.color || '#2c2c2c', { r: 0.3, m: 0.3 });
    const silver = _fm('#aaa', { r: 0.2, m: 0.6 });
    const accent = _fm('#c0392b');
    // Main body
    const main = new THREE.Mesh(new THREE.BoxGeometry(0.35, 0.45, 0.3), body);
    main.position.y = 0.225; main.castShadow = true; g.add(main);
    // Top hopper
    const hopper = new THREE.Mesh(new THREE.BoxGeometry(0.2, 0.12, 0.18), _fm('#1a1a1a'));
    hopper.position.set(0, 0.5, -0.03); g.add(hopper);
    // Lid
    const lid = new THREE.Mesh(new THREE.BoxGeometry(0.22, 0.02, 0.2), silver);
    lid.position.set(0, 0.57, -0.03); g.add(lid);
    // Drip tray
    const tray = new THREE.Mesh(new THREE.BoxGeometry(0.28, 0.02, 0.2), silver);
    tray.position.set(0, 0.01, 0.05); g.add(tray);
    // Nozzle
    const nozzle = new THREE.Mesh(new THREE.CylinderGeometry(0.015, 0.02, 0.06, 6), silver);
    nozzle.position.set(0, 0.12, 0.05); g.add(nozzle);
    // Cup
    const cup = new THREE.Mesh(new THREE.CylinderGeometry(0.04, 0.035, 0.08, 8), _fm('#f5f5f5'));
    cup.position.set(0, 0.05, 0.05); g.add(cup);
    // Cup handle
    const handle = new THREE.Mesh(new THREE.TorusGeometry(0.025, 0.006, 6, 8, Math.PI), _fm('#f5f5f5'));
    handle.position.set(0.045, 0.05, 0.05); handle.rotation.y = Math.PI / 2; g.add(handle);
    // Buttons
    for (let i = 0; i < 3; i++) {
        const btnC = i === 0 ? accent : _fm('#555');
        const bt = new THREE.Mesh(new THREE.CylinderGeometry(0.012, 0.012, 0.008, 8), btnC);
        bt.position.set(-0.08 + i * 0.08, 0.38, 0.16); bt.rotation.x = Math.PI / 2; g.add(bt);
    }
    // Steam pipe
    const pipe = new THREE.Mesh(new THREE.CylinderGeometry(0.008, 0.008, 0.12, 6), silver);
    pipe.position.set(0.14, 0.2, 0.1); pipe.rotation.z = 0.3; g.add(pipe);
}

// ── Pool Table (Billiard) ────────────────────────────────
function buildHQPoolTable(g, def) {
    const felt = _fm(def.color || '#006400', { r: 0.8 });
    const wood = _fm('#5c3a1e', { r: 0.6 });
    const darkW = _fm('#3a2510', { r: 0.7 });
    const metal = _fm('#b8860b', { r: 0.3, m: 0.5 });
    // Table surface (green felt)
    const surface = new THREE.Mesh(new THREE.BoxGeometry(2.4, 0.04, 1.3), felt);
    surface.position.y = 0.82; surface.castShadow = true; surface.receiveShadow = true; g.add(surface);
    // Rails (cushions)
    const railMat = wood;
    // Long rails
    for (let rz of [-0.67, 0.67]) {
        const rail = new THREE.Mesh(new THREE.BoxGeometry(2.5, 0.08, 0.06), railMat);
        rail.position.set(0, 0.87, rz); rail.castShadow = true; g.add(rail);
    }
    // Short rails
    for (let rx of [-1.22, 1.22]) {
        const rail = new THREE.Mesh(new THREE.BoxGeometry(0.06, 0.08, 1.4), railMat);
        rail.position.set(rx, 0.87, 0); rail.castShadow = true; g.add(rail);
    }
    // 6 Legs
    [[-1.0, -0.55], [-1.0, 0.55], [0, -0.55], [0, 0.55], [1.0, -0.55], [1.0, 0.55]].forEach(([lx, lz]) => {
        const leg = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.06, 0.8, 8), darkW);
        leg.position.set(lx, 0.4, lz); leg.castShadow = true; g.add(leg);
    });
    // Body frame under surface
    const frame = new THREE.Mesh(new THREE.BoxGeometry(2.3, 0.12, 1.2), darkW);
    frame.position.y = 0.74; g.add(frame);
    // 6 Pocket holes (gold rings)
    [[-1.15, -0.62], [-1.15, 0.62], [0, -0.65], [0, 0.65], [1.15, -0.62], [1.15, 0.62]].forEach(([px, pz]) => {
        const pocket = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.05, 0.03, 8), metal);
        pocket.position.set(px, 0.87, pz); g.add(pocket);
        const hole = new THREE.Mesh(new THREE.CylinderGeometry(0.04, 0.04, 0.05, 8), _fm('#000'));
        hole.position.set(px, 0.85, pz); g.add(hole);
    });
    // Balls (triangle formation)
    const ballColors = [0xffff00, 0x0000ff, 0xff0000, 0x800080, 0xff8c00, 0x006400, 0x8b0000, 0x000000, 0xffffff];
    let bi = 0;
    for (let row = 0; row < 4 && bi < ballColors.length; row++) {
        for (let col = 0; col <= row && bi < ballColors.length; col++) {
            const bx = 0.5 + row * 0.05;
            const bz = (col - row / 2) * 0.055;
            const ball = new THREE.Mesh(new THREE.SphereGeometry(0.022, 8, 6), _fm(ballColors[bi++]));
            ball.position.set(bx, 0.86, bz); g.add(ball);
        }
    }
}

// ── Tall Potted Tree ─────────────────────────────────────
function buildHQTallTree(g, def) {
    const potM = _fm('#6d4c2a', { r: 0.8 });
    const trunk = _fm('#5c3a1e', { r: 0.7 });
    // Pot
    const pot = new THREE.Mesh(new THREE.CylinderGeometry(0.2, 0.15, 0.3, 8), potM);
    pot.position.y = 0.15; pot.castShadow = true; g.add(pot);
    const rim = new THREE.Mesh(new THREE.CylinderGeometry(0.22, 0.22, 0.03, 8), potM);
    rim.position.y = 0.3; g.add(rim);
    // Soil
    const soil = new THREE.Mesh(new THREE.CylinderGeometry(0.18, 0.18, 0.03, 8), _fm('#3e2723', { r: 0.9 }));
    soil.position.set(0, 0.28, 0); g.add(soil);
    // Trunk
    const tr = new THREE.Mesh(new THREE.CylinderGeometry(0.035, 0.05, 1.0, 6), trunk);
    tr.position.y = 0.8; tr.castShadow = true; g.add(tr);
    // Canopy layers (spheres)
    [[0, 1.5, 0, 0.28], [0.12, 1.65, 0.08, 0.2], [-0.1, 1.6, -0.1, 0.22],
     [0.08, 1.75, -0.05, 0.16], [-0.06, 1.45, 0.12, 0.18]].forEach(([x, y, z, r]) => {
        const leaf = new THREE.Mesh(new THREE.SphereGeometry(r, 7, 5), _fm(0x228B22, { r: 0.8 }));
        leaf.position.set(x, y, z); leaf.castShadow = true; g.add(leaf);
    });
}

// ── Cactus ───────────────────────────────────────────────
function buildHQCactus(g, def) {
    const potM = _fm('#c0704a', { r: 0.7 });
    const cactus = _fm(def.color || '#2e8b57', { r: 0.6 });
    const darkG = _fm('#1a6b3a', { r: 0.6 });
    // Pot
    const pot = new THREE.Mesh(new THREE.CylinderGeometry(0.12, 0.1, 0.16, 8), potM);
    pot.position.y = 0.08; pot.castShadow = true; g.add(pot);
    const potRim = new THREE.Mesh(new THREE.CylinderGeometry(0.13, 0.13, 0.02, 8), potM);
    potRim.position.set(0, 0.16, 0); g.add(potRim);
    // Sand/soil
    const sand = new THREE.Mesh(new THREE.CylinderGeometry(0.1, 0.1, 0.02, 8), _fm('#c2b280'));
    sand.position.set(0, 0.15, 0); g.add(sand);
    // Main cactus body
    const body = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.07, 0.35, 8), cactus);
    body.position.y = 0.34; body.castShadow = true; g.add(body);
    // Top (rounded)
    const top = new THREE.Mesh(new THREE.SphereGeometry(0.06, 8, 6), cactus);
    top.position.y = 0.52; g.add(top);
    // Arms
    const armR = new THREE.Mesh(new THREE.CylinderGeometry(0.035, 0.04, 0.18, 6), darkG);
    armR.position.set(0.08, 0.4, 0); armR.rotation.z = -0.8; g.add(armR);
    const armRTop = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.035, 0.1, 6), darkG);
    armRTop.position.set(0.16, 0.5, 0); g.add(armRTop);
    const armL = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.035, 0.14, 6), darkG);
    armL.position.set(-0.07, 0.35, 0); armL.rotation.z = 0.9; g.add(armL);
    // Flower on top
    const flower = new THREE.Mesh(new THREE.SphereGeometry(0.02, 6, 4), _fm('#ff69b4'));
    flower.position.set(0, 0.56, 0); g.add(flower);
}

// ── Small Aquarium (bowl) ────────────────────────────────
function buildHQAquariumSmall(g, def) {
    const glass = new THREE.MeshStandardMaterial({ color: 0x87ceeb, transparent: true, opacity: 0.3, roughness: 0.1, metalness: 0.2 });
    const water = new THREE.MeshStandardMaterial({ color: 0x1e90ff, transparent: true, opacity: 0.35, roughness: 0.1 });
    // Bowl
    const bowl = new THREE.Mesh(new THREE.SphereGeometry(0.18, 12, 8, 0, Math.PI * 2, 0, Math.PI * 0.7), glass);
    bowl.position.y = 0.18; g.add(bowl);
    // Water inside
    const wat = new THREE.Mesh(new THREE.CylinderGeometry(0.15, 0.12, 0.18, 10), water);
    wat.position.y = 0.14; g.add(wat);
    // Gravel base
    const gravel = new THREE.Mesh(new THREE.CylinderGeometry(0.12, 0.14, 0.04, 8), _fm('#c2b280', { r: 0.9 }));
    gravel.position.y = 0.04; g.add(gravel);
    // Small fish (2)
    [[0.04, 0.16, 0.02, 0xff6347], [-0.03, 0.2, -0.03, 0xffa500]].forEach(([x, y, z, c]) => {
        const fish = new THREE.Mesh(new THREE.SphereGeometry(0.015, 6, 4), _fm(c));
        fish.position.set(x, y, z); fish.scale.set(1.5, 0.8, 0.6); g.add(fish);
        const tail = new THREE.Mesh(new THREE.ConeGeometry(0.012, 0.02, 4), _fm(c));
        tail.position.set(x - 0.02, y, z); tail.rotation.z = Math.PI / 2; g.add(tail);
    });
    // Small plant
    const plant = new THREE.Mesh(new THREE.ConeGeometry(0.02, 0.1, 4), _fm(0x228B22, { r: 0.7 }));
    plant.position.set(-0.04, 0.08, 0); g.add(plant);
}

// ── Large Aquarium (tank) ────────────────────────────────
function buildHQAquariumLarge(g, def) {
    const glass = new THREE.MeshStandardMaterial({ color: 0xadd8e6, transparent: true, opacity: 0.25, roughness: 0.05, metalness: 0.3 });
    const water = new THREE.MeshStandardMaterial({ color: 0x1c7ed6, transparent: true, opacity: 0.3, roughness: 0.1 });
    const frame = _fm('#333', { m: 0.5 });
    // Tank frame (bottom)
    const base = new THREE.Mesh(new THREE.BoxGeometry(1.2, 0.04, 0.45), frame);
    base.position.y = 0.62; g.add(base);
    // Stand
    const stand = new THREE.Mesh(new THREE.BoxGeometry(1.16, 0.6, 0.42), _fm('#2a1a10', { r: 0.7 }));
    stand.position.y = 0.3; stand.castShadow = true; g.add(stand);
    // Glass panels
    const gFront = new THREE.Mesh(new THREE.BoxGeometry(1.18, 0.5, 0.02), glass);
    gFront.position.set(0, 0.89, 0.22); g.add(gFront);
    const gBack = gFront.clone(); gBack.position.z = -0.22; g.add(gBack);
    const gLeft = new THREE.Mesh(new THREE.BoxGeometry(0.02, 0.5, 0.44), glass);
    gLeft.position.set(-0.59, 0.89, 0); g.add(gLeft);
    const gRight = gLeft.clone(); gRight.position.x = 0.59; g.add(gRight);
    // Water
    const wat = new THREE.Mesh(new THREE.BoxGeometry(1.14, 0.42, 0.4), water);
    wat.position.y = 0.85; g.add(wat);
    // Top frame
    const topF = new THREE.Mesh(new THREE.BoxGeometry(1.2, 0.03, 0.45), frame);
    topF.position.y = 1.14; g.add(topF);
    // Sand/gravel bed
    const sand = new THREE.Mesh(new THREE.BoxGeometry(1.1, 0.04, 0.38), _fm('#d4a574', { r: 0.9 }));
    sand.position.y = 0.66; g.add(sand);
    // Aquatic plants
    [[-0.4, 0, 0x228B22, 0.25], [-0.2, 0.05, 0x2ecc71, 0.2], [0.35, -0.05, 0x1abc9c, 0.22], [0.1, 0.08, 0x27ae60, 0.18]].forEach(([x, z, c, h]) => {
        const pl = new THREE.Mesh(new THREE.ConeGeometry(0.03, h, 5), _fm(c, { r: 0.7 }));
        pl.position.set(x, 0.68 + h / 2, z); g.add(pl);
    });
    // Fish (4 colorful)
    [[0.2, 0.85, 0.05, 0xff6347], [-0.15, 0.9, -0.05, 0xffa500], [0.3, 0.95, 0, 0x4169e1], [-0.3, 0.88, 0.08, 0xffff00]].forEach(([x, y, z, c]) => {
        const fish = new THREE.Mesh(new THREE.SphereGeometry(0.025, 6, 4), _fm(c));
        fish.position.set(x, y, z); fish.scale.set(1.6, 0.8, 0.6); g.add(fish);
        const tail = new THREE.Mesh(new THREE.ConeGeometry(0.018, 0.03, 4), _fm(c));
        tail.position.set(x - 0.03, y, z); tail.rotation.z = Math.PI / 2; g.add(tail);
    });
    // Bubbles
    [[-0.35, 0.95, 0.1], [-0.33, 1.02, 0.08], [-0.36, 1.08, 0.09]].forEach(([x, y, z]) => {
        const bub = new THREE.Mesh(new THREE.SphereGeometry(0.012, 6, 4),
            new THREE.MeshStandardMaterial({ color: 0xffffff, transparent: true, opacity: 0.3 }));
        bub.position.set(x, y, z); g.add(bub);
    });
    // Light strip
    const light = new THREE.Mesh(new THREE.BoxGeometry(0.8, 0.015, 0.06), _fm('#fff', { r: 0.1 }));
    light.position.set(0, 1.135, 0);
    light.material.emissive = new THREE.Color(0x87ceeb);
    light.material.emissiveIntensity = 0.5;
    g.add(light);
}

// ── Terrarium / Mini Garden ──────────────────────────────
function buildHQTerrarium(g, def) {
    const wood = _fm('#5c3a1e', { r: 0.7 });
    const soil = _fm('#3e2723', { r: 0.9 });
    const moss = _fm('#2d5a27', { r: 0.8 });
    // Wooden tray base
    const tray = new THREE.Mesh(new THREE.BoxGeometry(0.8, 0.05, 0.5), wood);
    tray.position.y = 0.025; tray.castShadow = true; g.add(tray);
    // Raised edge
    const edgeF = new THREE.Mesh(new THREE.BoxGeometry(0.82, 0.06, 0.02), wood);
    edgeF.position.set(0, 0.06, 0.25); g.add(edgeF);
    const edgeB = edgeF.clone(); edgeB.position.z = -0.25; g.add(edgeB);
    const edgeL = new THREE.Mesh(new THREE.BoxGeometry(0.02, 0.06, 0.5), wood);
    edgeL.position.set(-0.4, 0.06, 0); g.add(edgeL);
    const edgeR = edgeL.clone(); edgeR.position.x = 0.4; g.add(edgeR);
    // Soil layer
    const soilM = new THREE.Mesh(new THREE.BoxGeometry(0.76, 0.03, 0.46), soil);
    soilM.position.y = 0.065; g.add(soilM);
    // Moss patches
    [[-0.15, 0.1, 0.12], [0.2, 0, 0.1], [-0.05, -0.12, 0.08], [0.28, 0.15, 0.07]].forEach(([x, z, r]) => {
        const m = new THREE.Mesh(new THREE.CylinderGeometry(r, r, 0.015, 6), moss);
        m.position.set(x, 0.085, z); g.add(m);
    });
    // Rocks
    [[0.2, -0.1, '#888', 0.04], [-0.25, -0.05, '#777', 0.035], [0.1, 0.15, '#999', 0.03], [-0.1, 0.08, '#aaa', 0.025]].forEach(([x, z, c, r]) => {
        const rock = new THREE.Mesh(new THREE.SphereGeometry(r, 5, 4), _fm(c, { r: 0.8 }));
        rock.position.set(x, 0.085 + r * 0.5, z); rock.scale.set(1, 0.6, 1); g.add(rock);
    });
    // Mini trees (3)
    [[-0.25, 0.12, 0.18], [0.15, -0.08, 0.22], [0.32, 0.05, 0.15]].forEach(([x, z, h]) => {
        const trunk = new THREE.Mesh(new THREE.CylinderGeometry(0.008, 0.012, h * 0.6, 4), _fm('#5c3a1e'));
        trunk.position.set(x, 0.08 + h * 0.3, z); g.add(trunk);
        const canopy = new THREE.Mesh(new THREE.SphereGeometry(h * 0.35, 6, 4), _fm(0x228B22, { r: 0.8 }));
        canopy.position.set(x, 0.08 + h * 0.7, z); g.add(canopy);
    });
    // Small path (stone pieces)
    for (let i = 0; i < 4; i++) {
        const stone = new THREE.Mesh(new THREE.CylinderGeometry(0.02, 0.025, 0.01, 5), _fm('#bbb', { r: 0.7 }));
        stone.position.set(-0.15 + i * 0.1, 0.085, -0.02 + Math.sin(i) * 0.04);
        g.add(stone);
    }
}

// ── Rock Garden / Hòn Non Bộ (detailed) ──────────────────
function buildHQRockGarden(g, def) {
    // Scale entire model 2x so it's bigger than a desk
    const _outer = g;
    g = new THREE.Group();
    g.scale.set(2, 2, 2);
    const stone = _fm('#5a5a5a', { r: 0.85 });
    const darkStone = _fm('#3d3d3d', { r: 0.9 });
    const lightStone = _fm('#7a7a7a', { r: 0.8 });
    const water = new THREE.MeshStandardMaterial({ color: 0x1a6b5a, transparent: true, opacity: 0.5, roughness: 0.05 });
    const moss = _fm('#1e5a1e', { r: 0.8 });
    const lightMoss = _fm('#2d8a2d', { r: 0.75 });
    const wood = _fm('#5c3a1e', { r: 0.7 });
    const red = _fm('#8B2500');

    // ═══ Rectangular stone basin ═══
    const basinW = 1.4, basinD = 0.9, basinH = 0.1;
    const basinMat = _fm('#555', { r: 0.75 });
    const basinBase = new THREE.Mesh(new THREE.BoxGeometry(basinW, basinH, basinD), basinMat);
    basinBase.position.y = basinH / 2; basinBase.castShadow = true; g.add(basinBase);
    // Rim edges
    const rimH = 0.04;
    [[ basinW/2+0.02, 0, basinD, rimH], [-basinW/2-0.02, 0, basinD, rimH],
     [0, 0, 0.03, rimH]].forEach(([x, z, w, h], i) => {
        if (i < 2) {
            const rim = new THREE.Mesh(new THREE.BoxGeometry(0.04, basinH + rimH, basinD + 0.04), _fm('#4a4a4a'));
            rim.position.set(x, (basinH + rimH) / 2, 0); g.add(rim);
        }
    });
    const rimF = new THREE.Mesh(new THREE.BoxGeometry(basinW + 0.08, basinH + rimH, 0.04), _fm('#4a4a4a'));
    rimF.position.set(0, (basinH + rimH) / 2, basinD / 2 + 0.02); g.add(rimF);
    const rimB = rimF.clone(); rimB.position.z = -basinD / 2 - 0.02; g.add(rimB);

    // ═══ Water surface (solid color, no transparency to avoid flicker) ═══
    const waterSurf = new THREE.Mesh(new THREE.BoxGeometry(basinW - 0.08, 0.03, basinD - 0.08),
        _fm('#1a6b5a', { r: 0.15, m: 0.2 }));
    waterSurf.position.y = basinH + 0.005; waterSurf.receiveShadow = true; g.add(waterSurf);

    // ═══ Main mountain cluster (left-center, tallest) ═══
    [[0, 0.55, -0.1, 0.18, 0.7, 7], [0.08, 0.48, -0.15, 0.14, 0.6, 6],
     [-0.06, 0.42, -0.05, 0.12, 0.55, 6], [0.04, 0.65, -0.12, 0.08, 0.35, 5],
     [-0.1, 0.35, 0.0, 0.1, 0.4, 5]].forEach(([x, y, z, r, h, seg]) => {
        const peak = new THREE.Mesh(new THREE.ConeGeometry(r, h, seg), (h > 0.5) ? darkStone : stone);
        peak.position.set(x, y, z); peak.castShadow = true; g.add(peak);
    });
    // Jagged top spike
    const spike1 = new THREE.Mesh(new THREE.ConeGeometry(0.04, 0.2, 4), darkStone);
    spike1.position.set(0.02, 0.92, -0.11); g.add(spike1);

    // ═══ Second mountain cluster (right side) ═══
    [[0.4, 0.38, 0.0, 0.14, 0.5, 6], [0.45, 0.32, 0.08, 0.1, 0.4, 5],
     [0.35, 0.28, -0.08, 0.08, 0.35, 5], [0.42, 0.45, 0.02, 0.06, 0.22, 4]].forEach(([x, y, z, r, h, seg]) => {
        const peak = new THREE.Mesh(new THREE.ConeGeometry(r, h, seg), stone);
        peak.position.set(x, y, z); peak.castShadow = true; g.add(peak);
    });
    const spike2 = new THREE.Mesh(new THREE.ConeGeometry(0.03, 0.15, 4), darkStone);
    spike2.position.set(0.41, 0.62, 0.01); g.add(spike2);

    // ═══ Third cluster (far left, medium) ═══
    [[-0.35, 0.3, 0.05, 0.12, 0.4, 6], [-0.4, 0.25, -0.05, 0.09, 0.3, 5],
     [-0.3, 0.22, 0.12, 0.07, 0.25, 5]].forEach(([x, y, z, r, h, seg]) => {
        const peak = new THREE.Mesh(new THREE.ConeGeometry(r, h, seg), lightStone);
        peak.position.set(x, y, z); peak.castShadow = true; g.add(peak);
    });

    // ═══ Scattered boulders at base ═══
    [[0.2, 0.12, 0.25, 0.06], [-0.2, 0.11, 0.3, 0.05], [0.5, 0.11, -0.2, 0.045],
     [-0.5, 0.1, -0.15, 0.04], [0.55, 0.1, 0.2, 0.035], [-0.15, 0.1, 0.28, 0.04],
     [0.3, 0.11, -0.25, 0.05], [-0.45, 0.1, 0.2, 0.035]].forEach(([x, y, z, r]) => {
        const rock = new THREE.Mesh(new THREE.SphereGeometry(r, 5, 4), stone);
        rock.position.set(x, y, z); rock.scale.set(1.3, 0.6, 1.1); g.add(rock);
    });

    // ═══ Moss & vegetation on rocks ═══
    [[0.02, 0.6, -0.06, 0.07], [-0.08, 0.48, 0.02, 0.06], [0.1, 0.4, -0.08, 0.05],
     [0.42, 0.42, 0.06, 0.05], [0.38, 0.35, -0.04, 0.04], [-0.36, 0.32, 0.08, 0.05],
     [-0.32, 0.26, -0.02, 0.04], [0.06, 0.35, 0.05, 0.045],
     [-0.12, 0.55, -0.08, 0.04], [0.46, 0.5, 0.0, 0.035]].forEach(([x, y, z, r], i) => {
        const m = new THREE.Mesh(new THREE.SphereGeometry(r, 5, 3), i % 2 === 0 ? moss : lightMoss);
        m.position.set(x, y, z); m.scale.set(1.2, 0.35, 1.2); g.add(m);
    });

    // ═══ Bonsai trees (4) ═══
    [[-0.1, 0.55, 0.0, 0.14], [0.15, 0.42, -0.04, 0.1], [0.44, 0.48, -0.02, 0.11],
     [-0.38, 0.35, 0.0, 0.09]].forEach(([x, y, z, h]) => {
        // trunk (slight curve)
        const trunk = new THREE.Mesh(new THREE.CylinderGeometry(0.005, 0.01, h * 0.5, 4), wood);
        trunk.position.set(x, y + h * 0.15, z); g.add(trunk);
        // Multi-sphere canopy
        const leafColors = [0x1a6b1a, 0x228B22, 0x2d7a2d];
        [[0, h*0.4, 0, h*0.28], [h*0.08, h*0.48, h*0.05, h*0.2], [-h*0.06, h*0.44, -h*0.04, h*0.18]].forEach(([lx,ly,lz,lr], i) => {
            const leaf = new THREE.Mesh(new THREE.SphereGeometry(lr, 5, 4), _fm(leafColors[i % 3], { r: 0.8 }));
            leaf.position.set(x + lx, y + ly, z + lz); g.add(leaf);
        });
    });

    // ═══ Arched bridge ═══
    const bridgeX = 0.18, bridgeZ = 0.2;
    // Arc (half torus)
    const arc = new THREE.Mesh(new THREE.TorusGeometry(0.06, 0.008, 6, 12, Math.PI), _fm('#b8860b', { r: 0.5, m: 0.3 }));
    arc.position.set(bridgeX, 0.14, bridgeZ); arc.rotation.y = Math.PI / 4; g.add(arc);
    // Bridge deck
    const deck = new THREE.Mesh(new THREE.BoxGeometry(0.12, 0.006, 0.035), _fm('#8B6914', { r: 0.6 }));
    deck.position.set(bridgeX, 0.14, bridgeZ); deck.rotation.y = Math.PI / 4; g.add(deck);
    // Railings
    for (let side of [-0.015, 0.015]) {
        const rail = new THREE.Mesh(new THREE.BoxGeometry(0.12, 0.015, 0.003), _fm('#b8860b'));
        rail.position.set(bridgeX + Math.sin(Math.PI/4) * side, 0.155, bridgeZ + Math.cos(Math.PI/4) * side);
        rail.rotation.y = Math.PI / 4; g.add(rail);
    }

    // ═══ Pagoda (on main mountain) ═══
    const px = 0.0, py = 0.82, pz = -0.1;
    // Base platform
    const pPlat = new THREE.Mesh(new THREE.BoxGeometry(0.05, 0.01, 0.05), _fm('#daa520'));
    pPlat.position.set(px, py, pz); g.add(pPlat);
    // Pagoda body
    const pBody = new THREE.Mesh(new THREE.BoxGeometry(0.035, 0.04, 0.035), _fm('#f5deb3'));
    pBody.position.set(px, py + 0.03, pz); g.add(pBody);
    // Tiered roofs (3 levels)
    for (let i = 0; i < 3; i++) {
        const roofSize = 0.04 - i * 0.008;
        const roof = new THREE.Mesh(new THREE.ConeGeometry(roofSize, 0.015, 4), red);
        roof.position.set(px, py + 0.055 + i * 0.025, pz); g.add(roof);
        if (i < 2) {
            const tier = new THREE.Mesh(new THREE.BoxGeometry(roofSize * 0.7, 0.012, roofSize * 0.7), _fm('#f5deb3'));
            tier.position.set(px, py + 0.065 + i * 0.025, pz); g.add(tier);
        }
    }
    // Spire
    const spire = new THREE.Mesh(new THREE.CylinderGeometry(0.003, 0.003, 0.02, 4), _fm('#daa520'));
    spire.position.set(px, py + 0.12, pz); g.add(spire);

    // ═══ Waterfall streaks (white lines on rocks) ═══
    const waterfallMat = new THREE.MeshStandardMaterial({ color: 0xffffff, transparent: true, opacity: 0.35, roughness: 0.05 });
    [[0.06, 0.45, -0.05, 0.008, 0.25], [-0.04, 0.35, 0.0, 0.006, 0.2],
     [0.42, 0.3, 0.04, 0.006, 0.18]].forEach(([x, y, z, r, h]) => {
        const fall = new THREE.Mesh(new THREE.CylinderGeometry(r, r * 1.5, h, 4), waterfallMat);
        fall.position.set(x, y, z); g.add(fall);
    });

    // ═══ Koi fish (4) ═══
    [[0.25, 0.11, 0.15, 0xff6347], [-0.2, 0.11, 0.2, 0xffa500],
     [0.1, 0.11, 0.3, 0xffffff], [-0.35, 0.11, -0.2, 0xff4500]].forEach(([x, y, z, c]) => {
        const fish = new THREE.Mesh(new THREE.SphereGeometry(0.018, 6, 4), _fm(c));
        fish.position.set(x, y, z); fish.scale.set(1.8, 0.6, 0.7); g.add(fish);
        const tail = new THREE.Mesh(new THREE.ConeGeometry(0.014, 0.025, 4), _fm(c));
        tail.position.set(x - 0.025, y, z); tail.rotation.z = Math.PI / 2; g.add(tail);
    });

    // ═══ Water lily pads ═══
    const lilyMat = _fm('#228B22', { r: 0.6 });
    [[0.3, 0.12, -0.15], [-0.4, 0.12, 0.25], [0.0, 0.12, 0.32]].forEach(([x, y, z]) => {
        const pad = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.03, 0.005, 8), lilyMat);
        pad.position.set(x, y, z); g.add(pad);
        // Tiny flower
        const fl = new THREE.Mesh(new THREE.SphereGeometry(0.008, 5, 3), _fm('#ff69b4'));
        fl.position.set(x, y + 0.01, z); g.add(fl);
    });
    _outer.add(g);
}

// ── Master registry ──────────────────────────────────────
const HQ_BUILDERS = {
    desk_modern: buildHQDesk,
    desk_wood: buildHQDesk,
    table_round: buildHQRoundTable,
    chair_office: buildHQChair,
    chair_classic: buildHQClassicChair,
    chair_dining: buildHQDiningChair,
    sofa: buildHQSofa,
    bookshelf: buildHQBookshelf,
    monitor: buildHQMonitor,
    plant_pot: buildHQPlant,
    plant_tall: buildHQTallTree,
    plant_cactus: buildHQCactus,
    aquarium_small: buildHQAquariumSmall,
    aquarium_large: buildHQAquariumLarge,
    terrarium: buildHQTerrarium,
    rock_garden: buildHQRockGarden,
    cabinet: buildHQCabinet,
    whiteboard: buildHQWhiteboard,
    lantern: buildHQLantern,
    pillar_red: buildHQPillar,
    fridge: buildHQFridge,
    washing_machine: buildHQWashingMachine,
    bar_counter: buildHQBarCounter,
    coffee_machine: buildHQCoffeeMachine,
    pool_table: buildHQPoolTable,
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
