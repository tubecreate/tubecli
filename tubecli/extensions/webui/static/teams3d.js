/**
 * Teams 3D Office — Isometric 3D office with Roblox-style characters
 * Template-based office themes: ancient, modern, military, futuristic
 */

let scene3d, camera3d, renderer3d, controls3d, clock3d;
let officeGroup;
let agentCharacters = []; // { group, roleId, agentId, state, targetPos, walkTimer, limbs }
let particlesMesh;
let studioSceneData = null; // Saved studio layout

// Built-in studio asset catalog (same as studio.html)
const STUDIO_ASSETS = [
    {id:"desk_modern",name:"Bàn hiện đại",category:"furniture",mesh:"box",size:[1.6,0.07,0.9],color:"#f0ebe4",yOffset:0.72},
    {id:"desk_wood",name:"Bàn gỗ cổ điển",category:"furniture",mesh:"box",size:[1.4,0.06,0.8],color:"#5c3a1e",yOffset:0.45},
    {id:"chair_office",name:"Ghế xoay",category:"furniture",mesh:"box",size:[0.5,0.06,0.5],color:"#2d3250",yOffset:0.48},
    {id:"sofa",name:"Sofa",category:"furniture",mesh:"box",size:[1.8,0.5,0.8],color:"#3d4a8a",yOffset:0.25},
    {id:"bookshelf",name:"Tủ sách",category:"furniture",mesh:"box",size:[1.2,2.0,0.4],color:"#6b4226",yOffset:1.0},
    {id:"table_round",name:"Bàn tròn",category:"furniture",mesh:"cylinder",size:[0.6,0.72,0.6],color:"#d4c8b0",yOffset:0.36},
    {id:"cabinet",name:"Tủ hồ sơ",category:"furniture",mesh:"box",size:[0.6,1.2,0.5],color:"#8a8a8a",yOffset:0.6},
    {id:"plant_pot",name:"Chậu cây",category:"decoration",mesh:"cylinder",size:[0.25,0.8,0.25],color:"#22c55e",yOffset:0.4},
    {id:"lantern",name:"Đèn lồng",category:"decoration",mesh:"sphere",size:[0.2,0.2,0.2],color:"#cc3333",yOffset:2.5,emissive:true},
    {id:"whiteboard",name:"Bảng trắng",category:"decoration",mesh:"box",size:[1.5,1.0,0.05],color:"#f0f0f0",yOffset:1.5},
    {id:"monitor",name:"Màn hình",category:"decoration",mesh:"box",size:[0.7,0.5,0.04],color:"#1a1a2e",yOffset:1.05},
    {id:"pillar_red",name:"Cột đỏ",category:"decoration",mesh:"cylinder",size:[0.18,3.5,0.18],color:"#c9302c",yOffset:1.75},
    {id:"wall_segment",name:"Tường",category:"structure",mesh:"box",size:[2.0,3.5,0.15],color:"#c8bca8",yOffset:1.75},
    {id:"floor_tile",name:"Ô sàn",category:"structure",mesh:"box",size:[2.0,0.1,2.0],color:"#d4c8b0",yOffset:0.05},
    {id:"door_frame",name:"Cửa ra vào",category:"structure",mesh:"box",size:[1.0,2.5,0.15],color:"#5c3a1e",yOffset:1.25},
];

const CHAR_COLORS = [0xf43f5e, 0xa855f7, 0x22d3ee, 0x22c55e, 0xf59e0b, 0x3b82f6, 0xec4899, 0x14b8a6, 0xf97316, 0x8b5cf6, 0x06b6d4, 0x10b981];

// Office themes by template
const OFFICE_THEMES = {
    imperial_court: {
        name: 'Cung Điện Cổ Trang',
        floor: 0xb8956a, floorRough: 0.7,
        wall: 0x8b6f47, wallRough: 0.6,
        trim: 0xc9302c, // đỏ son
        desk: 0x5c3a1e, deskDetail: 0xc9302c,
        chair: 0x3d2510, chairDetail: 0xd4a030,
        monitor: null, // no monitors — scrolls instead
        accent1: 0xd4a030, accent2: 0xc9302c, accent3: 0x2d5016,
        fog: 0x120a04, ground: 0x0a0804,
        special: 'ancient',
    },
    dev_team: {
        name: 'Văn Phòng Hiện Đại',
        floor: 0xd4cfc6, floorRough: 0.85,
        wall: 0xe8e2d8, wallRough: 0.8,
        trim: 0x444444,
        desk: 0xf0ebe4, deskDetail: 0x333333,
        chair: 0x2d3250, chairDetail: 0x22d3ee,
        monitor: 0x1a1a2e,
        accent1: 0x3b82f6, accent2: 0x22d3ee, accent3: 0xa855f7,
        fog: 0x080a12, ground: 0x10121c,
        special: 'modern',
    },
    military: {
        name: 'Căn Cứ Quân Sự',
        floor: 0x4a5540, floorRough: 0.9,
        wall: 0x3d4435, wallRough: 0.85,
        trim: 0x2a2e24,
        desk: 0x5a5a4a, deskDetail: 0x3a3a2e,
        chair: 0x2e3028, chairDetail: 0x6b7a00,
        monitor: 0x1a1e14,
        accent1: 0x6b7a00, accent2: 0xcc6600, accent3: 0x334422,
        fog: 0x0a0c08, ground: 0x0c0e0a,
        special: 'military',
    },
    company: {
        name: 'Tập Đoàn Tương Lai',
        floor: 0x1a1a2e, floorRough: 0.3,
        wall: 0x12122a, wallRough: 0.2,
        trim: 0x22d3ee,
        desk: 0x1e1e3a, deskDetail: 0x22d3ee,
        chair: 0x141430, chairDetail: 0xa855f7,
        monitor: 0x0a0a1e,
        accent1: 0x22d3ee, accent2: 0xa855f7, accent3: 0x22c55e,
        fog: 0x040412, ground: 0x06061a,
        special: 'futuristic',
    },
};
const DEFAULT_THEME = OFFICE_THEMES.dev_team;

