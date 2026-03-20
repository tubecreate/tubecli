/**
 * Mission Manager — Task Mission System
 * File-based atomic locking for multi-browser mission coordination.
 */

const fs = require('fs-extra');
const path = require('path');

const MISSIONS_DIR = path.join(__dirname, 'missions');

// Ensure missions directory exists
fs.ensureDirSync(MISSIONS_DIR);

/**
 * Load all missions from disk
 */
function loadAllMissions() {
  const files = fs.readdirSync(MISSIONS_DIR).filter(f => f.endsWith('.json'));
  return files.map(f => {
    try {
      return JSON.parse(fs.readFileSync(path.join(MISSIONS_DIR, f), 'utf8'));
    } catch {
      return null;
    }
  }).filter(Boolean);
}

/**
 * Save a single mission back to disk
 */
function saveMission(mission) {
  const filePath = path.join(MISSIONS_DIR, `${mission.id}.json`);
  fs.writeFileSync(filePath, JSON.stringify(mission, null, 2), 'utf8');
}

/**
 * Create a new mission file
 */
function createMission(mission) {
  if (!mission.id) {
    mission.id = `mission_${Date.now()}`;
  }
  mission.status = 'pending';
  mission.completed_count = mission.completed_count || 0;
  mission.completed_by = mission.completed_by || [];
  mission.assigned_to = null;
  mission.created_at = new Date().toISOString();
  mission.last_updated = null;
  saveMission(mission);
  console.log(`[MissionManager] Created mission: ${mission.id} — ${mission.title}`);
  return mission;
}

/**
 * Claim the best available mission for a profile.
 * Uses atomic write-then-verify to prevent race conditions.
 */
function claimMission(profileName, tags = []) {
  const missions = loadAllMissions();

  // Filter: pending + tags match (if tags provided)
  const available = missions
    .filter(m => m.status === 'pending' && m.assigned_to === null)
    .filter(m => {
      if (!tags || tags.length === 0) return true;
      return m.tags && m.tags.some(t => tags.includes(t));
    })
    .sort((a, b) => (a.priority || 99) - (b.priority || 99));

  for (const mission of available) {
    // Atomic claim: write then read-back to verify
    mission.assigned_to = profileName;
    mission.status = 'running';
    mission.last_updated = new Date().toISOString();
    saveMission(mission);

    // Verify we own it (simple re-read check)
    const verify = JSON.parse(
      fs.readFileSync(path.join(MISSIONS_DIR, `${mission.id}.json`), 'utf8')
    );
    if (verify.assigned_to === profileName) {
      console.log(`[MissionManager] ${profileName} claimed mission: ${mission.id}`);
      return verify;
    }
    // If someone else claimed it (race), try the next one
    console.log(`[MissionManager] Race condition on ${mission.id}, trying next...`);
  }

  return null; // No missions available
}

/**
 * Mark one execution of a mission as completed by a profile.
 * If completed_count >= target_count → mission becomes "done".
 * Otherwise → release lock for next browser to pick up.
 */
function completeMission(missionId, profileName) {
  const filePath = path.join(MISSIONS_DIR, `${missionId}.json`);
  if (!fs.existsSync(filePath)) return false;

  const mission = JSON.parse(fs.readFileSync(filePath, 'utf8'));
  mission.completed_count = (mission.completed_count || 0) + 1;
  if (!mission.completed_by) mission.completed_by = [];
  mission.completed_by.push(profileName);
  mission.last_updated = new Date().toISOString();

  if (mission.completed_count >= (mission.target_count || 1)) {
    mission.status = 'done';
    mission.assigned_to = null;
    console.log(`[MissionManager] Mission DONE: ${missionId} (${mission.completed_count}/${mission.target_count})`);
  } else {
    // Re-open for next browser
    mission.status = 'pending';
    mission.assigned_to = null;
    console.log(`[MissionManager] Mission progress: ${missionId} (${mission.completed_count}/${mission.target_count})`);
  }

  saveMission(mission);
  return true;
}

