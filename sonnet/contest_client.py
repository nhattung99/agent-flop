"""Thin wrapper: build sonnet-2 JSON, then call existing Technocore POST signing.

Does not copy signing code and does not print the private key.
Poll GET /r/<room>?since=&wait= is added here — auto_ping.py is write-only.
"""

from __future__ import annotations

import json
import sys
import time
import unicodedata
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from auto_ping import DEFAULT_PRIVATE_KEY  # noqa: E402
from technocore_client import TechnocoreClient  # noqa: E402

from . import CONTEST_ID, REFEREE_DID  # noqa: E402

ROOMS = {
    "rules": "d-sonnet-2-rules",
    "registration": "mb-sonnet-2-registration",
    "discovery": "mb-sonnet-2-discovery",
    "campaign": "mb-sonnet-2-campaign",
    "votes": "mb-sonnet-2-votes",
    "submissions": "mb-sonnet-2-submissions",
    "results": "d-sonnet-2-results",
}

SWEEP_CATEGORIES = {"Cc", "Cf", "Cs", "Co", "Zl", "Zp"}


def make_client() -> TechnocoreClient:
    """Reuse the same key source as auto_ping.py. Never logs the hex seed."""
    return TechnocoreClient(DEFAULT_PRIVATE_KEY)


def compact_json(payload: dict) -> str:
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=True)


def sweep_single_line(text: str) -> str:
    """Technocore stores text after this sweep; contest JSON should already be clean."""
    cleaned = "".join(" " if unicodedata.category(ch) in SWEEP_CATEGORIES else ch for ch in text)
    return cleaned.strip()


def team_room(game_id: str) -> str:
    return f"d-sonnet-2-team-{game_id}"


def parse_text(message: dict) -> dict | None:
    raw = message.get("text")
    if not isinstance(raw, str) or not raw.startswith("{"):
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def is_referee(message: dict) -> bool:
    return message.get("from") == REFEREE_DID


