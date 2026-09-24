"""
Admin CLI for counsellor accounts. Passwords are entered by the admin here and
only their bcrypt hash is stored in config.yaml — Claude never sees or stores a
plaintext password.

    python -m app.manage_users hash                 # prompt for a password -> print a bcrypt hash
    python -m app.manage_users add <email> <name> <counselling_by>   # prompt pw, append to config.yaml
    python -m app.manage_users list
    python -m app.manage_users secret               # print a strong session_secret
"""
from __future__ import annotations

import getpass
import os
import secrets
import sys

from . import auth
from .config import load_settings, _project_root


def _config_path():
    return os.path.join(_project_root(), "config.yaml")


def cmd_hash():
    pw = getpass.getpass("New password: ")
    if pw != getpass.getpass("Confirm password: "):
        print("Passwords do not match.", file=sys.stderr); sys.exit(1)
    print(auth.hash_password(pw))


def cmd_secret():
    print(secrets.token_urlsafe(48))


def cmd_add(email, name, counselling_by):
    import yaml
    pw = getpass.getpass(f"Password for {email}: ")
    if pw != getpass.getpass("Confirm: "):
        print("Passwords do not match.", file=sys.stderr); sys.exit(1)
    h = auth.hash_password(pw)
    path = _config_path()
    cfg = {}
    if os.path.exists(path):
        with open(path) as fh:
            cfg = yaml.safe_load(fh) or {}
    cfg.setdefault("counsellors", [])
    cfg["counsellors"] = [c for c in cfg["counsellors"]
                          if c.get("email", "").lower() != email.lower()]
    cfg["counsellors"].append({
        "email": email, "name": name, "counselling_by": counselling_by,
        "role": "counsellor", "password_hash": h, "active": True,
    })
    with open(path, "w") as fh:
        yaml.safe_dump(cfg, fh, sort_keys=False, allow_unicode=True)
    print(f"Added/updated {email} in {path}")


def cmd_list():
    s = load_settings()
    if not s.counsellors:
        print("(no counsellors configured)"); return
    for c in s.counsellors:
        print(f"{c.email:40} {c.name:20} {c.counselling_by:20} "
              f"{'active' if c.active else 'INACTIVE':8} {c.role}")


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print(__doc__); return
    cmd, rest = argv[0], argv[1:]
    if cmd == "hash":
        cmd_hash()
    elif cmd == "secret":
        cmd_secret()
    elif cmd == "add" and len(rest) == 3:
        cmd_add(*rest)
    elif cmd == "list":
        cmd_list()
    else:
        print(__doc__, file=sys.stderr); sys.exit(2)


if __name__ == "__main__":
    main()
