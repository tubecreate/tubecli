
import { BrowserManager } from './browser_manager.js';
import fs from 'fs-extra';
import path from 'path';

async function testStats() {
    const manager = new BrowserManager();
    const profileName = 'test-stats-unit';
    
    console.log(`Testing stats for ${profileName}...`);
    
    // Ensure profile exists
    await manager.ensureProfile(profileName);
    
    // 1. Get Initial Stats
    let stats = await manager.getStats(profileName);
    console.log('Initial Stats:', stats);
    
    if (stats.level !== 1 || stats.class !== 'Novice') {
        console.error('FAIL: Initial stats incorrect');
    }

    // 2. Simulate Search Action (Tech) -> Should increase INT
    console.log('Update: Search "javascript code"...');
    stats = await manager.updateStats(profileName, 'search', { keyword: 'javascript code' });
    console.log('Stats after Search:', stats);
    
    if (stats.int <= 0) console.error('FAIL: INT did not increase');

    // 3. Simulate Comment -> Impact
    console.log('Update: Comment...');
    stats = await manager.updateStats(profileName, 'comment', {});
    console.log('Stats after Comment:', stats);
    
    if (stats.impact <= 0) console.error('FAIL: Impact did not increase');
    
    // 4. Check File Persistence
    const statsPath = path.join(manager.baseDir, profileName, 'stats.json');
    if (await fs.pathExists(statsPath)) {
        console.log('SUCCESS: stats.json created');
        const saved = await fs.readJson(statsPath);
        console.log('Saved Stats:', saved);
    } else {
        console.error('FAIL: stats.json not found');
    }
}

testStats().catch(console.error);
