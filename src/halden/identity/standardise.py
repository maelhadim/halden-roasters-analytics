"""Turn the many ways a customer types the same thing into one comparable value.

Every function keeps the raw value untouched elsewhere; these only build match keys.
"""
from __future__ import annotations

import re
import unicodedata

# Letters that Unicode decomposition does not reduce to ASCII, or reduces wrongly for German.
_FOLD = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "ł": "l", "ı": "i", "ø": "o", "æ": "ae"})

# Common short forms, grouped by the formal name. I wrote this list from general knowledge of
# English, German, Dutch and Irish names; a production system would use a maintained list.
_NICK_GROUPS = [
    ("william", "will", "bill", "billy", "liam"), ("robert", "rob", "bob", "bobby", "robbie"),
    ("elizabeth", "liz", "lizzie", "beth", "eliza"), ("katherine", "kate", "katie", "kathy"),
    ("catherine", "cathy", "cath", "kate"), ("jonathan", "jon", "jonny"), ("michael", "mike", "mick", "mickey"),
    ("thomas", "tom", "tommy"), ("daniel", "dan", "danny"), ("matthew", "matt"), ("christopher", "chris"),
    ("christian", "chris"), ("alexander", "alex", "sandy"), ("alexandra", "alex", "sandra"),
    ("samuel", "sam", "sammy"), ("samantha", "sam"), ("joseph", "joe", "joey"), ("rebecca", "becky", "becca"),
    ("richard", "rich", "rick", "dick"), ("james", "jim", "jimmy", "jamie"), ("anthony", "tony"),
    ("edward", "ed", "eddie", "ted"), ("margaret", "maggie", "peggy", "meg"), ("patrick", "paddy", "pat"),
    ("patricia", "pat", "trish"), ("siobhan", "shiv"), ("seamus", "shay"), ("benjamin", "ben"),
    ("nicholas", "nick"), ("andrew", "andy", "drew"), ("jennifer", "jen", "jenny"), ("susan", "sue", "susie"),
    ("katharina", "kathi", "katja"), ("maximilian", "max"), ("stefanie", "steffi"), ("wolfgang", "wolf"),
    ("margarete", "grete"), ("johanna", "hanna", "hannah"), ("johannes", "jan", "hans"),
    ("jacobus", "koos", "jaap"), ("cornelis", "kees"), ("wilhelmina", "mien", "willemijn"),
    ("hendrik", "henk"), ("gerardus", "gerard", "gert"), ("franziska", "franzi"), ("friedrich", "fritz"),
]
NICKNAMES: dict[str, str] = {}
for group in _NICK_GROUPS:
    for name in group:
        NICKNAMES.setdefault(name, group[0])

COUNTRY_DIAL = {"GB": "44", "IE": "353", "DE": "49", "NL": "31"}
_GMAIL = {"gmail.com", "googlemail.com"}


def fold(s: str | None) -> str:
    """Lower case, umlauts written out, accents and punctuation removed, single spaces."""
    if not isinstance(s, str) or not s:   # pandas hands over NaN, not None, for a missing value
        return ""
    s = s.strip().lower().translate(_FOLD)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-z ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def first_name_key(first: str | None) -> tuple[str, str, bool]:
    """(folded first given name, its formal form, is an initial only)."""
    f = fold(first)
    first_token = f.split(" ")[0] if f else ""
    is_initial = len(first_token) == 1
    return first_token, NICKNAMES.get(first_token, first_token), is_initial


def email_key(email: str | None) -> str:
    """One key per mailbox: case and spaces ignored, and gmail's dots and +tags removed,
    because gmail delivers all of those to the same inbox."""
    if not isinstance(email, str) or "@" not in email:
        return ""
    local, domain = email.strip().lower().rsplit("@", 1)
    local = local.split("+", 1)[0]
    if domain in _GMAIL:
        local, domain = local.replace(".", ""), "gmail.com"
    return f"{local}@{domain}"


def phone_key(phone: str | None, country: str | None) -> str:
    """International digits without the trunk 0, e.g. '+44(0)161 496 0054' -> '441614960054'.

    Extensions are dropped. A number in Excel's scientific notation has lost digits and
    gives no key, because two different numbers can look the same once rounded.
    """
    if not isinstance(phone, str) or re.fullmatch(r"\d\.\d+E\+\d+", phone.strip()):
        return ""
    p = re.split(r"x|ext", phone.lower())[0]
    intl = p.strip().startswith(("+", "00"))
    p = re.sub(r"\(0\)", "", p)
    digits = re.sub(r"\D", "", p)
    if p.strip().startswith("00"):
        digits = digits[2:]
    if intl:
        return digits
    dial = COUNTRY_DIAL.get(country or "", "")
    if digits.startswith("0") and dial:
        return dial + digits[1:]
    return dial + digits if dial and len(digits) >= 9 else digits


def postcode_key(pc: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", pc.upper()) if isinstance(pc, str) else ""


def street_key(street: str | None) -> str:
    return fold(street)
