/**
 * CapCut TTS — Node phải giữ mốc từ của MỌI khúc, dời theo thời lượng thật.
 *
 * Run:  node tests/capcut_tts_ws_marks_test.mjs     (exit 0 = pass; SKIP khi chưa build dist)
 *
 * VÌ SAO CÓ FILE NÀY
 *   Đo thật 13/9/2026 bằng WebSocket CapCut: CapCut chia văn bản thành khúc, gửi
 *   MỖI khúc một gói TTSResponse có mốc ĐẦY ĐỦ (tính TỪ ĐẦU KHÚC) rồi một gói audio.
 *   ttsWebSocket.ts cũ viết `if (marks.words.length) words = marks.words;` — gán đè,
 *   chỉ còn khúc cuối, mốc tính từ 0. Cả tuần mọi người tin đó là "CapCut chỉ trả
 *   mốc cho ~100 ký tự đầu" và cắt lời ở 90 ký tự, làm giọng ngắt giữa câu.
 *   Trường `duration` trong gói lệch ~2,08 lần so với audio thật, nên độ dài khúc
 *   phải đếm từ khung MP3.
 *
 * Test chạy file dist ĐÃ BUILD với WebSocket giả phát đúng thứ tự gói đã đo.
 */
import assert from 'node:assert';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const DIST = path.join(HERE, '..', 'data', 'extensions_external', 'capcut_tts', 'server', 'dist', 'lib', 'capcut', 'ttsWebSocket.js');
if (!fs.existsSync(DIST)) {
  console.log(`SKIP: chưa có ${DIST}`);
  process.exit(0);
}
const mod = await import(pathToFileURL(DIST).href);
const { synthesizeWithTimestamps, mp3Seconds } = mod.synthesizeWithTimestamps ? mod : mod.default;

// Khung MPEG2 Layer III 24 kHz 160 kbps: 480 byte, 576 mẫu = 0,024 s — đúng loại CapCut trả.
const frames = (n) => {
  const b = Buffer.alloc(480 * n);
  for (let k = 0; k < n; k += 1) b.set([0xff, 0xf3, 0xe4, 0xc4], k * 480);
  return b;
};
const near = (a, b, eps = 0.002) => Math.abs(a - b) <= eps;

// ── 1. đếm khung MP3 ──
assert(near(mp3Seconds(frames(67)), 1.608), `67 khung = 1,608 s, được ${mp3Seconds(frames(67))}`);
const id3 = Buffer.concat([Buffer.from([0x49, 0x44, 0x33, 3, 0, 0, 0, 0, 0, 20]), Buffer.alloc(20), frames(10)]);
assert(near(mp3Seconds(id3), 0.24), `bỏ qua thẻ ID3, được ${mp3Seconds(id3)}`);
assert.equal(mp3Seconds(Buffer.from('không phải mp3')), 0);
console.log('1 mp3Seconds : dem khung dung, bo the ID3, rac = 0');

// ── WebSocket + fetch giả phát đúng thứ tự gói đã đo ──
const run = async (plan) => {
  class FakeSocket {
    constructor() { this.l = {}; }
    addEventListener(t, f) { (this.l[t] ||= []).push(f); }
    accept() {}
    close() {}
    emit(data) { (this.l.message || []).forEach((f) => f({ data })); }
    send() {
      setTimeout(() => {
        this.emit(JSON.stringify({ event: 'TaskStarted' }));
        for (const step of plan) {
          if (step.words) {
            this.emit(JSON.stringify({
              event: 'TTSResponse',
              payload: JSON.stringify({
                text: step.text || '', duration: 9.99,           // trường duration sai như thật
                alignment: { words: step.words.map(([word, s, e]) => ({ word, start_time: s, end_time: e })) },
              }),
            }));
          }
          if (step.frames) {
            const b = frames(step.frames);
            this.emit(b.buffer.slice(b.byteOffset, b.byteOffset + b.length));
          }
        }
        this.emit(JSON.stringify({ event: 'TaskFinished' }));
      }, 0);
    }
  }
  const realFetch = globalThis.fetch;
  globalThis.fetch = async (url) => {
    if (String(url).includes('sami')) return { webSocket: new FakeSocket() };
    return { json: async () => ({ data: { token: 't', app_key: 'k' } }) };
  };
  try {
    return await synthesizeWithTimestamps({
      text: 'Hola mundo. Adiós amigo.', speaker: 'x', tokenUrl: 'https://edit-api-sg.capcut.com/lv/v1/common/tts/token',
      wsUrl: 'wss://sami-sg1.byteintlapi.com/internal/api/v1/ws', appId: '1', appVersion: '8.4.0',
      platformId: '7', signVersion: '1', sampleRate: 24000, userAgent: 'test', origin: 'https://www.capcut.com',
      timeoutMs: 5000,
    });
  } finally {
    globalThis.fetch = realFetch;
  }
};

// ── 2. mốc tính theo khúc → một trục thời gian ──
const r1 = await run([
  { text: 'Hola mundo.', words: [['Hola', 0.1, 0.3], ['mundo.', 0.35, 0.7]], frames: 40 },   // 0,96 s
  { text: ' Adiós amigo.', words: [['Adiós', 0.05, 0.4], ['amigo.', 0.45, 0.9]], frames: 50 }, // 1,20 s
]);
assert.equal(r1.words.length, 4, `giữ mốc của CẢ HAI khúc, được ${r1.words.length}`);
assert.deepEqual(r1.words.map((w) => w.word), ['Hola', 'mundo.', 'Adiós', 'amigo.']);
assert(near(r1.words[2].start, 0.96 + 0.05), `khúc 2 dời đúng 0,96 s, được ${r1.words[2].start}`);
assert(near(r1.words[3].end, 0.96 + 0.9), `mốc cuối ${r1.words[3].end}`);
assert(r1.words.every((w, i) => i === 0 || w.start >= r1.words[i - 1].start), 'mốc tăng dần');
assert(near(r1.duration, 2.16), `duration là độ dài audio THẬT (2,16 s), không phải trường sai 9,99: ${r1.duration}`);
assert.equal(r1.text, 'Hola mundo. Adiós amigo.', 'text là CẢ đoạn, không phải khúc cuối');
console.log('2 cong don  : 2 khuc giu du 4 moc | khuc 2 doi 0,96s | duration that');

// ── 3. mốc đã tuyệt đối thì không dời hai lần ──
const r2 = await run([
  { words: [['Hola', 0.1, 0.3], ['mundo.', 0.35, 0.7]], frames: 40 },
  { words: [['Adiós', 1.01, 1.36], ['amigo.', 1.41, 1.86]], frames: 50 },
]);
assert(near(r2.words[2].start, 1.01), `không dời lần hai, được ${r2.words[2].start}`);
console.log('3 tuyet doi : moc da tinh tu dau bai thi giu nguyen');

// ── 4. số gói audio lệch số gói mốc: dời theo audio đã tới TRƯỚC gói mốc ──
const r3 = await run([
  { words: [['Hola', 0.1, 0.3], ['mundo.', 0.35, 0.7]], frames: 20 },
  { frames: 20 },                                                   // khúc 1 gửi 2 gói audio
  { words: [['Adiós', 0.05, 0.4], ['amigo.', 0.45, 0.9]], frames: 50 },
]);
assert(near(r3.words[2].start, 0.96 + 0.05), `dời theo 2 gói audio trước nó (0,96 s), được ${r3.words[2].start}`);
console.log('4 lech goi  : doi theo audio da toi truoc goi moc');

console.log('OK capcut ws marks');