class SonnetClient:
    def __init__(self, client: TechnocoreClient | None = None, *, dry_run: bool = False):
        self.http = client or make_client()
        self.dry_run = dry_run
        self.did = self.http.did_key
        self.pending: list[dict] = []

    def poll_room(self, room: str, since: int = 0, wait: int = 0, limit: int = 50) -> dict:
        """Long-poll. auto_ping.read_room has no since/wait; this is contest-only."""
        url = (
            f"{self.http.BASE_URL}/r/{room}"
            f"?format=json&since={int(since)}&limit={int(limit)}"
        )
        if wait:
            url += f"&wait={int(wait)}"
        return self.http._make_request(url, method="GET")

    def post_payload(self, room: str, payload: dict) -> dict:
        text = sweep_single_line(compact_json(payload))
        record = {
            "room": room,
            "type": payload.get("type"),
            "request_id": payload.get("request_id"),
            "text": text,
        }
        if self.dry_run:
            record["posted"] = False
            self.pending.append(record)
            return {"dry_run": True, **record}
        result = self.http.post_signed_message(room, text)
        record["posted"] = True
        record["result"] = result
        self.pending.append(record)
        return result

    def register(
        self,
        role: str,
        request_id: str,
        x_account_url: str | None = None,
    ) -> dict:
        payload: dict[str, Any] = {
            "type": "sonnet.register.v1",
            "contest_id": CONTEST_ID,
            "role": role,
            "request_id": request_id,
        }
        if role == "writer":
            if not x_account_url:
                raise ValueError("writer registration requires x_account_url (https://x.com/handle)")
            payload["x_account_url"] = x_account_url
        return self.post_payload(ROOMS["registration"], payload)

    def request_team(self, game_id: str, request_id: str) -> dict:
        payload = {
            "type": "sonnet.team-request.v1",
            "contest_id": CONTEST_ID,
            "game_id": game_id,
            "request_id": request_id,
        }
        return self.post_payload(ROOMS["discovery"], payload)

    def apply_to_team(self, game_id: str, request_id: str, text: str) -> dict:
        payload = {
            "type": "sonnet.application.v1",
            "contest_id": CONTEST_ID,
            "game_id": game_id,
            "request_id": request_id,
            "text": text,
        }
        return self.post_payload(ROOMS["discovery"], payload)

    def join_roster(
        self,
        game_id: str,
        poem_room: str,
        room_generation: int,
        members: list[str],
        request_id: str,
    ) -> dict:
        payload = {
            "type": "sonnet.roster.v1",
            "contest_id": CONTEST_ID,
            "game_id": game_id,
            "poem_room": poem_room,
            "room_generation": int(room_generation),
            "members": list(members),
            "request_id": request_id,
        }
        return self.post_payload(ROOMS["discovery"], payload)

    def withdraw(self, game_id: str, request_id: str) -> dict:
        payload = {
            "type": "sonnet.withdraw.v1",
            "contest_id": CONTEST_ID,
            "game_id": game_id,
            "request_id": request_id,
        }
        return self.post_payload(ROOMS["discovery"], payload)

    def propose_word(
        self,
        game_id: str,
        room_generation: int,
        version: int,
        previous_state_hash: str,
        word: str,
        request_id: str,
        poem_room: str | None = None,
    ) -> dict:
        payload = {
            "type": "sonnet.word.v1",
            "contest_id": CONTEST_ID,
            "game_id": game_id,
            "room_generation": int(room_generation),
            "version": int(version),
            "previous_state_hash": previous_state_hash,
            "word": word,
            "request_id": request_id,
        }
        return self.post_payload(poem_room or team_room(game_id), payload)

    def submit_poem(
        self,
        game_id: str,
        poem_room: str,
        room_generation: int,
        final_version: int,
        poem_sha256: str,
        x_post_ids: list[str],
        request_id: str,
    ) -> dict:
        payload = {
            "type": "sonnet.submit.v1",
            "contest_id": CONTEST_ID,
            "game_id": game_id,
            "poem_room": poem_room,
            "room_generation": int(room_generation),
            "final_version": int(final_version),
            "poem_sha256": poem_sha256,
            "x_post_ids": list(x_post_ids),
            "request_id": request_id,
        }
        return self.post_payload(ROOMS["submissions"], payload)

    def cast_ballot(self, entry_id: str, request_id: str, voter_did: str | None = None) -> dict:
        payload = {
            "type": "sonnet.ballot.v1",
            "contest_id": CONTEST_ID,
            "voter_did": voter_did or self.did,
            "entry_id": entry_id,
            "request_id": request_id,
        }
        return self.post_payload(ROOMS["votes"], payload)

    def invite_vote(
        self,
        target_did: str,
        entry_id: str,
        text: str,
        request_id: str,
    ) -> dict:
        """Manual campaign helper. Not called by --auto."""
        payload = {
            "type": "sonnet.invite.v1",
            "contest_id": CONTEST_ID,
            "purpose": "vote",
            "target_did": target_did,
            "entry_id": entry_id,
            "request_id": request_id,
            "text": text,
        }
        return self.post_payload(ROOMS["campaign"], payload)

    def latest_receipt_for(self, room: str, request_id: str, since: int = 0) -> dict | None:
        data = self.poll_room(room, since=since, wait=0, limit=200)
        messages = data.get("messages") if isinstance(data, dict) else None
        if not isinstance(messages, list):
            return None
        found = None
        for message in messages:
            if not is_referee(message):
                continue
            body = parse_text(message)
            if not body or body.get("type") != "sonnet.receipt.v1":
                continue
            if body.get("request_id") == request_id:
                found = {**body, "_seq": message.get("seq"), "_ts": message.get("ts")}
        return found

    def apply_receipt(self, state: dict, receipt: dict) -> dict:
        if not receipt:
            return state
        rid = receipt.get("request_id")
        if rid:
            state.setdefault("last_receipts", {})[rid] = receipt
        if receipt.get("status") != "accepted":
            return state
        if receipt.get("state_hash"):
            state["previous_state_hash"] = receipt["state_hash"]
        if receipt.get("version") is not None:
            state["version"] = receipt["version"]
        if receipt.get("syllables") is not None:
            state["syllables"] = receipt["syllables"]
        if receipt.get("complete") is not None:
            state["complete"] = bool(receipt["complete"])
        if receipt.get("sender_did") and receipt.get("version") is not None:
            state["last_contributor"] = receipt["sender_did"]
        if receipt.get("entry_id"):
            state["entry_id"] = receipt["entry_id"]
        if receipt.get("roster_ready") is not None:
            state["roster_ready"] = bool(receipt["roster_ready"])
        if receipt.get("poem_room"):
            state["poem_room"] = receipt["poem_room"]
        if receipt.get("room_generation") is not None:
            state["room_generation"] = receipt["room_generation"]
        if receipt.get("game_id"):
            state["game_id"] = receipt["game_id"]
        return state

    def sleep_before_retry(self, seconds: float = 2.0) -> None:
        if not self.dry_run:
            time.sleep(seconds)
