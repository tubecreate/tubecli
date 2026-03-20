import re

# Read the file
with open('C:/tubecreate-vue/python-video-studio/browser-laucher/session_manager.js', 'r', encoding='utf-8') as f:
    content = f.read()

# Define the new methods
new_methods = '''
  /**
   * Load blacklist from profile config
   */
  async loadBlacklist() {
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
  }

  /**
   * Check if a URL/domain matches blacklist patterns
   */
  isBlacklisted(url) {
    if (!url || this.blacklist.length === 0) return false;
    
    const lowerUrl = url.toLowerCase();
    return this.blacklist.some(pattern => {
      const lowerPattern = pattern.toLowerCase();
      return lowerUrl.includes(lowerPattern);
    });
  }

  /**
   * Track domain access and return visit count for current week
   */
  trackDomainAccess(domain) {
    if (!domain) return 0;
    
    const now = Date.now();
    const weekAgo = now - (7 * 24 * 60 * 1000);
    
    // Initialize if needed
    if (!this.domainAccessHistory[domain]) {
      this.domainAccessHistory[domain] = [];
    }
    
    // Clean old visits
    this.domainAccessHistory[domain] = this.domainAccessHistory[domain].filter(t => t > weekAgo);
    
    // Add current visit
    this.domainAccessHistory[domain].push(now);
    
    return this.domainAccessHistory[domain].length;
  }
'''

# Find the position to insert (before scanPageContent method)
pattern = r'(\s+/\*\*\s+\*\s+Scan page content to detect available elements)'
match = re.search(pattern, content)

if match:
    insert_pos = match.start()
    updated_content = content[:insert_pos] + new_methods + '\n' + content[insert_pos:]
    
    # Write back
    with open('C:/tubecreate-vue/python-video-studio/browser-laucher/session_manager.js', 'w', encoding='utf-8') as f:
        f.write(updated_content)
    
    print("Successfully added methods to session_manager.js")
else:
    print("Could not find insertion point")