// Desk positions
const DESK_POS = [
    { x: -5, z: -3 }, { x: -2, z: -3 }, { x: 1, z: -3 }, { x: 4, z: -3 },
    { x: -5, z: 0 },  { x: -2, z: 0 },  { x: 1, z: 0 },  { x: 4, z: 0 },
    { x: -5, z: 3 },  { x: -2, z: 3 },  { x: 1, z: 3 },  { x: 4, z: 3 },
];

// ── Main init ──
function init3DOffice(containerEl, teamData, agentsList) {
    if (renderer3d) { renderer3d.dispose(); containerEl.innerHTML = ''; }
    agentCharacters = [];

    const theme = OFFICE_THEMES[teamData.template] || DEFAULT_THEME;
    const W = containerEl.clientWidth;
    const H = Math.max(500, containerEl.clientHeight);

    scene3d = new THREE.Scene();
    scene3d.fog = new THREE.FogExp2(theme.fog, 0.012);

    camera3d = new THREE.PerspectiveCamera(35, W / H, 0.1, 200);
    camera3d.position.set(14, 11, 14);
    camera3d.lookAt(0, 0, 0);

    const canvas = document.createElement('canvas');
    containerEl.appendChild(canvas);
    renderer3d = new THREE.WebGLRenderer({ canvas, antialias: true });
    renderer3d.setSize(W, H);
    renderer3d.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer3d.setClearColor(theme.fog);
    renderer3d.shadowMap.enabled = true;
    renderer3d.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer3d.toneMapping = THREE.ACESFilmicToneMapping;

    controls3d = new THREE.OrbitControls(camera3d, canvas);
    controls3d.enableDamping = true;
    controls3d.dampingFactor = 0.08;
    controls3d.maxPolarAngle = Math.PI / 2.3;
    controls3d.minDistance = 6;
    controls3d.maxDistance = 30;
    controls3d.target.set(0, 0, 0);

    clock3d = new THREE.Clock();

    setupLighting(theme);

    // Load studio scene FIRST, then build room with correct dimensions
    loadStudioScene(teamData.id).then(() => {
        setupRoom(theme, teamData.name);
        if (studioSceneData && studioSceneData.assets && studioSceneData.assets.length > 0) {
            renderStudioAssets(studioSceneData.assets);
        }
        buildFurnitureAndCharacters(teamData, agentsList, theme);
        setupParticles(theme);
    });

    window.addEventListener('resize', () => {
        const w = containerEl.clientWidth, h = Math.max(500, containerEl.clientHeight);
        camera3d.aspect = w / h;
        camera3d.updateProjectionMatrix();
        renderer3d.setSize(w, h);
    });

    // Click
    const raycaster = new THREE.Raycaster();
    const mouse = new THREE.Vector2();
    canvas.addEventListener('click', (e) => {
        const rect = canvas.getBoundingClientRect();
        mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
        mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
        raycaster.setFromCamera(mouse, camera3d);
        const allMeshes = [];
        agentCharacters.forEach(c => c.group.traverse(m => { if (m.isMesh) allMeshes.push(m); }));
        const hits = raycaster.intersectObjects(allMeshes);
        if (hits.length > 0) {
            for (const ac of agentCharacters) {
                let found = false;
                ac.group.traverse(m => { if (m === hits[0].object) found = true; });
                if (found && ac.roleId && typeof showAssignModal === 'function') {
                    showAssignModal(ac.roleId);
                    break;
                }
            }
        }
    });

    animate3d();
}

// ── Lighting ──
function setupLighting(theme) {
    scene3d.add(new THREE.AmbientLight(0x667788, 0.7));
    const sun = new THREE.DirectionalLight(0xffeedd, 0.9);
    sun.position.set(10, 15, 8);
    sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
    const d = 20;
    sun.shadow.camera.left = -d; sun.shadow.camera.right = d;
    sun.shadow.camera.top = d; sun.shadow.camera.bottom = -d;
    scene3d.add(sun);

    const p1 = new THREE.PointLight(theme.accent1, 0.5, 25);
    p1.position.set(-6, 4, 5);
    scene3d.add(p1);
    const p2 = new THREE.PointLight(theme.accent2, 0.4, 25);
    p2.position.set(6, 4, -5);
    scene3d.add(p2);
    const p3 = new THREE.PointLight(theme.accent3, 0.3, 18);
    p3.position.set(0, 5, 0);
    scene3d.add(p3);
}

