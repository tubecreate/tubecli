"""
TubeCLI REST API Server
FastAPI-based REST API for agents, skills, and workflows.
"""
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import os, sys
import mimetypes

# Fix Windows registry MIME type bug for CSS/JS/SVG files
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("image/png", ".png")
mimetypes.add_type("image/jpeg", ".jpg")
mimetypes.add_type("image/webp", ".webp")
mimetypes.add_type("application/json", ".json")


app = FastAPI(
    title="TubeCLI API",
    description="REST API for TubeCLI — AI Agent management, skills, and workflows.",
    version="0.1.0",
    docs_url="/api/v1/docs",
    redoc_url="/api/v1/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Cross-origin guard for the whole API surface ─────────────────────────
# CORS above is deliberately permissive so any local tool can call the API. That
# alone would let ANY web page the user happens to have open drive this server
# through their own browser: it binds to loopback, but the attacker's JavaScript
# runs inside the victim's browser, which is already on loopback. The dangerous
# reach is not only credential endpoints — POST /api/v1/extensions/install does
# git clone + pip install + npm install, i.e. arbitrary code execution.
#
# Guarding router-by-router missed that: only two extension routers carried the
# dependency, leaving every route defined here unprotected. A middleware covers
# the entire surface at once and cannot be forgotten when a route is added.
#
# Requests with no Origin header (curl, the CLI itself, Telegram, any
# server-side client) are untouched. Browser requests are allowed only from
# loopback, or from a host listed in TUBECLI_ALLOWED_ORIGIN_HOSTS for people who
# deliberately serve the dashboard on a LAN address.
@app.middleware("http")
async def _guard_cross_origin(request: Request, call_next):
    if request.method != "OPTIONS":  # let CORS preflight through
        try:
            from tubecli.core.origin_guard import is_origin_allowed
            if not is_origin_allowed(request.headers.get("origin"),
                                     request.headers.get("host", "")):
                from fastapi.responses import JSONResponse
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Cross-origin request refused. Open the dashboard "
                                       "from this machine, or set TUBECLI_ALLOWED_ORIGIN_HOSTS."},
                )
        except Exception:
            pass  # never let the guard itself take the server down
    return await call_next(request)


