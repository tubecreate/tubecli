/**
 * ═══════════════════════════════════════════════════════════════════
 *  TubeCLI Workflow Builder — Core Canvas Engine
 *  Pan/zoom canvas, drag-and-drop nodes, SVG bezier connections
 * ═══════════════════════════════════════════════════════════════════
 */

const WF = (() => {
  // ── State ──────────────────────────────────────────────────────
  const state = {
    nodes: [],          // { id, type, x, y, config, inputs[], outputs[], _el }
    connections: [],     // { id, from_node_id, from_port_id, to_node_id, to_port_id }
    nodeTypes: [],       // From API
    selectedNodeId: null,
    nextNodeNum: 1,

    // Canvas
    zoom: 1,
    panX: -25000,
    panY: -25000,
    OFFSET: 25000,
    isPanning: false,
    panStartX: 0,
    panStartY: 0,
    panStartPanX: 0,
    panStartPanY: 0,

    // Node drag
    draggingNode: null,
    dragOffsetX: 0,
    dragOffsetY: 0,

    // Port connection drag
    connectingFrom: null, // { nodeId, portId, isInput, x, y }
    tempLine: null,

    // Undo
    undoStack: [],

    // Execution
    isRunning: false,
  };

  // ── DOM refs ───────────────────────────────────────────────────
  let $canvas, $wrapper, $svg, $paletteList, $panelBody, $panelTitle, $logBody, $logStatus;

  // ── Init ───────────────────────────────────────────────────────
  function init() {
    $canvas = document.getElementById('canvas');
    $wrapper = document.getElementById('canvas-wrapper');
    $svg = document.getElementById('connections-svg');
    $paletteList = document.getElementById('palette-list');
    $panelBody = document.getElementById('panel-body');
    $panelTitle = document.getElementById('panel-title');
    $logBody = document.getElementById('log-body');
    $logStatus = document.getElementById('log-status');

    setupCanvasEvents();
    setupKeyboard();
    fetchNodeTypes();
    updateCanvasTransform();
  }

  // ── Fetch node types from API ──────────────────────────────────
  async function fetchNodeTypes() {
    try {
      const resp = await fetch('/api/v1/nodes');
      const data = await resp.json();
      state.nodeTypes = data.nodes || [];
      renderPalette();
    } catch (e) {
      console.warn('Failed to fetch node types, using defaults', e);
      state.nodeTypes = getDefaultNodeTypes();
      renderPalette();
    }
  }

  function getDefaultNodeTypes() {
    return [
      { type: 'text_input', name: 'Text Input', icon: '📝', category: 'Input', description: 'Manual text input' },
      { type: 'loop', name: 'Loop', icon: '🔄', category: 'Processing', description: 'Loop through items' },
      { type: 'api_request', name: 'API Request', icon: '🌐', category: 'Network', description: 'HTTP request' },
      { type: 'python_code', name: 'Python Code', icon: '🐍', category: 'Logic', description: 'Run Python' },
      { type: 'run_command', name: 'Run Command', icon: '💻', category: 'Logic', description: 'Shell command' },
      { type: 'ai_node', name: 'AI Inference', icon: '🧠', category: 'AI', description: 'AI processing (Ollama)' },
      { type: 'output', name: 'Output', icon: '📤', category: 'Output', description: 'Save output' },
      // New nodes
      { type: 'google_auth', name: 'Google Auth', icon: '🔐', category: 'Auth', description: 'Google API authentication' },
      { type: 'google_sheets', name: 'Google Sheets', icon: '📊', category: 'Integration', description: 'Read/Write Google Sheets' },
      { type: 'browser_action', name: 'Browser Action', icon: '🌐', category: 'Browser', description: 'Browser with profile system' },
      { type: 'json_parser', name: 'JSON Parser', icon: '📋', category: 'Data', description: 'Parse/extract/merge JSON' },
      { type: 'model_agent', name: 'Model Agent', icon: '🤖', category: 'AI', description: 'Multi-provider AI (Gemini, GPT, Claude, Grok)' },
      { type: 'custom', name: 'Custom Node', icon: '⚙️', category: 'Custom', description: 'User-defined code + ports' },
      { type: 'if_node', name: 'IF Condition', icon: '🔀', category: 'Logic', description: 'Conditional branching' },
      { type: 'switch_node', name: 'Switch', icon: '🔃', category: 'Logic', description: 'Multi-way routing' },
      { type: 'merge_node', name: 'Merge', icon: '🔗', category: 'Logic', description: 'Combine data streams' },
    ];
  }

  // ── Palette Rendering ──────────────────────────────────────────
  function renderPalette(filter = '') {
    const cats = {};
    const lf = filter.toLowerCase();
    state.nodeTypes.forEach(nt => {
      if (lf && !nt.name.toLowerCase().includes(lf) && !nt.type.toLowerCase().includes(lf)) return;
      const cat = nt.category || 'General';
      if (!cats[cat]) cats[cat] = [];
      cats[cat].push(nt);
    });

    $paletteList.innerHTML = '';
    const catColors = {
      'Input': 'var(--cat-input)', 'Output': 'var(--cat-output)',
      'Processing': 'var(--cat-processing)', 'Logic': 'var(--cat-logic)',
      'AI': 'var(--cat-ai)', 'Automation': 'var(--cat-automation)',
    };

    for (const [cat, nodes] of Object.entries(cats)) {
      const catEl = document.createElement('div');
      catEl.className = 'palette-category';
      catEl.innerHTML = `<div class="palette-category-label">${cat}</div>`;

      nodes.forEach(nt => {
        const item = document.createElement('div');
        item.className = 'palette-item';
        item.draggable = true;
        item.dataset.type = nt.type;
        const color = catColors[cat] || 'var(--cat-general)';
        const icon = nt.icon || '📦';
        const name = nt.name.startsWith(icon) ? nt.name.replace(icon, '').trim() : nt.name;
        item.innerHTML = `
          <div class="palette-item-icon" style="background:${color}20; color:${color}">${icon}</div>
          <span class="palette-item-name">${name}</span>
        `;
        item.addEventListener('dragstart', e => {
          e.dataTransfer.setData('node-type', nt.type);
          e.dataTransfer.effectAllowed = 'copy';
        });
        item.addEventListener('dblclick', () => addNode(nt.type));
        catEl.appendChild(item);
      });
      $paletteList.appendChild(catEl);
    }
  }

  function filterPalette(val) { renderPalette(val); }

  // ── Canvas Events ──────────────────────────────────────────────
  function setupCanvasEvents() {
    // Drop from palette
    $wrapper.addEventListener('dragover', e => { e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; });
    $wrapper.addEventListener('drop', e => {
      e.preventDefault();
      const type = e.dataTransfer.getData('node-type');
      if (type) {
        const rect = $wrapper.getBoundingClientRect();
        const x = (e.clientX - rect.left - state.panX) / state.zoom;
        const y = (e.clientY - rect.top - state.panY) / state.zoom;
        addNode(type, x, y);
      }
    });

    // Pan: middle mouse or space+drag
    $wrapper.addEventListener('mousedown', e => {
      if (e.button === 1 || (e.button === 0 && e.target === $canvas || e.target.classList.contains('canvas-grid'))) {
        if (e.button === 1 || e.target === $canvas || e.target.classList.contains('canvas-grid')) {
          state.isPanning = true;
          state.panStartX = e.clientX;
          state.panStartY = e.clientY;
          state.panStartPanX = state.panX;
          state.panStartPanY = state.panY;
          $wrapper.classList.add('panning');
          e.preventDefault();
        }
      }
    });

    window.addEventListener('mousemove', e => {
      if (state.isPanning) {
        state.panX = state.panStartPanX + (e.clientX - state.panStartX);
        state.panY = state.panStartPanY + (e.clientY - state.panStartY);
        updateCanvasTransform();
      }
      if (state.draggingNode) {
        handleNodeDrag(e);
      }
      if (state.connectingFrom) {
        handlePortDragMove(e);
      }
    });

    window.addEventListener('mouseup', e => {
      if (state.isPanning) {
        state.isPanning = false;
        $wrapper.classList.remove('panning');
      }
      if (state.draggingNode) {
        state.draggingNode = null;
      }
      if (state.connectingFrom) {
        handlePortDragEnd(e);
      }
    });

    // Zoom: scroll
    $wrapper.addEventListener('wheel', e => {
      e.preventDefault();
      const delta = e.deltaY > 0 ? -0.08 : 0.08;
      const newZoom = Math.max(0.2, Math.min(3, state.zoom + delta));

      // Zoom towards mouse
      const rect = $wrapper.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;

      const worldX = (mx - state.panX) / state.zoom;
      const worldY = (my - state.panY) / state.zoom;

      state.zoom = newZoom;
      state.panX = mx - worldX * state.zoom;
      state.panY = my - worldY * state.zoom;

      updateCanvasTransform();
    }, { passive: false });

    // Canvas click = deselect
    $wrapper.addEventListener('click', e => {
      if (e.target === $canvas || e.target.classList.contains('canvas-grid')) {
        selectNode(null);
      }
    });

    // Context menu
    $wrapper.addEventListener('contextmenu', e => {
      e.preventDefault();
      const menu = document.getElementById('context-menu');
      if (state.selectedNodeId) {
        menu.style.left = e.clientX + 'px';
        menu.style.top = e.clientY + 'px';
        menu.classList.add('visible');
      }
    });
    document.addEventListener('click', () => {
      document.getElementById('context-menu').classList.remove('visible');
    });
  }

  function updateCanvasTransform() {
    $canvas.style.transform = `translate(${state.panX}px, ${state.panY}px) scale(${state.zoom})`;
    const pct = Math.round(state.zoom * 100);
    const l1 = document.getElementById('zoom-label');
    const l2 = document.getElementById('zoom-label2');
    if (l1) l1.textContent = pct + '%';
    if (l2) l2.textContent = pct + '%';
  }

  // ── Keyboard ───────────────────────────────────────────────────
  function setupKeyboard() {
    document.addEventListener('keydown', e => {
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

      if (e.key === 'Delete' || e.key === 'Backspace') {
        deleteSelected();
      }
      if (e.ctrlKey && e.key === 'z') {
        e.preventDefault();
        undo();
      }
    });
  }

  // ── Port Definitions ───────────────────────────────────────────
  function getPortDefs(type) {
    const defs = {
      'text_input':   { inputs: [], outputs: [{ name: 'content', type: 'text' }, { name: 'lines', type: 'json' }] },
      'loop':         { inputs: [{ name: 'items', type: 'json' }], outputs: [{ name: 'current_item', type: 'text' }, { name: 'index', type: 'text' }] },
      'api_request':  { inputs: [{ name: 'trigger', type: 'any' }, { name: 'url', type: 'text' }], outputs: [{ name: 'response', type: 'json' }, { name: 'status', type: 'text' }] },
      'python_code':  { inputs: [{ name: 'text_input', type: 'text' }, { name: 'json_input', type: 'json' }], outputs: [{ name: 'result', type: 'any' }] },
      'run_command':  { inputs: [{ name: 'trigger', type: 'any' }], outputs: [{ name: 'stdout', type: 'text' }, { name: 'stderr', type: 'text' }] },
      'ai_node':      { inputs: [{ name: 'prompt', type: 'text' }], outputs: [{ name: 'response', type: 'text' }] },
      'output':       { inputs: [{ name: 'data', type: 'any' }], outputs: [] },
      // New nodes
      'google_auth':     { inputs: [], outputs: [{ name: 'credentials', type: 'json' }, { name: 'status', type: 'text' }] },
      'google_sheets':   { inputs: [{ name: 'credentials', type: 'json' }, { name: 'data', type: 'json' }, { name: 'range', type: 'text' }], outputs: [{ name: 'rows', type: 'json' }, { name: 'status', type: 'text' }] },
      'browser_action':  { inputs: [{ name: 'url', type: 'text' }, { name: 'prompt', type: 'text' }, { name: 'data', type: 'any' }], outputs: [{ name: 'result', type: 'text' }, { name: 'screenshot_path', type: 'text' }, { name: 'status', type: 'text' }] },
      'json_parser':     { inputs: [{ name: 'data', type: 'any' }, { name: 'expression', type: 'text' }], outputs: [{ name: 'result', type: 'any' }, { name: 'keys', type: 'json' }, { name: 'count', type: 'text' }] },
      'model_agent':     { inputs: [{ name: 'prompt', type: 'text' }, { name: 'context', type: 'text' }, { name: 'history', type: 'json' }], outputs: [{ name: 'response', type: 'text' }, { name: 'usage', type: 'json' }] },
      'custom':          { inputs: [{ name: 'input', type: 'any' }], outputs: [{ name: 'output', type: 'any' }] },
      'if_node':         { inputs: [{ name: 'data', type: 'any' }], outputs: [{ name: 'true_output', type: 'any' }, { name: 'false_output', type: 'any' }] },
      'switch_node':     { inputs: [{ name: 'data', type: 'any' }], outputs: [{ name: 'output_0', type: 'any' }, { name: 'output_1', type: 'any' }, { name: 'output_2', type: 'any' }, { name: 'output_3', type: 'any' }] },
      'merge_node':      { inputs: [{ name: 'input_1', type: 'any' }, { name: 'input_2', type: 'any' }], outputs: [{ name: 'merged', type: 'any' }] },
    };
    return defs[type] || { inputs: [{ name: 'input', type: 'any' }], outputs: [{ name: 'output', type: 'any' }] };
  }

  // ── Config Field Definitions ───────────────────────────────────
  function getConfigFields(type) {
    const fields = {
      'text_input': [{ name: 'text', label: 'Text Content', type: 'textarea', default: '' }],
      'loop': [{ name: 'delay_ms', label: 'Delay (ms)', type: 'number', default: 500 }],
      'api_request': [
        { name: 'url', label: 'URL', type: 'text', default: '' },
        { name: 'method', label: 'Method', type: 'select', default: 'GET', options: ['GET','POST','PUT','DELETE'] },
        { name: 'headers', label: 'Headers (JSON)', type: 'textarea', default: '{}' },
        { name: 'body', label: 'Body', type: 'textarea', default: '' },
      ],
      'python_code': [{ name: 'code', label: 'Python Code', type: 'textarea', default: '# Input available as `input_data`\nresult = input_data' }],
      'run_command': [
        { name: 'command', label: 'Command', type: 'textarea', default: '' },
        { name: 'cwd', label: 'Working Dir', type: 'text', default: '' },
      ],
      'ai_node': [
        { name: 'system_prompt', label: 'System Prompt', type: 'textarea', default: 'You are a helpful assistant.' },
        { name: 'model', label: 'Model', type: 'text', default: 'qwen:latest' },
      ],
      'output': [
        { name: 'filename', label: 'Filename', type: 'text', default: 'output.txt' },
      ],
      // New nodes
      'google_auth': [
        { name: 'credentials_json', label: 'Service Account JSON', type: 'textarea', default: '' },
        { name: 'scopes', label: 'Scopes (comma sep)', type: 'text', default: 'https://www.googleapis.com/auth/spreadsheets' },
      ],
      'google_sheets': [
        { name: 'spreadsheet_id', label: 'Spreadsheet ID', type: 'text', default: '' },
        { name: 'sheet_name', label: 'Sheet Name', type: 'text', default: 'Sheet1' },
        { name: 'range', label: 'Range', type: 'text', default: 'A1:Z1000' },
        { name: 'action', label: 'Action', type: 'select', default: 'read', options: ['read', 'write', 'append', 'update'] },
      ],
      'browser_action': [
        { name: 'profile_name', label: 'Browser Profile', type: 'text', default: '' },
        { name: 'action', label: 'Action', type: 'select', default: 'navigate', options: ['navigate', 'run_prompt', 'manual'] },
        { name: 'url', label: 'URL', type: 'text', default: '' },
        { name: 'prompt', label: 'AI Prompt', type: 'textarea', default: '' },
        { name: 'headless', label: 'Headless', type: 'select', default: 'false', options: ['false', 'true'] },
        { name: 'ai_model', label: 'AI Model', type: 'text', default: 'qwen:latest' },
        { name: 'wait_seconds', label: 'Wait (seconds)', type: 'number', default: 10 },
      ],
      'json_parser': [
        { name: 'action', label: 'Action', type: 'select', default: 'parse', options: ['parse', 'stringify', 'extract', 'filter', 'merge', 'transform'] },
        { name: 'expression', label: 'Path Expression', type: 'text', default: '' },
      ],
      'model_agent': [
        { name: 'provider', label: 'Provider', type: 'select', default: 'ollama', options: ['ollama', 'gemini', 'chatgpt', 'claude', 'grok'] },
        { name: 'model', label: 'Model', type: 'text', default: 'qwen:latest' },
        { name: 'api_key', label: 'API Key', type: 'text', default: '' },
        { name: 'system_prompt', label: 'System Prompt', type: 'textarea', default: 'You are a helpful assistant.' },
        { name: 'temperature', label: 'Temperature', type: 'number', default: 0.7 },
        { name: 'max_tokens', label: 'Max Tokens', type: 'number', default: 2048 },
        { name: 'agent_name', label: 'Use Agent Config (name)', type: 'text', default: '' },
      ],
      'custom': [
        { name: 'code', label: 'Python Code', type: 'textarea', default: 'output = input' },
        { name: 'input_ports', label: 'Input Ports (JSON array)', type: 'text', default: '["input"]' },
        { name: 'output_ports', label: 'Output Ports (JSON array)', type: 'text', default: '["output"]' },
      ],
      'if_node': [
        { name: 'value1', label: 'Value 1', type: 'text', default: '' },
        { name: 'operator', label: 'Operator', type: 'select', default: 'equals', options: ['equals','not_equals','contains','not_contains','starts_with','ends_with','greater_than','less_than','is_empty','is_not_empty','regex'] },
        { name: 'value2', label: 'Value 2', type: 'text', default: '' },
        { name: 'condition', label: 'Python Expression (advanced)', type: 'text', default: '' },
      ],
      'switch_node': [
        { name: 'field', label: 'Field to Match', type: 'text', default: '' },
        { name: 'rules', label: 'Rules JSON', type: 'textarea', default: '[{"value": "a", "output": 0}, {"value": "b", "output": 1}]' },
      ],
      'merge_node': [
        { name: 'mode', label: 'Mode', type: 'select', default: 'append', options: ['append', 'combine', 'join'] },
        { name: 'join_key', label: 'Join Key (for join mode)', type: 'text', default: '' },
      ],
    };
    return fields[type] || [];
  }

  // ── Port color ─────────────────────────────────────────────────
  function portColor(ptype) {
    const colors = { 'text': 'var(--port-text)', 'json': 'var(--port-json)', 'file': 'var(--port-file)', 'any': 'var(--port-any)' };
    return colors[ptype] || 'var(--port-any)';
  }

  // ── Category color ─────────────────────────────────────────────
  function catColor(type) {
    const nt = state.nodeTypes.find(n => n.type === type);
    const cat = nt ? nt.category : 'General';
    const colors = {
      'Input': '#3b82f6', 'Output': '#22c55e', 'Processing': '#f97316',
      'Logic': '#eab308', 'AI': '#a855f7', 'Automation': '#06b6d4',
      'Network': '#f97316', 'Auth': '#ef4444', 'Integration': '#10b981',
      'Browser': '#06b6d4', 'Data': '#3b82f6', 'Custom': '#8b5cf6',
    };
    return colors[cat] || '#6366f1';
  }

  // ── Add Node ───────────────────────────────────────────────────
  function addNode(type, x, y) {
    const nt = state.nodeTypes.find(n => n.type === type);
    if (!nt && !getPortDefs(type)) return;

    if (x == null) { x = state.OFFSET + 200 + state.nodes.length * 60; }
    if (y == null) { y = state.OFFSET + 150 + state.nodes.length * 40; }

    const portDefs = getPortDefs(type);
    const id = 'node_' + crypto.randomUUID().slice(0, 8);

    const node = {
      id,
      type,
      x, y,
      config: {},
      inputs: portDefs.inputs.map(p => ({ id: 'port_' + crypto.randomUUID().slice(0, 8), name: p.name, port_type: p.type })),
      outputs: portDefs.outputs.map(p => ({ id: 'port_' + crypto.randomUUID().slice(0, 8), name: p.name, port_type: p.type })),
      _el: null,
    };

    // Set default config
    getConfigFields(type).forEach(f => { node.config[f.name] = f.default; });

    state.nodes.push(node);
    renderNode(node);
    selectNode(node.id);
    toast(`Added ${nt ? nt.name : type}`, 'success');
    return node;
  }

  // ── Render Node DOM ────────────────────────────────────────────
  function renderNode(node) {
    const nt = state.nodeTypes.find(n => n.type === node.type);
    const color = catColor(node.type);
    const el = document.createElement('div');
    el.className = 'workflow-node';
    el.id = 'node-' + node.id;
    el.style.left = node.x + 'px';
    el.style.top = node.y + 'px';

    const title = node.label || (nt ? nt.name : node.type);
    const icon = nt ? nt.icon : '📦';
    const cleanTitle = icon && title.startsWith(icon) ? title.replace(icon, '').trim() : title;

    // Header
    let html = `
      <div class="node-header" style="background: ${color}15">
        <div class="node-icon" style="background:${color}30; color:${color}">${icon}</div>
        <div class="node-title">${cleanTitle}</div>
        <div class="node-delete" onclick="WF.deleteNode('${node.id}')">✕</div>
      </div>
      <div class="node-body">
    `;

    // Input ports
    node.inputs.forEach(p => {
      const c = portColor(p.port_type);
      const connected = isPortConnected(p.id) ? ' connected' : '';
      html += `
        <div class="node-port-row input">
          <div class="port input${connected}" id="port-${p.id}" data-port-id="${p.id}" data-node-id="${node.id}" data-is-input="true" style="border-color:${c}; color:${c}"></div>
          <span class="port-label input">${p.name}</span>
        </div>
      `;
    });

    // Output ports
    node.outputs.forEach(p => {
      const c = portColor(p.port_type);
      const connected = isPortConnected(p.id) ? ' connected' : '';
      html += `
        <div class="node-port-row output">
          <span class="port-label output">${p.name}</span>
          <div class="port output${connected}" id="port-${p.id}" data-port-id="${p.id}" data-node-id="${node.id}" data-is-input="false" style="border-color:${c}; color:${c}"></div>
        </div>
      `;
    });

    html += '</div>';
    el.innerHTML = html;

    // Node drag
    el.addEventListener('mousedown', e => {
      if (e.target.classList.contains('port') || e.target.classList.contains('node-delete')) return;
      e.stopPropagation();
      selectNode(node.id);
      state.draggingNode = node;
      const rect = $wrapper.getBoundingClientRect();
      state.dragOffsetX = (e.clientX - rect.left - state.panX) / state.zoom - node.x;
      state.dragOffsetY = (e.clientY - rect.top - state.panY) / state.zoom - node.y;
    });

    // Port drag (connection)
    el.querySelectorAll('.port').forEach(portEl => {
      portEl.addEventListener('mousedown', e => {
        e.stopPropagation();
        const portId = portEl.dataset.portId;
        const nodeId = portEl.dataset.nodeId;
        const isInput = portEl.dataset.isInput === 'true';
        const rect = portEl.getBoundingClientRect();
        const wrapperRect = $wrapper.getBoundingClientRect();
        const px = (rect.left + rect.width / 2 - wrapperRect.left - state.panX) / state.zoom;
        const py = (rect.top + rect.height / 2 - wrapperRect.top - state.panY) / state.zoom;
        state.connectingFrom = { nodeId, portId, isInput, x: px, y: py };
        createTempLine(px, py, px, py);
      });
    });

    node._el = el;
    $canvas.appendChild(el);
  }

  // ── Node Drag ──────────────────────────────────────────────────
  function handleNodeDrag(e) {
    const node = state.draggingNode;
    if (!node) return;
    const wrapperRect = $wrapper.getBoundingClientRect();
    node.x = (e.clientX - wrapperRect.left - state.panX) / state.zoom - state.dragOffsetX;
    node.y = (e.clientY - wrapperRect.top - state.panY) / state.zoom - state.dragOffsetY;
    node._el.style.left = node.x + 'px';
    node._el.style.top = node.y + 'px';
    redrawConnections();
  }

  // ── Port Connection Drag ───────────────────────────────────────
  function handlePortDragMove(e) {
    if (!state.connectingFrom) return;
    const wrapperRect = $wrapper.getBoundingClientRect();
    const mx = (e.clientX - wrapperRect.left - state.panX) / state.zoom;
    const my = (e.clientY - wrapperRect.top - state.panY) / state.zoom;
    updateTempLine(state.connectingFrom.x, state.connectingFrom.y, mx, my);
  }

  function handlePortDragEnd(e) {
    removeTempLine();
    if (!state.connectingFrom) return;

    // Find port under mouse
    const target = document.elementFromPoint(e.clientX, e.clientY);
    if (target && target.classList.contains('port')) {
      const toPortId = target.dataset.portId;
      const toNodeId = target.dataset.nodeId;
      const toIsInput = target.dataset.isInput === 'true';
      const from = state.connectingFrom;

      // Validate: must be different direction and different node
      if (from.nodeId !== toNodeId && from.isInput !== toIsInput) {
        const fromPortId = from.isInput ? toPortId : from.portId;
        const fromNodeId = from.isInput ? toNodeId : from.nodeId;
        const tpId = from.isInput ? from.portId : toPortId;
        const tnId = from.isInput ? from.nodeId : toNodeId;

        // Check not duplicate
        const exists = state.connections.some(c =>
          c.from_port_id === fromPortId && c.to_port_id === tpId
        );
        if (!exists) {
          createConnection(fromNodeId, fromPortId, tnId, tpId);
        }
      }
    }
    state.connectingFrom = null;
  }

  // ── Connections ────────────────────────────────────────────────
  function createConnection(fromNodeId, fromPortId, toNodeId, toPortId) {
    const conn = {
      id: 'conn_' + crypto.randomUUID().slice(0, 8),
      from_node_id: fromNodeId,
      from_port_id: fromPortId,
      to_node_id: toNodeId,
      to_port_id: toPortId,
    };
    state.connections.push(conn);
    updatePortVisuals(fromPortId, true);
    updatePortVisuals(toPortId, true);
    redrawConnections();
    toast('🔗 Connected', 'info');
  }

  function isPortConnected(portId) {
    return state.connections.some(c => c.from_port_id === portId || c.to_port_id === portId);
  }

  function updatePortVisuals(portId, connected) {
    const el = document.getElementById('port-' + portId);
    if (el) {
      if (connected) el.classList.add('connected');
      else el.classList.remove('connected');
    }
  }

  function getPortWorldPos(portId) {
    const portEl = document.getElementById('port-' + portId);
    if (!portEl) return null;
    const rect = portEl.getBoundingClientRect();
    const wrapperRect = $wrapper.getBoundingClientRect();
    return {
      x: (rect.left + rect.width / 2 - wrapperRect.left - state.panX) / state.zoom,
      y: (rect.top + rect.height / 2 - wrapperRect.top - state.panY) / state.zoom,
    };
  }

  function redrawConnections() {
    // Remove all existing paths except temp
    $svg.querySelectorAll('path:not(.temp-connection)').forEach(p => p.remove());

    state.connections.forEach(conn => {
      const fromPos = getPortWorldPos(conn.from_port_id);
      const toPos = getPortWorldPos(conn.to_port_id);
      if (!fromPos || !toPos) return;

      const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      const dx = Math.abs(toPos.x - fromPos.x) * 0.5;
      const d = `M ${fromPos.x} ${fromPos.y} C ${fromPos.x + dx} ${fromPos.y}, ${toPos.x - dx} ${toPos.y}, ${toPos.x} ${toPos.y}`;
      path.setAttribute('d', d);

      // Get port color
      const fromNode = state.nodes.find(n => n.id === conn.from_node_id);
      const fromPort = fromNode ? fromNode.outputs.find(p => p.id === conn.from_port_id) : null;
      const color = fromPort ? portColor(fromPort.port_type) : 'var(--port-any)';
      path.setAttribute('stroke', color);
      path.dataset.connId = conn.id;

      // Click to delete connection
      path.style.pointerEvents = 'visibleStroke';
      path.style.cursor = 'pointer';
      path.addEventListener('dblclick', () => {
        deleteConnection(conn.id);
      });

      $svg.appendChild(path);
    });
  }

  function deleteConnection(connId) {
    const conn = state.connections.find(c => c.id === connId);
    if (!conn) return;
    state.connections = state.connections.filter(c => c.id !== connId);
    // Update port visuals
    if (!isPortConnected(conn.from_port_id)) updatePortVisuals(conn.from_port_id, false);
    if (!isPortConnected(conn.to_port_id)) updatePortVisuals(conn.to_port_id, false);
    redrawConnections();
    toast('Disconnected', 'info');
  }

  // ── Temp connection line ───────────────────────────────────────
  function createTempLine(x1, y1, x2, y2) {
    removeTempLine();
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.classList.add('temp-connection');
    path.setAttribute('stroke', '#6366f1');
    updateTempLinePath(path, x1, y1, x2, y2);
    $svg.appendChild(path);
    state.tempLine = path;
  }

  function updateTempLine(x1, y1, x2, y2) {
    if (state.tempLine) updateTempLinePath(state.tempLine, x1, y1, x2, y2);
  }

  function updateTempLinePath(path, x1, y1, x2, y2) {
    const dx = Math.abs(x2 - x1) * 0.5;
    const d = `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
    path.setAttribute('d', d);
  }

  function removeTempLine() {
    if (state.tempLine) { state.tempLine.remove(); state.tempLine = null; }
  }

  // ── Selection ──────────────────────────────────────────────────
  function selectNode(nodeId) {
    // Deselect previous
    if (state.selectedNodeId) {
      const prev = document.getElementById('node-' + state.selectedNodeId);
      if (prev) prev.classList.remove('selected');
    }
    state.selectedNodeId = nodeId;
    if (nodeId) {
      const el = document.getElementById('node-' + nodeId);
      if (el) el.classList.add('selected');
      renderPropertyPanel(nodeId);
    } else {
      renderEmptyPanel();
    }
  }

  // ── Property Panel ─────────────────────────────────────────────
  function renderPropertyPanel(nodeId) {
    const node = state.nodes.find(n => n.id === nodeId);
    if (!node) { renderEmptyPanel(); return; }

    const nt = state.nodeTypes.find(n => n.type === node.type);
    $panelTitle.textContent = `⚙️ ${nt ? nt.name : node.type}`;

    const fields = getConfigFields(node.type);
    let html = '';

    // Node label
    html += `
      <div class="field-group">
        <label class="field-label">Node Label</label>
        <input class="field-input" type="text" value="${node.label || ''}" onchange="WF.updateConfig('${nodeId}', '_label', this.value)">
      </div>
    `;

    fields.forEach(f => {
      const val = node.config[f.name] ?? f.default ?? '';
      html += `<div class="field-group"><label class="field-label">${f.label}</label>`;

      if (f.type === 'textarea') {
        html += `<textarea class="field-textarea" rows="4" onchange="WF.updateConfig('${nodeId}', '${f.name}', this.value)">${val}</textarea>`;
      } else if (f.type === 'select') {
        html += `<select class="field-select" onchange="WF.updateConfig('${nodeId}', '${f.name}', this.value)">`;
        (f.options || []).forEach(opt => {
          html += `<option value="${opt}" ${opt === val ? 'selected' : ''}>${opt}</option>`;
        });
        html += '</select>';
      } else if (f.type === 'number') {
        html += `<input class="field-input" type="number" value="${val}" onchange="WF.updateConfig('${nodeId}', '${f.name}', Number(this.value))">`;
      } else {
        html += `<input class="field-input" type="text" value="${val}" onchange="WF.updateConfig('${nodeId}', '${f.name}', this.value)">`;
      }
      html += '</div>';
    });

    $panelBody.innerHTML = html;
  }

  function renderEmptyPanel() {
    $panelTitle.textContent = '⚙️ Properties';
    $panelBody.innerHTML = '<div class="panel-empty"><div class="panel-empty-icon">🖱️</div><span>Click a node to edit</span></div>';
  }

  function updateConfig(nodeId, key, value) {
    const node = state.nodes.find(n => n.id === nodeId);
    if (!node) return;
    if (key === '_label') { 
      node.label = value; 
      // Update DOM title immediately
      const el = document.getElementById('node-' + nodeId);
      if (el) {
        const nt = state.nodeTypes.find(n => n.type === node.type);
        const title = value || (nt ? nt.name : node.type);
        const icon = nt ? nt.icon : '📦';
        const cleanTitle = icon && title.startsWith(icon) ? title.replace(icon, '').trim() : title;
        el.querySelector('.node-title').textContent = cleanTitle;
      }
    }
    else { node.config[key] = value; }
  }

  // ── Delete ─────────────────────────────────────────────────────
  function deleteNode(nodeId) {
    const node = state.nodes.find(n => n.id === nodeId);
    if (!node) return;

    // Save undo
    const delConns = state.connections.filter(c => c.from_node_id === nodeId || c.to_node_id === nodeId);
    state.undoStack.push({ action: 'delete', node: { ...node, _el: null }, connections: delConns });

    // Remove connections
    state.connections = state.connections.filter(c => c.from_node_id !== nodeId && c.to_node_id !== nodeId);

    // Remove DOM
    if (node._el) node._el.remove();
    state.nodes = state.nodes.filter(n => n.id !== nodeId);

    if (state.selectedNodeId === nodeId) selectNode(null);
    redrawConnections();
    toast('🗑️ Deleted (Ctrl+Z to undo)', 'info');
  }

  function deleteSelected() {
    if (state.selectedNodeId) deleteNode(state.selectedNodeId);
  }

  function duplicateSelected() {
    if (!state.selectedNodeId) return;
    const node = state.nodes.find(n => n.id === state.selectedNodeId);
    if (!node) return;
    const newNode = addNode(node.type, node.x + 40, node.y + 40);
    if (newNode) {
      newNode.config = { ...node.config };
      renderPropertyPanel(newNode.id);
    }
  }

  // ── Undo ───────────────────────────────────────────────────────
  function undo() {
    const action = state.undoStack.pop();
    if (!action) return;
    if (action.action === 'delete') {
      const node = action.node;
      state.nodes.push(node);
      renderNode(node);
      action.connections.forEach(c => state.connections.push(c));
      redrawConnections();
      selectNode(node.id);
      toast('↩️ Restored', 'info');
    }
  }

  // ── Zoom ───────────────────────────────────────────────────────
  function zoomIn() { state.zoom = Math.min(3, state.zoom + 0.15); updateCanvasTransform(); redrawConnections(); }
  function zoomOut() { state.zoom = Math.max(0.2, state.zoom - 0.15); updateCanvasTransform(); redrawConnections(); }
  function zoomFit() {
    if (state.nodes.length === 0) return;
    const xs = state.nodes.map(n => n.x);
    const ys = state.nodes.map(n => n.y);
    const minX = Math.min(...xs) - 100;
    const minY = Math.min(...ys) - 100;
    const maxX = Math.max(...xs) + 300;
    const maxY = Math.max(...ys) + 200;

    const wrapperRect = $wrapper.getBoundingClientRect();
    const scaleX = wrapperRect.width / (maxX - minX);
    const scaleY = wrapperRect.height / (maxY - minY);
    state.zoom = Math.max(0.2, Math.min(1.5, Math.min(scaleX, scaleY)));
    state.panX = -minX * state.zoom + 50;
    state.panY = -minY * state.zoom + 50;
    updateCanvasTransform();
    setTimeout(redrawConnections, 50);
  }

  // ── Serialize / Deserialize ────────────────────────────────────
  function toJSON() {
    return {
      nodes: state.nodes.map(n => ({
        id: n.id, type: n.type, x: n.x, y: n.y, label: n.label || '',
        config: n.config,
        inputs: n.inputs.map(p => ({ id: p.id, name: p.name })),
        outputs: n.outputs.map(p => ({ id: p.id, name: p.name })),
      })),
      connections: state.connections.map(c => ({
        from_node_id: c.from_node_id, from_port_id: c.from_port_id,
        to_node_id: c.to_node_id, to_port_id: c.to_port_id,
      })),
    };
  }

  function fromJSON(data) {
    clearAll();
    (data.nodes || []).forEach(nd => {
      const portDefs = getPortDefs(nd.type);
      const node = {
        id: nd.id,
        type: nd.type,
        x: nd.x || state.OFFSET + 200,
        y: nd.y || state.OFFSET + 150,
        label: nd.label || '',
        config: nd.config || {},
        inputs: (nd.inputs || portDefs.inputs).map((p, i) => ({
          id: p.id || 'port_' + crypto.randomUUID().slice(0, 8),
          name: p.name || (portDefs.inputs[i] ? portDefs.inputs[i].name : 'input'),
          port_type: p.port_type || (portDefs.inputs[i] ? portDefs.inputs[i].type : 'any'),
        })),
        outputs: (nd.outputs || portDefs.outputs).map((p, i) => ({
          id: p.id || 'port_' + crypto.randomUUID().slice(0, 8),
          name: p.name || (portDefs.outputs[i] ? portDefs.outputs[i].name : 'output'),
          port_type: p.port_type || (portDefs.outputs[i] ? portDefs.outputs[i].type : 'any'),
        })),
        _el: null,
      };
      state.nodes.push(node);
      renderNode(node);
    });

    (data.connections || []).forEach(c => {
      state.connections.push({ id: 'conn_' + crypto.randomUUID().slice(0, 8), ...c });
      updatePortVisuals(c.from_port_id, true);
      updatePortVisuals(c.to_port_id, true);
    });

    setTimeout(redrawConnections, 100);
  }

  // ── Clear ──────────────────────────────────────────────────────
  function clearAll() {
    state.nodes.forEach(n => { if (n._el) n._el.remove(); });
    state.nodes = [];
    state.connections = [];
    state.selectedNodeId = null;
    state.undoStack = [];
    $svg.querySelectorAll('path').forEach(p => p.remove());
    renderEmptyPanel();
  }

  // ── Save / Load ────────────────────────────────────────────────
  async function saveWorkflow() {
    const data = toJSON();
    const name = prompt('Workflow name:', 'my_workflow');
    if (!name) return;
    try {
      const resp = await fetch('/api/v1/workflows', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, workflow_data: data }),
      });
      if (resp.ok) toast('💾 Saved!', 'success');
      else toast('Save failed', 'error');
    } catch (e) {
      // Fallback: download as file
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = name + '.json'; a.click();
      URL.revokeObjectURL(url);
      toast('💾 Downloaded as file', 'success');
    }
  }

  function loadWorkflow() {
    document.getElementById('file-load').click();
  }

  function handleFileLoad(event) {
    const file = event.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (e) => {
      try {
        const data = JSON.parse(e.target.result);
        fromJSON(data);
        toast('📂 Loaded!', 'success');
      } catch (err) {
        toast('Invalid JSON file', 'error');
      }
    };
    reader.readAsText(file);
    event.target.value = '';
  }

  function newWorkflow() {
    if (state.nodes.length > 0 && !confirm('Clear current workflow?')) return;
    clearAll();
    toast('📄 New workflow', 'info');
  }

  // ── n8n Import / Export ────────────────────────────────────────
  function importN8n() {
    document.getElementById('file-n8n').click();
  }

  function handleN8nImport(event) {
    const file = event.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (e) => {
      try {
        const n8nData = JSON.parse(e.target.result);
        const tcData = N8nBridge.toTubeCLI(n8nData);
        fromJSON(tcData);
        toast(`📥 Imported ${tcData.nodes.length} nodes from n8n`, 'success');
      } catch (err) {
        console.error(err);
        toast('n8n import failed: ' + err.message, 'error');
      }
    };
    reader.readAsText(file);
    event.target.value = '';
  }

  function exportN8n() {
    const tcData = toJSON();
    const n8nData = N8nBridge.toN8n(tcData);
    const blob = new Blob([JSON.stringify(n8nData, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = 'workflow_n8n.json'; a.click();
    URL.revokeObjectURL(url);
    toast('📤 Exported n8n JSON', 'success');
  }

  // ── Save as Skill ─────────────────────────────────────────────
  function saveAsSkill() {
    if (state.nodes.length === 0) { toast('No nodes to save', 'error'); return; }
    
    // Reset fields and show modal
    document.getElementById('skill-name-input').value = 'My Workflow Skill';
    document.getElementById('skill-trigger-input').value = '';
    document.getElementById('skill-desc-input').value = '';
    document.getElementById('save-skill-modal').classList.add('visible');
    document.getElementById('skill-name-input').focus();
  }

  async function submitSaveSkill() {
    const name = document.getElementById('skill-name-input').value.trim();
    const trigger = document.getElementById('skill-trigger-input').value.trim();
    const description = document.getElementById('skill-desc-input').value.trim();

    if (!name) {
      toast('Skill Name is required', 'error');
      return;
    }

    const data = toJSON();
    try {
      const resp = await fetch('/api/v1/workflows/save-as-skill', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, description, trigger, workflow_data: data }),
      });
      const result = await resp.json();
      if (result.status === 'created' || result.status === 'updated') {
        toast(`✅ ${result.message}`, 'success');
        document.getElementById('save-skill-modal').classList.remove('visible');
      } else {
        toast('❌ Failed: ' + (result.detail || 'Unknown error'), 'error');
      }
    } catch (e) {
      toast('❌ Save failed: ' + e.message, 'error');
    }
  }

  // ── Run Workflow ───────────────────────────────────────────────
  async function runWorkflow() {
    if (state.isRunning) return;
    if (state.nodes.length === 0) { toast('No nodes to run', 'error'); return; }
    state.isRunning = true;
    $logStatus.textContent = '🔄 Running...';
    addLog('engine', 'Workflow Engine', 'started', 'Starting workflow...');

    const data = toJSON();
    try {
      const resp = await fetch('/api/v1/workflows/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workflow_data: data }),
      });
      const result = await resp.json();

      if (result.logs) {
        result.logs.forEach(l => addLog(l.node_id, l.node_name, l.status, l.message));
      }
      $logStatus.textContent = result.status === 'completed' ? '✅ Done' : '⚠️ ' + result.status;
      toast('Workflow finished', result.status === 'completed' ? 'success' : 'error');
    } catch (e) {
      addLog('engine', 'Error', 'error', e.message);
      $logStatus.textContent = '❌ Error';
      toast('Run failed: ' + e.message, 'error');
    }
    state.isRunning = false;
  }

  function stopWorkflow() {
    toast('Stop requested', 'info');
    state.isRunning = false;
    $logStatus.textContent = '⏹ Stopped';
  }

  // ── Logs ───────────────────────────────────────────────────────
  function addLog(nodeId, nodeName, status, message) {
    const time = new Date().toLocaleTimeString('en', { hour12: false });
    const entry = document.createElement('div');
    entry.className = 'log-entry ' + status;
    entry.innerHTML = `<span class="log-time">${time}</span> <span class="log-node">[${nodeName}]</span> ${message}`;
    $logBody.appendChild(entry);
    $logBody.scrollTop = $logBody.scrollHeight;
  }

  function clearLogs() { $logBody.innerHTML = ''; $logStatus.textContent = '⏸️ Ready'; }

  // ── Toast ──────────────────────────────────────────────────────
  function toast(msg, type = 'info') {
    const el = document.createElement('div');
    el.className = 'toast ' + type;
    el.textContent = msg;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 3000);
  }

  // ── Boot ───────────────────────────────────────────────────────
  document.addEventListener('DOMContentLoaded', init);

  // ── Public API ─────────────────────────────────────────────────
  return {
    addNode, deleteNode, deleteSelected, duplicateSelected, selectNode,
    updateConfig, filterPalette,
    saveWorkflow, loadWorkflow, handleFileLoad, newWorkflow,
    importN8n, exportN8n, handleN8nImport,
    saveAsSkill, submitSaveSkill,
    runWorkflow, stopWorkflow, clearLogs,
    zoomIn, zoomOut, zoomFit, undo,
    toJSON, fromJSON, toast,
    state, // expose for debugging
  };
})();