// ── Room ──
function setupRoom(theme, teamName) {
    officeGroup = new THREE.Group();
    scene3d.add(officeGroup);

    // Use studio scene room dimensions if available, otherwise defaults
    const rW = (studioSceneData && studioSceneData.room_width) || 16;
    const rD = (studioSceneData && studioSceneData.room_depth) || 12;

    const floorMat = new THREE.MeshStandardMaterial({ color: theme.floor, roughness: theme.floorRough, metalness: 0.05 });
    const wallMat = new THREE.MeshStandardMaterial({ color: theme.wall, roughness: theme.wallRough, metalness: 0.05 });
    const trimMat = new THREE.MeshStandardMaterial({ color: theme.trim, roughness: 0.4, metalness: 0.2 });

    // Floor
    const floor = new THREE.Mesh(new THREE.BoxGeometry(rW, 0.15, rD), floorMat);
    floor.position.set(-0.5, -0.075, 0);
    floor.receiveShadow = true;
    officeGroup.add(floor);

    // Walls
    const backWall = new THREE.Mesh(new THREE.BoxGeometry(rW, 3.5, 0.15), wallMat);
    backWall.position.set(-0.5, 1.75, -rD / 2);
    backWall.castShadow = true; backWall.receiveShadow = true;
    officeGroup.add(backWall);
    const leftWall = new THREE.Mesh(new THREE.BoxGeometry(0.15, 3.5, rD), wallMat);
    leftWall.position.set(-0.5 - rW / 2, 1.75, 0);
    leftWall.castShadow = true;
    officeGroup.add(leftWall);

    // Trim lines
    const trimBack = new THREE.Mesh(new THREE.BoxGeometry(rW, 0.12, 0.1), trimMat);
    trimBack.position.set(-0.5, 0.06, -rD / 2 + 0.1);
    officeGroup.add(trimBack);
    const trimTop = new THREE.Mesh(new THREE.BoxGeometry(rW, 0.1, 0.1), trimMat);
    trimTop.position.set(-0.5, 3.45, -rD / 2 + 0.1);
    officeGroup.add(trimTop);

    // Ground plane
    const groundMat = new THREE.MeshStandardMaterial({ color: theme.ground, roughness: 0.9 });
    const ground = new THREE.Mesh(new THREE.PlaneGeometry(100, 100), groundMat);
    ground.rotation.x = -Math.PI / 2; ground.position.y = -0.08;
    ground.receiveShadow = true;
    scene3d.add(ground);

    const grid = new THREE.GridHelper(100, 200, 0x1a1e30, 0x1a1e30);
    grid.position.y = -0.07; grid.material.opacity = 0.2; grid.material.transparent = true;
    scene3d.add(grid);

    // Sign
    const signTex = makeText(teamName.toUpperCase(), colorHex(theme.accent1), 44);
    const signMat = new THREE.MeshBasicMaterial({ map: signTex, transparent: true, side: THREE.DoubleSide });
    const sign = new THREE.Mesh(new THREE.PlaneGeometry(7, 0.9), signMat);
    sign.position.set(-0.5, 2.9, -rD / 2 + 0.12);
    officeGroup.add(sign);

    // Adjust camera for larger rooms
    if (controls3d) {
        controls3d.maxDistance = Math.max(30, Math.max(rW, rD) * 1.5);
    }

    // Theme-specific decorations
    if (theme.special === 'ancient') addAncientDecor(rW, rD);
    if (theme.special === 'futuristic') addFuturisticDecor(rW, rD);
    if (theme.special === 'military') addMilitaryDecor(rW, rD);
}

function addAncientDecor(rW, rD) {
    const hw = rW / 2, hd = rD / 2;
    // Red pillars at corners
    const pillarMat = new THREE.MeshStandardMaterial({ color: 0xc9302c, roughness: 0.5 });
    [[-0.5 - hw + 0.3, -hd + 0.2], [-0.5 - hw + 0.3, hd - 0.2], [-0.5 + hw - 0.3, -hd + 0.2]].forEach(([x, z]) => {
        const pillar = new THREE.Mesh(new THREE.CylinderGeometry(0.18, 0.2, 3.5, 8), pillarMat);
        pillar.position.set(x, 1.75, z);
        pillar.castShadow = true;
        officeGroup.add(pillar);
    });
    // Lanterns on back wall
    const lanternMat = new THREE.MeshStandardMaterial({ color: 0xcc3333, emissive: 0xcc3333, emissiveIntensity: 0.5 });
    [[-0.5 - hw / 2, 2.8, -hd + 0.5], [-0.5 + hw / 3, 2.8, -hd + 0.5]].forEach(([x, y, z]) => {
        const lantern = new THREE.Mesh(new THREE.SphereGeometry(0.2, 8, 6), lanternMat);
        lantern.position.set(x, y, z);
        officeGroup.add(lantern);
        const glow = new THREE.PointLight(0xff4444, 0.3, 5);
        glow.position.set(x, y, z);
        officeGroup.add(glow);
    });
}

function addFuturisticDecor(rW, rD) {
    const hd = rD / 2;
    // Holographic rings
    const holoMat = new THREE.MeshBasicMaterial({ color: 0x22d3ee, transparent: true, opacity: 0.3 });
    for (let i = 0; i < 3; i++) {
        const ring = new THREE.Mesh(new THREE.TorusGeometry(1.5 + i * 0.3, 0.02, 8, 32), holoMat);
        ring.position.set(-0.5, 0.05, 0);
        ring.rotation.x = Math.PI / 2;
        officeGroup.add(ring);
    }
    // Neon strips on back wall
    const stripW = rW - 2;
    const neonMat = new THREE.MeshBasicMaterial({ color: 0xa855f7, transparent: true, opacity: 0.6 });
    const strip = new THREE.Mesh(new THREE.BoxGeometry(stripW, 0.04, 0.02), neonMat);
    strip.position.set(-0.5, 1.5, -hd + 0.12);
    officeGroup.add(strip);
    const strip2 = strip.clone();
    strip2.position.y = 2.5;
    strip2.material = new THREE.MeshBasicMaterial({ color: 0x22d3ee, transparent: true, opacity: 0.4 });
    officeGroup.add(strip2);
}

