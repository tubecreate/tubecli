import re

# Read the file
with open('C:/tubecreate-vue/python-video-studio/browser-laucher/session_manager.js', 'r', encoding='utf-8') as f:
    content = f.read()

# Find and replace updateContext method
old_pattern = r'(updateContext\(url\) \{\s+this\.currentContext\.url = url;\s+try \{\s+const urlObj = new URL\(url\);\s+if \(this\.currentContext\.domain && this\.currentContext\.domain !== urlObj\.hostname\) \{[^\}]+\}\s+this\.currentContext\.domain = urlObj\.hostname;)'

new_code = r'''\1
      
      // NEW: Track domain access for frequency filtering
      const visitCount = this.trackDomainAccess(urlObj.hostname);
      if (visitCount > 3) {
          console.log(`[SessionManager] Warning: ${urlObj.hostname} visited ${visitCount} times this week`);
      }'''

content = re.sub(old_pattern, new_code, content, flags=re.DOTALL)

# Write back
with open('C:/tubecreate-vue/python-video-studio/browser-laucher/session_manager.js', 'w', encoding='utf-8') as f:
    f.write(content)

print("Updated updateContext method")
