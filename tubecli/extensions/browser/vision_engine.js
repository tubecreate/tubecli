import axios from 'axios';
import path from 'path';
import fs from 'fs-extra';

const TUBECLI_PORT = process.env.TUBECLI_PORT || '5295';
const LOCAL_AI_URL = `http://localhost:${TUBECLI_PORT}/api/v1/localai/generate`;
const SCREENSHOT_DIR = path.resolve(process.cwd(), 'screenshots');

// Ensure screenshot directory exists
fs.ensureDirSync(SCREENSHOT_DIR);

/** First line only — these blobs are one long paragraph of stack trace. */
function firstLine(s) {
  return String(s || '').split('\n')[0].slice(0, 200);
}

/**
 * Did the local-AI proxy hand back a failure disguised as an answer?
 *
 * The proxy replies HTTP 200 with the error inside the response text, so the
 * only way to tell a diagnosis from a dead connection is to read it. Vision
 * needs a model that exists locally (llava); a server with no Ollama has none,
 * and that is a configuration fact, not an incident.
 */
function isProxyError(content) {
  const s = String(content || '');
  return /^(\s*)Error:/i.test(s)
      || /Connection refused|ConnectionError|Max retries exceeded|HTTPConnectionPool/i.test(s)
      || /model .*not found|no such model|pull the model/i.test(s);
}

/**
 * Capture screenshot and analyze it using LLaVA model.
 * @param {import('playwright').Page} page
 * @param {string} prompt - Question or instruction for the AI.
 */
export async function analyzeScreen(page, prompt = "Describe the current state of this web page and list any visible buttons or inputs.") {
  try {
    const timestamp = Date.now();
    const screenshotPath = path.join(SCREENSHOT_DIR, `screen_${timestamp}.jpg`);
    
    console.log('Waiting for page to stabilize (networkidle)...');
    try {
      await page.waitForLoadState('networkidle', { timeout: 10000 });
    } catch (e) {
      console.warn('Network idle timeout, proceeding with capture anyway...');
    }
    
    console.log(`Capturing screenshot to: ${screenshotPath}`);
    await page.screenshot({ path: screenshotPath, type: 'jpeg', quality: 80 });

    console.log('Sending screenshot to Visual AI (LLaVA)...');
    
    const payload = {
      model: "llava:latest",
      prompt: prompt,
      stream: false,
      images: [screenshotPath] // Local AI accepts local file paths
    };

    const response = await axios.post(LOCAL_AI_URL, payload, {
      headers: { 'Content-Type': 'application/json' },
      timeout: 60000 // Vision models can be slow
    });

    if (response.data && response.data.response) {
      console.log('Visual Analysis Result:', response.data.response);
      return response.data.response;
    } else {
      console.warn('Unexpected API response format:', response.data);
      return null;
    }

  } catch (error) {
    console.error('Visual Analysis failed:', error.message);
    if (error.response) {
        console.error('API Error Data:', error.response.data);
    }
    return null;
  }
}

/**
 * Analyze an error state and suggest an alternative action.
 * @param {import('playwright').Page} page
 * @param {string} goal - What the script was trying to do (e.g., "Click #submit").
 * @param {string} error - The error message received.
 * @returns {Promise<{action: string, params: object} | null>} - Suggested remedial action or null.
 */
