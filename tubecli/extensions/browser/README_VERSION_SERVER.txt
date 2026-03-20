BrowserAutomationStudio Version API (PHP)
=====================================

This script scans a directory for BrowserAutomationStudio application folders 
and returns a JSON list of available browser engines found in 'browser_versions.json'.

Deployment:
1. Upload 'check_versions.php' to your server.
2. Edit '$appsPath' in the script to point to your stored BAS versions root.
3. Access via browser or API to see the JSON list.

The script identifies:
- BAS Version
- Chromium Version
- Architecture
- Local Path on the server
