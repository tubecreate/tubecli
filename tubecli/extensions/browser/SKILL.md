---
name: Browser Automation
description: Core browser automation features including profile management, fingerprint spoofing, and AI interaction
---

# Browser Automation Extension

The `browser` extension provides a bridge between TubeCLI's AI agents and a local Node.js automation server utilizing Playwright to securely orchestrate Chromium profiles with advanced fingerprinting evasion.

## Features

- **Profile Management**: Create, list, block, and run isolated browser profiles.
- **Anti-Detect Engine**: Automatic masking of WebGL, UserAgent, WebRTC, Canvas, and Audio fingerprints.
- **AI Integration**: AI visual perception via `page_analyzer` routing and interactive visual element mapping.

## Usage

```bash
# Launch a browser profile attached to an instance
tubecli browser launch <profile_name>

# List all available browser profiles
tubecli browser profiles 

# Close an active profile and kill its associated processes
tubecli browser kill <profile_name>
```

## Developer API
Use `tubecli.extensions.browser.api_types` to integrate browser control into generic Agent node operations.