export async function diagnoseAndSuggest(page, goal, error) {
  try {
    const timestamp = Date.now();
    const screenshotPath = path.join(SCREENSHOT_DIR, `error_${timestamp}.jpg`);
    
    console.log('Capturing error state screenshot...');
    await page.screenshot({ path: screenshotPath, type: 'jpeg', quality: 80 });

    const prompt = `I am an automation script. 
My GOAL was: "${goal}".
I failed with ERROR: "${error}".

Analyze this screenshot. 
1. Explain briefly why the error might have happened.
2. Suggest an ALTERNATIVE way to achieve the goal using visible elements.
3. Return ONLY a JSON object (no markdown, no extra text) with this format:
{
  "explanation": "Brief explanation",
  "suggestedAction": {
    "action": "click" | "browse" | "search", 
    "params": { "selector": "actual visible selector" }
  }
}
If no solution is visible, return null. DO NOT ADD ANY TEXT OUTSIDE THE JSON.`;

    console.log('Asking Visual AI for a solution...');
    
    const payload = {
      model: "llava:latest",
      prompt: prompt,
      stream: false,
      images: [screenshotPath]
    };

    const response = await axios.post(LOCAL_AI_URL, payload, {
      headers: { 'Content-Type': 'application/json' },
      timeout: 60000 
    });

    if (response.data && response.data.response) {
      const content = response.data.response;

      // The local-AI proxy answers HTTP 200 even when it could not reach a
      // model, putting the failure in the response TEXT. Printing that under
      // "AI Diagnosis:" presented a connection error as if it were the model's
      // opinion — the log read "AI Diagnosis: Error: HTTPConnectionPool(...
      // port=11434 ... Connection refused)". Recognise it and say what it is.
      if (isProxyError(content)) {
        console.warn('Visual diagnosis unavailable: ' + firstLine(content));
        console.warn('  (needs a vision model, e.g. `ollama pull llava` on this machine)');
        return null;
      }

      console.log('AI Diagnosis:', content);

      try {
        // Find first '{' and last '}' to extract JSON
        const match = content.match(/\{[\s\S]*\}/);
        if (match) {
          let jsonStr = match[0];
          // Remove comments ( // ... or /* ... */ ) which might break JSON.parse
          jsonStr = jsonStr.replace(/\/\/.*$/gm, '').replace(/\/\*[\s\S]*?\*\//g, '');
          const result = JSON.parse(jsonStr);
          return result.suggestedAction || null;
        } else {
          console.warn('No JSON object found in response.');
          return null;
        }
      } catch (e) {
        console.warn('Failed to parse AI suggestion JSON. Raw content:', content);
        return null;
      }
    }
    return null;

  } catch (err) {
    // Distinguish "this machine has no vision model" from a genuine fault. The
    // first is the normal state of a headless server and should read as a note,
    // not an error the owner is meant to chase.
    if (isProxyError(err && err.message) || (err && err.code === 'ECONNREFUSED')) {
      console.warn('Visual diagnosis unavailable: ' + firstLine(err.message));
      console.warn('  (needs a vision model, e.g. `ollama pull llava` on this machine)');
    } else {
      console.error('Visual Error Diagnosis failed:', firstLine(err && err.message));
    }
    return null;
  }
}

/**
 * Generate a context-aware comment based on visual analysis.
 * @param {import('playwright').Page} page
 * @param {string} title - Video title.
 * @returns {Promise<string>} - Generated comment.
 */
/**
 * Generate a context-aware comment based on visual analysis.
 * Uses a 2-step process:
 * 1. LLaVA: Describe image in English.
 * 2. DeepSeek: Generate Vietnamese comment from Description + Title.
 * @param {import('playwright').Page} page
 * @param {string} title - Video title.
 * @param {string} aiModel - Text AI model to use.
 * @returns {Promise<string>} - Generated comment.
 */
// aiModel = "" means "let the server resolve it" — see AIEngine.
export async function generateContextAwareComment(page, title, userInstruction = "", aiModel = "") {
  try {
    const timestamp = Date.now();
    const screenshotPath = path.join(SCREENSHOT_DIR, `comment_context_${timestamp}.jpg`);
    
    console.log('Capturing video frame for comment generation...');
    try {
      const videoPlayer = page.locator('#movie_player, video').first();
      if (await videoPlayer.isVisible()) {
        await videoPlayer.screenshot({ path: screenshotPath, type: 'jpeg', quality: 80 });
      } else {
        await page.screenshot({ path: screenshotPath, type: 'jpeg', quality: 80 });
      }
    } catch (e) {
      await page.screenshot({ path: screenshotPath, type: 'jpeg', quality: 80 });
    }

    // Step 1: Get Visual Description from LLaVA (in English)
    console.log('Step 1: Asking LLaVA to describe the scene...');
    const visionPayload = {
      model: "llava:latest",
      prompt: "Describe the main action, person, or object in this video frame in one short English sentence.",
      stream: false,
      images: [screenshotPath]
    };
    
    let visualDescription = "";
    try {
      const visionResponse = await axios.post(LOCAL_AI_URL, visionPayload, { headers: { 'Content-Type': 'application/json' }, timeout: 60000 });
      if (visionResponse.data && visionResponse.data.response) {
        visualDescription = visionResponse.data.response.trim();
        console.log(`Visual Description: "${visualDescription}"`);
      }
    } catch (e) {
      console.warn('LLaVA description failed, proceeding with title only.');
    }

    // Step 2: Generate Comment using DeepSeek (Text Model)
    console.log('Step 2: Asking DeepSeek to write Vietnamese comment...');
    const contextPart = visualDescription ? `Visual Context: "${visualDescription}"` : "Visual Context: (Not available, rely on title)";
    
    // Custom Instruction handling
    const customInstruction = userInstruction 
        ? `STRICT REQUIREMENT: ${userInstruction}` 
        : "Tone: Casual, friendly, young internet user (gen Z).";

    const textPrompt = `You are a genuine YouTube viewer.
Video Title: "${title}"
${contextPart}

Task: Write a short, natural, and engaging comment in Vietnamese (1-2 sentences).
Instructions:
- If visual context is present, use it. If not, rely heavily on the Title.
- ${customInstruction}
- AVOID generic phrases like "Video hữu ích", "Cảm ơn", "Hay quá".
- If the title mentions games/bosses (e.g. "đánh boss"), comment about the difficulty or skill.
- ONLY return the comment text. No quotes.`;

    const textPayload = {
      model: aiModel, 
      prompt: textPrompt,
      stream: false
    };

    try {
      const textResponse = await axios.post(LOCAL_AI_URL, textPayload, { headers: { 'Content-Type': 'application/json' }, timeout: 60000 }); // Increased timeout
      if (textResponse.data && textResponse.data.response) {
         // Cleanup thinking tags <think>...</think> if present in R1 output
         let comment = textResponse.data.response.replace(/<think>[\s\S]*?<\/think>/g, '').trim();
         comment = comment.replace(/^"|"$/g, '');
         console.log(`Generated Comment: "${comment}"`);
         return comment;
      }
    } catch (e) {
      console.error('DeepSeek generation failed (Step 2):', e.message);
    }

    console.warn('AI Generation failed entirely. Using Smart Fallback.');
    return generateSmartFallback(title);

  } catch (err) {
    console.error('Visual Comment Generation failed:', err.message);
    return generateSmartFallback(title);
  }
}


/**
 * Generates a relevant comment based on title keywords when AI fails.
 * @param {string} title 
 * @returns {string}
 */
function generateSmartFallback(title) {
  const t = title.toLowerCase();
  
  if (t.includes('boss') || t.includes('đánh') || t.includes('trận') || t.includes('rank')) {
    return "Trận này đánh căng thật, skill đỉnh quá bạn ơi!";
  }
  if (t.includes('game') || t.includes('chơi') || t.includes('play')) {
    return "Game này nhìn cuốn thế, hôm nào phải thử mới được.";
  }
  if (t.includes('review') || t.includes('đánh giá') || t.includes('trên tay')) {
    return "Review chi tiết quá, cảm ơn bác đã chia sẻ nhé.";
  }
  if (t.includes('nhạc') || t.includes('music') || t.includes('cover') || t.includes('song')) {
    return "Nhạc hay lắm, nghe chill phết!";
  }
  if (t.includes('ăn') || t.includes('food') || t.includes('ẩm thực') || t.includes('món')) {
    return "Nhìn ngon quá, đói bụng luôn rồi nè :))";
  }
  if (t.includes('du lịch') || t.includes('vlog') || t.includes('đi')) {
    return "Cảnh đẹp quá, ước gì được đi một chuyến như này.";
  }
  if (t.includes('hướng dẫn') || t.includes('cách') || t.includes('tutorial')) {
    return "Hướng dẫn dễ hiểu lắm, để mình làm thử xem sao.";
  }
  
  // Default if no keywords match, but still slightly more engaging than "useful"
  return "Nội dung video thú vị lắm, hóng các video tiếp theo của bạn!";
}
