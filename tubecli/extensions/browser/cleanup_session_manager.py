
import re

file_path = 'C:/tubecreate-vue/python-video-studio/browser-laucher/session_manager.js'

with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Remove the redundant Blacklist Filtering block (Scoring part)
# This was around line 731
redundant_blacklist_score = r'// H\. NEW: Blacklist Filtering\s*if \(el\.href && this\.isBlacklisted\(el\.href\)\) \{[\s\S]*?score -= 200; // Heavy penalty for blacklisted links\s*\}'
content = re.sub(redundant_blacklist_score, '', content)

# Remove the redundant Frequency Filtering block (Scoring part)
# This was around line 737
redundant_freq_score = r'// I\. NEW: Frequency Filtering \(Weekly limit\)[\s\S]*?score -= 100; // Penalty for frequently visited domains\s*\}\s*\} catch \(e\) \{\}\s*\}'
content = re.sub(redundant_freq_score, '', content)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Cleaned up redundant filtering logic in SessionManager")
