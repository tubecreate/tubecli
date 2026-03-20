
import re

file_path = 'C:/tubecreate-vue/python-video-studio/browser-laucher/session_manager.js'

with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Update Constructor to init maxVisitsPerDay and call loadHistory
# Find constructor
constructor_match = re.search(r'constructor\(.*?\)\s*\{', content)
if constructor_match:
    # Add initializations
    init_code = """
    this.maxVisitsPerWeek = 3;
    this.maxVisitsPerDay = 1; // NEW: Daily limit
    this.domainAccessHistory = {}; 
    
    // Load history per profile
    this.loadHistory().catch(e => console.warn('[SessionManager] Failed to load history:', e.message));
    """
    # We'll inject this after super() or at end of constructor logic before loadBlacklist
    # Easier to replace specific lines or append. 
    # Let's replace the this.domainAccessHistory = {}; line
    content = content.replace("this.domainAccessHistory = {}; // NEW: Domain -> array of timestamps", init_code)

# 2. Add loadHistory and saveHistory methods
# We'll add them before loadBlacklist
methods_code = """
  async loadHistory() {
    if (!this.profileName) return;
    try {
      const historyPath = path.resolve('./profiles', this.profileName, 'history.json');
      if (await fs.pathExists(historyPath)) {
        const data = await fs.readJson(historyPath);
        this.domainAccessHistory = data.domainAccessHistory || {};
        // console.log(`[SessionManager] Loaded history for profile ${this.profileName}`);
      }
    } catch (e) {
      console.warn('[SessionManager] Failed to load history:', e.message);
    }
  }

  async saveHistory() {
    if (!this.profileName) return;
    try {
      const profileDir = path.resolve('./profiles', this.profileName);
      await fs.ensureDir(profileDir);
      const historyPath = path.join(profileDir, 'history.json');
      await fs.writeJson(historyPath, { domainAccessHistory: this.domainAccessHistory }, { spaces: 2 });
    } catch (e) {
      console.warn('[SessionManager] Failed to save history:', e.message);
    }
  }

"""
content = content.replace("async loadBlacklist() {", methods_code + "async loadBlacklist() {")

# 3. Update loadBlacklist to load maxVisitsPerDay
content = content.replace(
    "this.maxVisitsPerWeek = settings.maxVisitsPerWeek || 3;",
    "this.maxVisitsPerWeek = settings.maxVisitsPerWeek || 3;\n        this.maxVisitsPerDay = settings.maxVisitsPerDay || 1;"
)

# 4. Update trackDomainAccess to handle daily/weekly and save history
# Replace the old trackDomainAccess method
old_track_method = re.search(r'trackDomainAccess\(domain\)\s*\{[\s\S]*?return this\.domainAccessHistory\[domain\]\.length;\s*\}', content)
if old_track_method:
    new_track_method = """trackDomainAccess(domain) {
    if (!domain) return { day: 0, week: 0 };
    
    const now = Date.now();
    const oneDayAgo = now - (24 * 60 * 60 * 1000);
    const oneWeekAgo = now - (7 * 24 * 60 * 60 * 1000);
    
    // Initialize if needed
    if (!this.domainAccessHistory[domain]) {
      this.domainAccessHistory[domain] = [];
    }
    
    // Clean old visits (> 1 week)
    this.domainAccessHistory[domain] = this.domainAccessHistory[domain].filter(t => t > oneWeekAgo);
    
    // Add current visit
    this.domainAccessHistory[domain].push(now);
    
    // Calculate counts
    const weekCount = this.domainAccessHistory[domain].length;
    const dayCount = this.domainAccessHistory[domain].filter(t => t > oneDayAgo).length;
    
    // Persist
    this.saveHistory().catch(e => console.error(e));
    
    return { day: dayCount, week: weekCount };
  }"""
    content = content.replace(old_track_method.group(0), new_track_method)

# 5. Update _resolveActionParams for strict filtering
# We need to find the loop "for (const el of elements) {" and inject checks at the start

# Replace the loop body start
loop_start = "for (const el of elements) {\n              const text = el.text.toLowerCase();"
new_loop_start = """for (const el of elements) {
              // STRICT PRE-FILTERING
              if (el.href) {
                  // 1. Blacklist Check
                  if (this.isBlacklisted(el.href)) {
                      // console.log(`[Grounding] Skipped blacklisted: ${el.href}`);
                      continue; // SKIP COMPLETELY
                  }
                  
                  // 2. Frequency Check
                  try {
                       const url = new URL(el.href);
                       const domain = url.hostname;
                       const history = this.domainAccessHistory[domain] || [];
                       
                       const now = Date.now();
                       const oneDayAgo = now - (24 * 60 * 60 * 1000);
                       const oneWeekAgo = now - (7 * 24 * 60 * 60 * 1000);
                       
                       const weekVisits = history.filter(t => t > oneWeekAgo).length;
                       const dayVisits = history.filter(t => t > oneDayAgo).length;
                       
                       if (weekVisits >= this.maxVisitsPerWeek) {
                           // console.log(`[Grounding] Skipped (Max Week): ${domain}`);
                           continue; // SKIP COMPLETELY
                       }
                       
                       if (dayVisits >= this.maxVisitsPerDay) {
                           // console.log(`[Grounding] Skipped (Max Day): ${domain}`);
                           continue; // SKIP COMPLETELY
                       }
                  } catch(e) {}
              }

              const text = el.text.toLowerCase();"""

content = content.replace(loop_start, new_loop_start)


# 6. Update updateContext to handle object return from trackDomainAccess
# Find: const visitCount = this.trackDomainAccess(urlObj.hostname);
# Replace with destructuring and updated logging
update_context_match = r'const visitCount = this\.trackDomainAccess\(urlObj\.hostname\);'
new_update_context = """const { day, week } = this.trackDomainAccess(urlObj.hostname);
      if (week > this.maxVisitsPerWeek || day > this.maxVisitsPerDay) {
          console.log(`[SessionManager] Warning: ${urlObj.hostname} visits - Day: ${day}/${this.maxVisitsPerDay}, Week: ${week}/${this.maxVisitsPerWeek}`);
      }"""
content = re.sub(update_context_match, new_update_context, content)


with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Updated SessionManager with persistence and strict filtering")
