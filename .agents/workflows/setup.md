---
description: How to install and setup TubeCLI
---

# Setup TubeCLI

## Prerequisites
- Python 3.10+
- pip

## Steps

1. Navigate to the project directory:
```bash
cd tubecli
```

2. Install in development mode:
```bash
pip install -e .
```

3. Initialize workspace:
```bash
tubecli init
```

This creates:
- `data/` directory for agents, skills, and workflow data
- Default "Personal Assistant" agent
- 4 default skills (AI Summarizer, Data Collector, Report Generator, Batch Command Runner)

4. Verify installation:
```bash
tubecli --version
tubecli agent list
tubecli skill list
```