def check_and_generate_daily_keywords(agent, now_dt):
    """Checks if daily evolved keywords exist for the current date. Generates them via LLM if not."""
    import json
    from pathlib import Path
    from tubecli.core.agent import agent_manager
    from tubecli.core.brain import AgentBrain
    from tubecli.core.ai_generator import extract_json

    date_str = now_dt.strftime("%Y-%m-%d")
    routine = agent.routine or {}
    daily_keywords = routine.get("daily_keywords") or {}

    if daily_keywords.get("date") == date_str:
        return daily_keywords

    print(f"[Scheduler Callback] Daily keywords stale or missing for {date_str}. Generating evolved keywords via AI...")

    # 1. Retrieve recent history titles
    scraped_data_dir = Path(__file__).parent.parent / "extensions" / "browser" / "scraped_data"
    recent_history_titles = []
    allowed_profiles = getattr(agent, "allowed_profiles", []) or []
    for profile in allowed_profiles:
        history_path = scraped_data_dir / profile / "history.json"
        if history_path.exists():
            try:
                with open(history_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    articles = data.get("scrapedArticles", [])
                    filtered_articles = [
                        a for a in articles 
                        if not a.get("agentId") and not a.get("agent_id") or a.get("agentId") == agent.id or a.get("agent_id") == agent.id
                    ]
                    for a in filtered_articles[:15]:
                        if a.get("title") and a.get("title") != "Untitled":
                            recent_history_titles.append(f"- {a.get('title')} ({a.get('url', '')})")
            except Exception:
                pass

    # 2. Build interests list
    persona = agent.persona or {}
    interests = persona.get("interests", []) or routine.get("interests", []) or []
    work_habits = routine.get("workHabits") or persona.get("workHabits") or {}
    focus_areas = work_habits.get("focusAreas", []) or []
    combined_topics = list(dict.fromkeys([str(t) for t in interests + focus_areas if t]))

    history_text = "\n".join(recent_history_titles[:15]) if recent_history_titles else "No history yet (First day running)."

    # Language instruction for keyword generation
    agent_language = getattr(agent, "language", "auto") or "auto"
    _LANGUAGE_NAMES = {
        "auto": None,
        "vi": "Vietnamese",
        "en": "English",
        "zh": "Chinese (Simplified)",
        "zh-TW": "Chinese (Traditional)",
        "ja": "Japanese",
        "ko": "Korean",
        "es": "Spanish",
        "tr": "Turkish",
        "ru": "Russian",
        "fr": "French",
        "de": "German",
        "pt": "Portuguese",
        "ar": "Arabic",
        "th": "Thai",
        "id": "Indonesian",
    }
    lang_name = _LANGUAGE_NAMES.get(agent_language)
    lang_instruction = (
        f"\nIMPORTANT: Write ALL search queries in {lang_name}. The queries must be in {lang_name} language."
        if lang_name else ""
    )

    prompt = f"""You are the core intelligence of the agent '{agent.name}'.
Description / Profession of the agent:
"{agent.description}"

Agent's interests and focus topics:
{json.dumps(combined_topics, ensure_ascii=False)}

Here is the agent's recent web browsing history (last visited pages):
{history_text}

Your task is to generate a progressive and evolved set of search queries/keywords for today: {date_str}.{lang_instruction}
Rules for evolution and progression:
1. Progress from basic/foundational concepts to more advanced, specific, and deeper concepts based on what has been browsed.
2. Avoid repeating exactly the same queries or topics already found in the recent history.
3. Align the topics with the agent's profession and specific interest areas.
4. Provide exactly 5 distinct search queries for each of the following time periods: "morning", "afternoon", "evening", "night".
5. Return the result in raw JSON format matching this EXACT structure (output ONLY the JSON block, no explanations):
{{
  "morning": ["query 1", "query 2", "query 3", "query 4", "query 5"],
  "afternoon": ["query 1", "query 2", "query 3", "query 4", "query 5"],
  "evening": ["query 1", "query 2", "query 3", "query 4", "query 5"],
  "night": ["query 1", "query 2", "query 3", "query 4", "query 5"]
}}
"""
    messages = [
        {"role": "system", "content": "You are a precise JSON keyword generator. Output only valid JSON."},
        {"role": "user", "content": prompt}
    ]

    try:
        raw_response = AgentBrain._call_llm(agent.to_dict(), messages, temperature=0.7)
        json_str = extract_json(raw_response)
        evolved_data = json.loads(json_str)
        if all(k in evolved_data for k in ["morning", "afternoon", "evening", "night"]):
            new_keywords = {
                "date": date_str,
                "morning": evolved_data["morning"],
                "afternoon": evolved_data["afternoon"],
                "evening": evolved_data["evening"],
                "night": evolved_data["night"]
            }
            # Deep-reload routine from agent to avoid overwriting updates
            agent = agent_manager.get(agent.id)
            routine = agent.routine or {}
            routine["daily_keywords"] = new_keywords
            agent_manager.update(agent.id, routine=routine)
            print(f"[Scheduler Callback] Successfully saved daily evolved keywords: {new_keywords}")
            return new_keywords
    except Exception as e:
        print(f"[Scheduler Callback] Evolved daily keywords generation failed: {e}. Falling back to default interests.")

    return {}


def run_agent_routine(agent_id: str):
    """Callback for running an agent's daily behavior routine on schedule."""
    import random
    import datetime
    from tubecli.core.agent import agent_manager
    
    agent = agent_manager.get(agent_id)
    if not agent:
        print(f"[Scheduler Callback] Agent {agent_id} not found")
        return
        
    print(f"\n[Scheduler Callback] >>> Executing scheduled behavior routine for agent '{agent.name}' ({agent.id}) <<<")
    
    # 1. Resolve Profile Name
    profile_name = "default"
    if agent.allowed_profiles:
        selected = random.choice(agent.allowed_profiles)
        if isinstance(selected, dict):
            profile_name = selected.get("name", "default")
        else:
            profile_name = str(selected)
        print(f"[Scheduler Callback] Selected profile '{profile_name}' from allowed_profiles: {agent.allowed_profiles}")
    else:
        try:
            from tubecli.extensions.browser.profile_manager import list_profiles
            profiles = list_profiles()
            if profiles:
                selected = random.choice([p for p in profiles if (p.get("name") if isinstance(p, dict) else p) != "default"] or ["default"])
                if isinstance(selected, dict):
                    profile_name = selected.get("name", "default")
                else:
                    profile_name = str(selected)
                print(f"[Scheduler Callback] No profile assigned, selected random local profile '{profile_name}'")
        except Exception as e:
            print(f"[Scheduler Callback] Profile check warning: {e}")
            
    # 2. Determine Time of Day in Agent's Timezone
    tz_str = getattr(agent, "timezone", None)
    now = datetime.datetime.now()
    if tz_str and isinstance(tz_str, str) and tz_str.strip():
        tz_clean = tz_str.strip()
        try:
            from zoneinfo import ZoneInfo
            now = datetime.datetime.now(ZoneInfo(tz_clean))
        except Exception:
            try:
                import pytz
                now = datetime.datetime.now(pytz.timezone(tz_clean))
            except Exception:
                pass
                
    hour = now.hour
    time_period = "night"
    if 5 <= hour < 12:
        time_period = "morning"
    elif 12 <= hour < 17:
        time_period = "afternoon"
    elif 17 <= hour < 22:
        time_period = "evening"
        
    print(f"[Scheduler Callback] Period: {time_period} (hour: {hour}, timezone: {tz_str or 'local'})")
    
    # Check and generate daily keywords via AI
    daily_keywords = check_and_generate_daily_keywords(agent, now)
    if daily_keywords:
        agent = agent_manager.get(agent_id)
        
    # 3. Resolve Persona / Routine behavior configurations
    routine = agent.routine or {}
    persona = agent.persona or {}
    
    daily_routine = routine.get("dailyRoutine") or persona.get("dailyRoutine") or {}
    work_habits = routine.get("workHabits") or persona.get("workHabits") or {}
    
    period_tasks = {}
    if isinstance(daily_routine, dict):
        period_tasks = daily_routine.get(time_period, {})
        if not isinstance(period_tasks, dict):
            if isinstance(period_tasks, list):
                period_tasks = {str(task): True for task in period_tasks if task}
            else:
                period_tasks = {}
    elif isinstance(daily_routine, list):
        period_tasks = {str(task): True for task in daily_routine if task}
        
    active_tasks = []
    if isinstance(period_tasks, dict):
        active_tasks = [task for task, enabled in period_tasks.items() if enabled]
    
    behavior = "browse"
    if active_tasks:
        chosen_task = random.choice(active_tasks)
        print(f"[Scheduler Callback] Selected task '{chosen_task}' from active tasks: {active_tasks}")
        task_lower = chosen_task.lower()
        if any(x in task_lower for x in ["email", "mail"]):
            behavior = "checkEmails"
        elif any(x in task_lower for x in ["news", "headline", "calendar"]):
            behavior = "morningCheck"
        elif any(x in task_lower for x in ["video", "youtube"]):
            behavior = "watchVideos"
        elif any(x in task_lower for x in ["study", "learn", "course", "read"]):
            behavior = "study"
        elif any(x in task_lower for x in ["analyze", "research", "stock", "chart", "company"]):
            behavior = "work"
        else:
            behavior = "work"
    else:
        behavior = random.choice(["work", "research", "study", "morningCheck"])
        print(f"[Scheduler Callback] No active tasks. Using fallback behavior: {behavior}")
        
    # 4. Generate Diverse Prompt
    import hashlib
    interests = persona.get("interests") or routine.get("interests") or []
    if not isinstance(interests, list):
        interests = [interests] if interests else []
    focus_areas = work_habits.get("focusAreas") or []
    if not isinstance(focus_areas, list):
        focus_areas = [focus_areas] if focus_areas else []
    combined_topics = list(dict.fromkeys([str(t) for t in interests + focus_areas if t]))
    
    hour_slot = now.strftime('%Y%m%d%H')
    seed_str = f"{profile_name}|{agent.name}|{hour_slot}"
    seed_int = int(hashlib.md5(seed_str.encode()).hexdigest(), 16)
    rng = random.Random(seed_int)
    
    # Occasionally add a natural time marker (not a forced year number)
    _time_hints = ["", "", "", "latest", "recently", "this year", "new", "trending"]
    _time_hint = rng.choice(_time_hints).strip()

    def _with_hint(template: str) -> str:
        """Randomly sprinkle a natural time hint into a template, or leave as-is."""
        if _time_hint and "{topic}" in template and rng.random() < 0.35:
            return template.replace("{topic}", f"{_time_hint} {{topic}}")
        return template

    fmt_templates = {
        "work": [
            "how to {topic}",
            "{topic} best practices",
            "latest {topic} news",
            "{topic} tutorial for professionals",
            "{topic} tips and tricks",
            "top {topic} tools",
            "{topic} case study",
        ],
        "research": [
            "latest research on {topic}",
            "{topic} future trends",
            "what is {topic} explained",
            "{topic} in-depth analysis",
            "breakthroughs in {topic}",
        ],
        "study": [
            "learn {topic} from scratch",
            "{topic} for beginners",
            "{topic} complete guide",
            "{topic} online course free",
            "how to master {topic}",
        ],
        "morningCheck": [
            "{topic} news today",
            "breaking {topic} updates",
            "latest {topic} headlines",
        ],
        "entertainment": [
            "top {topic}",
            "{topic} highlights",
            "best {topic} videos",
        ],
        "watchVideos": [
            "best {topic} youtube",
            "{topic} video review",
            "{topic} documentary",
        ],
        "relax": [
            "{topic} life style tips",
            "{topic} wellness guide",
        ],
        "checkEmails": [
            "gmail", "outlook mail", "email inbox",
        ],
    }
    # Apply natural time hints to templates
    fmt_templates = {
        k: [_with_hint(t) for t in v]
        for k, v in fmt_templates.items()
    }
    
    fmts = fmt_templates.get(behavior, ["{topic} news", "about {topic}"])
    
    base_query = ""
    today_keywords = daily_keywords.get(time_period, []) if isinstance(daily_keywords, dict) else []
    if not isinstance(today_keywords, list):
        today_keywords = [today_keywords] if today_keywords else []

    if today_keywords:
        # --- Used-keyword tracking: pick next unused keyword, reset daily ---
        today_date = now.strftime('%Y-%m-%d')
        routine_data = agent.routine or {}
        used_meta = routine_data.get("used_keywords_today", {})
        if not isinstance(used_meta, dict):
            used_meta = {}

        # Reset if it's a new day
        if used_meta.get("date") != today_date:
            used_meta = {"date": today_date, "used": {}}

        used_dict = used_meta.get("used")
        if not isinstance(used_dict, dict):
            used_dict = {}
        period_used = used_dict.get(time_period, [])
        if not isinstance(period_used, list):
            period_used = []

        # Find first unused keyword (cycle back when all used)
        available = [kw for kw in today_keywords if kw not in period_used]
        if not available:
            print(f"[Scheduler Callback] All keywords used for '{time_period}' today. Resetting cycle.")
            period_used = []
            available = list(today_keywords)

        base_query = available[0] if available else ""
        print(f"[Scheduler Callback] Selected evolved query for period '{time_period}': '{base_query}'")

        # Mark as used and persist
        if base_query:
            period_used.append(base_query)
            if "used" not in used_meta:
                used_meta["used"] = {}
            used_meta["used"][time_period] = period_used
            routine_data["used_keywords_today"] = used_meta
            try:
                from tubecli.core.agent import agent_manager
                agent.routine = routine_data
                agent_manager.update(agent.id, routine=routine_data)
                print(f"[Scheduler Callback] Marked '{base_query}' as used for '{time_period}'. "
                      f"Remaining: {[kw for kw in today_keywords if kw not in period_used]}")
            except Exception as _e:
                print(f"[Scheduler Callback] Warning: could not persist used_keywords_today: {_e}")

    elif combined_topics:
        topic_idx = seed_int % len(combined_topics)
        topic = combined_topics[topic_idx]
        if len(combined_topics) > 1 and rng.random() < 0.3:
            topic2_idx = (topic_idx + 1) % len(combined_topics)
            topic2 = combined_topics[topic2_idx]
            combiner = rng.choice([f"{topic} vs {topic2}", f"{topic} and {topic2}", f"{topic} {topic2}"])
            base_query = rng.choice(fmts).replace("{topic}", combiner)
        else:
            base_query = rng.choice(fmts).replace("{topic}", topic)
    else:
        fallbacks = {
            "checkEmails": ["gmail", "outlook"],
            "morningCheck": ["breaking news today", "world news"],
            "work": ["github trending", "technology news"],
            "research": ["AI advancements", "science news", "latest research"],
            "study": ["free coding tutorials", "learning resources"],
            "watchVideos": ["youtube trending", "interesting tech videos"],
        }
        choices = fallbacks.get(behavior, ["latest news", "technology trends"])
        base_query = choices[seed_int % len(choices)]
        
    # Estimate browsing time based on keywords
    import random
    query_lower = base_query.lower()
    is_deep_topic = any(w in query_lower for w in ["tutorial", "guide", "learn", "how", "analysis", "study", "research", "documentation", "course", "master", "practice"])
    is_quick_topic = any(w in query_lower for w in ["weather", "price", "stock", "today", "news", "headline", "breaking"])
    
    if is_deep_topic:
        read_time = random.randint(180, 360)
    elif is_quick_topic:
        read_time = random.randint(45, 90)
    else:
        read_time = random.randint(90, 180)
        
    # Suffix templates — single-flow, NO going back to search
    # (Pattern 4 removed: "go back to search" caused double-search behavior)
    suffix_options = [
        # Pattern 1: Click result → read page
        f", then click the most relevant result, and read/scroll through the page for {read_time} seconds. Do NOT search again.",

        # Pattern 2: Click result → read → click an internal link on the same site
        f", then click a result, read it for {read_time // 2} seconds, then click an internal link within the SAME site and read for another {read_time // 2} seconds. Do NOT return to search.",

        # Pattern 3: Click result → watch/scroll media on the page
        f", then click a result, scroll through or watch any media on the page for {read_time} seconds. Stay on the page. Do NOT search again.",
    ]

    if behavior in ["watchVideos", "entertainment"]:
        prompt_suffix = f", then click a video result, and watch it for {random.randint(120, min(read_time, 300))} seconds. Do NOT search again."
    elif behavior == "checkEmails":
        prompt_suffix = f", then open the first email option, and browse/check emails for {random.randint(60, 120)} seconds. Do NOT search again."
    else:
        prompt_suffix = random.choice(suffix_options)
        
    prompt = f"Search for '{base_query}'" + prompt_suffix
    print(f"[Scheduler Callback] Generated prompt: \"{prompt}\"")
    

    context = {
        "agent_id": agent.id,
        "agent_name": agent.name,
        "time_period": time_period,
        "current_activity": behavior,
        "interests": combined_topics,
        "routine_tasks": period_tasks,
        "schedule_name": f"Scheduled Routine ({time_period})",
        "proxy_provider": getattr(agent, "proxy_provider", {"mode": "none"}),
        "avatar_type": getattr(agent, "avatar_type", "bot"),
        "avatar_color": getattr(agent, "avatar_color", "blue"),
        "enable_scraping": getattr(agent, "enable_scraping", False),
        "scraper_text_limit": getattr(agent, "scraper_text_limit", 10000),
        "language": getattr(agent, "language", "auto") or "auto",
    }
    
    if agent.auth:
        context["auth"] = agent.auth
        
    # Session time: average 5 min, max 10 min. Clamp read_time to 120-480s.
    read_time = max(120, min(480, read_time))   # 2-8 min
    # session_minutes = ceil(read_time / 60), capped to 10, floors at 2
    import math
    session_minutes = max(2, min(10, math.ceil(read_time / 60)))
    # Hard watchdog = session_minutes * 60 + 60s grace
    max_session_seconds = session_minutes * 60 + 60
    print(f"[Scheduler Callback] Session timing: read_time={read_time}s, "
          f"session_minutes={session_minutes}min, max_watchdog={max_session_seconds}s")

    def _do_launch():
        try:
            from tubecli.extensions.browser.process_manager import browser_process_manager

            # --- Kill any stale running sessions for this profile ---
            running = browser_process_manager.list_running()
            for inst in running:
                if inst.get("profile") == profile_name:
                    print(
                        f"[Scheduler Callback] Killing stale session {inst['instance_id']} "
                        f"for profile '{profile_name}' before spawning new one."
                    )
                    browser_process_manager.terminate(inst["instance_id"])

            print(
                f"[Scheduler Callback] Spawning browser profile '{profile_name}' "
                f"for agent '{agent.name}' (max {max_session_seconds}s)..."
            )
            result = browser_process_manager.spawn(
                profile=profile_name,
                prompt=prompt,
                headless=False,
                manual=False,
                ai_model=getattr(agent, "browser_ai_model", "qwen:latest"),
                context=context,
                max_duration=max_session_seconds,
                session_minutes=session_minutes,
            )
            instance_id = result.get("instance_id", "")
            spawn_status = result.get("status", "unknown")
            print(
                f"[Scheduler Callback] Spawn result: {spawn_status} "
                f"(PID: {result.get('pid')}, instance: {instance_id})"
            )
            if spawn_status == "error":
                print(f"[Scheduler Callback] Spawn error detail: {result.get('error')}")
        except Exception as e:
            print(f"[Scheduler Callback] Error launching browser: {e}")

    import threading
    threading.Thread(target=_do_launch, daemon=True).start()


@app.on_event("startup")
async def startup_event():
    import sys
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass
    from tubecli.core.telegram_listener import telegram_listener
    telegram_listener.start()

    # Pre-fetch Core update in background once on server startup
    import asyncio
    asyncio.create_task(check_for_updates())

    # Start PageWatcher scheduler (if web_crawler extension has watches)
    try:
        import sys
        from tubecli.config import EXTENSIONS_EXTERNAL_DIR
        wc_dir = os.path.join(str(EXTENSIONS_EXTERNAL_DIR), "web_crawler")
        if os.path.isdir(wc_dir) and wc_dir not in sys.path:
            sys.path.insert(0, wc_dir)
        from watcher import page_watcher
        if page_watcher.list_watches():
            page_watcher.start_scheduler()
            print("[Startup] PageWatcher scheduler started")
    except Exception as e:
        print(f"[Startup] PageWatcher not available: {e}")

    # Start the core background scheduler daemon
    try:
        from tubecli.core.scheduler import scheduler
        scheduler.set_agent_runner(run_agent_routine)
        
        def _run_skill_bg(skill_id):
            import asyncio
            async def _run():
                try:
                    print(f"[Scheduler] Executing scheduled skill {skill_id}...")
                    await run_skill(skill_id)
                except Exception as e:
                    print(f"[Scheduler] Error running scheduled skill {skill_id}: {e}")
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(_run())
            except RuntimeError:
                asyncio.run(_run())
                
        scheduler.set_runner(_run_skill_bg)
        scheduler.start(interval_sec=30)
        print("[Startup] Core background scheduler daemon started successfully")
    except Exception as e:
        print(f"[Startup] Failed to start Core background scheduler: {e}")

@app.on_event("shutdown")
async def shutdown_event():
    try:
        from tubecli.core.scheduler import scheduler
        scheduler.stop()
        print("[Shutdown] Core background scheduler daemon stopped")
    except Exception:
        pass
    from tubecli.core.telegram_listener import telegram_listener
    await telegram_listener.stop()

@app.post("/api/v1/system/shutdown")
async def shutdown_server():
    """Trigger a graceful shutdown of the TubeCLI server."""
    import threading
    import time
    def _shutdown():
        time.sleep(1)
        cli_pid = os.environ.get("TUBECLI_CLI_PID")
        if cli_pid:
            try:
                import signal
                if os.name == 'nt':
                    os.system(f"taskkill /F /PID {cli_pid}")
                else:
                    os.kill(int(cli_pid), signal.SIGTERM)
            except Exception:
                pass
        os._exit(0)
    threading.Thread(target=_shutdown).start()
    return {"status": "success", "message": "Server is shutting down..."}

# ── Pydantic Models ──────────────────────────────────────────────

class AgentCreateRequest(BaseModel):
    name: str
    description: str = ""
    system_prompt: str = "You are a helpful AI assistant."
    model: Optional[str] = None
    
    # New Fields
    allowed_skills: Optional[List[str]] = None
    avatar_icon: Optional[str] = "SMART_TOY"
    avatar_type: Optional[str] = "bot"
    avatar_color: Optional[str] = "blue"
    browser_ai_model: Optional[str] = "qwen:latest"
    telegram_token: Optional[str] = ""
    telegram_chat_id: Optional[str] = ""
    messenger_token: Optional[str] = ""
    messenger_page_id: Optional[str] = ""
    messenger_php_url: Optional[str] = ""
    direct_trigger_skill_id: Optional[str] = ""
    persona: Optional[Dict] = {}
    routine: Optional[Dict] = {}
    thinking_map: Optional[Dict] = {}
    allowed_profiles: Optional[List[str]] = []
    proxy_config: Optional[str] = ""
    proxy_provider: Optional[Dict] = {"mode": "static"}
    timezone: Optional[str] = None
    language: Optional[str] = "auto"
    auth: Optional[Dict] = {}
    cloud_api_keys: Optional[Dict] = {}
    enable_scraping: Optional[bool] = False
    scraper_text_limit: Optional[int] = 10000
    script_output_format: Optional[str] = "json"
    schedule_enabled: Optional[bool] = False
    schedule_repeat: Optional[str] = "Daily"
    schedule_interval: Optional[int] = 60
    schedule_active_days: Optional[List[str]] = []
    schedule_start_time: Optional[str] = "08:00"
    schedule_end_time: Optional[str] = "22:00"
    schedule_max_runs: Optional[int] = 10
    schedule_next_run: Optional[str] = None
    schedule_last_run: Optional[str] = None
    schedule_runs_today: Optional[int] = 0

class AgentGenerateRequest(BaseModel):
    name: str = ""
    description: str = ""
    provider: str = "ollama"
    model: str = "qwen:latest"
    api_key: Optional[str] = None
    output_target_prefix: str = "ai"

class ExtensionUpdateRequest(BaseModel):
    port: Optional[int] = None

class AgentUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    model: Optional[str] = None
    allowed_skills: Optional[List[str]] = None
    avatar_icon: Optional[str] = None
    avatar_type: Optional[str] = None
    avatar_color: Optional[str] = None
    browser_ai_model: Optional[str] = None
    telegram_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    messenger_token: Optional[str] = None
    messenger_page_id: Optional[str] = None
    messenger_php_url: Optional[str] = None
    direct_trigger_skill_id: Optional[str] = None
    persona: Optional[Dict] = None
    routine: Optional[Dict] = None
    thinking_map: Optional[Dict] = None
    allowed_profiles: Optional[List[str]] = None
    proxy_config: Optional[str] = None
    proxy_provider: Optional[Dict] = None
    timezone: Optional[str] = None
    language: Optional[str] = None
    auth: Optional[Dict] = None
    cloud_api_keys: Optional[Dict] = None
    enable_scraping: Optional[bool] = None
    scraper_text_limit: Optional[int] = None
    script_output_format: Optional[str] = None
    schedule_enabled: Optional[bool] = None
    schedule_repeat: Optional[str] = None
    schedule_interval: Optional[int] = None
    schedule_active_days: Optional[List[str]] = None
    schedule_start_time: Optional[str] = None
    schedule_end_time: Optional[str] = None
    schedule_max_runs: Optional[int] = None
    schedule_next_run: Optional[str] = None
    schedule_last_run: Optional[str] = None
    schedule_runs_today: Optional[int] = None

class SkillCreateRequest(BaseModel):
    name: str
    description: str = ""
    workflow_data: Dict = {}
    skill_type: str = "Skill"
    skill_format: Optional[str] = None
    commands: Optional[List[str]] = []
    trigger: Optional[str] = ""
    # Tool contract for LLM agents
    input_hint: Optional[str] = None
    when_to_use: Optional[str] = None
    examples: Optional[List[str]] = None

class SkillGenerateRequest(BaseModel):
    prompt: str
    provider: str = "ollama"
    model: str = ""
    api_key: str = ""

class WorkflowGenerateRequest(BaseModel):
    prompt: str
    provider: str = "ollama"
    model: str = ""
    api_key: str = ""

class WorkflowRunRequest(BaseModel):
    workflow_data: Dict
    input_text: str = ""

class WorkflowSaveRequest(BaseModel):
    name: str
    workflow_data: Dict


# ── Root ─────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
async def root():
    """Send the bare origin to the dashboard.

    There was no route here, so http://127.0.0.1:5295 — the address printed by the
    installers, the CLI banner and the "no API key" message — answered
    {"detail":"Not Found"}. That is the first thing a new user sees after a
    successful install, and it reads as a broken program.
    """
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/dashboard")


# ── Health ───────────────────────────────────────────────────────

@app.get("/api/v1/health")
async def health():
    from tubecli.config import get_api_port
    return {"status": "ok", "message": "TubeCLI API is running", "port": get_api_port()}


# ── Version & Update ──────────────────────────────────────────────

@app.get("/api/v1/version")
async def get_version_info():
    import subprocess
    from tubecli import __version__, __build__
    info = {"version": __version__, "build": __build__, "pip_version": __version__, "git_hash": None, "git_branch": None}
    try:
        repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        h = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=repo, timeout=3)
        b = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True, cwd=repo, timeout=3)
        if h.returncode == 0: info["git_hash"] = h.stdout.strip()
        if b.returncode == 0: info["git_branch"] = b.stdout.strip()
    except Exception:
        pass
    return info