function addMilitaryDecor(rW, rD) {
    const hw = rW / 2;
    // Sandbags at room edge
    const sbMat = new THREE.MeshStandardMaterial({ color: 0x6b6340, roughness: 0.95 });
    for (let i = 0; i < 4; i++) {
        const sb = new THREE.Mesh(new THREE.BoxGeometry(0.8, 0.3, 0.4), sbMat);
        sb.position.set(-0.5 + hw - 1, 0.15 + i * 0.25, -1 + i * 0.3);
        sb.rotation.y = 0.1 * i;
        officeGroup.add(sb);
    }
}

// ── Load Studio Scene ──
async function loadStudioScene(teamId) {
    studioSceneData = null;
    try {
        const res = await fetch(`/api/v1/studio3d/scenes/${teamId}`);
        if (res.ok) {
            const data = await res.json();
            studioSceneData = data.scene || null;
        }
    } catch (e) {
        console.warn('No studio scene for team', teamId);
    }
}

// ── Render Studio Custom Assets ──
function renderStudioAssets(sceneAssets) {
    sceneAssets.forEach(item => {
        const def = STUDIO_ASSETS.find(a => a.id === item.asset_id);
        if (!def) return;

        const color = new THREE.Color(def.color || '#888888');
        const mat = new THREE.MeshStandardMaterial({ color, roughness: 0.5, metalness: 0.1 });

        let geo;
        const [sx, sy, sz] = def.size || [1, 1, 1];
        switch (def.mesh) {
            case 'cylinder': geo = new THREE.CylinderGeometry(sx, sx, sy, 16); break;
            case 'sphere': geo = new THREE.SphereGeometry(sx, 12, 8); break;
            default: geo = new THREE.BoxGeometry(sx, sy, sz);
        }

        const mesh = new THREE.Mesh(geo, mat);
        mesh.position.set(item.x || 0, def.yOffset || 0.5, item.z || 0);
        mesh.rotation.y = item.rotation || 0;
        mesh.scale.setScalar(item.scale || 1);
        mesh.castShadow = true;
        mesh.receiveShadow = true;

        if (def.emissive) {
            mat.emissive = color;
            mat.emissiveIntensity = 0.5;
        }

        officeGroup.add(mesh);
    });
}

// ── Furniture & Characters (only assigned agents) ──
function buildFurnitureAndCharacters(teamData, agentsList, theme) {
    const nodes = teamData.nodes || [];
    const assignedNodes = nodes.filter(n => n.agent_id && n.agent_id.length > 0);

    if (assignedNodes.length === 0) {
        const emptyTex = makeText('Chưa có agent nào — Bấm 📊 Sơ đồ để gán', '#666677', 26, 600, 48);
        const emptySprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: emptyTex, transparent: true }));
        emptySprite.scale.set(6, 0.6, 1);
        emptySprite.position.set(-0.5, 1.5, 0);
        officeGroup.add(emptySprite);
        return;
    }

    // Use studio desk positions if available, fall back to defaults
    const hasStudio = studioSceneData && studioSceneData.assets && studioSceneData.assets.length > 0;
    const studioDesks = hasStudio
        ? studioSceneData.assets
            .filter(a => a.asset_id && (a.asset_id.startsWith('desk') || a.asset_id === 'table_round'))
        : [];

    // Build a map of agent_id -> desk position from studio assignments
    const agentDeskMap = {};
    studioDesks.forEach(d => {
        if (d.agent_id) agentDeskMap[d.agent_id] = { x: d.x, z: d.z };
    });
    const unassignedDesks = studioDesks.filter(d => !d.agent_id).map(d => ({ x: d.x, z: d.z }));
    let unassignedIdx = 0;

    assignedNodes.forEach((node, idx) => {
        // Priority: assigned desk > unassigned studio desk > default position
        let pos;
        if (agentDeskMap[node.agent_id]) {
            pos = agentDeskMap[node.agent_id];
        } else if (unassignedIdx < unassignedDesks.length) {
            pos = unassignedDesks[unassignedIdx++];
        } else {
            pos = DESK_POS[idx % DESK_POS.length];
        }

        const color = CHAR_COLORS[idx % CHAR_COLORS.length];
        const agent = agentsList.find(a => a.id === node.agent_id);

        // Only build default desks if no studio scene
        if (!hasStudio) {
            buildDesk(pos, theme, idx);
        }
        const charData = buildRobloxCharacter(pos, color, agent, node, theme);
        agentCharacters.push(charData);
    });
}

