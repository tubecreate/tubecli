import os

STRINGS_TO_REPLACE = {
    'WebUIPlugin': 'WebUIExtension',
    'pluginData =': 'extensionData =',
    'pluginData?': 'extensionData?',
    'pluginMap': 'extensionMap',
    'OllamaPlugin': 'OllamaExtension',
    'MultiAgentsPlugin': 'MultiAgentsExtension',
    'MarketPlugin': 'MarketExtension',
    'CloudApiPlugin': 'CloudApiExtension',
    'BrowserPlugin': 'BrowserExtension',
    'PLUGINS_CONFIG_FILE': 'EXTENSIONS_CONFIG_FILE',
    'BUILTIN_PLUGINS': 'BUILTIN_EXTENSIONS',
    'self._plugins': 'self._extensions',
    'list_plugins': 'list_extensions',
    'PluginUpdateRequest': 'ExtensionUpdateRequest',
    'PluginInstallRequest': 'ExtensionInstallRequest',
    'get_plugin_skill_mds': 'get_extension_skill_mds',
}

def process_file(filepath):
    if not filepath.endswith(('.py', '.js', '.html', '.md', '.json', '.css')):
        return
        
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        return

    new_content = content
    for old, new in STRINGS_TO_REPLACE.items():
        new_content = new_content.replace(old, new)
        
    if content != new_content:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"Updated: {filepath}")

def main():
    for root, dirs, files in os.walk(r'c:\tubecreate-vue\tubecli\tubecli'):
        for file in files:
            process_file(os.path.join(root, file))

if __name__ == '__main__':
    main()
