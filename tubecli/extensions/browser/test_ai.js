import { AIEngine } from './ai_engine.js';

async function test() {
  const ai = new AIEngine();
  const prompt = " mở profile 'profile2' vào google login 'voanhtk5@gmail.com:onlineconan:anhnhat5216@gmail.com' ";
  console.log('Testing Prompt:', prompt);
  
  // Simulate AI failure to trigger fallback
  const actions = await ai.planActions(prompt);
  console.log('Action Sequence:', JSON.stringify(actions, null, 2));
}

test();
