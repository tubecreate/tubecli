import { plugin } from 'playwright-with-fingerprints';
import fs from 'fs-extra';
import path from 'path';
import axios from 'axios';

function extractRawKey(jsonString, key) {
    const searchStr = `"${key}":`;
    const startIdx = jsonString.indexOf(searchStr);
    if (startIdx === -1) return null;
    let valStart = startIdx + searchStr.length;
    while (valStart < jsonString.length && /\s/.test(jsonString[valStart])) valStart++;
    let braceCount = 0;
    let inString = false;
    let escape = false;
    for (let i = valStart; i < jsonString.length; i++) {
        const char = jsonString[i];
        if (escape) { escape = false; continue; }
        if (char === '\\') { escape = true; continue; }
        if (char === '"') { inString = !inString; continue; }
        if (!inString) {
            if (char === '{' || char === '[') braceCount++;
            else if (char === '}' || char === ']') {
                braceCount--;
                if (braceCount === 0) return jsonString.slice(valStart, i + 1);
            } else if (braceCount === 0 && (char === ',' || char === '}')) {
                return jsonString.slice(valStart, i);
            }
        }
    }
    return null;
}

(async () => {
    try {
        const params = { tags: 'Microsoft Windows,Chrome' };
        console.log("1. Fetching raw response from API...");
        const resp = await axios.get('https://api.tubecreate.com/api/fingerprints/getfinger.php', { 
            params,
            responseType: 'text',
            timeout: 100000
        });
        const rawText = resp.data;
        const parsed = JSON.parse(rawText);
        const strAPI = extractRawKey(rawText, 'fingerprint');
        console.log("Fetched. Length:", strAPI.length);
        
        console.log("2. Writing to disk...");
        const testPath = path.resolve('./test_fp.json');
        await fs.outputFile(testPath, strAPI, 'utf8');
        
        console.log("3. Reading back from disk...");
        const strDisk = await fs.readFile(testPath, 'utf8');
        console.log("Read. Length:", strDisk.length);
        
        console.log("4. Comparing strings...");
        const isIdentical = strAPI === strDisk;
        console.log("Are strings identical?", isIdentical);
        
        if (!isIdentical) {
            console.log("Strings differ! Finding mismatch...");
            const minLen = Math.min(strAPI.length, strDisk.length);
            for (let i = 0; i < minLen; i++) {
                if (strAPI[i] !== strDisk[i]) {
                    console.log(`Mismatch at index ${i}: API char code ${strAPI.charCodeAt(i)} ('${strAPI[i]}') vs Disk char code ${strDisk.charCodeAt(i)} ('${strDisk[i]}')`);
                    break;
                }
            }
        }
        
        // Clean up test file
        await fs.remove(testPath);
        
    } catch (e) {
        console.error("Error:", e);
    }
    process.exit(0);
})();