@app.post("/api/v1/version/update")
async def perform_git_update():
    """Safe update: git pull + install only missing deps + restart.
    Mirrors the init_cmd.py option-9 logic. Never runs 'pip install -e .'
    which would break the running installation.
    """
    import subprocess, re, threading, time
    from tubecli import __build__
    from tubecli.config import BASE_DIR
    try:
        repo = str(BASE_DIR)

        # Step 1: git pull
        r = subprocess.run(["git", "pull"], capture_output=True, text=True, cwd=repo, timeout=60)
        pull_output = r.stdout.strip() or r.stderr.strip()
        if r.returncode != 0:
            return {"status": "error", "output": f"git pull failed: {pull_output}"}

        # Step 2: Check which files changed to determine if deps need updating
        changed_files = []
        try:
            r_diff = subprocess.run(
                ["git", "diff", "--name-only", "HEAD~1..HEAD"],
                capture_output=True, text=True, cwd=repo, timeout=10,
            )
            if r_diff.returncode == 0:
                changed_files = [f.strip() for f in r_diff.stdout.strip().split("\n") if f.strip()]
        except Exception:
            pass

        deps_changed = any(f in ("pyproject.toml", "requirements.txt", "setup.py", "setup.cfg") for f in changed_files)
        pip_output = ""

        # Step 3: Smart dependency check — only if pyproject.toml or requirements.txt changed
        if deps_changed:
            required_packages = set()
            # From pyproject.toml
            pyproject_path = os.path.join(repo, "pyproject.toml")
            if os.path.exists(pyproject_path):
                try:
                    with open(pyproject_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    in_deps = False
                    for line in content.splitlines():
                        stripped = line.strip()
                        if stripped.startswith("dependencies"):
                            in_deps = True
                            continue
                        if in_deps:
                            if stripped == "]":
                                break
                            match = re.match(r'^\s*"([a-zA-Z0-9_-]+)', stripped)
                            if match:
                                required_packages.add(match.group(1).lower().replace("-", "_"))
                except Exception:
                    pass

            # From requirements.txt
            req_path = os.path.join(repo, "requirements.txt")
            if os.path.exists(req_path):
                try:
                    with open(req_path, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if line and not line.startswith("#"):
                                pkg = re.split(r"[>=<!\[\];]", line)[0].strip().lower().replace("-", "_")
                                if pkg:
                                    required_packages.add(pkg)
                except Exception:
                    pass

            if required_packages:
                # Get installed packages
                installed = set()
                try:
                    r_pip = subprocess.run(
                        [sys.executable, "-m", "pip", "list", "--format=columns"],
                        capture_output=True, text=True, timeout=30,
                    )
                    if r_pip.returncode == 0:
                        for line in r_pip.stdout.splitlines()[2:]:
                            parts = line.split()
                            if parts:
                                installed.add(parts[0].lower().replace("-", "_"))
                except Exception:
                    pass

                missing = required_packages - installed
                if missing:
                    pip_r = subprocess.run(
                        [sys.executable, "-m", "pip", "install", *sorted(missing), "--quiet"],
                        capture_output=True, text=True, timeout=120,
                    )
                    pip_output = f"Installed {len(missing)} new package(s): {', '.join(sorted(missing))}"
                else:
                    pip_output = "All dependencies already satisfied."
            else:
                pip_output = "No dependencies to check."
        else:
            pip_output = "No dependency files changed, skipping pip."

        # Step 4: Read updated version from file
        new_version = __build__
        try:
            init_file = os.path.join(repo, "tubecli", "__init__.py")
            with open(init_file, "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("__version__"):
                        new_version = line.split("=")[1].strip().strip('"').strip("'")
                        break
        except Exception:
            pass

        # Step 5: Schedule restart — kill CLI parent process after response is sent
        # The CLI init_cmd.py menu loop will detect termination and the user
        # double-clicks the shortcut or runs 'tubecli init' again.
        restart_flag = os.path.join(repo, ".restarted")
        try:
            with open(restart_flag, "w") as f:
                f.write("1")
        except Exception:
            pass

        def _delayed_restart():
            time.sleep(2)
            cli_pid = os.environ.get("TUBECLI_CLI_PID")
            if cli_pid:
                try:
                    if os.name == 'nt':
                        os.system(f"taskkill /F /PID {cli_pid}")
                    else:
                        import signal
                        os.kill(int(cli_pid), signal.SIGTERM)
                except Exception:
                    pass
            # Restart CLI in a new process
            try:
                if os.name == 'nt':
                    CREATE_NO_WINDOW = 0x08000000
                    subprocess.Popen(
                        f'start "TubeCLI" cmd /k "cd /d {repo} && python -m tubecli.main init"',
                        shell=True, cwd=repo,
                    )
                else:
                    # `init` opens the interactive control panel, a loop that reads
                    # from stdin. Restarted detached on a headless host it hits EOF
                    # on the first prompt and aborts — so updating from the web
                    # killed this server (os._exit below) and replaced it with a
                    # process that died immediately, leaving no API at all.
                    # Restart what was actually running: the API server. The control
                    # panel is only restarted when a terminal is attached to it.
                    if os.environ.get("TUBECLI_CLI_PID") and sys.stdin and sys.stdin.isatty():
                        args = [sys.executable, "-m", "tubecli.main", "init"]
                    else:
                        args = [sys.executable, "-m", "tubecli.main", "api", "start"]
                        port_env = os.environ.get("TUBECLI_PORT")
                        if port_env:
                            args += ["--port", port_env]
                    subprocess.Popen(args, cwd=repo, start_new_session=True)
            except Exception:
                pass
            time.sleep(1)
            os._exit(0)

        threading.Thread(target=_delayed_restart, daemon=True).start()

        return {
            "status": "success",
            "output": pull_output,
            "pip_output": pip_output,
            "version": new_version,
            "restarting": True,
        }
    except Exception as e:
        return {"status": "error", "output": str(e)}

VERSION_CHECK_CACHE = {"data": None, "last_check": 0.0}
# The cache had no expiry: any result was kept for the life of the process, and
# `last_check` was written but never read. A release published while the server ran
# stayed invisible until someone restarted it — which is precisely the situation an
# update check exists for.
VERSION_CHECK_TTL = 1800  # 30 minutes

@app.get("/api/v1/version/check")
async def check_for_updates(force: bool = False):
    """Check GitHub for a newer version by reading pyproject.toml on main.

    Cached for VERSION_CHECK_TTL; pass ?force=true to bypass, which is what a
    "check now" button should do.
    """
    global VERSION_CHECK_CACHE
    import httpx, re, time
    now = time.time()
    if (VERSION_CHECK_CACHE["data"] is not None
            and not force
            and now - VERSION_CHECK_CACHE.get("last_check", 0) < VERSION_CHECK_TTL):
        return VERSION_CHECK_CACHE["data"]
    from tubecli import __version__
    print(f"[VersionCheck] Local version: {__version__}")
    try:
        raw_url = "https://raw.githubusercontent.com/tubecreate/tubecli/main/pyproject.toml"
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(raw_url)
            if resp.status_code != 200:
                print(f"[VersionCheck] GitHub returned {resp.status_code}")
                res = {"has_update": False, "error": f"GitHub returned {resp.status_code}"}
                VERSION_CHECK_CACHE["data"] = res
                VERSION_CHECK_CACHE["last_check"] = now
                return res
            text = resp.text
            # Match version specifically under [project] section to avoid false matches
            m = re.search(r'^\[project\].*?^version\s*=\s*"([^"]+)"', text, re.MULTILINE | re.DOTALL)
            if not m:
                # Fallback: match first version = "..." in file
                m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
            if not m:
                print("[VersionCheck] Could not parse version from GitHub pyproject.toml")
                res = {"has_update": False, "error": "Could not parse version"}
                VERSION_CHECK_CACHE["data"] = res
                VERSION_CHECK_CACHE["last_check"] = now
                return res
            remote_version = m.group(1)
            print(f"[VersionCheck] Remote version: {remote_version}")
            # Version comparison (supports N-part dotted versions like 2026.05.18.151200)
            try:
                local_parts = [int(x) for x in __version__.split(".")]
                remote_parts = [int(x) for x in remote_version.split(".")]
                has_update = remote_parts > local_parts
            except ValueError:
                # Fallback string comparison if parts are non-numeric
                has_update = remote_version != __version__
            print(f"[VersionCheck] has_update={has_update}")
            res = {
                "has_update": has_update,
                "current_version": __version__,
                "remote_version": remote_version,
            }
            VERSION_CHECK_CACHE["data"] = res
            VERSION_CHECK_CACHE["last_check"] = now
            return res
    except Exception as e:
        print(f"[VersionCheck] Error: {e}")
        res = {"has_update": False, "error": str(e)}
        VERSION_CHECK_CACHE["data"] = res
        VERSION_CHECK_CACHE["last_check"] = now
        return res


# ── Agents ───────────────────────────────────────────────────────

@app.get("/api/v1/agents")
async def list_agents():
    from tubecli.core.agent import agent_manager
    agents = agent_manager.get_all()
    return {"agents": [a.to_dict() for a in agents], "count": len(agents)}

@app.post("/api/v1/agents/generate")
async def generate_agent_with_ai(req: AgentGenerateRequest):
    from tubecli.core.ai_generator import generate_agent_json
    try:
        data = generate_agent_json(
            name=req.name,
            description=req.description,
            provider=req.provider,
            model=req.model,
            api_key=req.api_key or ""
        )
        return {"status": "success", "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/agents/{agent_id}")
async def get_agent(agent_id: str):
    from tubecli.core.agent import agent_manager
    agent = agent_manager.get(agent_id)
    if not agent:
        raise HTTPException(404, f"Agent {agent_id} not found")
    return agent.to_dict()

@app.post("/api/v1/agents")
async def create_agent(req: AgentCreateRequest):
    from tubecli.core.agent import agent_manager
    agent = agent_manager.create(**req.model_dump(exclude_none=True))
    return {"status": "created", "agent": agent.to_dict()}

@app.put("/api/v1/agents/{agent_id}")
async def update_agent(agent_id: str, req: AgentUpdateRequest):
    from tubecli.core.agent import agent_manager
    agent = agent_manager.update(agent_id, **req.model_dump(exclude_none=True))
    if not agent:
        raise HTTPException(404, f"Agent {agent_id} not found")
    return {"status": "updated", "agent": agent.to_dict()}

@app.delete("/api/v1/agents/{agent_id}")
async def delete_agent(agent_id: str):
    from tubecli.core.agent import agent_manager
    if not agent_manager.delete(agent_id):
        raise HTTPException(404, f"Agent {agent_id} not found")
    return {"status": "deleted", "agent_id": agent_id}

@app.post("/api/v1/agents/{agent_id}/test_routine")
async def test_agent_routine(agent_id: str):
    from tubecli.core.agent import agent_manager
    agent = agent_manager.get(agent_id)
    if not agent:
        raise HTTPException(404, f"Agent {agent_id} not found")
    try:
        run_agent_routine(agent_id)
        return {"status": "success", "message": f"Triggered behavior routine for agent '{agent.name}'"}
    except Exception as e:
        raise HTTPException(500, f"Failed to run behavior routine: {str(e)}")


@app.post("/api/v1/agents/{agent_id}/regenerate_keywords")
async def regenerate_agent_keywords(agent_id: str):
    """Force regenerate daily keywords for an agent (ignores cached date, applies current language)."""
    from tubecli.core.agent import agent_manager
    import asyncio, threading
    from datetime import datetime, timezone as tz

    agent = agent_manager.get(agent_id)
    if not agent:
        raise HTTPException(404, f"Agent {agent_id} not found")

    # Clear the cached date so check_and_generate_daily_keywords will re-generate
    routine = agent.routine or {}
    existing_dk = routine.get("daily_keywords") or {}
    existing_dk["date"] = ""  # force stale
    routine["daily_keywords"] = existing_dk
    agent_manager.update(agent_id, routine=routine)

    # Reload fresh agent and regenerate
    def _regen():
        try:
            fresh_agent = agent_manager.get(agent_id)
            now_dt = datetime.now(tz.utc)
            new_kw = check_and_generate_daily_keywords(fresh_agent, now_dt)
            print(f"[RegenKw] Regenerated keywords for agent '{fresh_agent.name}': {new_kw}")
        except Exception as e:
            print(f"[RegenKw] Error regenerating keywords for agent {agent_id}: {e}")

    threading.Thread(target=_regen, daemon=True).start()
    return {"status": "success", "message": f"Keyword regeneration started for agent '{agent.name}'. Language: {getattr(agent, 'language', 'auto')}"}


class DailyKeywordsUpdateRequest(BaseModel):
    morning: List[str] = []
    afternoon: List[str] = []
    evening: List[str] = []
    night: List[str] = []


@app.put("/api/v1/agents/{agent_id}/daily_keywords")
async def update_agent_daily_keywords(agent_id: str, req: DailyKeywordsUpdateRequest):
    """Manually set/override today's evolved keywords for an agent."""
    import datetime as _dt
    from tubecli.core.agent import agent_manager

    agent = agent_manager.get(agent_id)
    if not agent:
        raise HTTPException(404, f"Agent {agent_id} not found")

    # Use the agent's timezone so "today" matches what the scheduler sees.
    now = _dt.datetime.now()
    tz_str = getattr(agent, "timezone", None)
    if tz_str and isinstance(tz_str, str) and tz_str.strip():
        try:
            from zoneinfo import ZoneInfo
            now = _dt.datetime.now(ZoneInfo(tz_str.strip()))
        except Exception:
            pass

    def _clean(items):
        seen = []
        for kw in items or []:
            kw = str(kw).strip()
            if kw and kw not in seen:
                seen.append(kw)
        return seen

    routine = agent.routine or {}
    routine["daily_keywords"] = {
        "date": now.strftime("%Y-%m-%d"),
        "morning": _clean(req.morning),
        "afternoon": _clean(req.afternoon),
        "evening": _clean(req.evening),
        "night": _clean(req.night),
    }
    agent = agent_manager.update(agent_id, routine=routine)
    return {"status": "success", "agent": agent.to_dict()}


@app.get("/api/v1/agents/{agent_id}/history")
async def get_agent_history(agent_id: str):
    from tubecli.core.agent import agent_manager
    import json
    from pathlib import Path
    
    agent = agent_manager.get(agent_id)
    if not agent:
        raise HTTPException(404, f"Agent {agent_id} not found")
        
    allowed_profiles = getattr(agent, "allowed_profiles", []) or []
    scraped_data_dir = Path(__file__).parent.parent / "extensions" / "browser" / "scraped_data"
    
    all_articles = []
    for profile in allowed_profiles:
        history_path = scraped_data_dir / profile / "history.json"
        if history_path.exists():
            try:
                with open(history_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    articles = data.get("scrapedArticles", [])
                    for a in articles:
                        art_agent_id = a.get("agentId") or a.get("agent_id")
                        if not art_agent_id or art_agent_id == agent_id:
                            a_copy = dict(a)
                            a_copy["_profile"] = profile
                            all_articles.append(a_copy)
            except Exception as e:
                print(f"Error reading scraper history for {profile}: {e}")
                
    # Sort by scrapedAt desc
    all_articles.sort(key=lambda x: x.get("scrapedAt", ""), reverse=True)
    return all_articles


@app.get("/api/v1/agents/{agent_id}/scraped-article")
async def get_scraped_article_detail(agent_id: str, profile: str, url: str):
    from tubecli.core.agent import agent_manager
    from pathlib import Path
    import json
    
    agent = agent_manager.get(agent_id)
    if not agent:
        raise HTTPException(404, f"Agent {agent_id} not found")
        
    allowed_profiles = getattr(agent, "allowed_profiles", []) or []
    if profile not in allowed_profiles:
        raise HTTPException(403, f"Profile {profile} is not associated with this agent")
        
    scraped_data_dir = Path(__file__).parent.parent / "extensions" / "browser" / "scraped_data"
    articles_path = scraped_data_dir / profile / "articles.json"
    
    if not articles_path.exists():
        raise HTTPException(404, f"No articles found for profile {profile}")
        
    try:
        with open(articles_path, 'r', encoding='utf-8') as f:
            articles = json.load(f)
            if not isinstance(articles, list):
                articles = []
            for a in articles:
                if a.get("url") == url:
                    return a
    except Exception as e:
        raise HTTPException(500, f"Error reading articles: {str(e)}")
        
    raise HTTPException(404, f"Article not found in profile {profile}")


@app.post("/api/v1/agents/{agent_id}/rewrite-article")
async def rewrite_scraped_article(agent_id: str, profile: str, url: str):
    from tubecli.core.agent import agent_manager
    from tubecli.core.brain import AgentBrain
    from pathlib import Path
    import json
    
    agent = agent_manager.get(agent_id)
    if not agent:
        raise HTTPException(404, f"Agent {agent_id} not found")
        
    allowed_profiles = getattr(agent, "allowed_profiles", []) or []
    if profile not in allowed_profiles:
        raise HTTPException(403, f"Profile {profile} is not associated with this agent")
        
    scraped_data_dir = Path(__file__).parent.parent / "extensions" / "browser" / "scraped_data"
    articles_path = scraped_data_dir / profile / "articles.json"
    
    if not articles_path.exists():
        raise HTTPException(404, f"No articles found for profile {profile}")
        
    article = None
    try:
        with open(articles_path, 'r', encoding='utf-8') as f:
            articles = json.load(f)
            for a in articles:
                if a.get("url") == url:
                    article = a
                    break
    except Exception as e:
        raise HTTPException(500, f"Error reading articles: {str(e)}")
        
    if not article:
        raise HTTPException(404, f"Article not found in profile {profile}")
        
    title = article.get("title", "Untitled")
    content = article.get("content", "")
    if not content:
        raise HTTPException(400, "Bài viết này không có nội dung văn bản để viết lại.")
        
    agent_language = getattr(agent, "language", "auto") or "auto"
    _LANGUAGE_NAMES = {
        "auto": "Vietnamese",
        "vi": "Vietnamese",
        "en": "English",
        "zh": "Chinese (Simplified)",
        "zh-TW": "Chinese (Traditional)",
        "ja": "Japanese",
        "ko": "Korean",
        "es": "Spanish",
        "tr": "Turkish",
        "ru": "Russian",
        "fr": "French",
        "de": "German",
        "pt": "Portuguese",
        "ar": "Arabic",
        "th": "Thai",
        "id": "Indonesian",
    }
    lang_name = _LANGUAGE_NAMES.get(agent_language, "Vietnamese")
    
    system_prompt = f"Bạn là một AI biên tập viên nội dung. Nhiệm vụ của bạn là viết lại một bài viết cào được thành một bài viết mới, chất lượng cao, mạch lạc và hấp dẫn bằng ngôn ngữ {lang_name}."
    
    user_prompt = f"""Dưới đây là thông tin bài viết gốc:
    
Tiêu đề: {title}
Nội dung:
{content[:5000]}

Yêu cầu:
1. Hãy viết một bài viết hoàn toàn mới dựa trên nội dung bài viết gốc này.
2. Bài viết mới phải có tiêu đề hấp dẫn, phần mở đầu lôi cuốn, các phần nội dung rõ ràng (có tiêu đề phụ) và phần kết luận đúc rút thông tin.
3. Không sao chép nguyên văn, hãy viết lại bằng văn phong của bạn một cách sáng tạo và logic.
4. Trình bày bài viết bằng định dạng Markdown.
5. Ngôn ngữ của bài viết: {lang_name}.

Chỉ trả về nội dung bài viết bằng Markdown (không thêm lời giới thiệu của AI)."""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    
    try:
        raw_response = AgentBrain._call_llm(agent.to_dict(), messages, temperature=0.7)
        return {"status": "success", "content": raw_response}
    except Exception as e:
        raise HTTPException(500, f"Lỗi khi gọi AI viết lại bài: {str(e)}")


class GenerateContentRequest(BaseModel):
    selected_urls: Optional[List[str]] = []
    max_length: Optional[int] = 2000

@app.post("/api/v1/agents/{agent_id}/generate-content-from-today")
async def generate_content_from_today(agent_id: str, req: Optional[GenerateContentRequest] = None):
    from tubecli.core.agent import agent_manager
    from tubecli.core.brain import AgentBrain
    import json
    from pathlib import Path
    from datetime import datetime
    
    agent = agent_manager.get(agent_id)
    if not agent:
        raise HTTPException(404, f"Agent {agent_id} not found")
        
    allowed_profiles = getattr(agent, "allowed_profiles", []) or []
    scraped_data_dir = Path(__file__).parent.parent / "extensions" / "browser" / "scraped_data"
    
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    today_articles = []
    
    for profile in allowed_profiles:
        articles_path = scraped_data_dir / profile / "articles.json"
        if articles_path.exists():
            try:
                with open(articles_path, 'r', encoding='utf-8') as f:
                    articles = json.load(f)
                    if isinstance(articles, list):
                        for a in articles:
                            scraped_at = a.get("scrapedAt", "")
                            if scraped_at and today_str in scraped_at:
                                a_copy = dict(a)
                                a_copy["_profile"] = profile
                                today_articles.append(a_copy)
            except Exception as e:
                print(f"Error reading articles for {profile}: {e}")
                
    if not today_articles:
        raise HTTPException(400, "Không tìm thấy nội dung nào được cào (scraped) trong ngày hôm nay. Hãy chạy agent đi cào dữ liệu trước.")

    today_articles.sort(key=lambda x: x.get("scrapedAt", ""), reverse=True)
    
    selected_urls = req.selected_urls if req else []
    max_length = req.max_length if (req and req.max_length) else 2000
    
    if selected_urls:
        selected_articles = [a for a in today_articles if a.get("url") in selected_urls]
        if not selected_articles:
            selected_articles = today_articles[:3]
    else:
        selected_articles = today_articles[:3]
    
    context_text = ""
    for idx, art in enumerate(selected_articles, 1):
        title = art.get("title", "Untitled")
        url = art.get("url", "")
        content = art.get("content", "")
        content_snippet = content[:2000]
        context_text += f"Bài viết {idx}:\nTiêu đề: {title}\nĐường dẫn: {url}\nNội dung:\n{content_snippet}\n---\n\n"
        
    agent_language = getattr(agent, "language", "auto") or "auto"
    _LANGUAGE_NAMES = {
        "auto": "Vietnamese",
        "vi": "Vietnamese",
        "en": "English",
        "zh": "Chinese (Simplified)",
        "zh-TW": "Chinese (Traditional)",
        "ja": "Japanese",
        "ko": "Korean",
        "es": "Spanish",
        "tr": "Turkish",
        "ru": "Russian",
        "fr": "French",
        "de": "German",
        "pt": "Portuguese",
        "ar": "Arabic",
        "th": "Thai",
        "id": "Indonesian",
    }
    lang_name = _LANGUAGE_NAMES.get(agent_language, "Vietnamese")
    
    system_prompt = f"Bạn là một AI biên tập viên nội dung. Nhiệm vụ của bạn là tổng hợp các thông tin và bài viết đã cào được trong ngày để tạo ra một bài viết tổng hợp mới, chất lượng cao, mạch lạc và hấp dẫn bằng ngôn ngữ {lang_name}."
    
    user_prompt = f"""Dưới đây là các thông tin thu thập được trong ngày hôm nay:
    
{context_text}

Yêu cầu:
1. Hãy viết một bài viết tổng hợp mới dựa trên các thông tin trên.
2. Bài viết mới phải có tiêu đề hấp dẫn, phần mở đầu lôi cuốn, các phần nội dung rõ ràng (có tiêu đề phụ) và phần kết luận đúc rút thông tin.
3. Không sao chép nguyên văn, hãy tổng hợp, phân tích, biên tập và liên kết các thông tin lại một cách logic.
4. Trình bày bài viết bằng định dạng Markdown.
5. Ngôn ngữ của bài viết: {lang_name}.
6. Độ dài bài viết: Khoảng {max_length} ký tự.

Chỉ trả về nội dung bài viết bằng Markdown (không thêm lời giới thiệu của AI)."""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    
    try:
        raw_response = AgentBrain._call_llm(agent.to_dict(), messages, temperature=0.7)
        return {"status": "success", "content": raw_response}
    except Exception as e:
        raise HTTPException(500, f"Lỗi khi gọi AI tổng hợp bài viết: {str(e)}")




# ── Agent Chat ───────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str


# ── AI Proxy Endpoint for Browser Extension ──
@app.post("/api/v1/localai/chat/completions")
async def localai_chat_completions(req: Request):
    """
    Proxy endpoint used by browser extension (ai_engine.js).
    Routes to the correct AI provider based on Global Settings default_model.
    """
    import requests as _requests
    from tubecli.config import get_setting

    data = await req.json()
    messages = data.get("messages", [])

    # Read default model: try global_settings.json first, then settings.json
    import os as _os, json as _json
    from tubecli.config import DATA_DIR
    model = ""
    global_settings_file = _os.path.join(str(DATA_DIR), "global_settings.json")
    if _os.path.exists(global_settings_file):
        try:
            with open(global_settings_file, "r", encoding="utf-8") as f:
                gs = _json.load(f)
                model = gs.get("default_model", "")
        except Exception:
            pass
    if not model:
        model = get_setting("default_model", "qwen:latest")
    lower_model = model.lower()

    # Load cloud API keys
    cloud_keys_file = _os.path.join(str(DATA_DIR), "cloud_api_keys.json")
    cloud_keys = {}
    if _os.path.exists(cloud_keys_file):
        try:
            with open(cloud_keys_file, "r", encoding="utf-8") as f:
                cloud_keys = _json.load(f)
        except Exception:
            pass

    # Check if 9router is running and query its models list
    nr_running = False
    nr_models = []
    try:
        nr_key = ""
        if "9router" in cloud_keys:
            val = cloud_keys["9router"]
            if isinstance(val, str) and val:
                nr_key = val
            elif isinstance(val, dict):
                for label, info in val.items():
                    if isinstance(info, dict) and info.get("active", True):
                        nr_key = info.get("key", "") or info.get("api_key", "")
                        if nr_key:
                            break
        headers = {}
        if nr_key:
            headers["Authorization"] = f"Bearer {nr_key}"
        resp = _requests.get("http://localhost:20128/v1/models", headers=headers, timeout=0.5)
        if resp.status_code == 200:
            nr_running = True
            data = resp.json()
            if isinstance(data, dict) and "data" in data:
                nr_models = [m.get("id", m.get("name", "")) for m in data["data"] if isinstance(m, dict)]
    except Exception:
        pass

    # Determine provider from model name and 9router running state
    provider = "ollama"
    if "9router" in lower_model or "antigravity" in lower_model or "cx/" in lower_model:
        provider = "9router"
    elif "/" in lower_model:
        # Models with slashes like 'deepseek/deepseek-r1' are 9Router/OpenRouter models
        provider = "9router"
    elif nr_running and (model in nr_models or lower_model in [m.lower() for m in nr_models]):
        provider = "9router"
    elif "gemini" in lower_model:
        provider = "gemini"
    elif "gpt" in lower_model or "o1" in lower_model or "o3" in lower_model:
        provider = "chatgpt"
    elif "claude" in lower_model:
        provider = "claude"
    elif "deepseek" in lower_model:
        provider = "deepseek"
    elif "grok" in lower_model:
        provider = "grok"
    else:
        # Fallback to 9router if it's running on port 20128, otherwise ollama
        if nr_running:
            provider = "9router"
        else:
            provider = "ollama"

    # Get first active API key for selected provider
    api_key = ""
    if provider in cloud_keys:
        val = cloud_keys[provider]
        if isinstance(val, str) and val:
            # Legacy plain-string key format
            api_key = val
        elif isinstance(val, dict):
            for label, info in val.items():
                if isinstance(info, dict) and info.get("active", True):
                    api_key = info.get("key", "") or info.get("api_key", "")
                    if api_key:
                        break

    print(f"[AI Proxy] provider={provider} model={model} has_key={bool(api_key)}")

    response_content = ""
    try:
        if provider == "deepseek":
            if not api_key:
                raise Exception("No API key for Deepseek")
            resp = _requests.post(
                "https://api.deepseek.com/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": model, "messages": messages, "stream": False},
                timeout=180,
            )
            if resp.status_code == 200:
                response_content = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
            else:
                raise Exception(f"Deepseek {resp.status_code}: {resp.text[:300]}")

        elif provider == "gemini":
            if not api_key:
                raise Exception("No API key for Gemini")
            model_name = model if "gemini" in model else "gemini-2.0-flash"
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
            contents = []
            for msg in messages:
                role = "user" if msg["role"] in ("user", "system") else "model"
                contents.append({"role": role, "parts": [{"text": msg["content"]}]})
            resp = _requests.post(url, json={"contents": contents}, timeout=120)
            if resp.status_code == 200:
                response_content = resp.json().get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            else:
                raise Exception(f"Gemini {resp.status_code}: {resp.text[:300]}")

        elif provider == "chatgpt":
            if not api_key:
                raise Exception("No API key for OpenAI")
            resp = _requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": model or "gpt-4o-mini", "messages": messages, "temperature": 0.5},
                timeout=120,
            )
            if resp.status_code == 200:
                response_content = resp.json()["choices"][0]["message"]["content"]
            else:
                raise Exception(f"OpenAI {resp.status_code}: {resp.text[:300]}")

        elif provider == "claude":
            if not api_key:
                raise Exception("No API key for Claude")
            system_text = ""
            chat_msgs = []
            for msg in messages:
                if msg["role"] == "system":
                    system_text = msg["content"]
                else:
                    chat_msgs.append(msg)
            payload = {"model": model or "claude-sonnet-4-20250514", "max_tokens": 4096, "messages": chat_msgs}
            if system_text:
                payload["system"] = system_text
            resp = _requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": api_key, "Content-Type": "application/json", "anthropic-version": "2023-06-01"},
                json=payload, timeout=120,
            )
            if resp.status_code == 200:
                response_content = resp.json().get("content", [{}])[0].get("text", "")
            else:
                raise Exception(f"Claude {resp.status_code}: {resp.text[:300]}")

        elif provider == "grok":
            if not api_key:
                raise Exception("No API key for Grok")
            resp = _requests.post(
                "https://api.x.ai/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": model or "grok-3", "messages": messages, "temperature": 0.5},
                timeout=120,
            )
            if resp.status_code == 200:
                response_content = resp.json()["choices"][0]["message"]["content"]
            else:
                raise Exception(f"Grok {resp.status_code}: {resp.text[:300]}")

        elif provider == "9router":
            # 9Router local proxy (OpenAI compatible on port 20128)
            headers = {"Content-Type": "application/json"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            resp = _requests.post(
                "http://localhost:20128/v1/chat/completions",
                headers=headers,
                json={"model": model or "qwen2.5:7b", "messages": messages, "temperature": 0.5},
                timeout=120,
            )
            if resp.status_code == 200:
                response_content = resp.json()["choices"][0]["message"]["content"]
            else:
                raise Exception(f"9Router {resp.status_code}: {resp.text[:300]}")

        else:
            # Ollama (local)
            from tubecli.config import OLLAMA_BASE_URL
            resp = _requests.post(
                f"{OLLAMA_BASE_URL}/api/chat",
                json={"model": model, "messages": messages, "stream": False},
                timeout=120,
            )
            if resp.status_code == 200:
                response_content = resp.json().get("message", {}).get("content", "")
            else:
                raise Exception(f"Ollama {resp.status_code}: {resp.text[:300]}")

    except Exception as e:
        print(f"[AI Proxy] Error: {e}")
        response_content = f"Error: {e}"

    # Return OpenAI-compatible JSON for ai_engine.js
    return {
        "id": "chatcmpl-proxy",
        "object": "chat.completion",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": response_content},
                "finish_reason": "stop"
            }
        ]
    }


