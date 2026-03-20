import { AIEngine } from './ai_engine.js';

const engine = new AIEngine();
const prompt = "mở profile 'aaa' vào google tìm kiếm 'Tội a jaygay ủa lộn jaygray P1' click xem video 200-300s, nếu chưa login thì login 'voanhtk5@gmail.com:onlineconan:anhnhat5216@gmail.com' và comment theo nội dung của comment nội dung phù hơp với tiêu đều mô tả xong thoát";

async function run() {
  const result = await engine.planActions(prompt);
  console.log(JSON.stringify(result.actions, null, 2));
}

run();
