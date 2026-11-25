"""People, and the ways the same person ends up looking different in our systems."""
from __future__ import annotations

import unicodedata

import numpy as np
from faker import Faker

from .config import COUNTRIES

EMAIL_DOMAINS = {
    "GB": ("gmail.com", "outlook.com", "btinternet.com", "yahoo.co.uk", "hotmail.co.uk"),
    "IE": ("gmail.com", "outlook.com", "eircom.net", "yahoo.ie"),
    "DE": ("gmail.com", "web.de", "gmx.de", "t-online.de", "outlook.de"),
    "NL": ("gmail.com", "ziggo.nl", "outlook.com", "kpnmail.nl", "hotmail.nl"),
}
# Faker's invented town names ("South Margarettown") give the data away at a glance, so
# cities come from a fixed list of real ones, weighted roughly by size. Streets and
# postcodes still come from Faker and do not match the city.
CITIES = {
    "GB": ("London", "Manchester", "Birmingham", "Leeds", "Glasgow", "Bristol", "Liverpool", "Sheffield",
           "Edinburgh", "Cardiff", "Nottingham", "Leicester", "Brighton", "Newcastle upon Tyne", "York",
           "Oxford", "Cambridge", "Bath", "Norwich", "Stockport"),
    "IE": ("Dublin", "Cork", "Galway", "Limerick", "Waterford", "Kilkenny", "Sligo", "Drogheda", "Athlone",
           "Wexford"),
    "DE": ("Berlin", "Hamburg", "München", "Köln", "Frankfurt am Main", "Stuttgart", "Düsseldorf", "Leipzig",
           "Dresden", "Bremen", "Hannover", "Nürnberg", "Münster", "Freiburg im Breisgau", "Mainz"),
    "NL": ("Amsterdam", "Rotterdam", "Den Haag", "Utrecht", "Eindhoven", "Groningen", "Haarlem", "Leiden",
           "Nijmegen", "Delft", "Zwolle", "Maastricht"),
}

# Germany has large Polish and Turkish communities. Their names use letters that
# Windows-1252 cannot store, which is exactly what breaks the fulfilment file.
DE_EXTRA_NAMES = (("Łukasz", "Wiśniewski"), ("Ayşe", "Yılmaz"), ("Małgorzata", "Kowalczyk"),
                  ("Çağlar", "Öztürk"), ("Bartłomiej", "Dąbrowski"), ("Gülşen", "Kaya"),
                  ("Paweł", "Nowak"), ("Tuğba", "Şahin"))
WORK_DOMAINS = ("northgate-consulting.example", "brightwell.example", "kade-logistiek.example",
                "rheinwerk-gruppe.example", "liffey-partners.example")

NICKNAMES = {
    "William": "Will", "Robert": "Rob", "Elizabeth": "Liz", "Katherine": "Kate", "Catherine": "Cathy",
    "Jonathan": "Jon", "Michael": "Mike", "Thomas": "Tom", "Daniel": "Dan", "Matthew": "Matt",
    "Christopher": "Chris", "Alexander": "Alex", "Samuel": "Sam", "Joseph": "Joe", "Rebecca": "Becky",
    "Katharina": "Kathi", "Maximilian": "Max", "Alexandra": "Alex",
    "Christian": "Chris", "Stefanie": "Steffi", "Wolfgang": "Wolf", "Margarete": "Grete",
    "Johanna": "Hanna", "Jacobus": "Koos", "Johannes": "Jan", "Cornelis": "Kees", "Wilhelmina": "Mien",
    "Patrick": "Paddy", "Margaret": "Peggy", "Siobhan": "Shiv", "Seamus": "Shay",
}


def ascii_fold(s: str) -> str:
    """How an email local part gets built from a name: umlauts written out, accents dropped."""
    s = s.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    s = s.replace("Ä", "Ae").replace("Ö", "Oe").replace("Ü", "Ue")
    s = s.replace("ł", "l").replace("Ł", "L").replace("ı", "i")
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    return "".join(ch for ch in s if ch.isalnum() or ch in ".-")