function buildDesk(pos, theme, idx) {
    const g = new THREE.Group();
    g.position.set(pos.x, 0, pos.z);
    officeGroup.add(g);

    const deskMat = new THREE.MeshStandardMaterial({ color: theme.desk, roughness: 0.5, metalness: 0.1 });
    const detailMat = new THREE.MeshStandardMaterial({ color: theme.deskDetail, roughness: 0.4, metalness: 0.2 });

    if (theme.special === 'ancient') {
        // Low table (案)
        const top = new THREE.Mesh(new THREE.BoxGeometry(1.4, 0.06, 0.8), deskMat);
        top.position.set(0, 0.45, 0); top.castShadow = true; g.add(top);
        // Curved legs
        [[-0.55, -0.3], [-0.55, 0.3], [0.55, -0.3], [0.55, 0.3]].forEach(([lx, lz]) => {
            const leg = new THREE.Mesh(new THREE.BoxGeometry(0.06, 0.45, 0.06), deskMat);
            leg.position.set(lx, 0.225, lz); g.add(leg);
        });
        // Scroll on desk
        const scrollMat = new THREE.MeshStandardMaterial({ color: 0xf5e6c8, roughness: 0.8 });
        const scroll = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.06, 0.5, 8), scrollMat);
        scroll.position.set(0.3, 0.5, 0); scroll.rotation.z = Math.PI / 2; g.add(scroll);
        // Cushion instead of chair
        const cushMat = new THREE.MeshStandardMaterial({ color: theme.chairDetail, roughness: 0.7 });
        const cush = new THREE.Mesh(new THREE.CylinderGeometry(0.25, 0.28, 0.08, 8), cushMat);
        cush.position.set(0, 0.04, 0.65); g.add(cush);
    } else {
        // Modern/futuristic/military desk
        const top = new THREE.Mesh(new THREE.BoxGeometry(1.6, 0.07, 0.9), deskMat);
        top.position.set(0, 0.72, 0); top.castShadow = true; top.receiveShadow = true; g.add(top);
        // Legs
        const legMat = new THREE.MeshStandardMaterial({ color: theme.deskDetail, roughness: 0.6 });
        [[-0.7, -0.35], [-0.7, 0.35], [0.7, -0.35], [0.7, 0.35]].forEach(([lx, lz]) => {
            const leg = new THREE.Mesh(new THREE.BoxGeometry(0.05, 0.72, 0.05), legMat);
            leg.position.set(lx, 0.36, lz); leg.castShadow = true; g.add(leg);
        });
        // Monitor
        if (theme.monitor !== null) {
            const monMat = new THREE.MeshStandardMaterial({ color: theme.monitor, roughness: 0.3, metalness: 0.5 });
            const mon = new THREE.Mesh(new THREE.BoxGeometry(0.7, 0.5, 0.04), monMat);
            mon.position.set(0, 1.05, -0.25); mon.castShadow = true; g.add(mon);
            const scrColor = 0x22c55e;
            const scr = new THREE.Mesh(new THREE.PlaneGeometry(0.6, 0.4),
                new THREE.MeshBasicMaterial({ color: scrColor, transparent: true, opacity: 0.7 }));
            scr.position.set(0, 1.05, -0.22); g.add(scr);
            const stand = new THREE.Mesh(new THREE.BoxGeometry(0.04, 0.2, 0.04), monMat);
            stand.position.set(0, 0.86, -0.25); g.add(stand);
        }
        // Chair
        const chairMat = new THREE.MeshStandardMaterial({ color: theme.chair, roughness: 0.5 });
        const seat = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.06, 0.5), chairMat);
        seat.position.set(0, 0.48, 0.6); g.add(seat);
        const back = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.45, 0.05), chairMat);
        back.position.set(0, 0.72, 0.83); g.add(back);
    }

    // Detail accent strip on desk edge
    const strip = new THREE.Mesh(new THREE.BoxGeometry(1.6, 0.02, 0.02), detailMat);
    strip.position.set(0, theme.special === 'ancient' ? 0.48 : 0.76, theme.special === 'ancient' ? 0.4 : 0.45);
    g.add(strip);
}