@app.post("/api/v1/localai/generate")
async def localai_generate(req: Request):
    """
    Proxy endpoint for Ollama-style text generation (/api/generate).
    Used by browser extension (ai_engine.js) as fallback.
    Converts to chat/completions format internally.
    """
    data = await req.json()
    prompt = data.get("prompt", "")
    model = data.get("model", "")

    if not model:
        import os as _os, json as _json
        from tubecli.config import DATA_DIR, get_setting
        global_settings_file = _os.path.join(str(DATA_DIR), "global_settings.json")
        if _os.path.exists(global_settings_file):
            try:
                with open(global_settings_file, "r", encoding="utf-8") as f:
                    gs = _json.load(f)
                    model = gs.get("default_model", "")
            except Exception:
                pass
        if not model:
            model = get_setting("default_model", "qwen:latest")

    # Reuse the chat/completions logic by constructing a chat request
    from starlette.requests import Request as _Request
    from starlette.datastructures import Headers as _Headers
    import json as _json

    chat_body = _json.dumps({
        "messages": [{"role": "user", "content": prompt}],
        "model": model,
    }).encode()

    # Create a sub-request to reuse localai_chat_completions
    scope = req.scope.copy()
    scope["body"] = chat_body

    class FakeRequest:
        async def json(self_inner):
            return {"messages": [{"role": "user", "content": prompt}], "model": model}

    result = await localai_chat_completions(FakeRequest())

    # Convert chat format to generate format
    response_text = ""
    if isinstance(result, dict):
        choices = result.get("choices", [])
        if choices:
            response_text = choices[0].get("message", {}).get("content", "")

    return {
        "model": model,
        "response": response_text,
        "done": True,
    }


