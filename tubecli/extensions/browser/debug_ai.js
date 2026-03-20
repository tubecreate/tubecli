import { AIEngine } from './ai_engine.js';

const engine = new AIEngine();

async function test(prompt) {
  console.log(`\nTesting prompt: "${prompt}"`);
  const result = await engine.planActions(prompt);
  console.log(JSON.stringify(result, null, 2));
}

// Test cases
test("mở profile 'aaa' vào google tìm kiếm 'Quẩy lên ae ơi VIPNhat' click xem video 200-300s, nếu chưa login thì login");
test("mở profile 'aaa' vào google tìm kiếm 'Tội a jaygay ủa lộn jaygray P1' click xem video 200-300s");
