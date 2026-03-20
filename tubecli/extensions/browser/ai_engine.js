import axios from 'axios';

const LOCAL_AI_URL = 'http://localhost:5295/api/v1/localai/chat/completions';

/**
 * AI Engine to map natural language prompts to browser action sequences.
 */
export class AIEngine {
  constructor(model = 'deepseek-r1:latest') {
    this.model = model;
    this.actions = [
      { name: 'navigate', description: 'Go to a specific URL directly', params: ['url'] },
      { name: 'type', description: 'Type text into an input or the page', params: ['text', 'selector (optional)'] },
      { name: 'save_image', description: 'Detect and save the generated image on page', params: [] },
      { name: 'search', description: 'Search for a keyword on Google', params: ['keyword'] },
      { name: 'browse', description: 'Scroll and move mouse naturally', params: ['iterations'] },
      { name: 'click', description: 'Click on a result or selector', params: ['selector (optional)'] },
      { name: 'login', description: 'Login to Google/account', params: ['email', 'password'] },
      { name: 'comment', description: 'Post a context-aware comment', params: ['instruction (optional)'] },
      { name: 'watch', description: 'Watch video for specific time', params: ['duration (e.g. 50-100s)'] },
      { name: 'visual_scan', description: 'Analyze screen with AI and suggest actions', params: [] }
    ];
  }