@app.post("/api/v1/agents/{agent_id}/chat")
async def agent_chat(agent_id: str, req: ChatRequest):
    """Chat with an agent. The brain dispatches skills automatically."""
    import datetime as _dt
    from tubecli.core.agent import agent_manager
    from tubecli.core.skill import skill_manager
    from tubecli.core.brain import AgentBrain

    agent = agent_manager.get(agent_id)
    if not agent:
        raise HTTPException(404, f"Agent {agent_id} not found")

    agent_dict = agent.to_dict()

    # Get agent's allowed skills
    all_skills = skill_manager.get_all()
    if agent.allowed_skills:
        skills = [s.to_dict() for s in all_skills if s.id in agent.allowed_skills]
    else:
        skills = [s.to_dict() for s in all_skills]  # allow all if not restricted

    # Call brain
    brain_result = AgentBrain.chat(
        message=req.message,
        agent=agent_dict,
        skills=skills,
        history=agent.history_log or [],
    )

    reply = brain_result["reply"]
    skill_used = None

    # ── Handle Brain Result ──
    action = brain_result.get("action")
    
    if action == "run_skill" and brain_result.get("skill_id"):
        skill_id = brain_result["skill_id"]
        skill = skill_manager.get(skill_id)
        if skill:
            skill_used = skill.name
            skill_input = brain_result.get("skill_input", req.message)
            
            # Feature: Random Browser Profile Selection
            # If input mentions "random profile" or "ngẫu nhiên", and it's a browser skill
            if any(x in skill_input.lower() for x in ["ngẫu nhiên", "random profile", "mở profile"]):
                from tubecli.core.config import config_manager
                profiles = config_manager.get_browser_profiles()
                if profiles:
                    import random
                    chosen = random.choice(profiles)
                    skill_input += f"\n(AI Note: Randomly selected browser profile: {chosen})"
            
            try:
                # Call the Autonomous ReAct Loop
                skill_dict = skill.to_dict()
                final_answer = await AgentBrain.autonomous_run(
                    message=skill_input,
                    agent=agent_dict,
                    skill=skill_dict
                )
                reply = final_answer
                skill_manager.update(skill_id, last_run=_dt.datetime.now().isoformat())
            except Exception as e:
                from tubecli.i18n import t
                reply = t("brain.skill_run_error", name=skill.name, error=str(e))
        else:
            from tubecli.i18n import t
            reply = t("brain.skill_not_found", id=skill_id)

    elif action == "create_skill":
        # Feature: AI Self-Creation via Workflow Builder
        # 1. Generate real executable workflow from the user's request
        # 2. Run it immediately to handle the current request
        # 3. Save as a reusable skill for future similar requests
        from tubecli.core.ai_workflow_builder import generate_workflow
        from tubecli.core.workflow_engine import WorkflowEngine
        from tubecli.nodes.registry import create_node_from_dict

        action_data_raw = brain_result.get("_raw_action", {})
        skill_name = action_data_raw.get("name") or brain_result.get("skill_name", "New Skill")
        skill_desc = action_data_raw.get("description") or brain_result.get("skill_desc", "")
        skill_instructions = action_data_raw.get("instructions") or brain_result.get("skill_instructions", [])

        # Determine provider/model from agent config
        wf_provider = agent_dict.get("provider", "ollama")
        wf_model = agent_dict.get("model", "") or agent_dict.get("chatbot_model", "")
        wf_api_key = agent_dict.get("api_key", "")
        if not wf_provider or wf_provider == "local":
            wf_provider = "ollama"

        wf_data = None
        wf_result = None
        try:
            # Build enriched prompt: original request + instructions hint
            gen_prompt = req.message
            if skill_instructions:
                gen_prompt += "\n\nHints: " + "; ".join(skill_instructions)

            # Generate the workflow
            wf_data = generate_workflow(
                prompt=gen_prompt,
                provider=wf_provider,
                model=wf_model,
                api_key=wf_api_key or "__CLOUD_API__",
            )

            # Run the workflow immediately for the user's current request
            nodes_data = wf_data.get("nodes", [])
            connections = wf_data.get("connections", [])
            if nodes_data:
                # Inject user message into first text_input node
                for nd in nodes_data:
                    if nd.get("type") in ("text_input", "manual_input"):
                        nd.setdefault("config", {})["text"] = req.message
                        break

                wf_nodes = [create_node_from_dict(nd) for nd in nodes_data]
                engine = WorkflowEngine(nodes=wf_nodes, connections=connections)
                wf_result = await engine.run()

        except Exception as wf_err:
            print(f"[AutoSkill] Workflow generate/run failed: {wf_err}")

        # Derive trigger commands from skill name + instructions
        trigger_cmds = [skill_name.lower()]
        for instr in (skill_instructions or []):
            words = [w.lower() for w in instr.split() if len(w) > 3]
            if words:
                trigger_cmds.append(" ".join(words[:3]))
        trigger_cmds = list(set(trigger_cmds))[:5]

        # Save as skill (create or update)
        try:
            existing_skill = skill_manager.find_by_name(skill_name)
            if existing_skill and wf_data:
                skill_manager.update(
                    existing_skill.id,
                    workflow_data=wf_data,
                    description=skill_desc or f"AI-generated: {skill_name}",
                    commands=trigger_cmds,
                )
                new_skill = existing_skill
            else:
                new_skill = skill_manager.create(
                    name=skill_name,
                    description=skill_desc or f"AI-generated workflow skill: {skill_name}",
                    skill_type="AI Workflow",
                    workflow_data=wf_data or {
                        "sop": "\n".join(skill_instructions or []),
                        "nodes": []
                    },
                    commands=trigger_cmds,
                )
            skill_used = f"Created Skill: {skill_name}"

            # Build reply from workflow result or confirmation message
            if wf_result and wf_result.get("status") == "completed":
                # Extract output from last node
                node_results = wf_result.get("node_results", {})
                output_texts = []
                for nid, nr in node_results.items():
                    if isinstance(nr, dict):
                        for key in ("result", "response", "stdout", "rows", "output"):
                            if nr.get(key):
                                output_texts.append(str(nr[key])[:500])
                                break
                    elif nr:
                        output_texts.append(str(nr)[:500])
                if output_texts:
                    reply = "\n".join(output_texts)
                    reply += f"\n\n✅ *Đã lưu thành skill '{skill_name}'* — lần sau hỏi tương tự sẽ dùng ngay."
                else:
                    reply = f"✅ Đã tạo và chạy workflow cho '{skill_name}'.\nĐã lưu thành skill để dùng lại."
            else:
                reply = (
                    f"✅ Đã tạo skill **{skill_name}**\n"
                    f"📝 {skill_desc}\n"
                    f"🔑 Triggers: `{'`, `'.join(trigger_cmds)}`\n\n"
                    f"Lần sau hỏi tương tự AI sẽ chạy skill này ngay lập tức."
                )

        except Exception as e:
            from tubecli.i18n import t
            reply = t("brain.skill_create_error", error=str(e))

    # Save to history
    history = agent.history_log or []
    history.append({"role": "user", "content": req.message, "timestamp": _dt.datetime.now().isoformat()})
    history.append({"role": "assistant", "content": reply, "timestamp": _dt.datetime.now().isoformat(),
                     "skill_used": skill_used})

    # Keep history manageable (last 50 messages)
    if len(history) > 50:
        history = history[-50:]

    agent_manager.update(agent_id, history_log=history)

    # ── Background Memory Update (non-blocking) ──
    import asyncio
    async def _bg_memory_update():
        try:
            from tubecli.core.brain import AgentBrain
            AgentBrain.post_chat_memory_update(agent_id, agent_dict, history)
            # If history was marked summarized, save it back
            agent_manager.update(agent_id, history_log=history)
        except Exception as e:
            print(f"[Memory] Background update error: {e}")
    asyncio.create_task(_bg_memory_update())

    return {
        "reply": reply,
        "skill_used": skill_used,
        "history": history[-20:],  # return last 20 for UI
    }