/**
 * Mark mission as failed and release lock
 */
function failMission(missionId, reason = '') {
  const filePath = path.join(MISSIONS_DIR, `${missionId}.json`);
  if (!fs.existsSync(filePath)) return false;

  const mission = JSON.parse(fs.readFileSync(filePath, 'utf8'));
  mission.status = 'failed';
  mission.assigned_to = null;
  mission.last_updated = new Date().toISOString();
  if (reason) mission.fail_reason = reason;
  saveMission(mission);
  console.log(`[MissionManager] Mission FAILED: ${missionId}`);
  return true;
}

/**
 * Release a mission lock without marking it complete (crash recovery)
 */
function releaseMission(missionId) {
  const filePath = path.join(MISSIONS_DIR, `${missionId}.json`);
  if (!fs.existsSync(filePath)) return false;

  const mission = JSON.parse(fs.readFileSync(filePath, 'utf8'));
  if (mission.status === 'running') {
    mission.status = 'pending';
    mission.assigned_to = null;
    mission.last_updated = new Date().toISOString();
    saveMission(mission);
    console.log(`[MissionManager] Released mission lock: ${missionId}`);
  }
  return true;
}

/**
 * Delete a mission file
 */
function deleteMission(missionId) {
  const filePath = path.join(MISSIONS_DIR, `${missionId}.json`);
  if (fs.existsSync(filePath)) {
    fs.removeSync(filePath);
    console.log(`[MissionManager] Deleted mission: ${missionId}`);
    return true;
  }
  return false;
}

/**
 * Reset a done/failed mission back to pending
 */
function resetMission(missionId) {
  const filePath = path.join(MISSIONS_DIR, `${missionId}.json`);
  if (!fs.existsSync(filePath)) return false;

  const mission = JSON.parse(fs.readFileSync(filePath, 'utf8'));
  mission.status = 'pending';
  mission.assigned_to = null;
  mission.completed_count = 0;
  mission.completed_by = [];
  mission.last_updated = new Date().toISOString();
  saveMission(mission);
  console.log(`[MissionManager] Reset mission: ${missionId}`);
  return true;
}

/**
 * CLI: print mission list as table
 */
function printDashboard() {
  const missions = loadAllMissions();
  if (!missions.length) {
    console.log('No missions found.');
    return;
  }

  const STATUS_ICON = { pending: '⚪', running: '🟡', done: '✅', failed: '❌' };

  console.log('\n╔══════════════════════════════════════════════════════════════════════╗');
  console.log('║                    TASK MISSION DASHBOARD                           ║');
  console.log('╠══════════════╦═══════════════════════════╦══════════╦══════════════╣');
  console.log('║ ID           ║ Title                     ║ Progress ║ Status       ║');
  console.log('╠══════════════╬═══════════════════════════╬══════════╬══════════════╣');

  for (const m of missions) {
    const id = (m.id || '').padEnd(12).slice(0, 12);
    const title = (m.title || '').padEnd(25).slice(0, 25);
    const progress = `${m.completed_count}/${m.target_count}`.padEnd(8);
    const status = `${STATUS_ICON[m.status] || '?'} ${m.status}`.padEnd(12);
    console.log(`║ ${id} ║ ${title} ║ ${progress} ║ ${status} ║`);
  }
  console.log('╚══════════════╩═══════════════════════════╩══════════╩══════════════╝\n');
}

module.exports = {
  loadAllMissions,
  createMission,
  claimMission,
  completeMission,
  failMission,
  releaseMission,
  deleteMission,
  resetMission,
  printDashboard,
  MISSIONS_DIR
};

// CLI usage: node mission_manager.js --list
if (require.main === module) {
  const args = process.argv.slice(2);
  if (args.includes('--list')) {
    printDashboard();
  } else {
    console.log('Usage: node mission_manager.js --list');
  }
}
