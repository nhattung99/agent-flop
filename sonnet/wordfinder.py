"""Download the pinned contest dictionary/validator and index words by syllables.

Uses the upstream validate_word() logic; does not guess syllable counts.
"""

from __future__ import annotations

import hashlib
import importlib.util
import re
import sys
import urllib.request
from pathlib import Path
from types import ModuleType

PINNED_COMMIT = "e1999094c359ef7390bdf07fe2a151393a5c2f51"
PACKAGE_BASE = (
    f"https://raw.githubusercontent.com/flop-labs/technocore-sonnet-challenge/{PINNED_COMMIT}"
)
CMUDICT_SHA256 = "81917843c7f44ce2b094ac63873c2c7a4cf802040792c455ba3ca406891c3d22"
VALIDATE_SHA256 = "1d00c6c788cc92a97f7125a64eb7454dc410d2c7049ae6d03200a11e5eb7ae54"

CACHE_DIR = Path(__file__).resolve().parent / "_cache"
CMUDICT_PATH = CACHE_DIR / "cmudict.dict"
VALIDATE_PATH = CACHE_DIR / "sonnet_validate.py"

VOWELS = {"AA", "AE", "AH", "AO", "AW", "AY", "EH", "ER", "EY", "IH", "IY", "OW", "OY", "UH", "UW"}
WORD_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)*")