@app.delete("/api/v1/agents/{agent_id}/chat")
async def clear_chat_history(agent_id: str):
    """Clear an agent's chat history."""
    from tubecli.core.agent import agent_manager
    agent = agent_manager.get(agent_id)
    if not agent:
        raise HTTPException(404, f"Agent {agent_id} not found")
    agent_manager.update(agent_id, history_log=[])
    return {"status": "cleared", "agent_id": agent_id}


# ── Agent Memory API ─────────────────────────────────────────────

@app.get("/api/v1/agents/{agent_id}/memory")
async def get_agent_memory(agent_id: str):
    """Get full memory overview for an agent (sessions + knowledge)."""
    from tubecli.core.agent import agent_manager
    from tubecli.core.memory import AgentMemory
    agent = agent_manager.get(agent_id)
    if not agent:
        raise HTTPException(404, f"Agent {agent_id} not found")
    return AgentMemory.get_full_memory(agent_id)


@app.delete("/api/v1/agents/{agent_id}/memory")
async def clear_agent_memory(agent_id: str):
    """Clear all memory for an agent (sessions + knowledge)."""
    from tubecli.core.agent import agent_manager
    from tubecli.core.memory import AgentMemory
    agent = agent_manager.get(agent_id)
    if not agent:
        raise HTTPException(404, f"Agent {agent_id} not found")
    AgentMemory.clear_all(agent_id)
    return {"status": "cleared", "agent_id": agent_id}


@app.get("/api/v1/agents/{agent_id}/memory/sessions")
async def get_agent_sessions(agent_id: str):
    """Get session summaries for an agent."""
    from tubecli.core.memory import SessionMemory
    sessions = SessionMemory.get_recent_sessions(agent_id, limit=20)
    return {"agent_id": agent_id, "sessions": sessions, "count": len(sessions)}


@app.get("/api/v1/agents/{agent_id}/memory/knowledge")
async def get_agent_knowledge(agent_id: str):
    """Get knowledge facts for an agent."""
    from tubecli.core.memory import KnowledgeMemory
    facts = KnowledgeMemory.get_knowledge(agent_id)
    return {"agent_id": agent_id, "knowledge": facts, "count": len(facts)}


class AddFactRequest(BaseModel):
    fact: str
    category: str = "technical"
    importance: str = "medium"


@app.post("/api/v1/agents/{agent_id}/memory/knowledge")
async def add_agent_fact(agent_id: str, req: AddFactRequest):
    """Manually add a knowledge fact for an agent."""
    from tubecli.core.agent import agent_manager
    from tubecli.core.memory import KnowledgeMemory
    agent = agent_manager.get(agent_id)
    if not agent:
        raise HTTPException(404, f"Agent {agent_id} not found")
    KnowledgeMemory.add_fact(agent_id, req.fact, req.category, req.importance)
    return {"status": "added", "agent_id": agent_id, "fact": req.fact}


# ── Team Memory API ──────────────────────────────────────────────

@app.get("/api/v1/teams/{team_id}/memory")
async def get_team_memory(team_id: str):
    """Get team shared memory (briefings + knowledge)."""
    from tubecli.core.memory import TeamMemory
    return {
        "team_id": team_id,
        "briefings": TeamMemory.get_briefings(team_id, limit=10),
        "knowledge": TeamMemory.get_team_knowledge(team_id),
    }


class TeamBriefingRequest(BaseModel):
    briefing: str
    context: Dict = {}


@app.post("/api/v1/teams/{team_id}/memory/briefing")
async def add_team_briefing(team_id: str, req: TeamBriefingRequest):
    """Add a task briefing for a team."""
    from tubecli.core.memory import TeamMemory
    TeamMemory.save_briefing(team_id, req.briefing, req.context)
    return {"status": "added", "team_id": team_id}


@app.delete("/api/v1/teams/{team_id}/memory")
async def clear_team_memory(team_id: str):
    """Clear all team memory."""
    from tubecli.core.memory import TeamMemory
    TeamMemory.clear(team_id)
    return {"status": "cleared", "team_id": team_id}


# ── Skills ───────────────────────────────────────────────────────

@app.get("/api/v1/skills")
async def list_skills():
    from tubecli.core.skill import skill_manager
    skills = skill_manager.get_all()
    return {"skills": [s.to_dict() for s in skills], "count": len(skills)}

@app.get("/api/v1/skills/{skill_id}")
async def get_skill(skill_id: str):
    from tubecli.core.skill import skill_manager
    skill = skill_manager.get(skill_id)
    if not skill:
        raise HTTPException(404, f"Skill {skill_id} not found")
    return skill.to_dict()

@app.post("/api/v1/skills")
async def create_skill(req: SkillCreateRequest):
    from tubecli.core.skill import skill_manager
    data = req.model_dump()
    # Drop unset optional fields so Skill defaults apply
    data = {k: v for k, v in data.items() if v is not None}
    commands = data.get("commands") or []
    trigger = data.pop("trigger", "")
    if trigger and not commands:
        commands = [c.strip() for c in trigger.split(",") if c.strip()]
    data["commands"] = commands
    skill = skill_manager.create(**data)
    return {"status": "created", "skill": skill.to_dict()}

@app.put("/api/v1/skills/{skill_id}")
async def update_skill_endpoint(skill_id: str, req: SkillCreateRequest):
    from tubecli.core.skill import skill_manager
    data = req.model_dump()
    # Drop unset optional fields so a partial update never clobbers them
    data = {k: v for k, v in data.items() if v is not None}
    commands = data.get("commands") or []
    trigger = data.pop("trigger", "")
    if trigger and not commands:
        commands = [c.strip() for c in trigger.split(",") if c.strip()]
    data["commands"] = commands
    
    # Remove id/created_at if passed in updates
    data.pop("id", None)
    data.pop("created_at", None)
    
    skill = skill_manager.update(skill_id, **data)
    if not skill:
        raise HTTPException(404, f"Skill {skill_id} not found")
    return {"status": "updated", "skill": skill.to_dict()}

@app.post("/api/v1/skills/generate-ai")
async def generate_skill_ai_endpoint(req: SkillGenerateRequest):
    from tubecli.core.ai_workflow_builder import generate_skill_with_ai
    try:
        result = generate_skill_with_ai(
            prompt=req.prompt,
            provider=req.provider,
            model=req.model,
            api_key=req.api_key
        )
        return {"status": "success", "skill": result}
    except Exception as e:
        raise HTTPException(500, f"Skill AI generation failed: {str(e)}")

@app.delete("/api/v1/skills/{skill_id}")
async def delete_skill(skill_id: str):
    from tubecli.core.skill import skill_manager
    if not skill_manager.delete(skill_id):
        raise HTTPException(404, f"Skill {skill_id} not found")
    return {"status": "deleted", "skill_id": skill_id}


class SaveAsSkillRequest(BaseModel):
    id: Optional[str] = None
    name: str
    description: str = ""
    trigger: str = ""
    workflow_data: Dict = {}
    skill_type: str = "Workflow Skill"


@app.post("/api/v1/workflows/save-as-skill")
async def save_workflow_as_skill(req: SaveAsSkillRequest):
    """Convert a workflow into a reusable Skill that Agents can execute."""
    from tubecli.core.skill import skill_manager

    if not req.name:
        raise HTTPException(400, "Skill name is required")

    commands = [req.trigger.strip()] if req.trigger and req.trigger.strip() else []

    if req.id:
        existing = skill_manager.get(req.id)
        if existing:
            skill_manager.update(
                existing.id,
                name=req.name,
                workflow_data=req.workflow_data,
                description=req.description,
                commands=commands,
            )
            return {"status": "updated", "skill": existing.to_dict(), "message": f"Skill '{req.name}' updated"}

    # Check if name already exists as fallback
    existing_by_name = skill_manager.find_by_name(req.name)
    if existing_by_name:
        skill_manager.update(
            existing_by_name.id,
            workflow_data=req.workflow_data,
            description=req.description,
            commands=commands,
        )
        return {"status": "updated", "skill": existing_by_name.to_dict(), "message": f"Skill '{req.name}' updated (by name)"}

    skill = skill_manager.create(
        name=req.name,
        description=req.description or f"Workflow skill: {req.name}",
        skill_type=req.skill_type,
        workflow_data=req.workflow_data,
        commands=commands
    )
    return {"status": "created", "skill": skill.to_dict(), "message": f"Skill '{req.name}' created successfully"}


@app.post("/api/v1/skills/{skill_id}/run")
async def run_skill(skill_id: str, input_text: str = ""):
    """Run a skill by executing its stored workflow. Returns error guidance for AI agents."""
    from tubecli.core.skill import skill_manager
    from tubecli.nodes.registry import create_node_from_dict
    from tubecli.core.workflow_engine import WorkflowEngine

    skill = skill_manager.get(skill_id)
    if not skill:
        raise HTTPException(404, f"Skill {skill_id} not found")

    import datetime
    skill_manager.update(skill_id, last_run=datetime.datetime.now().isoformat())

    if getattr(skill, "skill_format", "workflow") == "browser_script":
        # Temporary payload for browser_script format (pass to runner)
        # Assuming the browser_scripts extension exposes an endpoint or function.
        # For now, return a placeholder result telling the agent/UI to route to script runner.
        return {
            "status": "success", 
            "message": "Browser script triggered", 
            "action": "run_browser_script", 
            "script_id": skill.workflow_data.get("script_id"),
            "data": input_text
        }
        
    elif getattr(skill, "skill_format", "workflow") == "markdown" or getattr(skill, "skill_type", "") == "Markdown":
        # Markdown SOP simply returns its content for LLM context
        # (legacy UI-created skills carry skill_type="Markdown" with format "workflow")
        return {
            "status": "success",
            "message": "Markdown SOP loaded",
            "action": "load_sop",
            "sop_content": skill.workflow_data.get("markdown_content") or skill.workflow_data.get("markdown") or skill.workflow_data.get("sop") or "",
            "data": input_text
        }

    elif getattr(skill, "skill_format", "workflow") == "extension_action":
        # Dispatch to an extension endpoint (skills without workflow nodes
        # that wrap extension features like Subtitle, TTS, Studios...)
        wf = skill.workflow_data or {}
        endpoint = wf.get("endpoint", "")
        if not endpoint:
            raise HTTPException(400, (
                f"Skill '{skill.name}' is an extension_action but has no endpoint. "
                "Set workflow_data.endpoint (e.g. '/api/v1/subtitle/extract')."
            ))
        import httpx
        method = (wf.get("method") or "POST").upper()
        payload = dict(wf.get("payload") or {})
        input_key = wf.get("input_key") or "input"
        payload.setdefault(input_key, input_text)
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://internal") as client:
                if method == "GET":
                    resp = await client.get(endpoint, params=payload, timeout=300)
                else:
                    resp = await client.request(method, endpoint, json=payload, timeout=300)
            if resp.status_code >= 400:
                return {
                    "status": "error",
                    "message": f"Extension endpoint {endpoint} returned HTTP {resp.status_code}",
                    "guidance": resp.text[:500],
                }
            try:
                data = resp.json()
            except Exception:
                data = {"raw": resp.text[:2000]}
            return {"status": "success", "message": "Extension action completed", "outputs": data}
        except Exception as e:
            raise HTTPException(500, f"Extension action dispatch failed: {e}")

    # Default to Workflow Execution
    wf = skill.workflow_data
    nodes_data = wf.get("nodes", [])
    connections = wf.get("connections", [])

    if not nodes_data:
        # Clear guidance for both humans and AI agents instead of a bare 400
        raise HTTPException(400, (
            f"Skill '{skill.name}' has no workflow nodes, so it cannot be executed. "
            "Open Dashboard → Skills and build its workflow, or set skill_format to "
            "'extension_action' with workflow_data.endpoint if it wraps an extension feature. "
            "AI agents: pick a different skill for this task."
        ))

    if input_text:
        for nd in nodes_data:
            if nd.get("type") in ("text_input", "manual_input"):
                nd.setdefault("config", {})["text"] = input_text

    try:
        nodes = [create_node_from_dict(nd) for nd in nodes_data]
    except Exception as e:
        raise HTTPException(400, f"Node creation error: {e}")

    engine = WorkflowEngine(nodes=nodes, connections=connections)
    result = await engine.run()

    # Collect error guidance from node results for AI agents
    errors = []
    guidance = []
    if result.get("logs"):
        for log in result["logs"]:
            if log.get("status") == "error" or "Error" in str(log.get("message", "")):
                errors.append({"node": log.get("node_name", ""), "error": log.get("message", "")})
    if result.get("node_results"):
        for node_id, node_result in result["node_results"].items():
            if isinstance(node_result, dict):
                if node_result.get("_error_guidance"):
                    guidance.append(node_result["_error_guidance"])
                if "Error" in str(node_result.get("status", "")):
                    errors.append({"node": node_id, "error": node_result.get("status", "")})

    if errors or guidance:
        from tubecli.i18n import t
        result["_skill_errors"] = errors
        result["_skill_guidance"] = guidance or [
            t("brain.workflow_error_guidance")
        ]

    return result


