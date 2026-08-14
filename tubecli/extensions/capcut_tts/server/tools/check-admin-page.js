// Trang admin là một chuỗi template trong TypeScript, nên TypeScript KHÔNG
// kiểm tra được JavaScript nằm bên trong. Một dấu nháy sai escape là đủ làm
// chết toàn bộ script, trang hiện ra nhưng bấm gì cũng không phản ứng.
//
// Script này bóc từng thẻ <script> ra và bắt Node parse thử.
// Chạy trong `npm run build` để lỗi bị chặn từ lúc build.
const vm = require('node:vm');

const { adminPage } = require('../dist/lib/admin/adminPage.js');

const blocks = [...adminPage.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(
  (match) => match[1]
);

if (blocks.length === 0) {
  console.error('check-admin-page: không tìm thấy thẻ <script> nào');
  process.exit(1);
}

let failed = 0;

blocks.forEach((code, index) => {
  try {
    new vm.Script(code, { filename: `adminPage.script[${index}].js` });
    console.log(
      `  script[${index}] OK (${(code.length / 1024).toFixed(1)}KB)`
    );
  } catch (error) {
    failed += 1;
    console.error(`  script[${index}] LỖI CÚ PHÁP: ${error.message}`);

    const line = Number(String(error.stack).match(/\[\d+\]\.js:(\d+)/)?.[1]);
    if (line) {
      const lines = code.split('\n');
      for (let i = Math.max(0, line - 2); i < Math.min(lines.length, line + 1); i += 1) {
        console.error(`    ${i + 1} | ${lines[i]}`);
      }
    }
  }
});

// Các hàm được gọi từ onclick phải tồn tại ở phạm vi toàn cục,
// nếu không sẽ thành "... is not defined" khi người dùng bấm.
// từ khoá JS không phải tên hàm, ví dụ onkeydown="if(...)"
const keywords = new Set(['if', 'for', 'while', 'switch', 'return', 'typeof', 'this']);
const handlers = [...adminPage.matchAll(/on\w+="(\w+)\(/g)]
  .map((m) => m[1])
  .filter((name) => !keywords.has(name));
const missing = [...new Set(handlers)].filter(
  (name) => !new RegExp(`(function ${name}\\b|${name}\\s*=\\s*(async\\s*)?\\()`).test(adminPage)
);

if (missing.length) {
  failed += 1;
  console.error(`  handler thiếu định nghĩa: ${missing.join(', ')}`);
}

if (failed) {
  console.error('check-admin-page: THẤT BẠI');
  process.exit(1);
}

console.log('check-admin-page: tất cả script hợp lệ');