class PersonFactory:
    def __init__(self, rng: np.random.Generator, seed: int):
        self.rng = rng
        self.fakers = {}
        for i, c in enumerate(COUNTRIES):
            f = Faker(c.locale)
            f.seed_instance(seed + i)
            self.fakers[c.code] = f
        self.n = 0

    def new_person(self, country: str) -> dict:
        f = self.fakers[country]
        self.n += 1
        first = f.first_name()
        last = f.last_name()
        if country == "DE" and self.rng.random() < 0.015:
            first, last = DE_EXTRA_NAMES[int(self.rng.integers(len(DE_EXTRA_NAMES)))]
        domain = EMAIL_DOMAINS[country][self.rng.integers(len(EMAIL_DOMAINS[country]))]
        email = self._email(first, last, domain)
        return {
            "person_id": f"P{self.n:06d}",
            "country_code": country,
            "first_name": first,
            "last_name": last,
            "email": email,
            "phone": f.phone_number(),
            "street": f.street_address().replace("\n", ", "),
            "city": self.city(country),
            "postcode": f.postcode(),
        }

    def _email(self, first: str, last: str, domain: str) -> str:
        style = self.rng.integers(4)
        a, b = ascii_fold(first).lower(), ascii_fold(last).lower().replace(" ", "")
        if style == 0:
            local = f"{a}.{b}"
        elif style == 1:
            local = f"{a[0]}{b}"
        elif style == 2:
            local = f"{a}{b}{self.rng.integers(1, 99)}"
        else:
            local = f"{a}_{b}{self.rng.integers(60, 99)}"
        return f"{local}@{domain}"

    def other_email(self, person: dict, work: bool) -> str:
        """A second address for the same person: a work address, or a new personal one."""
        if work:
            domain = WORK_DOMAINS[self.rng.integers(len(WORK_DOMAINS))]
        else:
            options = EMAIL_DOMAINS[person["country_code"]]
            domain = options[self.rng.integers(len(options))]
        for _ in range(5):
            e = self._email(person["first_name"], person["last_name"], domain)
            if e != person["email"]:
                return e
        return f"{ascii_fold(person['first_name']).lower()}.{self.rng.integers(100, 999)}@{domain}"

    def new_address(self, country: str) -> dict:
        f = self.fakers[country]
        return {"street": f.street_address().replace("\n", ", "), "city": self.city(country),
                "postcode": f.postcode()}

    def city(self, country: str) -> str:
        names = CITIES[country]
        w = np.array([1 / (i + 1) ** 0.8 for i in range(len(names))])
        return names[int(self.rng.choice(len(names), p=w / w.sum()))]

    def name_variant(self, first: str, last: str) -> tuple[str, str, str]:
        """Return (first, last, kind): how a re-keyed or re-registered record spells the name."""
        options = []
        if first in NICKNAMES:
            options.append("nickname")
        if ascii_fold(last) != last or ascii_fold(first) != first:
            options.append("transliterated")
        if len(last) > 4:
            options.append("typo")
        options += ["case", "initial", "same"]
        kind = options[self.rng.integers(len(options))]
        if kind == "nickname":
            return NICKNAMES[first], last, kind
        if kind == "transliterated":
            fold = lambda s: s.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
            return fold(first), fold(last), kind
        if kind == "typo":
            i = int(self.rng.integers(1, len(last) - 2))
            return first, last[:i] + last[i + 1] + last[i] + last[i + 2:], kind
        if kind == "case":
            return first.upper(), last.upper(), kind
        if kind == "initial":
            return first[0] + ".", last, kind
        return first, last, kind

    def email_variant(self, email: str) -> str:
        """Same mailbox, typed differently: capitals, or a gmail dot."""
        local, domain = email.split("@")
        if domain == "gmail.com" and "." in local and self.rng.random() < 0.5:
            return local.replace(".", "", 1) + "@" + domain
        return local[:1].upper() + local[1:] + "@" + domain
