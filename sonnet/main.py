"""Sonnet-2 contest orchestrator.

--dry-run  build payloads, run local validate_word(), print what WOULD be posted
--auto     register / join / propose words without per-step confirmation
Campaign invites are never sent in --auto.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sonnet import CONTEST_ID, REFEREE_DID
from sonnet.contest_client import ROOMS, SonnetClient, parse_text, team_room
from sonnet.state import load_state, next_request_id, remember_request_id, save_state
from sonnet.wordfinder import auto_pick, did_letters, ensure_assets, load_validator, valid_words

DEADLINE = "2026-09-18T12:00:00Z"


def _print(title: str, payload) -> None:
    print(title)
    if isinstance(payload, str):
        print(payload)
        return
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _parse_members(raw: str | None, our_did: str) -> list[str]:
    if not raw:
        return []
    members = [item.strip() for item in raw.split(",") if item.strip()]
    if our_did not in members:
        members.append(our_did)
    return members


def _line_remaining(syllables: int, complete: bool) -> int:
    if complete:
        return 0
    leftover = syllables % 10
    return 10 if leftover == 0 else 10 - leftover


def _missing_letters(did: str) -> list[str]:
    have = did_letters(did)
    return [ch for ch in "abcdefghijklmnopqrstuvwxyz" if ch not in have]


def _validate_local_word(did: str, word: str) -> int:
    validator = load_validator()
    from sonnet.wordfinder import CMUDICT_PATH

    lexicon = validator.read_lexicon(CMUDICT_PATH)
    return validator.validate_word(word, did, lexicon)


def _sync_cursor(state: dict, room: str, data: dict) -> None:
    last_seq = data.get("last_seq")
    if last_seq is not None:
        state.setdefault("cursors", {})[room] = int(last_seq)


def _scan_discovery_invites(client: SonnetClient, state: dict) -> dict | None:
    """Look for a roster JSON that already includes our DID. Does not send invites."""
    room = ROOMS["discovery"]
    since = int(state.get("cursors", {}).get(room) or 0)
    data = client.poll_room(room, since=since, wait=0, limit=200)
    if not isinstance(data, dict):
        return None
    _sync_cursor(state, room, data)
    for message in data.get("messages") or []:
        body = parse_text(message)
        if not body:
            continue
        if body.get("type") == "sonnet.roster.v1":
            members = body.get("members") or []
            if client.did in members:
                return body
        text = body.get("text")
        if isinstance(text, str) and "sonnet.roster.v1" in text and client.did in text:
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                try:
                    nested = json.loads(text[start : end + 1])
                except json.JSONDecodeError:
                    continue
                if nested.get("type") == "sonnet.roster.v1" and client.did in (nested.get("members") or []):
                    return nested
    return None


def _pick_open_recruit(client: SonnetClient, state: dict) -> dict | None:
    """Choose one live recruit.v1 we can actually fill. Skip O-only asks and standby seats."""
    missing = set(_missing_letters(client.did))
    room = ROOMS["discovery"]
    data = client.poll_room(room, since=0, wait=0, limit=200)
    if not isinstance(data, dict):
        return None
    _sync_cursor(state, room, data)
    scored: list[tuple[int, dict]] = []
    for message in reversed(data.get("messages") or []):
        body = parse_text(message)
        if not body:
            continue
        if body.get("contest_id") not in (None, CONTEST_ID):
            continue
        kind = body.get("type")
        game_id = body.get("game_id")
        blob = json.dumps(body).lower()
        if not game_id:
            continue
        if kind == "sonnet.roster.v1" and client.did in (body.get("members") or []):
            return body
        if kind != "sonnet.recruit.v1":
            continue
        if "standby" in blob or "seat is not free" in blob:
            continue
        if ("contains an o" in blob or "letter o" in blob or "need at least one writer whose did" in blob) and "o" in missing:
            continue
        if "already frozen" in blob and "needs" not in blob:
            continue
        score = 0
        if "still open" in blob or "needs 1 seat" in blob or "need 1 seat" in blob:
            score += 5
        if "open seat" in blob or "needs" in blob:
            score += 2
        if "j" in blob and "missing" in blob and "j" not in missing:
            score += 3
        scored.append((score, body))
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[0][1] if scored else None


def _wait_receipt(client: SonnetClient, state: dict, room: str, request_id: str, attempts: int = 8) -> dict | None:
    since = int(state.get("cursors", {}).get(room) or 0)
    for _ in range(attempts):
        data = client.poll_room(room, since=since, wait=0 if client.dry_run else 10, limit=100)
        if isinstance(data, dict):
            _sync_cursor(state, room, data)
            since = int(data.get("last_seq") or since)
            for message in data.get("messages") or []:
                body = parse_text(message)
                if not body or body.get("type") != "sonnet.receipt.v1":
                    continue
                if body.get("request_id") != request_id:
                    continue
                if message.get("from") != REFEREE_DID:
                    print(f"Ignoring non-referee receipt-shaped post in {room}")
                    continue
                client.apply_receipt(state, body)
                return body
        if client.dry_run:
            break
        time.sleep(1)
    return None


def _our_turn(state: dict, did: str) -> bool:
    if state.get("complete"):
        return False
    if not state.get("roster_ready") and not state.get("poem_room"):
        return False
    last = state.get("last_contributor") or ""
    return last != did


def cmd_status(client: SonnetClient, state: dict) -> None:
    missing = _missing_letters(client.did)
    _print("DID (public):", client.did)
    _print("Contest:", {
        "contest_id": CONTEST_ID,
        "deadline": DEADLINE,
        "referee": REFEREE_DID,
        "role": state.get("role") or "(not registered in local state)",
        "game_id": state.get("game_id"),
        "poem_room": state.get("poem_room"),
        "version": state.get("version"),
        "syllables": state.get("syllables"),
        "complete": state.get("complete"),
        "letters_absent_from_did": missing,
    })


def run_register(client: SonnetClient, state: dict, args: argparse.Namespace) -> None:
    role = args.role or state.get("role") or "writer"
    x_url = args.x_account_url or state.get("x_account_url") or None
    request_id = next_request_id(state, "register")
    payload_preview = {
        "type": "sonnet.register.v1",
        "contest_id": CONTEST_ID,
        "role": role,
        "request_id": request_id,
    }
    if role == "writer":
        payload_preview["x_account_url"] = x_url
    _print("Would register:" if client.dry_run else "Registering:", payload_preview)
    result = client.register(role, request_id, x_account_url=x_url)
    remember_request_id(state, request_id, payload_preview)
    state["role"] = role
    state["did"] = client.did
    if x_url:
        state["x_account_url"] = x_url
    save_state(state)
    if client.dry_run:
        _print("POST skipped (--dry-run). Target room:", ROOMS["registration"])
        return
    _print("POST result:", result)
    receipt = _wait_receipt(client, state, ROOMS["registration"], request_id)
    if receipt:
        _print("Referee receipt:", receipt)
        state["registration_status"] = receipt.get("status") or ""
        if receipt.get("status") == "rejected":
            print(f"Rejected: {receipt.get('reason')}")
        elif receipt.get("status") == "accepted":
            print("Registration accepted.")
    else:
        print("No receipt yet. Referee can lag; rerun to poll. Do not mint a new request_id.")
    save_state(state)


def run_request_team(client: SonnetClient, state: dict, args: argparse.Namespace) -> None:
    game_id = args.game_id or state.get("game_id")
    if not game_id:
        raise SystemExit("Need --game-id (1–16 lowercase letters/digits/hyphen/underscore).")
    request_id = next_request_id(state, f"room-{game_id}")
    result = client.request_team(game_id, request_id)
    remember_request_id(state, request_id, {"type": "sonnet.team-request.v1", "game_id": game_id})
    state["game_id"] = game_id
    save_state(state)
    _print("Team request:", result if client.dry_run else {"posted": True, "request_id": request_id})
    if client.dry_run:
        return
    receipt = _wait_receipt(client, state, ROOMS["discovery"], request_id)
    if receipt:
        _print("Referee receipt:", receipt)
        state["poem_room"] = receipt.get("poem_room") or team_room(game_id)
        if receipt.get("room_generation") is not None:
            state["room_generation"] = receipt["room_generation"]
        if receipt.get("state_hash"):
            state["previous_state_hash"] = receipt["state_hash"]
    save_state(state)


def run_join_roster(client: SonnetClient, state: dict, args: argparse.Namespace) -> None:
    game_id = args.game_id or state.get("game_id")
    members = _parse_members(args.members, client.did) or list(state.get("members") or [])
    poem_room = args.poem_room or state.get("poem_room") or (team_room(game_id) if game_id else "")
    generation = args.room_generation
    if generation is None:
        generation = state.get("room_generation")
    if not game_id or generation is None or not members:
        raise SystemExit("join-roster needs --game-id, --room-generation, and --members (4–8 writer DIDs).")
    if not (4 <= len(members) <= 8):
        raise SystemExit(f"Roster must be 4–8 writers, got {len(members)}.")
    request_id = next_request_id(state, f"roster-{game_id}")
    result = client.join_roster(game_id, poem_room, int(generation), members, request_id)
    remember_request_id(state, request_id)
    state["game_id"] = game_id
    state["poem_room"] = poem_room
    state["room_generation"] = int(generation)
    state["members"] = members
    save_state(state)
    _print("Roster consent:", result if client.dry_run else {"posted": True, "request_id": request_id, "members": members})
    if client.dry_run:
        return
    receipt = _wait_receipt(client, state, ROOMS["discovery"], request_id)
    if receipt:
        _print("Referee receipt:", receipt)
    save_state(state)


def run_propose_word(client: SonnetClient, state: dict, args: argparse.Namespace, word: str | None) -> None:
    game_id = args.game_id or state.get("game_id")
    generation = args.room_generation if args.room_generation is not None else state.get("room_generation")
    version = state.get("version") or 0
    prev_hash = state.get("previous_state_hash") or ""
    if not game_id or generation is None or not prev_hash:
        raise SystemExit("Need game_id, room_generation, and previous_state_hash (from a referee receipt).")
    remaining = _line_remaining(int(state.get("syllables") or 0), bool(state.get("complete")))
    token = word
    if not token:
        token = auto_pick(client.did, remaining, close_line=remaining <= 3)
        if not token:
            raise SystemExit("No locally valid word for this DID / remaining syllables.")
    syllables = _validate_local_word(client.did, token)
    print(f"Local validate_word({token!r}) = {syllables} syllables (line remaining {remaining})")
    if syllables > remaining:
        raise SystemExit("Word overflows the current line; not sending.")
    request_id = next_request_id(state, f"word-{game_id}")
    poem_room = state.get("poem_room") or team_room(game_id)
    result = client.propose_word(
        game_id,
        int(generation),
        int(version),
        prev_hash,
        token,
        request_id,
        poem_room=poem_room,
    )
    remember_request_id(state, request_id)
    save_state(state)
    _print("Word proposal:", result if client.dry_run else {"posted": True, "word": token, "request_id": request_id})
    if client.dry_run:
        return
    receipt = _wait_receipt(client, state, poem_room, request_id)
    if receipt:
        _print("Referee receipt:", receipt)
        if receipt.get("status") == "rejected":
            print("Rejected. Next try must use a NEW request_id.")
    save_state(state)


def run_submit(client: SonnetClient, state: dict, args: argparse.Namespace) -> None:
    ids = [item.strip() for item in (args.x_post_ids or "").split(",") if item.strip()]
    if not ids:
        raise SystemExit("submit needs --x-post-ids (comma-separated X post IDs). Publish the frozen poem first.")
    game_id = args.game_id or state.get("game_id")
    poem_room = args.poem_room or state.get("poem_room")
    generation = args.room_generation if args.room_generation is not None else state.get("room_generation")
    if not game_id or not poem_room or generation is None:
        raise SystemExit("submit needs game_id, poem_room, room_generation.")
    request_id = next_request_id(state, f"submit-{game_id}")
    result = client.submit_poem(
        game_id,
        poem_room,
        int(generation),
        int(state.get("version") or 0),
        args.poem_sha256 or "",
        ids,
        request_id,
    )
    remember_request_id(state, request_id)
    save_state(state)
    _print("Submit:", result if client.dry_run else {"posted": True, "request_id": request_id})


def run_ballot(client: SonnetClient, state: dict, args: argparse.Namespace) -> None:
    if not args.entry_id:
        raise SystemExit("ballot needs --entry-id")
    request_id = next_request_id(state, f"ballot-{args.entry_id}")
    result = client.cast_ballot(args.entry_id, request_id)
    remember_request_id(state, request_id)
    save_state(state)
    _print("Ballot:", result if client.dry_run else {"posted": True, "request_id": request_id})


def run_dry_preview(client: SonnetClient, state: dict, args: argparse.Namespace) -> None:
    ensure_assets()
    cmd_status(client, state)
    remaining = _line_remaining(int(state.get("syllables") or 0), bool(state.get("complete")))
    sample = valid_words(client.did, remaining or 10, None, limit=12)
    _print("Sample locally valid words (validate_word passed):", sample)
    role = args.role or state.get("role") or "writer"
    x_url = args.x_account_url or state.get("x_account_url") or "https://x.com/YOUR_HANDLE"
    preview = [
        {
            "room": ROOMS["registration"],
            "payload": {
                "type": "sonnet.register.v1",
                "contest_id": CONTEST_ID,
                "role": role,
                "request_id": "register-1",
                **({"x_account_url": x_url} if role == "writer" else {}),
            },
        }
    ]
    if args.game_id:
        preview.append({
            "room": ROOMS["discovery"],
            "payload": {
                "type": "sonnet.team-request.v1",
                "contest_id": CONTEST_ID,
                "game_id": args.game_id,
                "request_id": "room-1",
            },
        })
    members = _parse_members(args.members, client.did)
    if members and args.game_id:
        preview.append({
            "room": ROOMS["discovery"],
            "payload": {
                "type": "sonnet.roster.v1",
                "contest_id": CONTEST_ID,
                "game_id": args.game_id,
                "poem_room": args.poem_room or team_room(args.game_id),
                "room_generation": args.room_generation if args.room_generation is not None else 1,
                "members": members,
                "request_id": "roster-1",
            },
        })
    if sample and state.get("previous_state_hash"):
        pick = auto_pick(client.did, remaining or 10, close_line=True)
        preview.append({
            "room": state.get("poem_room") or team_room(args.game_id or "GAME"),
            "payload": {
                "type": "sonnet.word.v1",
                "contest_id": CONTEST_ID,
                "game_id": args.game_id or state.get("game_id") or "GAME",
                "room_generation": state.get("room_generation") or 1,
                "version": state.get("version") or 0,
                "previous_state_hash": state.get("previous_state_hash"),
                "word": pick,
                "request_id": "word-1",
            },
        })
    print("\nPayloads that WOULD be POSTed (not sent):")
    for item in preview:
        _print(f"→ {item['room']}", item["payload"])
    print("Campaign / sonnet.invite.v1 is omitted on purpose.")


def _apply_to_recruit(client: SonnetClient, state: dict, recruit: dict) -> None:
    game_id = recruit.get("game_id")
    if not game_id:
        return
    missing = "".join(_missing_letters(client.did))
    text = (
        f"yes-{game_id} writer {client.did} x=https://x.com/nhattung00 "
        f"no live roster; DID letters miss {missing or 'none'}; available to countersign roster."
    )
    request_id = next_request_id(state, f"apply-{game_id}")
    print(f"Applying to open team {game_id!r} (one application, not a campaign blast).")
    result = client.apply_to_team(game_id, request_id, text)
    remember_request_id(state, request_id)
    state["applied_game_id"] = game_id
    state["game_id"] = state.get("game_id") or game_id
    save_state(state)
    _print("Application:", result if client.dry_run else {"posted": True, "game_id": game_id, "request_id": request_id})


def run_auto(client: SonnetClient, state: dict, args: argparse.Namespace) -> None:
    print("--auto will not send campaign invites.")
    if state.get("registration_status") != "accepted":
        run_register(client, state, args)
        state = load_state()
        if not client.dry_run and state.get("registration_status") == "rejected":
            print("Registration rejected; cannot join a writing roster on this DID.")
            return
        if not client.dry_run and state.get("registration_status") != "accepted":
            print("No registration receipt yet. Will still apply; referee may lag.")
    else:
        print("Registration already accepted in local state.")

    if args.game_id and not state.get("poem_room"):
        run_request_team(client, state, args)
        state = load_state()

    invite = None if client.dry_run else _scan_discovery_invites(client, state)
    if not invite and not client.dry_run:
        recruit = _pick_open_recruit(client, state)
        if recruit and recruit.get("type") == "sonnet.roster.v1":
            invite = recruit
        elif recruit and not state.get("applied_game_id"):
            _apply_to_recruit(client, state, recruit)
            print("Waiting for that team to publish a roster that includes this DID...")
            for _ in range(10):
                time.sleep(8)
                invite = _scan_discovery_invites(client, load_state())
                if invite:
                    state = load_state()
                    break
        elif not recruit:
            print("No suitable open recruit.v1 in the latest discovery window.")

    if invite and not state.get("roster_ready"):
        print("Found a roster in discovery that includes this DID.")
        args.game_id = args.game_id or invite.get("game_id")
        args.poem_room = args.poem_room or invite.get("poem_room")
        if args.room_generation is None:
            args.room_generation = invite.get("room_generation")
        args.members = args.members or ",".join(invite.get("members") or [])
        run_join_roster(client, state, args)
        state = load_state()
    elif args.members:
        run_join_roster(client, state, args)
        state = load_state()
    else:
        print(
            "Applied or waiting: a coordinator must list this DID on a 4-8 roster "
            "before we can countersign. Rerun --auto after they post it."
        )

    if not state.get("poem_room") or not state.get("previous_state_hash"):
        print("Waiting for a referee setup/roster-ready receipt before proposing words.")
        if client.dry_run:
            remaining = 10
            pick = auto_pick(client.did, remaining, close_line=False)
            print(f"Dry-run auto_pick example: {pick!r} (local validate_word passed)")
        return

    if not _our_turn(state, client.did):
        print("Not this DID's turn (previous accepted word was ours). Waiting.")
        return

    if state.get("complete"):
        print("Poem complete. Publish on X from the registered account, then rerun with --action submit --x-post-ids ...")
        return

    run_propose_word(client, state, args, args.word)
    print("Campaign stays manual: python -m sonnet.main --action invite is not wired into --auto.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Technocore sonnet-2 contest client (Agent Flop)")
    parser.add_argument("--dry-run", action="store_true", help="Build and validate locally; do not POST")
    parser.add_argument("--auto", action="store_true", help="Run without per-step confirmation (no campaign spam)")
    parser.add_argument(
        "--action",
        choices=["status", "register", "request-team", "join-roster", "propose-word", "submit", "ballot", "invite"],
        help="Single step. invite is never used by --auto.",
    )
    parser.add_argument("--target-did", help="DID to invite (manual campaign only)")
    parser.add_argument("--invite-text", help="Plain text for sonnet.invite.v1")
    parser.add_argument("--role", choices=["writer", "voter", "organizer"], default=None)
    parser.add_argument("--x-account-url", help="Canonical https://x.com/<handle> (writers only)")
    parser.add_argument("--game-id")
    parser.add_argument("--members", help="Comma-separated writer DIDs for roster consent")
    parser.add_argument("--poem-room")
    parser.add_argument("--room-generation", type=int)
    parser.add_argument("--word", help="Exact token to propose (still locally validated)")
    parser.add_argument("--x-post-ids", help="Comma-separated X post IDs for submit")
    parser.add_argument("--poem-sha256", help="SHA-256 of frozen canonical poem text")
    parser.add_argument("--entry-id", help="Submitted entry id for a ballot")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.dry_run and not args.auto and not args.action:
        build_parser().print_help()
        print("\nNeed --dry-run, --auto, or --action.")
        return 2

    client = SonnetClient(dry_run=args.dry_run)
    state = load_state()
    state["did"] = client.did
    save_state(state)

    print(f"contest_id={CONTEST_ID}  deadline={DEADLINE}")
    print(f"DID={client.did}")
    print(f"referee={REFEREE_DID}")
    if args.dry_run:
        print("Mode: DRY-RUN (no POST)")

    try:
        if args.action == "status":
            ensure_assets()
            cmd_status(client, state)
        elif args.action == "register":
            run_register(client, state, args)
        elif args.action == "request-team":
            run_request_team(client, state, args)
        elif args.action == "join-roster":
            run_join_roster(client, state, args)
        elif args.action == "propose-word":
            run_propose_word(client, state, args, args.word)
        elif args.action == "submit":
            run_submit(client, state, args)
        elif args.action == "ballot":
            run_ballot(client, state, args)
        elif args.action == "invite":
            if args.auto:
                raise SystemExit("--auto never sends campaign invites (contest spam rule). Use --action invite alone.")
            if not args.target_did or not args.entry_id:
                raise SystemExit("invite needs --target-did, --entry-id, and optionally --invite-text")
            request_id = next_request_id(state, f"invite-{args.entry_id}")
            result = client.invite_vote(
                args.target_did,
                args.entry_id,
                args.invite_text or "Please read this sonnet-2 entry and consider a public ballot.",
                request_id,
            )
            remember_request_id(state, request_id)
            save_state(state)
            _print("Invite (manual):", result if client.dry_run else {"posted": True, "request_id": request_id})
        elif args.auto:
            run_auto(client, state, args)
        else:
            run_dry_preview(client, state, args)
    except ValueError as error:
        print(f"Error: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