_validator: ModuleType | None = None
_lexicon: dict[str, int] | None = None
_rhyme_keys: dict[str, str] | None = None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(url: str, dest: Path, expected_sha256: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and _sha256_file(dest) == expected_sha256:
        return
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    req = urllib.request.Request(url, headers={"User-Agent": "AgentFlop-sonnet/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp, tmp.open("wb") as out:
        while True:
            chunk = resp.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)
    actual = _sha256_file(tmp)
    if actual != expected_sha256:
        tmp.unlink(missing_ok=True)
        raise ValueError(
            f"hash mismatch for {dest.name}: expected {expected_sha256}, got {actual}"
        )
    tmp.replace(dest)


def ensure_assets() -> tuple[Path, Path]:
    """Fetch pinned cmudict.dict + sonnet_validate.py and verify SHA-256."""
    _download(f"{PACKAGE_BASE}/cmudict.dict", CMUDICT_PATH, CMUDICT_SHA256)
    _download(f"{PACKAGE_BASE}/sonnet_validate.py", VALIDATE_PATH, VALIDATE_SHA256)
    return CMUDICT_PATH, VALIDATE_PATH


def load_validator() -> ModuleType:
    global _validator
    if _validator is not None:
        return _validator
    ensure_assets()
    spec = importlib.util.spec_from_file_location("sonnet_validate_pinned", VALIDATE_PATH)
    if spec is None or spec.loader is None:
        raise ImportError("cannot load pinned sonnet_validate.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    _validator = module
    return module


def _phone_stem(phone: str) -> str:
    return phone[:-1] if phone[-1:] in {"0", "1", "2"} else phone


def _syllable_count(phones: list[str]) -> int:
    return sum(_phone_stem(p) in VOWELS and p[-1:] in {"0", "1", "2"} for p in phones)


def _rhyme_key(phones: list[str]) -> str:
    last_stress = None
    last_vowel = None
    for i, phone in enumerate(phones):
        stem = _phone_stem(phone)
        if stem not in VOWELS:
            continue
        last_vowel = i
        if phone[-1:] in {"1", "2"}:
            last_stress = i
    start = last_stress if last_stress is not None else last_vowel
    if start is None:
        return ""
    return " ".join(_phone_stem(p) for p in phones[start:])


def _build_indexes() -> tuple[dict[str, int], dict[str, str]]:
    global _lexicon, _rhyme_keys
    if _lexicon is not None and _rhyme_keys is not None:
        return _lexicon, _rhyme_keys
    validator = load_validator()
    lexicon = validator.read_lexicon(CMUDICT_PATH)
    rhyme_keys: dict[str, str] = {}
    for line in CMUDICT_PATH.read_text(encoding="utf-8").splitlines():
        fields = line.split("#", 1)[0].split()
        if not fields or fields[0].startswith(";;;"):
            continue
        word = re.sub(r"\(\d+\)$", "", fields[0]).lower()
        if not WORD_RE.fullmatch(word):
            continue
        phones = fields[1:]
        if _syllable_count(phones) != lexicon.get(word):
            continue
        key = _rhyme_key(phones)
        if key:
            rhyme_keys[word] = key
    _lexicon = lexicon
    _rhyme_keys = rhyme_keys
    return lexicon, rhyme_keys


def did_letters(did: str) -> set[str]:
    return {ch for ch in did.lower() if "a" <= ch <= "z"}


def valid_words(
    did: str,
    syllables_remaining: int,
    rhyme_hint: str | None = None,
    *,
    limit: int = 80,
) -> list[dict]:
    """Words that pass upstream validate_word() and fit the remaining syllable budget.

    rhyme_hint may be a dictionary word (matched by its rhyme key) or a CMUdict
    rhyme key such as ``EY T``. Empty/None skips the rhyme filter.
    """
    if syllables_remaining < 1:
        return []
    validator = load_validator()
    lexicon, rhyme_keys = _build_indexes()
    hint_key = None
    if rhyme_hint:
        hint = rhyme_hint.strip()
        hint_key = rhyme_keys.get(hint.lower()) or (hint.upper() if hint else None)

    allowed = did_letters(did)
    matches: list[dict] = []
    for word, count in lexicon.items():
        if count > syllables_remaining:
            continue
        letters = {ch for ch in word if "a" <= ch <= "z"}
        if letters - allowed:
            continue
        if hint_key:
            if rhyme_keys.get(word) != hint_key:
                continue
        try:
            validated = validator.validate_word(word, did, lexicon)
        except ValueError:
            continue
        if validated != count:
            continue
        matches.append(
            {
                "word": word,
                "syllables": count,
                "rhyme_key": rhyme_keys.get(word, ""),
                "fills_line": count == syllables_remaining,
            }
        )

    matches.sort(key=lambda item: (item["syllables"], item["word"]))
    if limit and len(matches) > limit:
        return matches[:limit]
    return matches


def auto_pick(
    did: str,
    syllables_remaining: int,
    rhyme_hint: str | None = None,
    *,
    close_line: bool = False,
) -> str | None:
    """Pick one locally valid token. Prefer a word that exactly fills the line."""
    validator = load_validator()
    lexicon, _unused_rhyme = _build_indexes()
    common = (
        "a", "the", "and", "in", "we", "is", "as", "at", "an", "it", "be", "by",
        "my", "me", "she", "he", "his", "her", "that", "this", "will", "can",
        "still", "night", "light", "heart", "said", "yes", "when", "then",
        "all", "any", "each", "such", "than", "them", "these", "those",
    )
    common_hits = []
    for word in common:
        try:
            count = validator.validate_word(word, did, lexicon)
        except ValueError:
            continue
        if 1 <= count <= syllables_remaining:
            common_hits.append({"word": word, "syllables": count, "fills_line": count == syllables_remaining})

    hint = rhyme_hint if (close_line or syllables_remaining <= 2) else None
    candidates = []
    if close_line or not common_hits:
        candidates = valid_words(did, syllables_remaining, hint, limit=400)
        if not candidates and hint:
            candidates = valid_words(did, syllables_remaining, None, limit=400)

    preferred_fill = [item for item in (common_hits + candidates) if item["fills_line"]] if close_line else []
    pool = preferred_fill or common_hits or candidates
    if not pool:
        return None
    token = pool[0]["word"]
    if pool[0]["fills_line"]:
        token = f"{token}."
    validator.validate_word(token, did, lexicon)
    return token