// ── Roblox-style character ──
function buildRobloxCharacter(pos, color, agent, node, theme) {
    const group = new THREE.Group();
    const homeY = theme.special === 'ancient' ? 0.25 : 0.0;
    group.position.set(pos.x, homeY, pos.z + 0.55);
    officeGroup.add(group);

    const bodyColor = agent ? new THREE.Color(color) : new THREE.Color(0x555566);
    const skinColor = agent ? 0xf5d0a9 : 0x888899;
    const mat = (c) => new THREE.MeshStandardMaterial({ color: c, roughness: 0.5 });

    // Torso
    const torso = new THREE.Mesh(new THREE.BoxGeometry(0.4, 0.45, 0.22), mat(bodyColor));
    torso.position.y = 0.75; torso.castShadow = true;
    group.add(torso);

    // Head
    const head = new THREE.Mesh(new THREE.BoxGeometry(0.32, 0.32, 0.3), mat(skinColor));
    head.position.y = 1.15; head.castShadow = true;
    group.add(head);

    // Eyes
    const eyeMat = new THREE.MeshBasicMaterial({ color: 0x111111 });
    const eyeL = new THREE.Mesh(new THREE.BoxGeometry(0.06, 0.06, 0.02), eyeMat);
    eyeL.position.set(-0.08, 1.17, 0.16); group.add(eyeL);
    const eyeR = eyeL.clone(); eyeR.position.x = 0.08; group.add(eyeR);
    // Smile
    const smile = new THREE.Mesh(new THREE.BoxGeometry(0.1, 0.03, 0.02), eyeMat);
    smile.position.set(0, 1.08, 0.16); group.add(smile);

    // Left Arm
    const armL = new THREE.Mesh(new THREE.BoxGeometry(0.14, 0.42, 0.14), mat(bodyColor));
    armL.position.set(-0.3, 0.75, 0); armL.castShadow = true;
    group.add(armL);
    // Right Arm
    const armR = armL.clone(); armR.position.x = 0.3;
    group.add(armR);

    // Left Leg
    const legL = new THREE.Mesh(new THREE.BoxGeometry(0.16, 0.4, 0.16), mat(0x334455));
    legL.position.set(-0.1, 0.32, 0); legL.castShadow = true;
    group.add(legL);
    // Right Leg
    const legR = legL.clone(); legR.position.x = 0.1;
    group.add(legR);

    // Name label
    const labelName = agent ? agent.name : node.role.replace(/^[^\s]+\s/, '').substring(0, 20);
    const labelTex = makeText(labelName, '#22d3ee', 30, 384, 48);
    const labelSprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: labelTex, transparent: true, depthTest: false }));
    labelSprite.scale.set(1.8, 0.35, 1);
    labelSprite.position.y = 1.55;
    group.add(labelSprite);

    // Status badge
    const statusColor = agent ? '#22c55e' : '#666677';
    const statusText = agent ? '● online' : '○ trống';
    const statusTex = makeText(statusText, statusColor, 22, 192, 32);
    const statusSprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: statusTex, transparent: true, depthTest: false }));
    statusSprite.scale.set(1.0, 0.2, 1);
    statusSprite.position.y = 1.35;
    group.add(statusSprite);

    // Emoji badge
    const emojiTex = makeText(node.emoji || '🤖', '#ffffff', 36, 64, 64);
    const emojiSprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: emojiTex, transparent: true, depthTest: false }));
    emojiSprite.scale.set(0.4, 0.4, 1);
    emojiSprite.position.y = 1.75;
    group.add(emojiSprite);

    return {
        group,
        roleId: node.role_id,
        agentId: node.agent_id || '',
        hasAgent: !!agent,
        limbs: { armL, armR, legL, legR, head, torso },
        homePos: { x: pos.x, z: pos.z + 0.55 },
        deskPos: { x: pos.x, z: pos.z },  // desk center for facing
        homeY,
        // State machine
        state: 'working',     // working, walking, returning, chatting, looking
        stateTimer: Math.random() * 3 + 2,  // shorter initial timer so they start moving sooner
        targetPos: null,
        walkSpeed: 0.008 + Math.random() * 0.004,
        turnTarget: 0,
        bobPhase: Math.random() * Math.PI * 2,
    };
}

