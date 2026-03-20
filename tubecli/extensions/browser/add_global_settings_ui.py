import re

# Read the file
with open('C:/tubecreate-vue/python-video-studio/browser-laucher/web_manager/public/index.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Find where to insert (before "// Init")
functions_code = '''
        // Global Settings Functions
        async function openGlobalSettings() {
            try {
                const res = await fetch(`${API_URL}/global-settings`);
                const settings = await res.json();
                
                document.getElementById('globalBlacklist').value = (settings.blacklist || []).join('\\n');
                document.getElementById('globalMaxVisits').value = settings.maxVisitsPerWeek || 3;
                
                openModal('globalSettingsModal');
            } catch (err) {
                showStatus('Failed to load global settings', 'error');
            }
        }

        async function saveGlobalSettings() {
            const blacklist = document.getElementById('globalBlacklist').value
                .split('\\n')
                .map(line => line.trim())
                .filter(line => line.length > 0);
            const maxVisitsPerWeek = parseInt(document.getElementById('globalMaxVisits').value) || 3;

            try {
                const res = await fetch(`${API_URL}/global-settings`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ blacklist, maxVisitsPerWeek })
                });

                if (res.ok) {
                    closeModal();
                    showStatus('Global settings saved!', 'success');
                } else {
                    showStatus('Failed to save global settings', 'error');
                }
            } catch (err) {
                showStatus('Error saving global settings: ' + err.message, 'error');
            }
        }
'''

# Find the "// Init" comment and insert before it
pattern = r'(\s+// Init)'
content = re.sub(pattern, functions_code + r'\n\1', content)

# Write back
with open('C:/tubecreate-vue/python-video-studio/browser-laucher/web_manager/public/index.html', 'w', encoding='utf-8') as f:
    f.write(content)

print("Added global settings functions to index.html")
