
# Read the file
file_path = 'C:/tubecreate-vue/python-video-studio/browser-laucher/web_manager/public/index.html'
with open(file_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Fix line 290
# Original lines 290-291: 
# document.getElementById('globalBlacklist').value = (settings.blacklist || []).join('
# ');
#
# We want to merge them into one line with \n inside the string
# The index is 0-based, so line 290 is at index 289
if len(lines) > 291:
    line_290 = lines[289].replace('\n', '') # Remove the newline at the end of line 290
    line_291 = lines[290]
    
    # Check if we are looking at the right lines
    if "join('" in line_290 and "');" in line_291:
        # Construct the fixed line: ...join('\n');
        fixed_line = line_290 + "\\n" + line_291
        
        # Replace the two lines with the single fixed line
        lines[289] = fixed_line
        lines[290] = "" # Empty the second line to remove it

# Fix line 302 (now shifted or maybe not if we just empty the line)
# Let's find the second occurrence.
# Original lines 302-303:
# .split('
# ')
#
# We want to merge into .split('\n')

# Iterate through lines to find the split pattern since line numbers might be tricky if we modified the list
# But wait, modifying list while iterating is tricky. Let's just do a string replacement on the whole content.
# It's safer.

with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Replace the specific broken patterns
# Pattern 1: .join('\n') broken across lines
content = content.replace(".join('\n');", ".join('\\n');") # If already correct (unlikely given error)
# The actual broken pattern in file is likely .join('\r\n') or just \n
# Let's use regex to find the broken string literal
import re

# Fix .join('...')
content = re.sub(r"\.join\('[\r\n]+'\)", ".join('\\\\n')", content)

# Fix .split('...')
content = re.sub(r"\.split\('[\r\n]+'\)", ".split('\\\\n')", content)


# Write back
with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Fixed JavaScript syntax errors in index.html using regex")