# ── Workflows ────────────────────────────────────────────────────

@app.post("/api/v1/workflows/generate")
async def generate_workflow_with_ai(req: WorkflowGenerateRequest):
    """Generate a workflow from a natural language prompt using AI."""
    from tubecli.core.ai_workflow_builder import generate_workflow
    try:
        result = generate_workflow(
            prompt=req.prompt,
            provider=req.provider,
            model=req.model,
            api_key=req.api_key,
        )
        return {"status": "success", "workflow_data": result}
    except Exception as e:
        raise HTTPException(500, f"Workflow generation failed: {str(e)}")


@app.post("/api/v1/workflows/run")
async def run_workflow(req: WorkflowRunRequest):
    import asyncio
    from tubecli.nodes.registry import create_node_from_dict
    from tubecli.core.workflow_engine import WorkflowEngine

    nodes_data = req.workflow_data.get("nodes", [])
    connections = req.workflow_data.get("connections", [])

    if req.input_text:
        for nd in nodes_data:
            if nd.get("type") in ("text_input", "manual_input"):
                nd.setdefault("config", {})["text"] = req.input_text

    try:
        nodes = [create_node_from_dict(nd) for nd in nodes_data]
    except Exception as e:
        raise HTTPException(400, f"Node creation error: {e}")

    engine = WorkflowEngine(nodes=nodes, connections=connections)
    result = await engine.run()
    return result


