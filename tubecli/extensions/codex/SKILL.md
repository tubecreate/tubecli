---
name: "Codex"
description: "Mission control: create tasks, assign to an agent/team, wait for human approval, worker runs in the background, accept results."
version: "1.0.0"
author: "TubeCreate"
---

# 🎛 Codex — work control panel

Codex is where ALL work that truly needs doing lives. Any request that **runs long**, is **resource-heavy** (LLM, browser, download/upload), **changes data or the outside world**, or **needs someone to review the result** → do NOT do it inline; create a Codex task and report the task number to the user. Only answer directly when the question is a quick lookup/explanation that produces no change.

## 🛑 Approval rules (MANDATORY)
- Tasks created by the AI are **ALWAYS** in `pending_approval` state and **wait for human approval**. The AI **must not** approve its own tasks.
- After creating a task, **NEVER** say the work has run/finished. Only say: created `#<n>`, awaiting approval, and instruct the user to type `approve <n>`.
- Lifecycle: `pending_approval → queued → running → review → done` (+ `failed` can be retried, `rejected`, `cancelled`).

## ⚠️ FLAT PAYLOAD rule (MANDATORY)
The action parser can only read JSON that is **one level deep, all scalar values** (string/number/bool). Do **NOT** use nested objects, do **NOT** use arrays in an action.
To split a large job into smaller ones → emit **MULTIPLE consecutive `codex_create_task` actions**, one `goal` per action. Never pack a list of subtasks into a single action.

## 📥 codex_create_task — create a new task
```json
{"action": "codex_create_task", "goal": "Full description of what needs to be done", "title": "Short title", "assignee_type": "agent", "assignee": "Agent name or team name", "skill": "Skill name (optional)", "priority": 0}
```
- `goal` (required) — a self-contained description; the worker reads only this string.
- `assignee_type`: `"agent"` or `"team"`. `assignee` takes a **NAME** (matching an existing agent/team name), no ID needed.
- `priority`: the higher the number, the sooner it runs (default 0).

## 📥 codex_list_tasks — view the list
```json
{"action": "codex_list_tasks", "status": "active"}
```
`status`: `active` (default) | `pending_approval` | `queued` | `running` | `review` | `done` | `failed` | `rejected` | `cancelled`.

## 📥 codex_task_status — details of one task
```json
{"action": "codex_task_status", "task": "3"}
```
`task` takes a short number (`3`), the full id, or part of the title.

## 📥 codex_approve / codex_reject — decide on the user's behalf
Only use when the **user explicitly states** they want to approve/reject.
```json
{"action": "codex_approve", "task": "3", "note": "Reason (optional)"}
```
```json
{"action": "codex_reject", "task": "3", "note": "Reason (optional)"}
```

## 📥 codex_cancel — cancel a pending/running task
```json
{"action": "codex_cancel", "task": "3"}
```

## 📥 codex_retry — re-run a `failed` or `review` task
```json
{"action": "codex_retry", "task": "3"}
```

## 🌐 HTTP API (via `run_api`, prefix `/api/v1/codex`)
Prefer the `codex_*` actions above. Only use `run_api` for GET endpoints not in the action list.

| Method | Endpoint | Purpose |
|--------|----------|----------|
| GET | `/api/v1/codex/stats` | Count tasks by status |
| GET | `/api/v1/codex/tasks?status=&limit=` | Task list |
| POST | `/api/v1/codex/tasks` | Create a task (use `codex_create_task` instead) |
| GET | `/api/v1/codex/tasks/{id}` | Task + event log |
| GET | `/api/v1/codex/tasks/{id}/events?after=&limit=` | Event log |
| POST | `/api/v1/codex/tasks/{id}/approve` · `/reject` · `/cancel` · `/retry` | Decisions |
| POST | `/api/v1/codex/tasks/{id}/review` | Acceptance (`accepted: true/false`) |
| POST | `/api/v1/codex/tasks/{id}/plan` | AI breaks down the goal (SLOW 10–60s) |
| GET | `/api/v1/codex/assignees` | List of agents + teams |
| GET | `/api/v1/codex/worker` | Worker status |

Visual dashboard: `GET /codex`.

## ⌨️ Text commands (0 token — the user types them directly, the AI need not process them)
`codex` · `codex <n>` · `approve <n>` · `reject <n>` · `retry <n>` · `accept <n>` · `codex cancel <n>` · `codex running|done|failed`
(A bare «cancel»/«huỷ» is already claimed by the bot's plan-confirmation flow, so cancelling a task must be typed with the `codex` prefix.)
When the user's message matches this form, **do not** emit an action — the system handles it itself.

## 💡 Examples
**User:** "Research 5 of my competitor YouTube channels, then write a report"
→ long, resource-heavy, needs review ⇒ create a task, don't do it yourself:
```json
{"action": "codex_create_task", "goal": "Research 5 competitor YouTube channels in the same niche; compare posting frequency, titles, thumbnails, average views, and write a summary report with recommendations", "title": "5 YouTube competitors report", "assignee_type": "team", "assignee": "Research Team"}
```

**User:** "Translate this article then post it to WordPress, and once done create an illustration"
→ two jobs ⇒ **two separate actions**, don't cram them into an array:
```json
{"action": "codex_create_task", "goal": "Translate the article into Vietnamese and publish it to WordPress", "title": "Translate + publish to WordPress", "assignee_type": "agent", "assignee": "Writer"}
```
```json
{"action": "codex_create_task", "goal": "Create an illustration for the article just published to WordPress", "title": "Article illustration", "assignee_type": "agent", "assignee": "Designer"}
```

**User:** "Are there any tasks waiting for my approval?"
```json
{"action": "codex_list_tasks", "status": "pending_approval"}
```

**User:** "How is task 3 going?"
```json
{"action": "codex_task_status", "task": "3"}
```
