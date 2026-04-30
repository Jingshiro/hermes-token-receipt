"""token_receipt plugin — Print a cute token usage receipt.

Usage:
    /receipt           Print the token receipt for current session
"""

from __future__ import annotations

import os
import random
import socket
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from zoneinfo import ZoneInfo


# ═════════════════════════════════════════════════════════════════════════════
# Jokes loader
# ═════════════════════════════════════════════════════════════════════════════

def _load_jokes() -> list[str]:
    """Load jokes from jokes.yaml, fallback to defaults if missing."""
    plugin_dir = Path(__file__).parent
    jokes_file = plugin_dir / "jokes.yaml"
    
    defaults = [
        "你知道吗？把一个人类蒸馏成 skill 大约需要 {n} token。",
        "你知道吗？让 GPT 学会闭嘴需要 {n} token，但它从没成功过。",
        "你知道吗？让 Agent 承认自己不知道需要 {n} token，让它假装知道只需要 12。",
        "你知道吗？把\"加班是福报\"翻译成英文，BPE 分词器会哭出 {n} token。",
        "你知道吗？每删掉一条产品需求文档里的\"赋能\"，能省 {n} token。",
    ]
    
    try:
        if jokes_file.exists():
            with open(jokes_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if data and "jokes" in data and isinstance(data["jokes"], list):
                    return data["jokes"]
    except Exception:
        pass
    
    return defaults


def _get_random_joke() -> str:
    """Get a random joke with random token number, formatted for width."""
    jokes = _load_jokes()
    joke_template = random.choice(jokes) if jokes else "你知道吗？打印这张小票需要 {n} token。"
    n = random.randint(800, 999_999)
    raw_joke = joke_template.format(n=f"{n:,}")
    
    # Manual line wrapping at ~34 chars to avoid overflow on mobile/narrow screens
    import textwrap
    wrapped_lines = textwrap.wrap(raw_joke, width=34)
    return "\n  ".join(wrapped_lines)


# ═════════════════════════════════════════════════════════════════════════════
# Data collection helpers
# ═════════════════════════════════════════════════════════════════════════════

def _get_session_id() -> Optional[str]:
    """Get current session ID from context vars or environment."""
    try:
        # Preferred way: use gateway's session context
        from gateway.session_context import get_session_env
        sid = get_session_env("HERMES_SESSION_KEY")
        if sid:
            return sid
    except (ImportError, Exception):
        pass

    # Fallback to os.environ (for CLI/legacy)
    for key in ["HERMES_SESSION_KEY", "HERMES_SESSION_CHAT_ID", "HERMES_SESSION_ID"]:
        val = os.getenv(key)
        if val:
            return val
    return None


def _get_session_data(session_id: str) -> Dict[str, Any]:
    """Fetch session data from SessionDB."""
    try:
        from hermes_state import SessionDB
        
        db = SessionDB()
        # Resolve prefix (important for CLI where users might use short IDs)
        resolved_id = db.resolve_session_id(session_id) or session_id
        session = db.get_session(resolved_id)
        if session:
            return dict(session)
    except Exception:
        pass
    
    # Secondary Fallback: try gateway session store file
    try:
        from hermes_cli.config_loader import get_hermes_home
        
        sessions_dir = Path(get_hermes_home()) / "sessions"
        if sessions_dir.exists():
            import json
            sessions_file = sessions_dir / "sessions.json"
            if sessions_file.exists():
                with open(sessions_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for key, entry in data.items():
                        if entry.get("session_id") == session_id or key == session_id:
                            return entry
    except Exception:
        pass
    
    return {}


def _get_location() -> str:
    """Get location from env or timezone."""
    # Try HERMES_LOCATION first
    loc = os.getenv("HERMES_LOCATION", "").strip()
    if loc:
        return loc
    
    # Try to infer from timezone
    try:
        tz = datetime.now().astimezone().tzinfo
        if tz:
            tz_name = str(tz)
            # Map common timezones to locations
            tz_map = {
                "Asia/Shanghai": "Shanghai",
                "Asia/Beijing": "Beijing",
                "Asia/Hong_Kong": "Hong Kong",
                "Asia/Tokyo": "Tokyo",
                "Asia/Seoul": "Seoul",
                "Asia/Singapore": "Singapore",
                "Asia/Taipei": "Taipei",
                "America/New_York": "New York",
                "America/Los_Angeles": "Los Angeles",
                "America/Chicago": "Chicago",
                "Europe/London": "London",
                "Europe/Paris": "Paris",
                "Europe/Berlin": "Berlin",
                "Australia/Sydney": "Sydney",
                "UTC": "UTC",
            }
            if tz_name in tz_map:
                return tz_map[tz_name]
    except Exception:
        pass
    
    return "Localhost"


def _format_duration(seconds: float) -> str:
    """Format duration in Xh Ym Zs format."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    
    parts = []
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0 or hours > 0:
        parts.append(f"{minutes}m")
    parts.append(f"{secs}s")
    
    return " ".join(parts)


# ═════════════════════════════════════════════════════════════════════════════
# Receipt formatter
# ═════════════════════════════════════════════════════════════════════════════

def _get_model_display_name(model_id: str) -> str:
    """Map model ID to display name from config."""
    try:
        import yaml
        from pathlib import Path
        config_path = Path.home() / ".hermes" / "config.yaml"
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
                
            # Check providers in config
            providers = config.get("providers", {})
            for p_name, p_data in providers.items():
                # 1. Check the official 'models' dictionary
                models_dict = p_data.get("models", {})
                if isinstance(models_dict, dict) and model_id in models_dict:
                    return models_dict[model_id]

                # 2. Fallback: Check available_models_json (legacy support)
                models_json = p_data.get("available_models_json")
                if models_json:
                    import json
                    try:
                        models_list = json.loads(models_json)
                        for m in models_list:
                            if m.get("id") == model_id:
                                return m.get("name", model_id)
                    except Exception:
                        pass
                
                # 3. Fallback: Check model_display_name if this provider's active model matches
                if p_data.get("model") == model_id and p_data.get("model_display_name"):
                    return p_data["model_display_name"]
                    
            # Check the top-level model default
            main_model = config.get("model", {})
            if main_model.get("default") == model_id or main_model.get("model") == model_id:
                p_name = main_model.get("provider")
                if p_name:
                    p_data = providers.get(p_name, {})
                    # Check its models dict first
                    if p_data.get("models") and model_id in p_data["models"]:
                        return p_data["models"][model_id]
                    # Then display name
                    if p_data.get("model_display_name"):
                        return p_data["model_display_name"]
    except Exception:
        pass
    
    return model_id


def _build_receipt(
    session_id: str = "--",
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    models: list[str] = None,
    turn_count: int = 0,
    started_at: Optional[float] = None,
    location: str = "--",
    host: str = "--",
) -> str:
    """Build the ASCII receipt."""
    if not models:
        models = ["--"]
    
    # Format timestamp
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    printed_at = now.strftime("%Y-%m-%d %H:%M:%S")
    
    # Calculate duration
    if started_at:
        duration_seconds = now.timestamp() - started_at
        duration = _format_duration(duration_seconds)
    else:
        duration = "--"
    
    # Truncate session_id
    if session_id.startswith("agent:m"):
        short_id = "LATEST"
    else:
        parts = session_id.split("_")
        if len(parts) >= 3:
            short_id = f"{parts[1]}_{parts[2]}"
        else:
            short_id = session_id[:8] if len(session_id) > 8 else session_id
    
    # Get random joke
    joke = _get_random_joke()
    
    # Format models - join with comma, if too long it will be handled by the layout
    model_str = ", ".join(models)
    if len(model_str) > 24:
        model_str = model_str[:21] + "..."
    
    # Build receipt lines
    lines = [
        "```",
        "         HERMES TOKEN RECEIPT",
        f"       —— No.{short_id:>8} ——",
        "──────────────────────────────────────",
        f"  Time      : {printed_at} CST",
        f"  Location  : {location} @ {host}",
        f"  Models    : {model_str}",
        "──────────────────────────────────────",
        f"  Prompt      ........ {prompt_tokens:>8,} tk",
        f"  Completion  ........ {completion_tokens:>8,} tk",
        "  ───────────────────────────────────",
        f"  TOTAL       ........ {total_tokens:>8,} tk",
        "──────────────────────────────────────",
        f"  Turns     : {turn_count}",
        f"  Duration  : {duration}",
        "──────────────────────────────────────",
        f"  {joke}",
        "──────────────────────────────────────",
        "        Thanks for the compute ♥",
        "```",
    ]
    
    return "\n".join(lines)


# ═════════════════════════════════════════════════════════════════════════════
# Main command handler
# ═════════════════════════════════════════════════════════════════════════════

async def cmd_receipt(raw_args: str) -> Optional[str]:
    """Handler for /receipt command.
    
    Args:
        raw_args: Raw arguments passed to the command
    
    Returns:
        Formatted receipt string or None
    """
    raw_args = raw_args.strip()
    
    # ═════════════════════════════════════════════════════════════════════════
    # Subcommand: /receipt joke {content}
    # ═════════════════════════════════════════════════════════════════════════
    if raw_args.startswith("joke "):
        new_joke = raw_args[5:].strip()
        if not new_joke:
            return "Error: Joke content cannot be empty."
            
        plugin_dir = Path(__file__).parent
        jokes_file = plugin_dir / "jokes.yaml"
        
        try:
            jokes_data = {"jokes": []}
            if jokes_file.exists():
                with open(jokes_file, "r", encoding="utf-8") as f:
                    content = yaml.safe_load(f)
                    if isinstance(content, dict) and "jokes" in content:
                        jokes_data = content
            
            if new_joke not in jokes_data["jokes"]:
                jokes_data["jokes"].append(new_joke)
                with open(jokes_file, "w", encoding="utf-8") as f:
                    # Use a clean dump without persona
                    yaml.dump(jokes_data, f, allow_unicode=True, sort_keys=False)
                return "Joke added successfully. Changes will take effect after gateway restart."
            else:
                return "Joke already exists in the collection."
        except Exception as e:
            return f"Failed to save joke: {str(e)}"

    # ═════════════════════════════════════════════════════════════════════════
    # Main Receipt Logic
    # ═════════════════════════════════════════════════════════════════════════
    # Get session ID
    session_id = _get_session_id() or "--"
    
    # Get session data from DB
    session_data = _get_session_data(session_id) if session_id != "--" else {}
    
    # If SessionID lookup failed but we have a session_key, try to resolve it
    if not session_data and session_id.startswith("agent:"):
        try:
            from hermes_state import SessionDB
            db = SessionDB()
            # Try resolution via DB's resolve_session_id
            resolved_id = db.resolve_session_id(session_id)
            if resolved_id and resolved_id != session_id:
                session_data = _get_session_data(resolved_id)
                if session_data:
                    session_id = resolved_id
        except Exception:
            pass
    
    # If still no data, try to find a session that matches our model and is very recent
    if not session_data:
        try:
            from hermes_state import SessionDB
            db = SessionDB()
            # If session_id is a gateway key (contains agent:), directly fetch latest feishu.
            if "agent:" in session_id:
                with db._lock:
                    cursor = db._conn.execute(
                        "SELECT * FROM sessions WHERE source = 'feishu' ORDER BY started_at DESC LIMIT 1"
                    )
                    row = cursor.fetchone()
            else:
                with db._lock:
                    cursor = db._conn.execute(
                        "SELECT * FROM sessions WHERE id = ?",
                        (session_id,)
                    )
                    row = cursor.fetchone()
                    
            if row:
                session_data = dict(zip([d[0] for d in cursor.description], row))
                session_id = session_data.get("id", "--")
        except Exception as e:
            pass

    
    # Absolute fallback: latest session regardless of source
    if not session_data:
        try:
            from hermes_state import SessionDB
            db = SessionDB()
            with db._lock:
                cursor = db._conn.execute("SELECT * FROM sessions ORDER BY started_at DESC LIMIT 1")
                row = cursor.fetchone()
                if row:
                    session_data = dict(zip([d[0] for d in cursor.description], row))
                    session_id = session_data.get("id", "--")
        except Exception:
            pass

    # Extract token counts using SessionDB field names
    prompt_tokens = int(session_data.get("input_tokens", 0) or 0)
    completion_tokens = int(session_data.get("output_tokens", 0) or 0)
    cache_read = int(session_data.get("cache_read_tokens", 0) or 0)
    cache_write = int(session_data.get("cache_write_tokens", 0) or 0)
    reasoning = int(session_data.get("reasoning_tokens", 0) or 0)
    
    # Total includes all token types
    total_tokens = prompt_tokens + completion_tokens + cache_read + cache_write + reasoning
    
    # Collect all models used in this session
    models_used = []
    
    # 1. Get models from message history
    try:
        from hermes_state import SessionDB
        db = SessionDB()
        with db._lock:
            # First check if the messages table has a model column
            cursor = db._conn.execute("PRAGMA table_info(messages)")
            columns = [row[1] for row in cursor.fetchall()]
            
            if "model" in columns:
                cursor = db._conn.execute(
                    "SELECT DISTINCT model FROM messages WHERE session_id = ? AND model IS NOT NULL",
                    (session_id,)
                )
                rows = cursor.fetchall()
                for row in rows:
                    m_name = _get_model_display_name(row[0])
                    if m_name not in models_used:
                        models_used.append(m_name)
    except Exception:
        pass

    # 2. Add current active model from context if not already present
    try:
        from gateway.session_context import get_session_env
        current_model = get_session_env("HERMES_MODEL")
        if current_model:
            m_name = _get_model_display_name(current_model)
            if m_name not in models_used:
                # Add to the beginning so it's most prominent
                models_used.insert(0, m_name)
    except Exception:
        pass
        
    # 3. Fallback to session_data model if still empty
    if not models_used:
        m_id = session_data.get("model")
        if m_id:
            models_used.append(_get_model_display_name(m_id))
    
    # Get turn count
    turn_count = session_data.get("message_count", 0) or 0
    
    # Get start time
    started_at = session_data.get("started_at")
    
    # Get location and host
    location = _get_location()
    host = socket.gethostname()
    
    # Build and return receipt
    return _build_receipt(
        session_id=session_id,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        models=models_used,
        turn_count=turn_count,
        started_at=started_at,
        location=location,
        host=host,
    )


# ═════════════════════════════════════════════════════════════════════════════
# Plugin registration
# ═════════════════════════════════════════════════════════════════════════════

def register(ctx) -> None:
    """Register the token_receipt plugin."""
    ctx.register_command(
        "receipt",
        handler=cmd_receipt,
        description="Print a token usage receipt for the current session.",
    )