// ── Animation loop ──
let elapsedTime3d = 0;
function animate3d() {
    requestAnimationFrame(animate3d);
    // IMPORTANT: getDelta() must be called BEFORE getElapsedTime()
    // because getElapsedTime() internally calls getDelta() and resets it to ~0
    const dt = clock3d.getDelta();
    elapsedTime3d += dt;
    const t = elapsedTime3d;
    controls3d.update();

    agentCharacters.forEach(ac => {
        if (!ac.hasAgent) {
            // Unassigned: just bob slightly
            ac.group.position.y = ac.homeY + Math.sin(t * 0.8 + ac.bobPhase) * 0.02;
            return;
        }

        ac.stateTimer -= dt;

        switch (ac.state) {
            case 'working': {
                // Face the desk (rotate towards desk, away from camera)
                var deskAngle = Math.atan2(
                    ac.deskPos.x - ac.group.position.x,
                    ac.deskPos.z - ac.group.position.z
                );
                // If at home pos (very close), face default direction (towards desk = Math.PI)
                if (Math.abs(ac.homePos.x - ac.group.position.x) < 0.2 && Math.abs(ac.homePos.z - ac.group.position.z) < 0.2) {
                    deskAngle = Math.PI; // face away from camera
                }
                ac.group.rotation.y = deskAngle;

                // Sit at desk position
                ac.group.position.set(ac.homePos.x, ac.homeY, ac.homePos.z);

                // Typing animation — rapid small arm movements
                ac.limbs.armL.rotation.x = -0.8 + Math.sin(t * 6 + ac.bobPhase) * 0.12;
                ac.limbs.armR.rotation.x = -0.8 + Math.sin(t * 6 + ac.bobPhase + 2) * 0.12;
                ac.limbs.armL.rotation.z = 0.15;
                ac.limbs.armR.rotation.z = -0.15;

                // Head slightly tracking the screen
                ac.limbs.head.rotation.x = -0.1;
                ac.limbs.head.rotation.y = Math.sin(t * 0.3 + ac.bobPhase) * 0.08;

                // Subtle body breathing
                ac.limbs.torso.scale.y = 1 + Math.sin(t * 1.5 + ac.bobPhase) * 0.015;

                // Legs relaxed (not extreme bend)
                ac.limbs.legL.rotation.x = -0.3;
                ac.limbs.legR.rotation.x = -0.3;

                if (ac.stateTimer <= 0) {
                    var rand = Math.random();
                    if (rand < 0.40) {
                        // Stand up and walk — prefer interesting furniture
                        ac.state = 'walking';
                        ac.stateTimer = 4 + Math.random() * 5;
                        ac.targetPos = pickWalkTarget(ac);
                        resetLimbs(ac);
                    } else if (rand < 0.55) {
                        ac.state = 'chatting';
                        ac.stateTimer = 3 + Math.random() * 3;
                        resetLimbs(ac);
                    } else if (rand < 0.65) {
                        ac.state = 'looking';
                        ac.stateTimer = 2 + Math.random() * 3;
                        resetLimbs(ac);
                    } else {
                        // Keep working
                        ac.stateTimer = 3 + Math.random() * 5;
                    }
                }
                break;
            }

            case 'walking':
                // Legs upright for walking
                if (ac.targetPos) {
                    const dx = ac.targetPos.x - ac.group.position.x;
                    const dz = ac.targetPos.z - ac.group.position.z;
                    const dist = Math.sqrt(dx * dx + dz * dz);

                    if (dist > 0.15) {
                        var stepX = dx * ac.walkSpeed * 60 * dt;
                        var stepZ = dz * ac.walkSpeed * 60 * dt;
                        var nextX = ac.group.position.x + stepX;
                        var nextZ = ac.group.position.z + stepZ;

                        // Collision check against furniture
                        var blocked = isBlockedByFurniture(nextX, nextZ, 0.35, ac.group.position.x, ac.group.position.z);
                        if (blocked) {
                            // Steer sideways — perpendicular to direction
                            var perpX = -dz / dist;
                            var perpZ = dx / dist;
                            var sideSign = Math.random() < 0.5 ? 1 : -1;
                            nextX = ac.group.position.x + perpX * 0.15 * sideSign;
                            nextZ = ac.group.position.z + perpZ * 0.15 * sideSign;
                            // If still blocked, skip and pick new target
                            if (isBlockedByFurniture(nextX, nextZ, 0.35, ac.group.position.x, ac.group.position.z)) {
                                ac.targetPos = pickWalkTarget(ac);
                                break;
                            }
                        }

                        ac.group.position.x = nextX;
                        ac.group.position.z = nextZ;
                        ac.group.rotation.y = Math.atan2(dx, dz);
                        // Walking animation: legs and arms swing
                        ac.limbs.legL.rotation.x = Math.sin(t * 8) * 0.5;
                        ac.limbs.legR.rotation.x = Math.sin(t * 8 + Math.PI) * 0.5;
                        ac.limbs.armL.rotation.x = Math.sin(t * 8 + Math.PI) * 0.4;
                        ac.limbs.armR.rotation.x = Math.sin(t * 8) * 0.4;
                        ac.limbs.armL.rotation.z = 0;
                        ac.limbs.armR.rotation.z = 0;
                        // Bob up/down
                        ac.group.position.y = ac.homeY + Math.abs(Math.sin(t * 8)) * 0.06;
                    } else {
                        // Reached destination, wander or go home
                        if (ac.stateTimer > 1.5) {
                            ac.targetPos = pickWalkTarget(ac);
                        } else {
                            ac.targetPos = null;
                        }
                    }
                }
                if (ac.stateTimer <= 0 || !ac.targetPos) {
                    // Return to desk
                    ac.state = 'returning';
                    ac.stateTimer = 6;
                    ac.targetPos = { x: ac.homePos.x, z: ac.homePos.z };
                }
                break;

            case 'returning':
                if (ac.targetPos) {
                    const dx = ac.targetPos.x - ac.group.position.x;
                    const dz = ac.targetPos.z - ac.group.position.z;
                    const dist = Math.sqrt(dx * dx + dz * dz);
                    if (dist > 0.15) {
                        ac.group.position.x += dx * ac.walkSpeed * 60 * dt;
                        ac.group.position.z += dz * ac.walkSpeed * 60 * dt;
                        ac.group.rotation.y = Math.atan2(dx, dz);
                        ac.limbs.legL.rotation.x = Math.sin(t * 8) * 0.5;
                        ac.limbs.legR.rotation.x = Math.sin(t * 8 + Math.PI) * 0.5;
                        ac.limbs.armL.rotation.x = Math.sin(t * 8 + Math.PI) * 0.3;
                        ac.limbs.armR.rotation.x = Math.sin(t * 8) * 0.3;
                        ac.group.position.y = ac.homeY + Math.abs(Math.sin(t * 8)) * 0.05;
                    } else {
                        // Back at desk → start working
                        ac.group.position.set(ac.homePos.x, ac.homeY, ac.homePos.z);
                        resetLimbs(ac);
                        ac.state = 'working';
                        ac.stateTimer = 5 + Math.random() * 10;
                    }
                }
                break;

            case 'looking':
                // Stand near desk, look around the room
                ac.group.position.set(ac.homePos.x, ac.homeY, ac.homePos.z);
                ac.limbs.head.rotation.y = Math.sin(t * 1.2 + ac.bobPhase) * 0.7;
                ac.limbs.head.rotation.x = Math.sin(t * 0.7 + ac.bobPhase) * 0.15;
                ac.limbs.torso.rotation.y = Math.sin(t * 0.6 + ac.bobPhase) * 0.2;
                ac.group.rotation.y = Math.sin(t * 0.4 + ac.bobPhase) * 0.5;
                // Hands on hips
                ac.limbs.armL.rotation.z = 0.4;
                ac.limbs.armR.rotation.z = -0.4;
                ac.limbs.armL.rotation.x = -0.3;
                ac.limbs.armR.rotation.x = -0.3;

                if (ac.stateTimer <= 0) {
                    resetLimbs(ac);
                    ac.state = 'working';
                    ac.stateTimer = 5 + Math.random() * 8;
                }
                break;

            case 'chatting':
                // Face a random direction (simulating talking to someone)
                ac.group.position.set(ac.homePos.x, ac.homeY, ac.homePos.z);
                ac.group.rotation.y = ac.bobPhase; // consistent direction

                // Wave right arm while talking
                ac.limbs.armR.rotation.x = Math.sin(t * 3) * 0.5 - 0.4;
                ac.limbs.armR.rotation.z = -0.35;
                // Left arm relaxed
                ac.limbs.armL.rotation.x = -0.15;
                ac.limbs.armL.rotation.z = 0.1;
                // Head nodding
                ac.limbs.head.rotation.x = Math.sin(t * 2.5) * 0.12;
                ac.limbs.head.rotation.y = Math.sin(t * 0.8) * 0.15;
                // Subtle weight shift
                ac.limbs.torso.rotation.y = Math.sin(t * 0.5) * 0.05;

                if (ac.stateTimer <= 0) {
                    resetLimbs(ac);
                    ac.state = 'working';
                    ac.stateTimer = 4 + Math.random() * 6;
                }
                break;
        }
    });

    if (particlesMesh) particlesMesh.rotation.y = t * 0.015;

    renderer3d.render(scene3d, camera3d);
}

