"""Secure Shopping credentials from process, DB-local or existing user config.

No credential is sent to the browser extension or merchant website.
Every read of a file credential requires regular owned mode-0600 data.
"""
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import secrets

MAX_INDEX_PROVIDER_CALLS_PER_UTC_DAY = 24


def _secret_path(db_path):
    return Path(str(db_path) + ".serpapi.key")


def _shared_config_path():
    # The user's existing shell-sourceable configuration; no shell executed.
    override=os.environ.get("TRACECART_SERPAPI_CONFIG_FILE","").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".config" / "tracecart" / "serpapi.env"


def _disabled_path(db_path):
    return Path(str(db_path) + ".serpapi.disabled")


def _read_secure_file(path):
    if not path.exists():
        return None
    st=path.lstat()
    if (path.is_symlink() or not path.is_file() or
            st.st_uid != os.getuid() or st.st_mode & 0o077 or
            st.st_size > 4096):
        raise ValueError("INSECURE_SHOPPING_CREDENTIAL_FILE")
    return path.read_text(encoding="ascii")


def read_provider_key(db_path):
    # An operator's opt-out must also disable a previously sourced or
    # shared key; never modify the shared ~/.config file itself.
    if _disabled_path(db_path).exists():
        return None,"DISABLED_FOR_THIS_DATABASE"
    env=os.environ.get("SERPAPI_API_KEY","")
    if env:
        return env,"ENVIRONMENT"
    raw=_read_secure_file(_secret_path(db_path))
    if raw is not None:
        text=raw.strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{20,128}",text):
            raise ValueError("INVALID_SHOPPING_CREDENTIAL_FILE")
        return text,"LOCAL_FILE"
    shared=_read_secure_file(_shared_config_path())
    if shared is None:
        return None,"NOT_CONFIGURED"
    keys=[]
    for line in shared.splitlines():
        line=line.strip()
        if not line or line.startswith("#"):
            continue
        match=re.fullmatch(
            r"""(?:export\s+)?SERPAPI_API_KEY\s*=\s*(['"]?)([A-Za-z0-9_-]{20,128})\1""",
            line)
        if not match:
            raise ValueError("INVALID_SHARED_SERPAPI_CONFIG")
        keys.append(match.group(2))
    if len(keys)!=1:
        raise ValueError("INVALID_SHARED_SERPAPI_CONFIG")
    return keys[0],"EXISTING_USER_CONFIG"


def save_provider_key(db_path, value):
    if type(value) is not str or not re.fullmatch(r"[a-zA-Z0-9_-]{20,128}",value):
        raise ValueError("INVALID_PROVIDER_KEY_FORMAT")
    disabled=_disabled_path(db_path)
    if disabled.exists():
        disabled.unlink()
    path=_secret_path(db_path)
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+"."+secrets.token_hex(5)+".tmp")
    fd=os.open(str(tmp),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    try:
        with os.fdopen(fd,"w",encoding="ascii") as file:
            file.write(value+"\n")
        os.replace(str(tmp),str(path))
    finally:
        if tmp.exists():
            tmp.unlink()


def disable_provider_key(db_path):
    path=_secret_path(db_path)
    if path.is_symlink():
        raise ValueError("INSECURE_SHOPPING_CREDENTIAL_FILE")
    if path.exists():
        path.unlink()
    disabled=_disabled_path(db_path)
    disabled.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(str(disabled),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600) if not disabled.exists() else None
    if fd is not None:
        os.close(fd)
    # Do not remove ~/.config/tracecart/serpapi.env or unset other shells.
    return True


def reserve_provider_budget(db_path, job_id, daily_cap=MAX_INDEX_PROVIDER_CALLS_PER_UTC_DAY):
    """Atomic 2-query reservation for a single research job before any paid call."""
    import sqlite3
    if type(job_id) is not str or not re.fullmatch(r"[A-Za-z0-9_-]{16,45}",job_id):
        raise ValueError("INVALID_RESEARCH_ID")
    day=datetime.now(timezone.utc).date().isoformat()
    with sqlite3.connect(str(db_path),timeout=8) as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("""CREATE TABLE IF NOT EXISTS cart_shopping_budget (
           utc_date TEXT NOT NULL, job_id TEXT NOT NULL, reserved_calls INTEGER NOT NULL,
           PRIMARY KEY(utc_date,job_id))""")
        used=db.execute("""SELECT COALESCE(SUM(reserved_calls),0)
           FROM cart_shopping_budget WHERE utc_date=?""",(day,)).fetchone()[0]
        existing=db.execute("""SELECT reserved_calls FROM cart_shopping_budget
           WHERE utc_date=? AND job_id=?""",(day,job_id)).fetchone()
        if existing or used+2>daily_cap:
            return False
        db.execute("""INSERT INTO cart_shopping_budget
           (utc_date,job_id,reserved_calls) VALUES (?,?,2)""",(day,job_id))
        return True


def provider_usage(db_path):
    import sqlite3
    day=datetime.now(timezone.utc).date().isoformat()
    with sqlite3.connect(str(db_path),timeout=5) as db:
        try:
            used=db.execute("""SELECT COALESCE(SUM(reserved_calls),0)
               FROM cart_shopping_budget WHERE utc_date=?""",(day,)).fetchone()[0]
        except sqlite3.OperationalError:
            used=0
    return {"reserved_calls_today":used,
            "daily_cap":MAX_INDEX_PROVIDER_CALLS_PER_UTC_DAY,
            "max_calls_per_cart":2,
            "day_utc":day}
