import re

# Read the file
with open('C:/tubecreate-vue/python-video-studio/browser-laucher/session_manager.js', 'r', encoding='utf-8') as f:
    content = f.read()

# Update loadBlacklist to load from global settings
old_code = '''async loadBlacklist() {
    try {
      const profilePath = path.resolve('./profiles', this.profileName);
      const configPath = path.join(profilePath, 'config.json');
      
      if (await fs.pathExists(configPath)) {
        const config = await fs.readJson(configPath);
        this.blacklist = config.blacklist || [];
        console.log(`[SessionManager] Loaded ${this.blacklist.length} blacklist patterns`);
      }
    } catch (e) {
      console.warn('[SessionManager] Failed to load blacklist:', e.message);
    }
  }'''

new_code = '''async loadBlacklist() {
    try {
      const settingsPath = path.resolve('./data/global_settings.json');
      
      if (await fs.pathExists(settingsPath)) {
        const settings = await fs.readJson(settingsPath);
        this.blacklist = settings.blacklist || [];
        this.maxVisitsPerWeek = settings.maxVisitsPerWeek || 3;
        console.log(`[SessionManager] Loaded ${this.blacklist.length} blacklist patterns, maxVisits: ${this.maxVisitsPerWeek}`);
      }
    } catch (e) {
      console.warn('[SessionManager] Failed to load global settings:', e.message);
    }
  }'''

content = content.replace(old_code, new_code)

# Update the frequency check to use maxVisitsPerWeek property
content = content.replace('if (visitCount > 3)', 'if (visitCount > this.maxVisitsPerWeek)')

# Write back
with open('C:/tubecreate-vue/python-video-studio/browser-laucher/session_manager.js', 'w', encoding='utf-8') as f:
    f.write(content)

print("Updated SessionManager to use global settings")
