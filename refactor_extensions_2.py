import os
import re

TARGET_DIRS = [
    r'c:\tubecreate-vue\tubecli\tubecli',
    r'c:\tubecreate-vue\tubecli',
]

def process_file(filepath):
    # Only process `.py`, `.js`, `.html`, `.md`, `.json`, `.css`
    if not filepath.endswith(('.py', '.js', '.html', '.md', '.json', '.css')):
        return
        
    if 'node_modules' in filepath or '.git' in filepath or '__pycache__' in filepath:
        return

    if os.path.basename(filepath) in ('refactor_extensions.py', 'refactor_extensions_2.py'):
        return

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        return

    # Specific replacements first to ensure safety
    new_content = content.replace('tubecli.extensions.market.plugin', 'tubecli.extensions.market.extension')
    new_content = new_content.replace('.plugin import', '.extension import')
    new_content = new_content.replace('import plugin', 'import extension')
    new_content = new_content.replace('plugin.py', 'extension.py')
    
    # Generic word replacements
    new_content = re.sub(r'\bPlugin\b', 'Extension', new_content)
    new_content = re.sub(r'\bplugin\b', 'extension', new_content)
    new_content = re.sub(r'\bPlugins\b', 'Extensions', new_content)
    new_content = re.sub(r'\bplugins\b', 'extensions', new_content)
    
    # Capitalized / Title Case
    new_content = re.sub(r'\bPLUGIN\b', 'EXTENSION', new_content)
    new_content = re.sub(r'\bPLUGINS\b', 'EXTENSIONS', new_content)

    if content != new_content:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"Updated: {filepath}")

def main():
    for d in TARGET_DIRS:
        if not os.path.exists(d): continue
        for root, dirs, files in os.walk(d):
            # don't process root twice
            if d == r'c:\tubecreate-vue\tubecli' and root.startswith(r'c:\tubecreate-vue\tubecli\tubecli'):
                continue
            for file in files:
                process_file(os.path.join(root, file))

if __name__ == '__main__':
    main()
