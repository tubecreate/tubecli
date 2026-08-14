// Sinh audio test qua HTTP, KHÔNG truyền text qua shell.
// Truyền qua argv của shell làm hỏng ký tự nhiều byte (đã đo: text tiếng Nhật
// bị cắt còn 1/6 độ dài) nên toàn bộ body dựng và gửi trong Node.
const fs = require('fs');
const http = require('http');

const [, , base, casesFile, outDir] = process.argv;
const cases = JSON.parse(fs.readFileSync(casesFile, 'utf8'));

const post = (body) =>
  new Promise((resolve, reject) => {
    const payload = Buffer.from(JSON.stringify(body), 'utf8');
    const url = new URL(base);
    const req = http.request(
      {
        hostname: url.hostname,
        port: url.port,
        path: '/v2/synthesize',
        method: 'POST',
        headers: {
          'Content-Type': 'application/json; charset=utf-8',
          'Content-Length': payload.length,
        },
      },
      (res) => {
        const chunks = [];
        res.on('data', (c) => chunks.push(c));
        res.on('end', () =>
          resolve({ status: res.statusCode, body: Buffer.concat(chunks) })
        );
      }
    );
    req.on('error', reject);
    req.write(payload);
    req.end();
  });

(async () => {
  for (const c of cases) {
    const body = { text: c.text, speaker: c.speaker };
    if (c.platform) body.platform = c.platform;

    try {
      const r = await post(body);
      const file = `${outDir}/${c.file}`;
      if (r.status === 200) fs.writeFileSync(file, r.body);
      console.log(
        `${c.name.padEnd(22)} ${String(c.engine).padEnd(7)} http=${r.status} ${String(r.body.length).padStart(7)}B  text=${c.text.length}ch`
      );
    } catch (e) {
      console.log(`${c.name.padEnd(22)} LỖI ${e.message}`);
    }
  }
})();
