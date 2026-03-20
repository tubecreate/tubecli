import re

# Read the file
with open('C:/tubecreate-vue/python-video-studio/browser-laucher/web_manager/public/index.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix the broken newline strings - they got split across lines
# Line 290-291: .join('\r\n')
content = content.replace(".join('\\r\\n')", ".join('\\n')")

# Line 302-303: .split('\r\n')
content = content.replace(".split('\\r\\n')", ".split('\\n')")

# Write back
with open('C:/tubecreate-vue/python-video-studio/browser-laucher/web_manager/public/index.html', 'w', encoding='utf-8') as f:
    f.write(content)

print("Fixed JavaScript syntax errors in index.html")