  /**
   * Analyzes a prompt and returns a list of actions with parameters and optional metadata.
   * @param {string} prompt 
   * @returns {Promise<{actions: Array<{action: string, params: object}>, profile?: string}>}
   */
  async planActions(prompt, stats = null) {
    console.log(`AI is thinking about: "${prompt}"...`);
    
    let statsContext = "";
    if (stats) {
        statsContext = `
7. RPG STATS (YOU ARE A "${stats.class.toUpperCase()}" - Level ${stats.level}):
   - INT (Intelligence): ${stats.int}
   - IMPACT (Contribution): ${stats.impact}
   - ASSIST (Support): ${stats.assist}
   - MISTAKE (Errors): ${stats.mistake}
   - KDA: ${stats.kda}
   
   GUIDELINES FOR "${stats.class.toUpperCase()}":
   ${stats.class === 'Scholar' ? '- Focus on reading, researching, and using technical keywords.' : ''}
   ${stats.class === 'Builder' ? '- Focus on creating content, typing prompts, and generating value.' : ''}
   ${stats.class === 'Supporter' ? '- Focus on watching videos, liking, and clicking useful links.' : ''}
   ${stats.class === 'Novice' ? '- Explore randomly to gain experience.' : ''}
   
   GOAL: Improve your lowest stat while fulfilling the user's request.
`;
    }

    const systemPrompt = `You are a browser automation orchestrator. 
Your job is to convert user instructions into a JSON sequence of browser actions.

CRITICAL RULES:
1. COMPLETENESS: DO NOT skip steps. If the user says "type X then save", you MUST include both 'type' and 'save_image'.
2. SEARCH FLOW: Always 'click' after 'search' to enter the site.
3. NO Hallucinated Comments: NEVER use 'comment' for instructions like "if Cloudflare appears". Do NOT add "verify" steps unless explicitly requested.
4. SITE BREAKDOWN:
   - "nhập/prompt/tạo/vẽ/viết [Text]": {"action": "type", "params": {"text": "..."}}
     * CRITICAL: If the user wants an IMAGE, prepend "Create an image of: " to the text.
     * CRITICAL: If the user wants a VIDEO, prepend "Create a video of: " to the text.
   - "lưu ảnh/save image": {"action": "save_image", "params": {}}
   - "bấm/submit": {"action": "click", "params": {"type": "enter"}}
5. USE ONLY THESE ACTIONS:
${JSON.stringify(this.actions, null, 2)}
6. PROFILE: Extract 'mở profile "xyz"' into ROOT "profile".
${statsContext}

Example Output: {
  "profile": "bbb",
  "actions": [
    {"action": "navigate", "params": {"url": "https://chatgpt.com"}},
    {"action": "type", "params": {"text": "Create an image of: con mèo"}},
    {"action": "click", "params": {"type": "enter"}},
    {"action": "save_image", "params": {}}
  ]
}
NOTE: Only add verification steps if explicitly asked or if navigation fails.
`;

    try {
      console.log(`Sending request to Local AI (Model: ${this.model})...`);
      const response = await axios.post(LOCAL_AI_URL, {
        model: this.model,
        messages: [
          { role: 'system', content: systemPrompt },
          { role: 'user', content: prompt }
        ],
        stream: false
      }, { timeout: 180000 }); // 180s for DeepSeek-R1 reasoning

      let content = response.data.choices[0].message.content;
      console.log('AI Response:', content);
      
      // Clean up <think> tags if present (common in reasoning models)
      content = content.replace(/<think>[\s\S]*?<\/think>/gi, '').trim();

      // Attempt 1: Extract from ```json code block
      const codeBlockMatch = content.match(/```json([\s\S]*?)```/);
      if (codeBlockMatch) {
         try {
            return JSON.parse(codeBlockMatch[1]);
         } catch (e) { console.warn('Failed to parse JSON code block:', e.message); }
      }

      // Attempt 2: Extract largest JSON object
      const jsonMatch = content.match(/\{[\s\S]*\}/);
      if (jsonMatch) {
        try {
            return JSON.parse(jsonMatch[0]);
        } catch (e) { console.warn('Failed to parse regex-matched JSON:', e.message); }
      }
      
      // Attempt 3: Direct parse
      const parsed = JSON.parse(content);
      return Array.isArray(parsed) ? { actions: parsed } : parsed;
    } catch (error) {
      console.error('AI Thinking Error:', error.message);
      if (error.response) {
          console.error('AI Server Status:', error.response.status);
          console.error('AI Server Data:', error.response.data);
      }
      
      console.warn('⚠️ AI ANALYSIS FAILED - Using Regex Fallback Logic');
      console.warn('This may result in less accurate action parsing.');
      
      // Sequential Fallback logic
      let actions = [];
      let profile = null;

      // Extract Profile if mentioned
      const profileMatch = prompt.match(/mở\s+profile\s+['"]([^'"]+)['"]/i) || prompt.match(/profile\s+['"]?([^'"]+)['"]?/i);
      if (profileMatch) {
        profile = profileMatch[1];
        // Remove profile part from prompt to avoid double-matching search/navigate
        prompt = prompt.replace(profileMatch[0], '');
      }

      const actionMarkers = [
        { key: 'navigate', patterns: [/vào\s+(https?:\/\/[^\s]+)/i, /vào\s+grok/i, /vào\s+google/i, /vào\s+youtube/i, /truy\s+cập/i] },
        { key: 'search', patterns: [/tìm\s+kiếm/i, /search/i, /tìm/i, /find/i] },
        { key: 'type', patterns: [/nhập/i, /type/i, /gõ/i, /với\s+prompt/i, /prompt\s+['"]?([^'"]+)['"]?/i, /tạo\s+hình/i, /vẽ\s+hình/i, /vẽ/i, /tạo/i, /viết/i] },
        { key: 'browse', patterns: [/lướt\s+web/i, /lướt/i, /browse/i, /scroll/i, /wait/i, /đợi/i, /chờ/i] },
        { key: 'watch', patterns: [/xem\s+video/i, /watch/i, /xem/i, /view/i] },
        { key: 'click', patterns: [/bấm\s+vào/i, /click\s+vào/i, /click/i, /bấm/i, /tap/i, /cloudflare/i, /check/i, /verify/i] },
        { key: 'login', patterns: [/login/i, /đăng\s+nhập/i] },
        { key: 'comment', patterns: [/comment/i, /bình\s+luận/i] },
        { key: 'save_image', patterns: [/lưu\s+ảnh/i, /save\s+image/i, /tải\s+ảnh/i, /download\s+image/i] },
        { key: 'visual_scan', patterns: [/visual\s+scan/i, /scan\s+màn\s+hình/i] }
      ];

      // Remove overlapping matches (keep longest/first)
      // Example: "click vào" matches "click" and "vào" -> keep "click vào"
      const uniqueMarkers = actionMarkers.flatMap(m => {
        // ... (find matches) logic omitted for brevity in replace block, assuming existing logic remains
        // Re-implementing the mapping part to be safe if I can't see it all, but tool only replaces target.
        // Wait, I can't see the matching logic here. I should only replace the definitions and the distance check down below.
        // Let's split this into two replacements if needed or just target the array definition first.
      }); 
      // ACTUALLY, I will just replace the array definition first.
      
      // ... separating for clarity in thought ...
      
      // Let's do the Array update first.

      // Find all markers in the text
      let foundMarkers = [];
      for (const am of actionMarkers) {
        for (const pattern of am.patterns) {
          let match;
          const globalPattern = new RegExp(pattern, 'gi');
          while ((match = globalPattern.exec(prompt)) !== null) {
            foundMarkers.push({
              key: am.key,
              index: match.index,
              length: match[0].length,
              text: match[0]
            });
          }
        }
      }

      // Sort markers by position
      foundMarkers.sort((a, b) => a.index - b.index);
      
      console.log('Detected Markers (Pre-filter):', JSON.stringify(foundMarkers));
      
      // Filter out false positives: "search" in compound phrases
      foundMarkers = foundMarkers.filter((m) => {
        if (m.key === 'search') {
          // Get context around the match (20 chars before and after)
          const start = Math.max(0, m.index - 5);
          const end = Math.min(prompt.length, m.index + m.length + 10);
          const context = prompt.substring(start, end).toLowerCase();
          
          // Skip if "search" is part of a compound noun/phrase
          const compoundPhrases = [
            'search result',
            'search engine',
            'search box',
            'search bar',
            'search button',
            'search field',
            'search page'
          ];
          
          for (const phrase of compoundPhrases) {
            if (context.includes(phrase)) {
              console.log(`Skipping 'search' in compound phrase: "${context.trim()}"`);
              return false; // Filter out this match
            }
          }
        }
        return true; // Keep this match
      });

      // Deduplicate overlapping markers
      foundMarkers = foundMarkers.filter((m, i) => {
        return !foundMarkers.some((other, oi) => {
          if (oi === i) return false;
          // Exact overlap or containment
          const covers = other.index <= m.index && (other.index + other.length) >= (m.index + m.length);
          if (other.index === m.index) return other.length > m.length;
          
          // REMOVED Proximity deduplication to allow close consecutive actions (e.g. click -> watch)
          // const distance = Math.abs(m.index - other.index);
          // const isProximityMatch = distance < 11 && oi < i; 

          // Repeated intent deduplication: skip if same key already found close by
          // Increased range to 10 chars to catch "Read/Browse"
          const distance = Math.abs(m.index - other.index);
          const isRepeatedIntent = m.key === other.key && distance < 10 && oi < i;

          return covers || isRepeatedIntent;
        });
      });
      
      console.log('Detected Markers (Post-filter):', JSON.stringify(foundMarkers));

      // Process markers in order
      for (let i = 0; i < foundMarkers.length; i++) {
        const current = foundMarkers[i];
        const next = foundMarkers[i + 1];
        
        const start = current.index + current.length;
        const end = next ? next.index : prompt.length;
        const segmentContext = prompt.substring(start, end).trim();
        // Look ahead context includes the next 30 chars regardless of markers
        const lookAheadContext = prompt.substring(current.index, Math.min(prompt.length, current.index + 50)).toLowerCase();

        if (current.key === 'navigate') {
          // Extract site name or URL
          let target = segmentContext.split(/[,;.]|[\s.,]+(then|and|và|rồi|sau đó|xong)\s+/i)[0].trim();
          target = target.replace(/^to\s+/i, '').replace(/[.,;]$/, '').trim();
          
          if (target.toLowerCase().includes('grok')) target = 'grok.com';
          else if (target.toLowerCase().includes('google')) target = 'google.com';
          else if (target.toLowerCase().includes('youtube')) target = 'youtube.com';

          actions.push({ action: 'navigate', params: { url: target } });
        } else if (current.key === 'type') {
          // Extract text to type
          let text = segmentContext.split(/[,;.]|[\s.,]+(then|and|và|rồi|sau đó|xong)\s+/i)[0].trim();
          text = text.replace(/^(với\s+)?prompt\s+/i, '').replace(/[.,;]$/, '').trim();
          text = text.replace(/^['"]|['"]$/g, '');
          
          // Prepend intent prefix if creating asset
          if (lookAheadContext.includes('ảnh') || lookAheadContext.includes('hình') || lookAheadContext.includes('image')) {
              text = `Create an image of: ${text}`;
          } else if (lookAheadContext.includes('video') || lookAheadContext.includes('phim')) {
              text = `Create a video of: ${text}`;
          }

          actions.push({ action: 'type', params: { text: text || 'hello' } });
        } else if (current.key === 'search') {
          // Extract keyword, stopping at common separators
          let keyword = segmentContext.split(/[,;.]|[\s.,]+(then|and|và|rồi|sau đó|xong)\s+/i)[0].trim();
          
          // Clean up: remove leading/trailing punctuation and "for"
          keyword = keyword.replace(/^for\s+/i, '').replace(/[.,;]$/, '').trim();
          
          // Remove quotes
          keyword = keyword.replace(/^['"]|['"]$/g, '');
          actions.push({ action: 'search', params: { keyword: keyword || 'tubecreate' } });
        } else if (current.key === 'browse') {
          const contextForTime = prompt.substring(Math.max(0, current.index - 5), end).toLowerCase();
          const timeMatch = contextForTime.match(/(\d+)/);
          let iterations = 5;
          if (timeMatch) {
            iterations = Math.floor(parseInt(timeMatch[1]) / 3);
          }
          actions.push({ action: 'browse', params: { iterations: Math.max(1, Math.min(iterations, 20)) } });
        } else if (current.key === 'watch') {
          // Match "20-30s", "30s", "20%"
          const timeMatch = segmentContext.match(/(\d+)-(\d+)s?/) || segmentContext.match(/(\d+)s?/) || segmentContext.match(/(\d+)%/);
          let duration = '60s';
          if (timeMatch) {
             duration = timeMatch[0]; // Capture full string including % or s
          }
          actions.push({ action: 'watch', params: { duration } });
        } else if (current.key === 'click') {
          const isVaoGoogle = current.text.toLowerCase() === 'vào' && segmentContext.toLowerCase().startsWith('google');
          if (!isVaoGoogle) {
            const params = {};
            // Look ahead for "video" or "youtube" in a broader window
            if (lookAheadContext.includes('video') || lookAheadContext.includes('youtube')) {
              params.type = 'video';
            } else {
               // Extract text target: "click [on] [Target] [delimiter]"
               let rawTarget = segmentContext;
               
                // Remove leading prepositions
                rawTarget = rawTarget.replace(/^(on|vào|nút|button|the|to)\s+/i, '').trim();
                
                // Stop at delimiters including punctuation-joined ones like "data, then"
                const delimitersRegex = /[,;.]|(\s|[,.])+(and|then|và|sau đó|rồi|xong)\s+/i;
                rawTarget = rawTarget.split(delimitersRegex)[0].trim();
                
                // Clean up trailing punctuation
                rawTarget = rawTarget.replace(/[.,;]$/, '').trim();
                
                // Remove quotes
                rawTarget = rawTarget.replace(/^['"]|['"]$/g, '');
                
                // PATTERN DETECTION: "first result", "first link", "first answer" -> default click (no text param)
                const isFirstResultPattern = /^first\s+(result|link|answer|item|option|search\s+result)/i.test(rawTarget);
                
                if (isFirstResultPattern) {
                    // Leave params empty - click.js will default to first search result
                    console.log('Detected "first result" pattern - using default click behavior');
                } else if (rawTarget.length > 0 && rawTarget.length < 50) { // Safety limit length
                    params.text = rawTarget;
                }
            }
            actions.push({ action: 'click', params });
          }
        } else if (current.key === 'login') {
          // Extract email/username and password
          // Priority 1: "username:password:recovery" or "username:password" (no spaces around colon)
          // Allow username to be email OR just a string (e.g. voanhtk5)
          const tripleMatch = segmentContext.match(/([^\s:'"]+)[:]([^\s:'"]+)[:]([^\s:'"]+)/);
          const doubleMatch = tripleMatch ? null : segmentContext.match(/([^\s:'"]+)[:]([^\s'"]+)/);
          
          if (tripleMatch) {
            actions.push({ action: 'login', params: { email: tripleMatch[1], password: tripleMatch[2], recoveryEmail: tripleMatch[3] } });
          } else if (doubleMatch) {
            actions.push({ action: 'login', params: { email: doubleMatch[1], password: doubleMatch[2] } });
          } else {
             // Fallback for space-separated
            const parts = segmentContext.split(/[\s:'"]+/).filter(p => p.length > 0 && !p.toLowerCase().includes('login'));
            // ... (keep existing extensive logic if needed, or simplify)
            // For now, simpler fallback for emails
            const email = parts.find(p => p.includes('@')) || parts[0] || '';
            const password = parts.find(p => p !== email && p.length > 3) || '';
            actions.push({ action: 'login', params: { email, password, recoveryEmail: '' } });
          }
        } else if (current.key === 'comment') {
          // Extract content: "comment [instruction] [until next keyword]"
          const instructionParams = {};
          
          // Look at the text immediately following the command in the segment
          let rawInstruction = segmentContext
            .replace(/comment|bình luận|nhận xét|viết/gi, '')
            .trim();
            
          // Stop at common delimiters OR other action keywords if they accidentally leaked into this segment
          const delimiters = [',', 'rồi', 'xong', 'sau đó', 'login', 'đăng nhập', 'click', 'bấm', 'vào', 'watch', 'xem'];
          // Find first occurrence of any delimiter
          let cutIndex = rawInstruction.length;
          
          for (const d of delimiters) {
             const idx = rawInstruction.toLowerCase().indexOf(d);
             if (idx !== -1 && idx < cutIndex) {
                 cutIndex = idx;
             }
          }
          
          rawInstruction = rawInstruction.substring(0, cutIndex).trim();

          // Also allow explicit quoting: comment "blah blah"
          const quoteMatch = segmentContext.match(/['"]([^'"]+)['"]/);
          
          if (quoteMatch) {
             instructionParams.instruction = quoteMatch[1];
          } else if (rawInstruction.length > 3) {
             instructionParams.instruction = rawInstruction;
          } else {
             // Default if no instruction provided
             instructionParams.instruction = "nice video";
          }

          actions.push({ action: 'comment', params: instructionParams });
        } else if (current.key === 'save_image') {
          actions.push({ action: 'save_image', params: {} });
        } else if (current.key === 'visual_scan') {
          actions.push({ action: 'visual_scan', params: {} });
        }
      }

      // --- Post-Processing: Inject missing CLIIC actions ---
      // Rule: If Search is immediately followed by Watch, insert a Click in between.
      for (let i = 0; i < actions.length - 1; i++) {
        if (actions[i].action === 'search' && actions[i+1].action === 'watch') {
             console.log('Injecting implicit CLICK between SEARCH and WATCH');
             actions.splice(i + 1, 0, { action: 'click', params: { type: 'video' } });
             i++; // Skip the newly inserted action
        }
      }

      return {
        profile,
        actions: actions.length > 0 ? actions : [{ action: 'search', params: { keyword: 'tubecreate' } }]
      };
    }
  }
}