// Helper: check if position (px, pz) with radius collides with any furniture
// Only block LARGE obstacles: bookshelf, sofa, cabinet, wall_segment, whiteboard
const SOLID_ASSETS = ['bookshelf', 'sofa', 'cabinet', 'wall_segment', 'whiteboard', 'desk_modern', 'desk_wood', 'monitor'];
function isBlockedByFurniture(px, pz, radius, currentX, currentZ) {
    if (!studioSceneData || !studioSceneData.assets) return false;
    for (var i = 0; i < studioSceneData.assets.length; i++) {
        var a = studioSceneData.assets[i];
        if (!SOLID_ASSETS.includes(a.asset_id)) continue;
        var catalog = STUDIO_ASSETS.find(c => c.id === a.asset_id);
        if (!catalog) continue;
        // Half-sizes of the asset bounding box (XZ plane)
        var hw = (catalog.size[0] * (a.scale || 1)) / 2 + radius;
        var hd = (catalog.size[2] * (a.scale || 1)) / 2 + radius;
        // Skip if character is already inside this object (avoid getting stuck)
        if (currentX !== undefined && Math.abs(currentX - a.x) < hw && Math.abs(currentZ - a.z) < hd) {
            continue;
        }
        // AABB check
        if (Math.abs(px - a.x) < hw && Math.abs(pz - a.z) < hd) {
            return true;
        }
    }
    return false;
}

// Helper: pick a walk destination — prefer interesting furniture objects
const INTERESTING_ASSETS = ['bookshelf','sofa','table_round','plant_pot','whiteboard','cabinet','lantern','door_frame'];
function pickWalkTarget(ac) {
    // 70% chance: walk to a nearby furniture piece
    if (studioSceneData && studioSceneData.assets && Math.random() < 0.7) {
        const interesting = studioSceneData.assets.filter(a => INTERESTING_ASSETS.includes(a.asset_id));
        if (interesting.length > 0) {
            const target = interesting[Math.floor(Math.random() * interesting.length)];
            // Stand near the object (offset 0.5-1 unit away)
            const offsetAngle = Math.random() * Math.PI * 2;
            const offsetDist = 0.5 + Math.random() * 0.8;
            return {
                x: target.x + Math.cos(offsetAngle) * offsetDist,
                z: target.z + Math.sin(offsetAngle) * offsetDist,
            };
        }
    }
    // Fallback: random walk near home
    const angle = Math.random() * Math.PI * 2;
    const dist = 1.5 + Math.random() * 3;
    return {
        x: ac.homePos.x + Math.cos(angle) * dist,
        z: ac.homePos.z + Math.sin(angle) * dist,
    };
}

// Helper: reset all limb rotations
function resetLimbs(ac) {
    ac.limbs.armL.rotation.set(0, 0, 0);
    ac.limbs.armR.rotation.set(0, 0, 0);
    ac.limbs.legL.rotation.set(0, 0, 0);
    ac.limbs.legR.rotation.set(0, 0, 0);
    ac.limbs.head.rotation.set(0, 0, 0);
    ac.limbs.torso.rotation.set(0, 0, 0);
    ac.limbs.torso.scale.y = 1;
    ac.group.rotation.y = 0;
}

// ── Particles ──
function setupParticles(theme) {
    const count = 150;
    const geo = new THREE.BufferGeometry();
    const pos = new Float32Array(count * 3);
    for (let i = 0; i < count; i++) {
        pos[i * 3] = (Math.random() - 0.5) * 30;
        pos[i * 3 + 1] = 0.5 + Math.random() * 8;
        pos[i * 3 + 2] = (Math.random() - 0.5) * 30;
    }
    geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    const mat = new THREE.PointsMaterial({ color: theme.accent1, size: 0.04, transparent: true, opacity: 0.3 });
    particlesMesh = new THREE.Points(geo, mat);
    scene3d.add(particlesMesh);
}

// ── Text texture ──
function makeText(text, color = '#ffffff', fontSize = 32, w = 512, h = 64) {
    const c = document.createElement('canvas');
    c.width = w; c.height = h;
    const ctx = c.getContext('2d');
    ctx.clearRect(0, 0, w, h);
    // Glow
    ctx.shadowColor = color;
    ctx.shadowBlur = 10;
    ctx.font = `bold ${fontSize}px Inter, Arial, sans-serif`;
    ctx.fillStyle = color;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(text, w / 2, h / 2);
    // Sharp
    ctx.shadowBlur = 0;
    ctx.fillStyle = '#ffffff';
    ctx.globalAlpha = 0.6;
    ctx.fillText(text, w / 2, h / 2);
    const tex = new THREE.CanvasTexture(c);
    tex.needsUpdate = true;
    return tex;
}

function colorHex(num) {
    return '#' + num.toString(16).padStart(6, '0');
}
