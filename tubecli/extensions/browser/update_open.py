import re

# Read the file
with open('C:/tubecreate-vue/python-video-studio/browser-laucher/open.js', 'r', encoding='utf-8') as f:
    content = f.read()

# Replace the SessionManager instantiation
old_line = "const session = new SessionManager(minSessionMinutes, userGoal, aiModel, agentContext);"
new_line = "const session = new SessionManager(minSessionMinutes, userGoal, aiModel, agentContext, args.profile || 'default');"

content = content.replace(old_line, new_line)

# Write back
with open('C:/tubecreate-vue/python-video-studio/browser-laucher/open.js', 'w', encoding='utf-8') as f:
    f.write(content)

print("Updated SessionManager instantiation in open.js")
