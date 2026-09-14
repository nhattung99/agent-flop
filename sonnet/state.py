"""Local contest resume file. Never stores a private key."""

from __future__ import annotations

import json
from pathlib import Path

STATE_PATH = Path(__file__).resolve().parent / "state.json"

DEFAULT_STATE = {
    "contest_id": "sonnet-2",
    "did": "",
    "role": "",
    "x_account_url": "",
    "game_id": "",
    "poem_room": "",
    "room_generation": None,
    "version": 0,
    "previous_state_hash": "",
    "members": [],
    "roster_ready": False,
    "complete": False,
    "syllables": 0,
    "last_contributor": "",
    "entry_id": "",
    "used_request_ids": [],
    "request_payloads": {},
    "cursors": {},
    "last_receipts": {},
    "registration_status": "",
    "applied_game_id": "",
}


def load_state(path: Path | None = None) -> dict:
    target = path or STATE_PATH
    if not target.exists():
        return json.loads(json.dumps(DEFAULT_STATE))
    with target.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    state = json.loads(json.dumps(DEFAULT_STATE))
    state.update(data)
    state.setdefault("used_request_ids", [])
    state.setdefault("request_payloads", {})
    state.setdefault("cursors", {})
    state.setdefault("last_receipts", {})
    state.setdefault("members", [])
    state.setdefault("registration_status", "")
    state.setdefault("applied_game_id", "")
    return state


def save_state(state: dict, path: Path | None = None) -> None:
    target = path or STATE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    tmp.replace(target)


def remember_request_id(state: dict, request_id: str, payload: dict | None = None) -> None:
    ids = state.setdefault("used_request_ids", [])
    if request_id not in ids:
        ids.append(request_id)
    if payload is not None:
        state.setdefault("request_payloads", {})[request_id] = payload


def next_request_id(state: dict, prefix: str) -> str:
    n = 1 + sum(1 for item in state.get("used_request_ids", []) if str(item).startswith(prefix))
    candidate = f"{prefix}-{n}"
    used = set(state.get("used_request_ids") or [])
    while candidate in used:
        n += 1
        candidate = f"{prefix}-{n}"
    return candidate
