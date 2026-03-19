import os
import re

TARGET_DIRS = [
    r'c:\tubecreate-vue\tubecli\tubecli',
]

# Order matters! Replace more specific ones first
REPLACEMENTS = [
    # 1. Imports and variable names
    ('tubecli.plugins', 'tubecli.extensions'),
    ('from tubecli.plugins', 'from tubecli.extensions'),
    ('tubecli.core.plugin_manager', 'tubecli.core.extension_manager'),
    ('plugin_manager.py', 'extension_manager.py'),
    ('plugin_cmd.py', 'extension_cmd.py'),
    ('plugin_instance', 'extension_instance'),
    ('plugin_manager', 'extension_manager'),
    ('PluginManager', 'ExtensionManager'),
    
    # 2. Base classes
    ('class Plugin(', 'class Extension('),
    ('Plugin(', 'Extension('),
    ('from tubecli.core.extension_manager import Plugin', 'from tubecli.core.extension_manager import Extension'),
    ('def __init__(self, name: str = "', 'def __init__(self, name: str = "'), # Just to align structure if needed
    
    # 3. Directories & JSON
    ('plugins.json', 'extensions.json'),
    ('plugins_external', 'extensions_external'),
    ('tubecli-plugin.json', 'tubecli-extension.json'),
    ('PLUGINS_DIR', 'EXTENSIONS_DIR'),
    ('PLUGINS_EXTERNAL_DIR', 'EXTENSIONS_EXTERNAL_DIR'),
    
    # 4. API Endpoints
    ('/api/v1/plugins', '/api/v1/extensions'),
    
    # 5. CLI Commands
    ('tubecli plugin', 'tubecli extension'),
    ('@app.command("plugin")', '@app.command("extension")'),
    ('plugin command group', 'extension command group'),
    
    # 6. General text replacements (be careful with these)
    ('register_plugin_nodes', 'register_extension_nodes'),
    ('discover_plugins', 'discover_extensions'),
    ('discover_external_plugins', 'discover_external_extensions'),
    ('get_plugins', 'get_extensions'),
    ('load_plugin', 'load_extension'),
    ('init_plugins', 'init_extensions'),
    
    # In API strings
    ('Manage plugins', 'Manage extensions'),
    ('Plugin system', 'Extension system'),
]

# Specifically for replacing `Plugin` to `Extension` in class definitions and type hints:
REGEX_REPLACEMENTS = [
    (r'\bPlugin\b', 'Extension'),
    (r'\bplugin\b', 'extension'),
    (r'\bPlugins\b', 'Extensions'),
    (r'\bplugins\b', 'extensions'),
]

def process_file(filepath):
    # Skip standard python cache and git
    if '__pycache__' in filepath or '.git' in filepath:
        return

    # Only process `.py`, `.js`, `.html`, `.md`, `.json`
    if not filepath.endswith(('.py', '.js', '.html', '.md', '.json', '.css')):
        return
        
    # Exclude this script itself and node_modules if any
    if os.path.basename(filepath) == 'refactor_extensions.py' or 'node_modules' in filepath:
        return

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
        return

    new_content = content
    
    # Exact replacements
    for old, new in REPLACEMENTS:
        new_content = new_content.replace(old, new)

    # Some targeted regex to catch 'plugin' -> 'extension' in variables that were missed
    # Be careful not to mess up anything generic... 
    # Let's do a safe targeted regex on known structures
    new_content = re.sub(r'def\s+(\w+)_plugin\b', r'def \1_extension', new_content)
    new_content = re.sub(r'\bplugin_(\w+)\b', r'extension_\1', new_content)
    new_content = re.sub(r'\b(\w+)_plugin\b', r'\1_extension', new_content)

    # In app.js, plugins might specifically refer to the extension list variables etc.
    # We replaced `plugins` -> `extensions` above in exact matches. Let's do generic word replacement safely
    new_content = re.sub(r'\bplugins\b', 'extensions', new_content)
    new_content = re.sub(r'\bPlugins\b', 'Extensions', new_content)
    
    if content != new_content:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"Updated: {filepath}")

def main():
    for d in TARGET_DIRS:
        for root, dirs, files in os.walk(d):
            for file in files:
                process_file(os.path.join(root, file))

    # Also check config files in outer dir if any
    process_file(r'c:\tubecreate-vue\tubecli\tubecli_config.py')  # if exists
    
if __name__ == '__main__':
    main()
