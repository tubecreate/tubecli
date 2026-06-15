# Script Studio

Visual browser automation script editor & manager for TubeCLI.

## Features
- Create and manage browser automation scripts
- Visual step editor with drag-drop reordering
- Element picker with live browser preview
- Variable interpolation ({{variable_name}})
- **Functions** — reusable scripts callable from other scripts
- Execution history and real-time logging
- Import/Export scripts as JSON

## Storage
Scripts are stored as individual JSON files in `scripts/` directory. Each file = one script.

## Step Types
- **navigate**: Go to a URL
- **click**: Click an element by CSS selector
- **type**: Enter text into an input field
- **wait**: Wait for element to appear
- **wait_hidden**: Wait for element to disappear
- **sleep**: Pause for N milliseconds
- **evaluate**: Run JavaScript code in page context
- **extract**: Get text/attribute from element, save to variable
- **screenshot**: Capture page screenshot
- **download**: Wait for and save downloads
- **condition**: If/else branching
- **loop**: Repeat steps N times
- **keyboard**: Press keyboard keys (Enter, Tab, etc.)
- **scroll**: Scroll page up/down
- **hover**: Hover over element
- **mouse_move**: Move mouse to coordinates
- **ai_generate**: Use AI to generate text, save to variable
- **call_function**: Call a reusable function (see below)

## Functions

Functions are scripts marked with `is_function: true`. They define inputs and outputs, and can be called from any script via the `call_function` step.

### Available Functions

#### `gmail_login_with_2fa` — Google/Gmail Login
Đăng nhập Google/Gmail với email, password và tự xử lý 2FA.

**Inputs:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `email` | string | ✅ | Gmail/Google email |
| `password` | string | ✅ | Account password |
| `totp_secret` | string | ❌ | TOTP 2FA secret (base32) |

**Outputs:**
| Name | Type | Description |
|------|------|-------------|
| `login_status` | string | "success" or "failed" |

**Usage example (as step in another script):**
```json
{
    "action": "call_function",
    "label": "Login Gmail",
    "params": {
        "function_slug": "gmail_login_with_2fa",
        "inputs": {
            "email": "{{profile_email}}",
            "password": "{{profile_password}}",
            "totp_secret": "{{totp_secret}}"
        },
        "outputs": {
            "my_login_result": "login_status"
        }
    }
}
```

### Creating New Functions

A function is a regular script JSON with extra fields:
```json
{
    "name": "My Function",
    "slug": "my_function",
    "is_function": true,
    "function_inputs": [
        {"name": "param1", "type": "string", "required": true, "description": "What this does"},
        {"name": "param2", "type": "string", "required": false, "description": "Optional param"}
    ],
    "function_outputs": [
        {"name": "result", "type": "string", "description": "What this returns"}
    ],
    "steps": [ ... ]
}
```

### How call_function Works
1. Caller maps its variables → function input names
2. Function runs with those inputs as {{variables}}
3. After function completes, outputs are mapped back to caller's variables
4. Variable scope is isolated — function doesn't pollute caller's scope

## Variables
- Defined in `variables` array: `[{"name": "email", "default": "test@gmail.com"}]`
- Referenced in step params: `{{variable_name}}`
- Runtime values passed via API: `POST /run` with `{"variables": {"email": "real@gmail.com"}}`
- Special variables: `_loop_index`, `_last_download`, `_ai_text`

## API
- `GET /api/v1/scripts` — List all scripts
- `POST /api/v1/scripts` — Create script
- `GET /api/v1/scripts/{slug}` — Get script by slug
- `PUT /api/v1/scripts/{slug}` — Update script
- `DELETE /api/v1/scripts/{slug}` — Delete script
- `POST /api/v1/scripts/{slug}/run` — Run script
- `GET /api/v1/scripts/functions` — List all functions (lightweight, no steps)
- `GET /api/v1/scripts/functions/{slug}` — Get function with full detail
- `GET /api/v1/scripts/by-slug/{slug}` — Get any script by slug