@app.get("/api/v1/workflows")
async def list_workflows():
    """List all saved workflows."""
    import json
    from tubecli.config import DATA_DIR

    wf_dir = os.path.join(DATA_DIR, "workflows")
    os.makedirs(wf_dir, exist_ok=True)

    workflows = []
    for fname in os.listdir(wf_dir):
        if fname.endswith(".json"):
            fpath = os.path.join(wf_dir, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                workflows.append({
                    "name": fname.replace(".json", ""),
                    "node_count": len(data.get("nodes", [])),
                    "modified": os.path.getmtime(fpath),
                })
            except Exception:
                pass
    return {"workflows": workflows, "count": len(workflows)}


@app.post("/api/v1/workflows")
async def save_workflow(req: WorkflowSaveRequest):
    """Save a workflow to disk."""
    import json
    from tubecli.config import DATA_DIR

    wf_dir = os.path.join(DATA_DIR, "workflows")
    os.makedirs(wf_dir, exist_ok=True)

    safe_name = "".join(c for c in req.name if c.isalnum() or c in "_- ").strip()
    if not safe_name:
        raise HTTPException(400, "Invalid workflow name")

    fpath = os.path.join(wf_dir, safe_name + ".json")
    with open(fpath, "w", encoding="utf-8") as f:
        json.dump(req.workflow_data, f, indent=2, ensure_ascii=False)

    return {"status": "saved", "name": safe_name}


@app.get("/api/v1/workflows/{name}")
async def get_workflow(name: str):
    """Get a saved workflow by name."""
    import json
    from tubecli.config import DATA_DIR

    fpath = os.path.join(DATA_DIR, "workflows", name + ".json")
    if not os.path.exists(fpath):
        raise HTTPException(404, f"Workflow '{name}' not found")

    with open(fpath, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {"name": name, "workflow_data": data}


@app.delete("/api/v1/workflows/{name}")
async def delete_workflow(name: str):
    """Delete a saved workflow."""
    from tubecli.config import DATA_DIR

    fpath = os.path.join(DATA_DIR, "workflows", name + ".json")
    if not os.path.exists(fpath):
        raise HTTPException(404, f"Workflow '{name}' not found")

    os.remove(fpath)
    return {"status": "deleted", "name": name}


# ── Nodes ────────────────────────────────────────────────────────

@app.get("/api/v1/nodes")
async def list_nodes():
    from tubecli.nodes.registry import list_available_nodes
    return {"nodes": list_available_nodes()}


# ── Extensions Management ───────────────────────────────────────────

@app.get("/api/v1/extensions")
async def list_extensions():
    from tubecli.core.extension_manager import extension_manager
    extensions = extension_manager.get_all()
    return {"extensions": [p.to_dict() for p in extensions], "count": len(extensions)}

@app.post("/api/v1/extensions/{name}/enable")
async def enable_extension(name: str):
    from tubecli.core.extension_manager import extension_manager
    if extension_manager.enable(name):
        return {"status": "enabled", "extension": name}
    raise HTTPException(404, f"Extension '{name}' not found")

@app.post("/api/v1/extensions/{name}/disable")
async def disable_extension(name: str):
    from tubecli.core.extension_manager import extension_manager
    if extension_manager.disable(name):
        return {"status": "disabled", "extension": name}
    raise HTTPException(404, f"Extension '{name}' not found")

@app.put("/api/v1/extensions/{name}")
async def update_extension(name: str, req: ExtensionUpdateRequest):
    from tubecli.core.extension_manager import extension_manager
    extension = extension_manager.get(name)
    if not extension:
         raise HTTPException(404, f"Extension '{name}' not found")
    
    if req.port is not None:
        extension_manager.set_port(name, req.port)
        
    return {"status": "updated", "extension": extension.to_dict()}


@app.get("/api/v1/extensions/{name}/info")
async def extension_info(name: str):
    """Get detailed info about a extension including manifest and SKILL.md."""
    from tubecli.core.extension_manager import extension_manager
    extension = extension_manager.get(name)
    if not extension:
        raise HTTPException(404, f"Extension '{name}' not found")
    info = extension.to_dict()
    info["manifest"] = extension.get_manifest()
    info["nodes"] = list(extension.get_nodes().keys()) if extension.get_nodes() else []
    skill_md = extension.get_skill_md()
    info["skill_md_content"] = skill_md[:2000] if skill_md else None
    return info


@app.get("/api/v1/extensions/{name}/locale/{lang}")
async def extension_locale(name: str, lang: str):
    """Return locale strings for an extension.
    Looks for locales/{lang}.json, falls back to en.json, returns {} if none found.
    """
    from tubecli.core.extension_manager import extension_manager
    import re
    # Sanitize lang to prevent path traversal
    if not re.match(r'^[a-z]{2}(-[A-Z]{2})?$', lang):
        lang = "en"
    extension = extension_manager.get(name)
    if not extension or not extension.extension_dir:
        return {}
    locales_dir = os.path.join(extension.extension_dir, "locales")
    # `json` was never imported in this scope, so json.load() raised NameError,
    # the bare `except Exception` swallowed it, and this endpoint always returned
    # {} — every caller got zero strings and rendered raw keys.
    import json
    # English underneath, requested language on top, so a partially translated
    # locale file degrades to English per key rather than leaking key names.
    merged = {}
    for try_lang in (["en", lang] if lang != "en" else ["en"]):
        locale_path = os.path.join(locales_dir, f"{try_lang}.json")
        if not os.path.isfile(locale_path):
            continue
        try:
            with open(locale_path, "r", encoding="utf-8") as f:
                merged.update(json.load(f))
        except Exception:
            pass
    return merged


class ExtensionInstallRequest(BaseModel):
    git_url: str


@app.post("/api/v1/extensions/install")
async def install_extension(req: ExtensionInstallRequest):
    """Install a extension from a git repository URL."""
    from tubecli.core.extension_manager import extension_manager
    result = extension_manager.install_from_git(req.git_url)
    if result["status"] == "error":
        raise HTTPException(400, result["message"])
    return result


@app.delete("/api/v1/extensions/{name}/uninstall")
async def uninstall_extension(name: str):
    """Uninstall an external extension."""
    from tubecli.core.extension_manager import extension_manager
    result = extension_manager.uninstall(name)
    if result["status"] == "error":
        raise HTTPException(400, result["message"])
    return result


@app.get("/api/v1/extensions/{name}/package")
async def package_extension(name: str):
    """Package all files of an extension into a JSON structure for Market upload.
    Returns manifest + all source files so buyers can fully install the extension.
    Auto-detects pip dependencies from Python imports.
    """
    import re
    import ast
    import json as json_lib
    from tubecli.core.extension_manager import extension_manager

    ext = extension_manager.get(name)
    if not ext:
        raise HTTPException(404, f"Extension '{name}' not found")

    ext_dir = ext.extension_dir
    if not ext_dir or not os.path.isdir(ext_dir):
        raise HTTPException(400, "Extension directory not found")

    # ── Mapping: Python module name → pip package name ──────────────
    # Standard library modules are excluded automatically via sys.stdlib_module_names (Python 3.10+)
    # or a manual list. Any module not in stdlib that is imported is considered a dep.
    IMPORT_TO_PIP = {
        # Media / video
        "yt_dlp": "yt-dlp",
        "imageio_ffmpeg": "imageio-ffmpeg",
        "imageio": "imageio",
        "cv2": "opencv-python",
        "PIL": "Pillow",
        "moviepy": "moviepy",
        "ffmpeg": "ffmpeg-python",
        # HTTP / network
        "requests": "requests",
        "httpx": "httpx",
        "aiohttp": "aiohttp",
        "bs4": "beautifulsoup4",
        "lxml": "lxml",
        "selenium": "selenium",
        "playwright": "playwright",
        "pyppeteer": "pyppeteer",
        # Data / AI
        "numpy": "numpy",
        "pandas": "pandas",
        "sklearn": "scikit-learn",
        "scipy": "scipy",
        "torch": "torch",
        "tensorflow": "tensorflow",
        "openai": "openai",
        "anthropic": "anthropic",
        "google.generativeai": "google-generativeai",
        # Web / API
        "fastapi": "fastapi",
        "pydantic": "pydantic",
        "uvicorn": "uvicorn",
        "flask": "Flask",
        "django": "Django",
        "starlette": "starlette",
        # Utils
        "dotenv": "python-dotenv",
        "yaml": "PyYAML",
        "toml": "tomli",
        "rich": "rich",
        "click": "click",
        "tqdm": "tqdm",
        "loguru": "loguru",
        "cryptography": "cryptography",
        "jwt": "PyJWT",
        "paramiko": "paramiko",
        "pyautogui": "pyautogui",
        "pynput": "pynput",
        "pyperclip": "pyperclip",
        "psutil": "psutil",
        "pytesseract": "pytesseract",
        "docx": "python-docx",
        "openpyxl": "openpyxl",
        "xlrd": "xlrd",
        "reportlab": "reportlab",
        "telegram": "python-telegram-bot",
        "discord": "discord.py",
        "tweepy": "tweepy",
        "boto3": "boto3",
        "google.cloud": "google-cloud",
        "google.auth": "google-auth",
        "pymongo": "pymongo",
        "redis": "redis",
        "sqlalchemy": "SQLAlchemy",
        "alembic": "alembic",
        "celery": "celery",
    }

    # Known stdlib top-level module names (supplemented if sys.stdlib_module_names unavailable)
    import sys
    try:
        _STDLIB = sys.stdlib_module_names  # Python 3.10+
    except AttributeError:
        _STDLIB = {
            "os", "sys", "re", "io", "ast", "abc", "math", "time", "json",
            "uuid", "enum", "copy", "glob", "shutil", "logging", "pathlib",
            "typing", "hashlib", "base64", "struct", "socket", "threading",
            "asyncio", "subprocess", "functools", "itertools", "collections",
            "contextlib", "dataclasses", "importlib", "inspect", "traceback",
            "random", "string", "token", "tokenize", "weakref", "signal",
            "platform", "tempfile", "datetime", "calendar", "urllib",
            "http", "html", "email", "csv", "sqlite3", "xml", "zipfile",
            "tarfile", "gzip", "bz2", "lzma", "codecs", "multiprocessing",
        }

    def _scan_imports(py_source: str) -> set:
        """Extract top-level module names from Python source."""
        found = set()
        try:
            tree = ast.parse(py_source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        found.add(alias.name.split(".")[0])
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        found.add(node.module.split(".")[0])
        except SyntaxError:
            # Fallback: regex
            for m in re.finditer(r"^(?:import|from)\s+([\w]+)", py_source, re.MULTILINE):
                found.add(m.group(1))
        return found

    # ── Collect all files ──────────────────────────────────────────
    SKIP_DIRS = {
        "__pycache__", ".git", "node_modules", ".venv", "venv",
        "data", "db", "logs", "tmp", "dist", "build",
        ".env", ".vscode", ".idea", "coverage",
    }
    SKIP_EXTS = {".pyc", ".pyo", ".egg-info", ".sqlite3", ".db", ".log", ".exe", ".dll", ".so", ".zip", ".tar", ".gz"}
    MAX_FILE_SIZE = 500_000  # 500KB per file

    # ── Parse .gitignore for extra exclusions ──
    gitignore_patterns = set()
    gitignore_path = os.path.join(ext_dir, ".gitignore")
    if os.path.isfile(gitignore_path):
        try:
            with open(gitignore_path, "r") as f:
                for line in f:
                    line = line.strip().rstrip("/")
                    if line and not line.startswith("#"):
                        gitignore_patterns.add(line)
        except Exception:
            pass

    files = []
    all_imports: set = set()

    for root, dirs, filenames in os.walk(ext_dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and d not in gitignore_patterns]

        for fname in filenames:
            if any(fname.endswith(e) for e in SKIP_EXTS):
                continue

            fpath = os.path.join(root, fname)
            rel_path = os.path.relpath(fpath, ext_dir).replace("\\", "/")

            if os.path.getsize(fpath) > MAX_FILE_SIZE:
                continue

            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    content = f.read()
                files.append({"path": rel_path, "content": content})

                # Scan Python files for imports
                if fname.endswith(".py"):
                    all_imports |= _scan_imports(content)
            except (UnicodeDecodeError, PermissionError):
                continue

    # ── Auto-detect pip packages ───────────────────────────────────
    detected_deps: list = []

    # 1. From requirements.txt (highest priority, preserves version pins)
    req_deps: set = set()
    req_file = os.path.join(ext_dir, "requirements.txt")
    if os.path.exists(req_file):
        try:
            with open(req_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        detected_deps.append(line)
                        pkg = re.split(r"[=<>!;]", line)[0].strip().lower().replace("-", "_")
                        req_deps.add(pkg)
        except Exception:
            pass

    # 2. From scanned imports → map to pip packages
    # Respect exclude_auto_deps from manifest (for lazy-loaded heavy deps)
    exclude_auto = set()
    if os.path.exists(os.path.join(ext_dir, "tubecli-extension.json")):
        try:
            with open(os.path.join(ext_dir, "tubecli-extension.json"), "r", encoding="utf-8-sig") as f:
                _m = json_lib.load(f)
            for exc in _m.get("exclude_auto_deps", []):
                exclude_auto.add(exc.lower().replace("-", "_"))
        except Exception:
            pass

    req_deps_normalized = {r.replace("-", "_").lower() for r in req_deps}
    for module in sorted(all_imports):
        if module in _STDLIB:
            continue
        # Skip modules in exclude_auto_deps (heavy deps installed on-demand)
        if module.lower().replace("-", "_") in exclude_auto:
            continue
        # Check if already covered by requirements.txt
        mod_normalized = module.replace("-", "_").lower()
        pip_name = IMPORT_TO_PIP.get(module)
        if not pip_name:
            continue  # Unknown mapping, skip
        pip_normalized = pip_name.replace("-", "_").lower()
        if pip_normalized in exclude_auto:
            continue
        if pip_normalized in req_deps_normalized or mod_normalized in req_deps_normalized:
            continue  # Already in requirements.txt
        detected_deps.append(pip_name)

    # 3. Merge with existing manifest.dependencies (don't lose manually declared ones)
    read_manifest_path = os.path.join(ext_dir, "tubecli-extension.json")
    manifest = {}
    if os.path.exists(read_manifest_path):
        with open(read_manifest_path, "r", encoding="utf-8-sig") as f:
            manifest = json_lib.load(f)

    existing_deps = manifest.get("dependencies", [])
    existing_normalized = {d.replace("-", "_").lower() for d in existing_deps}
    for dep in existing_deps:
        dep_norm = dep.replace("-", "_").lower()
        if dep_norm not in {d.replace("-", "_").lower() for d in detected_deps}:
            detected_deps.append(dep)

    # Deduplicate while preserving order
    seen = set()
    final_deps = []
    for dep in detected_deps:
        key = re.split(r"[=<>!;]", dep)[0].strip().lower().replace("-", "_")
        if key not in seen:
            seen.add(key)
            final_deps.append(dep)

    # Update manifest with auto-detected deps
    manifest["dependencies"] = final_deps

    return {
        "status": "success",
        "manifest": manifest,
        "files": files,
        "file_count": len(files),
        "detected_deps": final_deps,
    }


@app.get("/api/v1/extensions/skill-mds")
async def get_extension_skill_mds():
    """Return all SKILL.md contents from enabled extensions for AI agents."""
    from tubecli.core.extension_manager import extension_manager
    return {"skill_mds": extension_manager.get_all_skill_mds()}


# ── System Version & Update ─────────────────────────────────────────

@app.get("/api/v1/system/version")
async def system_version():
    """Get current system version and git info."""
    import subprocess
    from tubecli import __version__
    from tubecli.config import BASE_DIR

    git_hash = ""
    git_branch = ""
    project_root = str(BASE_DIR)

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=project_root, capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            git_hash = result.stdout.strip()
    except Exception:
        pass

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=project_root, capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            git_branch = result.stdout.strip()
    except Exception:
        pass

    return {
        "version": __version__,
        "git_hash": git_hash,
        "git_branch": git_branch,
    }


@app.post("/api/v1/system/check-update")
async def system_check_update():
    """Check if a system update is available by comparing local vs remote git."""
    import subprocess
    from tubecli import __version__
    from tubecli.config import BASE_DIR

    project_root = str(BASE_DIR)

    try:
        # Fetch latest from remote
        subprocess.run(
            ["git", "fetch", "origin"],
            cwd=project_root, capture_output=True, text=True, timeout=30,
        )

        # Get current hash
        r_local = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=project_root, capture_output=True, text=True, timeout=10,
        )
        current_hash = r_local.stdout.strip() if r_local.returncode == 0 else ""

        # Get remote hash
        r_remote = subprocess.run(
            ["git", "rev-parse", "--short", "origin/main"],
            cwd=project_root, capture_output=True, text=True, timeout=10,
        )
        latest_hash = r_remote.stdout.strip() if r_remote.returncode == 0 else ""

        # Count commits behind
        r_count = subprocess.run(
            ["git", "rev-list", "--count", "HEAD..origin/main"],
            cwd=project_root, capture_output=True, text=True, timeout=10,
        )
        commits_behind = int(r_count.stdout.strip()) if r_count.returncode == 0 else 0

        # Get changelog (commit messages)
        changelog = []
        if commits_behind > 0:
            r_log = subprocess.run(
                ["git", "log", "--oneline", f"HEAD..origin/main", "--format=%s"],
                cwd=project_root, capture_output=True, text=True, timeout=10,
            )
            if r_log.returncode == 0:
                changelog = [line.strip() for line in r_log.stdout.strip().split("\n") if line.strip()]

        return {
            "has_update": commits_behind > 0,
            "current_version": __version__,
            "current_hash": current_hash,
            "latest_hash": latest_hash,
            "commits_behind": commits_behind,
            "changelog": changelog[:20],
        }
    except Exception as e:
        raise HTTPException(500, f"Failed to check for updates: {e}")


@app.post("/api/v1/system/update")
async def system_update():
    """Pull latest code from git and reinstall dependencies."""
    import subprocess, sys
    from tubecli import __version__
    from tubecli.config import BASE_DIR

    project_root = str(BASE_DIR)
    old_version = __version__

    try:
        # Git pull
        r_pull = subprocess.run(
            ["git", "pull", "origin", "main"],
            cwd=project_root, capture_output=True, text=True, timeout=60,
        )
        if r_pull.returncode != 0:
            return {"status": "error", "error": f"git pull failed: {r_pull.stderr}"}

        # Reinstall (update dependencies)
        r_install = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-e", ".", "--quiet"],
            cwd=project_root, capture_output=True, text=True, timeout=120,
        )

        # Read new version from file (since module cache still has old value)
        new_version = old_version
        init_file = os.path.join(project_root, "tubecli", "__init__.py")
        try:
            with open(init_file, "r") as f:
                for line in f:
                    if line.startswith("__version__"):
                        new_version = line.split("=")[1].strip().strip('"').strip("'")
                        break
        except Exception:
            pass

        return {
            "status": "success",
            "old_version": old_version,
            "new_version": new_version,
            "git_output": r_pull.stdout.strip()[:500],
            "message": "Updated successfully! Please restart the API server to apply changes.",
        }
    except Exception as e:
        raise HTTPException(500, f"Update failed: {e}")


# ── Extension Update ─────────────────────────────────────────────────

@app.post("/api/v1/extensions/{name}/check-update")
async def check_extension_update(name: str):
    """Check if an external extension has updates available."""
    import subprocess
    import json
    from tubecli.core.extension_manager import (
        extension_manager,
        compare_versions,
        get_git_tracking_branch,
        get_git_commit_version,
    )
    from tubecli.extensions.market.market_service import market_service

    ext = extension_manager.get(name)
    if not ext:
        raise HTTPException(404, f"Extension '{name}' not found")

    # System extensions update with the core system
    if ext.extension_type != "external":
        return {
            "name": name,
            "has_update": False,
            "message": "System extensions update with 'System Update'. Use Settings → Update.",
            "current_version": ext.version,
        }

    ext_dir = ext.extension_dir
    git_dir = os.path.join(ext_dir, ".git") if ext_dir else None

    if ext_dir and git_dir and os.path.isdir(git_dir):
        # Git-based checking
        try:
            subprocess.run(
                ["git", "fetch", "origin"],
                cwd=ext_dir, capture_output=True, text=True, timeout=15,
            )
            branch = get_git_tracking_branch(ext_dir)

            r_count = subprocess.run(
                ["git", "rev-list", "--count", f"HEAD..origin/{branch}"],
                cwd=ext_dir, capture_output=True, text=True, timeout=10,
            )
            commits_behind = int(r_count.stdout.strip()) if r_count.returncode == 0 else 0

            changelog = []
            if commits_behind > 0:
                r_log = subprocess.run(
                    ["git", "log", "--oneline", f"HEAD..origin/{branch}", "--format=%s"],
                    cwd=ext_dir, capture_output=True, text=True, timeout=10,
                )
                if r_log.returncode == 0:
                    changelog = [l.strip() for l in r_log.stdout.strip().split("\n") if l.strip()]

            # Fetch remote version from git manifest, fallback to remote commit date
            remote_version = None
            try:
                res_show = subprocess.run(
                    ["git", "show", f"origin/{branch}:tubecli-extension.json"],
                    cwd=ext_dir, capture_output=True, text=True, timeout=10
                )
                if res_show.returncode == 0:
                    r_manifest = json.loads(res_show.stdout)
                    remote_version = r_manifest.get("version")
            except Exception:
                pass
            
            if not remote_version or compare_versions(remote_version, "2000.01.01.000000") < 0:
                remote_version = get_git_commit_version(ext_dir, remote=True, branch=branch) or "2026.05.21.000000"

            return {
                "name": name,
                "has_update": commits_behind > 0,
                "current_version": ext.version,
                "remote_version": remote_version,
                "commits_behind": commits_behind,
                "changelog": changelog[:10],
                "is_git": True,
            }
        except Exception as e:
            raise HTTPException(500, f"Failed to check extension git update: {e}")
    else:
        # Marketplace-based checking
        try:
            check_res = await market_service.check_name_exists(ext.name)
            if check_res.get("exists") and check_res.get("item"):
                item = check_res["item"]
                market_version = item.get("version", "0.0.0")
                if compare_versions(market_version, ext.version) > 0:
                    return {
                        "name": name,
                        "has_update": True,
                        "current_version": ext.version,
                        "remote_version": market_version,
                        "public_id": check_res.get("public_id", ""),
                        "is_git": False,
                    }
            return {
                "name": name,
                "has_update": False,
                "message": "Extension is up to date on marketplace.",
                "current_version": ext.version,
                "is_git": False,
            }
        except Exception as e:
            raise HTTPException(500, f"Failed to check extension marketplace update: {e}")


@app.post("/api/v1/extensions/{name}/update")
async def update_extension(name: str):
    """Pull latest code/updates for an external extension."""
    from tubecli.core.extension_manager import extension_manager

    result = extension_manager.update_extension(name)
    if result.get("status") == "error":
        raise HTTPException(400, result.get("message", "Update failed"))
    return result


# ── Aggregated i18n (per-extension locales) ─────────────────────────

@app.get("/api/v1/i18n/{lang}")
async def get_aggregated_i18n(lang: str):
    """Aggregate locale files from ALL extensions into a single flat dict.
    Scans both built-in extensions and external extensions directories.
    """
    import re
    import json
    import os

    # Sanitize lang
    if not re.match(r'^[a-z]{2}(-[A-Z]{2})?$', lang):
        lang = "en"

    merged = {}

    def _load_locales_from_dir(base_dir):
        """Scan a directory for subdirectories containing locales/."""
        if not os.path.isdir(base_dir):
            return
        for entry in os.listdir(base_dir):
            ext_dir = os.path.join(base_dir, entry)
            if not os.path.isdir(ext_dir):
                continue
            locales_dir = os.path.join(ext_dir, "locales")
            if not os.path.isdir(locales_dir):
                continue
            # English underneath, then the requested language on top. The previous
            # version `break`ed after the first file it found, so an extension that
            # shipped vi.json missing a few keys leaked those key names into the UI
            # as literal text instead of degrading to English.
            for try_lang in (["en", lang] if lang != "en" else ["en"]):
                locale_path = os.path.join(locales_dir, f"{try_lang}.json")
                if not os.path.isfile(locale_path):
                    continue
                try:
                    with open(locale_path, "r", encoding="utf-8") as f:
                        merged.update(json.load(f))
                except Exception:
                    pass

    # 1. Built-in extensions: tubecli/extensions/*/locales/
    builtin_ext_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "extensions")
    _load_locales_from_dir(builtin_ext_dir)

    # 2. External extensions: data/extensions_external/*/locales/
    from tubecli.config import EXTENSIONS_EXTERNAL_DIR
    _load_locales_from_dir(str(EXTENSIONS_EXTERNAL_DIR))

    # No _DEBUG block here: this endpoint is reachable from the browser and was
    # returning absolute install paths (which include the OS username).
    return merged


# ── Language Settings ────────────────────────────────────────────────

class LanguageUpdateRequest(BaseModel):
    language: str


@app.get("/api/v1/settings/language")
async def get_language_setting():
    """Get current language setting."""
    from tubecli.config import get_language, SUPPORTED_LANGUAGES
    return {
        "language": get_language(),
        "supported": SUPPORTED_LANGUAGES,
    }


@app.put("/api/v1/settings/language")
async def set_language_setting(req: LanguageUpdateRequest):
    """Update language setting."""
    from tubecli.config import set_language, SUPPORTED_LANGUAGES
    from tubecli.i18n import load_language
    if req.language not in SUPPORTED_LANGUAGES:
        raise HTTPException(400, f"Unsupported language: {req.language}. Supported: {SUPPORTED_LANGUAGES}")
    set_language(req.language)
    load_language(req.language)
    return {"status": "updated", "language": req.language}


# ── Profile Settings ───────────────────────────────────────────────────

class ProfileUpdateRequest(BaseModel):
    profile: str


@app.get("/api/v1/settings/default-profile")
async def get_default_profile_setting():
    """Get current default browser profile."""
    from tubecli.config import get_setting
    return {"profile": get_setting("default_browser_profile", "default")}


@app.put("/api/v1/settings/default-profile")
async def set_default_profile_setting(req: ProfileUpdateRequest):
    """Update default browser profile."""
    from tubecli.config import set_setting
    set_setting("default_browser_profile", req.profile)
    return {"status": "updated", "profile": req.profile}


# ── Register Extension Routes ───────────────────────────────────────
from tubecli.core.extension_manager import extension_manager
extension_manager.discover_extensions()
extension_manager.register_api_routes(app)
