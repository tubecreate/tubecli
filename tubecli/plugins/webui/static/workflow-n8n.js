/**
 * ═══════════════════════════════════════════════════════════════════
 *  n8n ↔ TubeCLI Workflow JSON Bridge
 *  Import/Export converter for n8n workflow format
 * ═══════════════════════════════════════════════════════════════════
 */

const N8nBridge = (() => {

  // ── Node Type Mapping ──────────────────────────────────────────
  const N8N_TO_TC = {
    'n8n-nodes-base.httpRequest':       'api_request',
    'n8n-nodes-base.code':              'python_code',
    'n8n-nodes-base.executeCommand':    'run_command',
    'n8n-nodes-base.set':               'text_input',
    'n8n-nodes-base.manualTrigger':     'text_input',
    'n8n-nodes-base.splitInBatches':    'loop',
    'n8n-nodes-base.openAi':            'ai_node',
    'n8n-nodes-base.writeBinaryFile':   'output',
    'n8n-nodes-base.readWriteFile':     'output',
    'n8n-nodes-base.noOp':              'text_input',
    // New mappings
    'n8n-nodes-base.google':            'google_auth',
    'n8n-nodes-base.googleSheets':      'google_sheets',
    'n8n-nodes-base.puppeteer':         'browser_action',
    'n8n-nodes-base.if':                'if_node',
    'n8n-nodes-base.switch':            'switch_node',
    'n8n-nodes-base.merge':             'merge_node',
  };

  const TC_TO_N8N = {};
  for (const [k, v] of Object.entries(N8N_TO_TC)) {
    if (!TC_TO_N8N[v]) TC_TO_N8N[v] = k;
  }
  // Preferred mappings (override duplicates)
  TC_TO_N8N['text_input']      = 'n8n-nodes-base.set';
  TC_TO_N8N['api_request']     = 'n8n-nodes-base.httpRequest';
  TC_TO_N8N['python_code']     = 'n8n-nodes-base.code';
  TC_TO_N8N['run_command']     = 'n8n-nodes-base.executeCommand';
  TC_TO_N8N['loop']            = 'n8n-nodes-base.splitInBatches';
  TC_TO_N8N['ai_node']         = 'n8n-nodes-base.openAi';
  TC_TO_N8N['output']          = 'n8n-nodes-base.writeBinaryFile';
  // New mappings
  TC_TO_N8N['google_auth']     = 'n8n-nodes-base.google';
  TC_TO_N8N['google_sheets']   = 'n8n-nodes-base.googleSheets';
  TC_TO_N8N['browser_action']  = 'n8n-nodes-base.puppeteer';
  TC_TO_N8N['json_parser']     = 'n8n-nodes-base.set';
  TC_TO_N8N['model_agent']     = 'n8n-nodes-base.openAi';
  TC_TO_N8N['custom']          = 'n8n-nodes-base.code';
  TC_TO_N8N['if_node']         = 'n8n-nodes-base.if';
  TC_TO_N8N['switch_node']     = 'n8n-nodes-base.switch';
  TC_TO_N8N['merge_node']      = 'n8n-nodes-base.merge';

  // ── n8n → TubeCLI ─────────────────────────────────────────────
  function toTubeCLI(n8nData) {
    const nodes = [];
    const connections = [];
    const nodeNameToId = {};
    const OFFSET = 25000;

    // 1. Convert nodes
    (n8nData.nodes || []).forEach((n8nNode, idx) => {
      const tcType = N8N_TO_TC[n8nNode.type] || 'text_input';
      const id = n8nNode.id || ('node_n8n_' + idx);
      const pos = n8nNode.position || [300 + idx * 250, 200];

      const node = {
        id: id,
        type: tcType,
        x: pos[0] + OFFSET,
        y: pos[1] + OFFSET,
        label: n8nNode.name || '',
        config: convertN8nParams(tcType, n8nNode.parameters || {}),
        inputs: getDefaultPorts(tcType, true),
        outputs: getDefaultPorts(tcType, false),
      };

      nodeNameToId[n8nNode.name] = id;
      nodes.push(node);
    });

    // 2. Convert connections
    // n8n format: { "NodeName": { "main": [[{ "node": "TargetName", "type": "main", "index": 0 }]] } }
    if (n8nData.connections && typeof n8nData.connections === 'object') {
      for (const [fromName, outputs] of Object.entries(n8nData.connections)) {
        const fromId = nodeNameToId[fromName];
        if (!fromId) continue;
        const fromNode = nodes.find(n => n.id === fromId);
        if (!fromNode) continue;

        const mainOutputs = outputs.main || [];
        mainOutputs.forEach((targets, outputIdx) => {
          if (!Array.isArray(targets)) return;
          targets.forEach(target => {
            const toId = nodeNameToId[target.node];
            if (!toId) return;
            const toNode = nodes.find(n => n.id === toId);
            if (!toNode) return;

            const fromPortId = fromNode.outputs[outputIdx] ? fromNode.outputs[outputIdx].id : (fromNode.outputs[0] ? fromNode.outputs[0].id : null);
            const inputIdx = target.index || 0;
            const toPortId = toNode.inputs[inputIdx] ? toNode.inputs[inputIdx].id : (toNode.inputs[0] ? toNode.inputs[0].id : null);

            if (fromPortId && toPortId) {
              connections.push({
                from_node_id: fromId,
                from_port_id: fromPortId,
                to_node_id: toId,
                to_port_id: toPortId,
              });
            }
          });
        });
      }
    }

    return { nodes, connections };
  }

  // ── TubeCLI → n8n ─────────────────────────────────────────────
  function toN8n(tcData) {
    const OFFSET = 25000;
    const nodeIdToName = {};
    const n8nNodes = [];

    // 1. Convert nodes
    (tcData.nodes || []).forEach((tcNode, idx) => {
      const n8nType = TC_TO_N8N[tcNode.type] || 'n8n-nodes-base.set';
      const name = tcNode.label || tcNode.type + '_' + idx;
      nodeIdToName[tcNode.id] = name;

      n8nNodes.push({
        id: tcNode.id,
        name: name,
        type: n8nType,
        typeVersion: 1,
        position: [
          Math.round((tcNode.x || OFFSET) - OFFSET),
          Math.round((tcNode.y || OFFSET) - OFFSET),
        ],
        parameters: convertTcParams(tcNode.type, tcNode.config || {}),
      });
    });

    // 2. Convert connections
    const n8nConnections = {};
    (tcData.connections || []).forEach(conn => {
      const fromName = nodeIdToName[conn.from_node_id];
      const toName = nodeIdToName[conn.to_node_id];
      if (!fromName || !toName) return;

      // Determine output index
      const fromNode = tcData.nodes.find(n => n.id === conn.from_node_id);
      let outputIdx = 0;
      if (fromNode) {
        const oi = (fromNode.outputs || []).findIndex(p => p.id === conn.from_port_id);
        if (oi >= 0) outputIdx = oi;
      }

      // Determine input index
      const toNode = tcData.nodes.find(n => n.id === conn.to_node_id);
      let inputIdx = 0;
      if (toNode) {
        const ii = (toNode.inputs || []).findIndex(p => p.id === conn.to_port_id);
        if (ii >= 0) inputIdx = ii;
      }

      if (!n8nConnections[fromName]) n8nConnections[fromName] = { main: [] };
      while (n8nConnections[fromName].main.length <= outputIdx) {
        n8nConnections[fromName].main.push([]);
      }
      n8nConnections[fromName].main[outputIdx].push({
        node: toName,
        type: 'main',
        index: inputIdx,
      });
    });

    return {
      name: 'TubeCLI Export',
      nodes: n8nNodes,
      connections: n8nConnections,
      active: false,
      settings: { executionOrder: 'v1' },
      meta: { instanceId: 'tubecli-export' },
    };
  }

  // ── Helpers ────────────────────────────────────────────────────
  function convertN8nParams(tcType, params) {
    const config = {};
    switch (tcType) {
      case 'api_request':
        config.url = params.url || '';
        config.method = params.method || params.requestMethod || 'GET';
        config.headers = params.headerParameters ? JSON.stringify(params.headerParameters) : '{}';
        config.body = params.body || params.jsonBody || '';
        break;
      case 'python_code':
        config.code = params.jsCode || params.code || params.pythonCode || '# Imported from n8n';
        break;
      case 'run_command':
        config.command = params.command || '';
        config.cwd = params.cwd || '';
        break;
      case 'text_input':
        if (params.values && params.values.string) {
          const vals = params.values.string.map(v => `${v.name}=${v.value}`).join('\n');
          config.text = vals;
        } else {
          config.text = params.text || JSON.stringify(params);
        }
        break;
      case 'loop':
        config.delay_ms = params.batchSize ? 500 : 500;
        break;
      case 'ai_node':
      case 'model_agent':
        config.system_prompt = params.systemMessage || 'You are a helpful assistant.';
        config.model = params.model || 'qwen:latest';
        config.provider = params.provider || 'ollama';
        config.api_key = params.apiKey || '';
        break;
      case 'output':
        config.filename = params.fileName || 'output.txt';
        break;
      case 'google_sheets':
        config.spreadsheet_id = params.documentId || params.spreadsheetId || '';
        config.sheet_name = params.sheetName || 'Sheet1';
        config.range = params.range || 'A1:Z1000';
        config.action = params.operation || 'read';
        break;
      case 'google_auth':
        config.scopes = params.scopes || 'https://www.googleapis.com/auth/spreadsheets';
        break;
      case 'browser_action':
        config.url = params.url || '';
        config.action = params.action || 'navigate';
        config.profile_name = params.profileName || '';
        break;
      case 'if_node':
        config.value1 = params.value1 || '';
        config.operator = params.operation || 'equals';
        config.value2 = params.value2 || '';
        break;
      case 'switch_node':
        config.field = params.dataPropertyName || '';
        break;
      case 'merge_node':
        config.mode = params.mode || 'append';
        config.join_key = params.joinKey || '';
        break;
      default:
        Object.assign(config, params);
    }
    return config;
  }

  function convertTcParams(tcType, config) {
    const params = {};
    switch (tcType) {
      case 'api_request':
        params.url = config.url || '';
        params.method = config.method || 'GET';
        break;
      case 'python_code':
        params.jsCode = config.code || '';
        break;
      case 'run_command':
        params.command = config.command || '';
        break;
      case 'text_input':
        params.values = { string: [{ name: 'text', value: config.text || '' }] };
        break;
      case 'ai_node':
      case 'model_agent':
        params.model = config.model || 'qwen:latest';
        params.systemMessage = config.system_prompt || '';
        if (config.provider) params.provider = config.provider;
        if (config.api_key) params.apiKey = config.api_key;
        break;
      case 'output':
        params.fileName = config.filename || 'output.txt';
        break;
      case 'google_sheets':
        params.documentId = config.spreadsheet_id || '';
        params.sheetName = config.sheet_name || 'Sheet1';
        params.range = config.range || '';
        params.operation = config.action || 'read';
        break;
      case 'google_auth':
        params.scopes = config.scopes || '';
        break;
      case 'browser_action':
        params.url = config.url || '';
        params.action = config.action || 'navigate';
        params.profileName = config.profile_name || '';
        break;
      case 'if_node':
        params.value1 = config.value1 || '';
        params.operation = config.operator || 'equals';
        params.value2 = config.value2 || '';
        break;
      case 'switch_node':
        params.dataPropertyName = config.field || '';
        break;
      case 'merge_node':
        params.mode = config.mode || 'append';
        params.joinKey = config.join_key || '';
        break;
      default:
        Object.assign(params, config);
    }
    return params;
  }

  function getDefaultPorts(type, isInputs) {
    const portDefs = {
      'text_input':      { inputs: [], outputs: ['content', 'lines'] },
      'loop':            { inputs: ['items'], outputs: ['current_item', 'index'] },
      'api_request':     { inputs: ['trigger', 'url'], outputs: ['response', 'status'] },
      'python_code':     { inputs: ['input'], outputs: ['output'] },
      'run_command':     { inputs: ['trigger'], outputs: ['stdout', 'stderr'] },
      'ai_node':         { inputs: ['prompt'], outputs: ['response'] },
      'output':          { inputs: ['data'], outputs: [] },
      // New nodes
      'google_auth':     { inputs: [], outputs: ['credentials', 'status'] },
      'google_sheets':   { inputs: ['credentials', 'data', 'range'], outputs: ['rows', 'status'] },
      'browser_action':  { inputs: ['url', 'prompt', 'data'], outputs: ['result', 'screenshot_path', 'status'] },
      'json_parser':     { inputs: ['data', 'expression'], outputs: ['result', 'keys', 'count'] },
      'model_agent':     { inputs: ['prompt', 'context', 'history'], outputs: ['response', 'usage'] },
      'custom':          { inputs: ['input'], outputs: ['output'] },
      'if_node':         { inputs: ['data'], outputs: ['true_output', 'false_output'] },
      'switch_node':     { inputs: ['data'], outputs: ['output_0', 'output_1', 'output_2', 'output_3'] },
      'merge_node':      { inputs: ['input_1', 'input_2'], outputs: ['merged'] },
    };
    const defs = portDefs[type] || { inputs: ['input'], outputs: ['output'] };
    const names = isInputs ? defs.inputs : defs.outputs;
    return names.map(name => ({
      id: 'port_' + crypto.randomUUID().slice(0, 8),
      name: name,
    }));
  }

  return { toTubeCLI, toN8n };
})();
