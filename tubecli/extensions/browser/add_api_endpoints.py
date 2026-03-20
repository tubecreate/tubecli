import re

# Read the file
with open('C:/tubecreate-vue/python-video-studio/browser-laucher/web_manager/server.js', 'r', encoding='utf-8') as f:
    content = f.read()

# Add endpoints before "// Start Server"
new_endpoints = '''
// API: Get Global Settings
app.get('/api/global-settings', async (req, res) => {
    try {
        const settingsPath = path.join(PROJECT_ROOT, 'data', 'global_settings.json');
        
        let settings = { blacklist: [], maxVisitsPerWeek: 3 };
        if (await fs.pathExists(settingsPath)) {
            settings = await fs.readJson(settingsPath);
        }
        res.json(settings);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// API: Save Global Settings
app.post('/api/global-settings', async (req, res) => {
    try {
        const { blacklist, maxVisitsPerWeek } = req.body;
        const settingsPath = path.join(PROJECT_ROOT, 'data', 'global_settings.json');
        
        await fs.ensureDir(path.join(PROJECT_ROOT, 'data'));
        await fs.writeJson(settingsPath, { 
            blacklist: blacklist || [], 
            maxVisitsPerWeek: maxVisitsPerWeek || 3 
        }, { spaces: 2 });
        
        res.json({ success: true });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

'''

# Insert before "// Start Server"
content = content.replace('// Start Server', new_endpoints + '// Start Server')

# Write back
with open('C:/tubecreate-vue/python-video-studio/browser-laucher/web_manager/server.js', 'w', encoding='utf-8') as f:
    f.write(content)

print("Added global settings endpoints to server.js")
