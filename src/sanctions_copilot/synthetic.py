"""Synthetic customer book: SDV for realistic attribute structure, Faker for PII, planted list hits for labels.

Why both tools
- SDV (GaussianCopulaSynthesizer) learns the *joint distribution* of customer attributes: segment, country,
  age, turnover, PEP flag, risk rating. In a real engagement you fit it on the bank's masked customer table;
  here it is fitted on a seed table built from documented rules (FATF lists, segment economics), so the
  correlations are explicit and reviewable.
- Faker fills in the PII SDV should never learn from real data: names consistent with the sampled country,
  dates of birth consistent with the sampled age, passport-style identifiers and company names.
- Planted cases turn the book into a labelled test set: true matches built from real list entries with the
  perturbations seen in production (aliases, transliteration, name order, typos, dropped middle names,
  transposed or partial DOBs), and near-misses (same name, different generation) that should be cleared.

The output never contains real customers. Planted rows reuse public sanctions-list data only.
"""

from __future__ import annotations

import csv
import json
import random
import re
from dataclasses import dataclass
from datetime import date, timedelta
from importlib import resources
from pathlib import Path
from typing import Optional

from unidecode import unidecode

from .models import PartyType, WatchlistEntry
from .normalize import normalize_country, parse_dob

CUSTOMER_COLUMNS = ["customer_id", "name", "party_type", "dob", "country", "nationality", "id_numbers",
                    "segment", "industry", "pep", "risk_rating", "annual_turnover_usd", "customer_since"]
LABEL_COLUMNS = ["customer_id", "label", "list_uid", "method"]

# (iso2, weight, name generator key). Weights sketch an international bank's client mix.
COUNTRY_MIX = [
    ("us", 26, "en_US"), ("gb", 10, "en_GB"), ("de", 4, "de_DE"), ("fr", 4, "fr_FR"), ("es", 3, "es_ES"),
    ("it", 2, "it_IT"), ("nl", 2, "nl_NL"), ("mx", 4, "es_MX"), ("co", 2, "es_CO"), ("br", 3, "pt_BR"),
    ("ve", 1, "es_CO"), ("in", 6, "en_IN"), ("cn", 4, "zh_CN"), ("hk", 2, "zh_TW"), ("kr", 2, "ko"),
    ("jp", 2, "ja_JP"), ("vn", 1, "vi_VN"), ("ru", 2, "ru_RU"), ("ua", 2, "uk_UA"), ("tr", 2, "tr_TR"),
    ("bg", 1, "bg_BG"), ("ae", 3, "arabic"), ("sa", 1, "arabic"), ("eg", 1, "arabic"), ("jo", 1, "arabic"),
    ("lb", 1, "arabic"), ("iq", 0.6, "arabic"), ("sy", 0.3, "arabic"), ("kw", 0.5, "arabic"), ("pk", 1, "arabic"),
    ("ir", 0.3, "persian"), ("ng", 2, "en_NG"), ("ke", 1, "en_KE"), ("ph", 1, "en_US"), ("id", 1, "id_ID"),
]

ARABIC_GIVEN = ["Mohammed", "Muhammad", "Ahmed", "Ali", "Omar", "Hassan", "Hussein", "Khalid", "Youssef", "Ibrahim",
                "Abdullah", "Mahmoud", "Mustafa", "Tariq", "Karim", "Samir", "Walid", "Nabil", "Faisal", "Hamza",
                "Fatima", "Aisha", "Mariam", "Layla", "Noura", "Huda", "Rania", "Salma", "Yasmin", "Zainab", "Imran",
                "Bilal", "Usman", "Saad", "Rashid", "Jamal", "Adnan", "Nasser", "Majid", "Ziad"]
ARABIC_FAMILY = ["Al-Hassan", "Haddad", "Khoury", "Al-Masri", "Nasser", "Saleh", "Hamdan", "Al-Sayed", "Mansour",
                 "Aziz", "Farouk", "Qureshi", "Khan", "Siddiqui", "Al-Amin", "Rahman", "Abbas", "Yousef", "Darwish",
                 "Al-Tamimi", "Suleiman", "Barakat", "Hijazi", "Al-Najjar", "Shaikh", "Malik", "Chaudhry", "Awad",
                 "Al-Khatib", "Jaber", "Issa", "Hamad", "Al-Zahrani", "Al-Harbi", "Karam", "Fakhoury"]
PERSIAN_GIVEN = ["Reza", "Ali", "Mohammad", "Hossein", "Mehdi", "Amir", "Farhad", "Saeed", "Behnam", "Kaveh",
                 "Maryam", "Zahra", "Fatemeh", "Leila", "Shirin", "Neda", "Parisa", "Sara", "Arash", "Dariush"]
PERSIAN_FAMILY = ["Hosseini", "Mohammadi", "Rezaei", "Ahmadi", "Karimi", "Moradi", "Jafari", "Tehrani", "Rahimi",
                  "Kazemi", "Sadeghi", "Ebrahimi", "Najafi", "Shirazi", "Esfahani", "Ghorbani", "Heydari", "Azizi"]

TRANSLIT = [("mohammed", "muhammad"), ("muhammad", "mohamed"), ("mohamed", "mohammad"), ("yusuf", "youssef"),
            ("youssef", "yousef"), ("aleksandr", "alexander"), ("alexander", "aleksandr"), ("dmitriy", "dmitri"),
            ("dmitry", "dmitri"), ("sergey", "sergei"), ("sergei", "sergey"), ("yevgeniy", "evgeny"), ("hussein", "husain"),
            ("hossein", "hussein"), ("abdul", "abd al"), ("abd al", "abdul"), ("ou", "u"), ("kh", "h"), ("iy", "y"),
            ("ei", "ey"), ("ch", "tch"), ("j", "dj"), ("q", "k"), ("ph", "f")]

SEGMENTS = ["retail", "private_banking", "sme", "corporate"]
HIGH_RISK_INDUSTRIES = ["money_services", "precious_metals", "shipping", "arms_dual_use", "crypto_exchange", "oil_trading"]
INDUSTRIES = ["manufacturing", "retail_trade", "technology", "real_estate", "healthcare", "logistics",
              "professional_services", "construction", "hospitality", "agriculture", *HIGH_RISK_INDUSTRIES]
LEGAL_FORM = {"us": "LLC", "gb": "Ltd", "de": "GmbH", "fr": "SAS", "es": "S.L.", "it": "S.r.l.", "nl": "B.V.",
              "mx": "S.A. de C.V.", "co": "S.A.S.", "br": "Ltda", "ve": "C.A.", "in": "Pvt Ltd", "cn": "Co., Ltd.",
              "hk": "Limited", "kr": "Co., Ltd.", "jp": "K.K.", "vn": "JSC", "ru": "OOO", "ua": "TOV", "tr": "A.S.",
              "bg": "EOOD", "ae": "FZE", "sa": "LLC", "eg": "S.A.E.", "jo": "LLC", "lb": "SAL", "iq": "LLC",
              "sy": "LLC", "kw": "WLL", "pk": "Pvt Ltd", "ir": "PJS", "ng": "Ltd", "ke": "Ltd", "ph": "Inc.", "id": "PT"}


def fatf_lists() -> dict:
    return json.loads(resources.files("sanctions_copilot.data").joinpath("fatf_lists.json").read_text(encoding="utf-8"))


@dataclass
class GenerationReport:
    customers: int
    planted_true_matches: int
    planted_near_misses: int
    method: str
    sdv_quality_score: Optional[float]
    seed_rows: int
    list_source: str
    path: str


# ----------------------------------------------------------------------------------------------
# Step 1: attribute structure (seed rules -> SDV)
# ----------------------------------------------------------------------------------------------

def build_seed(n: int, rng: random.Random) -> list[dict]:
    """Rule-based seed table. Each rule is a documented assumption a bank's own data would replace."""
    fatf = fatf_lists()
    black, grey = set(fatf["call_for_action"]), set(fatf["increased_monitoring"])
    countries = [c for c, _, _ in COUNTRY_MIX]
    weights = [w for _, w, _ in COUNTRY_MIX]
    rows = []
    for _ in range(n):
        country = rng.choices(countries, weights)[0]
        is_entity = rng.random() < 0.22
        segment = rng.choices(["sme", "corporate"], [0.75, 0.25])[0] if is_entity else \
            rng.choices(["retail", "private_banking"], [0.93, 0.07])[0]
        age = 0 if is_entity else int(min(92, max(18, rng.gauss(46 if segment == "retail" else 58, 14))))
        base = {"retail": 55_000, "private_banking": 2_500_000, "sme": 1_200_000, "corporate": 40_000_000}[segment]
        turnover = round(base * rng.lognormvariate(0, 0.8), -2)
        industry = rng.choice(INDUSTRIES) if is_entity else "n/a"
        pep = (not is_entity) and rng.random() < (0.04 if segment == "private_banking" else 0.004)
        score = 0
        score += 3 if country in black else 2 if country in grey else 0
        score += 2 if pep else 0
        score += 2 if industry in HIGH_RISK_INDUSTRIES else 0
        score += 1 if segment == "private_banking" else 0
        score += 1 if rng.random() < 0.08 else 0  # adverse media / unexplained noise
        risk = "high" if score >= 3 else "medium" if score >= 1 else "low"
        rows.append({
            "customer_type": "entity" if is_entity else "individual", "segment": segment, "country": country,
            "age": age, "annual_turnover_usd": turnover, "industry": industry, "pep": bool(pep),
            "risk_rating": risk, "tenure_years": round(min(40, rng.expovariate(1 / 6)), 1),
        })
    return rows


def _fit_sample(rows: list[dict], n: int, numeric: list[str], categorical: list[str], boolean: list[str]):
    import math

    import pandas as pd
    from sdv.metadata import Metadata
    from sdv.single_table import GaussianCopulaSynthesizer

    df = pd.DataFrame(rows)
    df["log_turnover"] = df.pop("annual_turnover_usd").map(lambda v: math.log(max(v, 1.0)))
    md = Metadata.detect_from_dataframe(data=df, table_name="t")
    for col in [*numeric, "log_turnover"]:
        md.update_column(column_name=col, sdtype="numerical", table_name="t")
    for col in categorical:
        md.update_column(column_name=col, sdtype="categorical", table_name="t")
    for col in boolean:
        md.update_column(column_name=col, sdtype="boolean", table_name="t")
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        synth = GaussianCopulaSynthesizer(md, enforce_min_max_values=True, default_distribution="truncnorm")
        synth.fit(df)
    out = synth.sample(num_rows=n)
    quality = None
    try:
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from sdv.evaluation.single_table import evaluate_quality

            quality = float(evaluate_quality(df, out, md, verbose=False).get_score())
    except Exception:
        pass
    out["annual_turnover_usd"] = out.pop("log_turnover").map(lambda v: round(math.exp(v), -2))
    return out.to_dict(orient="records"), quality


def sample_attributes(n: int, rng: random.Random, use_sdv: bool = True, seed_rows: int = 3000) -> tuple[list[dict], str, Optional[float]]:
    """Individuals and entities are modelled separately: their attributes follow different distributions,
    and a single copula over both produces impossible mixtures (e.g. 18-year-old corporates)."""
    seed = build_seed(seed_rows, rng)
    if use_sdv:
        try:
            import sdv  # noqa: F401
        except ImportError:
            use_sdv = False
    if not use_sdv:
        return build_seed(n, rng), "rules-only (install sdv for learned distributions)", None

    ind = [{k: r[k] for k in ("segment", "country", "age", "annual_turnover_usd", "pep", "risk_rating", "tenure_years")}
           for r in seed if r["customer_type"] == "individual"]
    ent = [{k: r[k] for k in ("segment", "country", "industry", "annual_turnover_usd", "risk_rating", "tenure_years")}
           for r in seed if r["customer_type"] == "entity"]
    n_ent = round(n * len(ent) / len(seed))
    rows_i, q_i = _fit_sample(ind, n - n_ent, ["age", "tenure_years"], ["segment", "country", "risk_rating"], ["pep"])
    rows_e, q_e = _fit_sample(ent, n_ent, ["tenure_years"], ["segment", "country", "industry", "risk_rating"], [])
    for r in rows_i:
        r.update(customer_type="individual", industry="n/a", age=int(min(95, max(18, round(r["age"])))))
    for r in rows_e:
        r.update(customer_type="entity", pep=False, age=0)
    rows = rows_i + rows_e
    rng.shuffle(rows)
    qs = [q for q in (q_i, q_e) if q is not None]
    return rows, "sdv-gaussian-copula (individuals + entities)", round(sum(qs) / len(qs), 3) if qs else None


# ----------------------------------------------------------------------------------------------
# Step 2: PII with Faker
# ----------------------------------------------------------------------------------------------

class NameFactory:
    def __init__(self, seed: int):
        from faker import Faker

        self._fakers: dict[str, "Faker"] = {}
        self._Faker = Faker
        self.seed = seed
        self.rng = random.Random(seed)

    def _f(self, loc: str):
        if loc not in self._fakers:
            f = self._Faker(loc)
            f.seed_instance(self.seed + len(self._fakers))
            self._fakers[loc] = f
        return self._fakers[loc]

    def person(self, key: str) -> str:
        r = self.rng
        if key == "arabic":
            given = r.choice(ARABIC_GIVEN)
            middle = f" {r.choice(ARABIC_GIVEN)}" if r.random() < 0.35 else ""
            return f"{given}{middle} {r.choice(ARABIC_FAMILY)}"
        if key == "persian":
            return f"{r.choice(PERSIAN_GIVEN)} {r.choice(PERSIAN_FAMILY)}"
        if key == "ko":
            f = self._f("ko_KR")
            fam = unidecode(f.last_name()).strip().title()
            given = unidecode(f.first_name()).strip().title()
            return f"{fam} {given}" if r.random() < 0.5 else f"{given} {fam}"
        f = self._f(key)
        if key in ("zh_CN", "zh_TW", "ja_JP") and hasattr(f, "last_romanized_name"):
            fam, given = f.last_romanized_name().title(), f.first_romanized_name().title()
            return f"{fam} {given}" if r.random() < 0.5 else f"{given} {fam}"
        name = f"{f.first_name()} {f.last_name()}"
        if key == "ru_RU" and r.random() < 0.3 and hasattr(f, "middle_name"):
            name = f"{f.first_name()} {f.middle_name()} {f.last_name()}"
        return unidecode(name).strip()

    def company(self, key: str, country: str) -> str:
        loc = {"arabic": "en_US", "persian": "en_US", "ko": "en_US", "zh_CN": "en_US", "zh_TW": "en_US",
               "ja_JP": "en_US", "ru_RU": "en_US", "uk_UA": "en_US", "bg_BG": "en_US"}.get(key, key)
        base = unidecode(self._f(loc).company())
        base = re.sub(r"\b(LLC|Ltd|Inc|PLC|GmbH|S\.?A\.?|Group|and Sons|& Co)\b\.?", "", base, flags=re.I)
        base = re.sub(r"[,\s]+$", "", re.sub(r"\s+", " ", base)).strip(" ,-")
        if key == "arabic" and self.rng.random() < 0.6:
            base = f"{self.rng.choice(['Al', 'Dar', 'Bayt'])} {self.rng.choice(ARABIC_FAMILY).replace('Al-', '')} {self.rng.choice(['Trading', 'General Trading', 'Contracting', 'Investments', 'Exchange'])}"
        return f"{base} {LEGAL_FORM.get(country, 'Ltd')}".strip()

    def passport(self, country: str) -> str:
        r = self.rng
        return f"{country.upper()}{r.choice('ABCDEFGHJKLMNPRSTUVWXYZ')}{r.randint(1000000, 9999999)}"


# ----------------------------------------------------------------------------------------------
# Step 3: planted true matches and near-misses from the live watchlist
# ----------------------------------------------------------------------------------------------

def display_name(listed: str) -> str:
    if "," in listed:
        last, first = [x.strip() for x in listed.split(",", 1)]
        listed = f"{first} {last}"
    return listed.title() if listed.isupper() else listed


def perturb_name(name: str, method: str, rng: random.Random) -> str:
    toks = name.split()
    if method == "order_swap" and len(toks) >= 2:
        return " ".join(reversed(toks))
    if method == "drop_middle" and len(toks) >= 3:
        return " ".join([toks[0], toks[-1]])
    if method == "typo":
        idx = [i for i, t in enumerate(toks) if len(t) >= 5]
        if idx:
            i = rng.choice(idx)
            t = toks[i]
            j = rng.randint(1, len(t) - 2)
            op = rng.choice(["swap", "drop", "double"])
            t = t[:j] + t[j + 1] + t[j] + t[j + 2:] if op == "swap" else t[:j] + t[j + 1:] if op == "drop" else t[:j] + t[j] + t[j:]
            toks[i] = t
            return " ".join(toks)
    if method == "translit":
        low = name.lower()
        for a, b in TRANSLIT:
            if a in low:
                return re.sub(a, b, low, count=1).title()
    return name


def _dob_variant(entry: WatchlistEntry, rng: random.Random) -> tuple[Optional[str], str]:
    parsed = [d for d in (parse_dob(x) for x in entry.dobs) if d]
    if not parsed:
        return None, "no_dob"
    d = rng.choice(parsed)
    roll = rng.random()
    if d.exact and roll < 0.55:
        return d.exact.isoformat(), "dob_exact"
    if d.exact and roll < 0.65 and d.exact.day <= 12 and d.exact.day != d.exact.month:
        return f"{d.exact.month:02d}/{d.exact.day:02d}/{d.exact.year}", "dob_transposed"  # read back as DD/MM
    if roll < 0.9:
        return str(rng.randint(d.year_min, d.year_max)), "dob_year_only"
    return None, "dob_missing"


def _strong_aliases(entry: WatchlistEntry) -> list[str]:
    """Aliases with at least two meaningful name parts. Single-token/kunya-style 'weak' aliases (e.g. 'Abu Khalil')
    are excluded, in line with OFAC guidance that weak AKAs are not expected to be screened on their own."""
    from .normalize import normalize_name

    return [a for a in entry.aliases if len(normalize_name(a).core_tokens) >= 2]


def plant_true_match(entry: WatchlistEntry, rng: random.Random) -> tuple[dict, str]:
    strong = _strong_aliases(entry)
    use_alias = bool(strong) and rng.random() < 0.3
    base = display_name(rng.choice(strong) if use_alias else entry.name)
    method = rng.choice(["exact", "order_swap", "typo", "drop_middle", "translit"])
    name = perturb_name(base, method, rng)
    dob, dob_method = (None, "n/a") if entry.party_type != PartyType.individual else _dob_variant(entry, rng)
    country = normalize_country(entry.countries[0]) if entry.countries and rng.random() < 0.7 else None
    ids = [rng.choice(entry.id_numbers)] if entry.id_numbers and rng.random() < 0.2 else []
    row = {"name": name, "party_type": entry.party_type.value if entry.party_type != PartyType.aircraft else "entity",
           "dob": dob or "", "country": (country or "").upper(), "nationality": (country or "").upper(),
           "id_numbers": ";".join(ids)}
    return row, f"{'alias+' if use_alias else ''}{method}/{dob_method}{'/id' if ids else ''}"


def plant_near_miss(entry: WatchlistEntry, rng: random.Random, today: date) -> Optional[tuple[dict, str]]:
    parsed = [d for d in (parse_dob(x) for x in entry.dobs) if d]
    if entry.party_type != PartyType.individual or not parsed:
        return None
    year = parsed[0].year_min
    options = [y for y in range(1935, today.year - 18) if abs(y - year) >= 15]
    if not options:
        return None
    y = rng.choice(options)
    dob = date(y, rng.randint(1, 12), rng.randint(1, 28)).isoformat()
    name = display_name(entry.name)
    if rng.random() < 0.3:
        name = perturb_name(name, "translit", rng)
    country = rng.choice(["us", "gb", "de", "ca", "au", "fr", "es"])
    return ({"name": name, "party_type": "individual", "dob": dob, "country": country.upper(),
             "nationality": country.upper(), "id_numbers": ""}, f"same_name_dob_gap_{abs(y - year)}y")


# ----------------------------------------------------------------------------------------------
# Orchestration
# ----------------------------------------------------------------------------------------------

def generate(n: int, watchlist_entries: list[WatchlistEntry], out_dir: str | Path, seed: int = 42,
             use_sdv: bool = True, true_match_rate: float = 0.01, near_miss_rate: float = 0.01,
             list_source: str = "") -> GenerationReport:
    rng = random.Random(seed)
    today = date.today()
    attrs, method, quality = sample_attributes(n, rng, use_sdv=use_sdv)
    names = NameFactory(seed)
    key_by_country = {c: k for c, _, k in COUNTRY_MIX}
    customers, labels = [], []
    for i, a in enumerate(attrs, start=1):
        country = a["country"]
        key = key_by_country.get(country, "en_US")
        is_entity = a["customer_type"] == "entity"
        dob = "" if is_entity else (today - timedelta(days=int(a["age"]) * 365 + rng.randint(0, 364))).isoformat()
        nationality = country if rng.random() < 0.88 else rng.choice([c for c, _, _ in COUNTRY_MIX])
        customers.append({
            "customer_id": f"CUST-{i:06d}",
            "name": names.company(key, country) if is_entity else names.person(key),
            "party_type": "entity" if is_entity else "individual",
            "dob": dob, "country": country.upper(), "nationality": "" if is_entity else nationality.upper(),
            "id_numbers": "" if is_entity else names.passport(nationality),
            "segment": a["segment"], "industry": a["industry"], "pep": str(bool(a["pep"])).lower(),
            "risk_rating": a["risk_rating"], "annual_turnover_usd": int(a["annual_turnover_usd"] or 0),
            "customer_since": (today - timedelta(days=int(float(a["tenure_years"] or 0) * 365))).isoformat(),
        })
        labels.append({"customer_id": f"CUST-{i:06d}", "label": "none", "list_uid": "", "method": "faker"})

    # Plant labelled cases by overwriting identity fields of randomly chosen customers.
    pool = [e for e in watchlist_entries if len(e.name.split()) >= 2]
    individuals = [e for e in pool if e.party_type == PartyType.individual]
    n_tm = max(5, int(n * true_match_rate)) if pool else 0
    n_nm = max(5, int(n * near_miss_rate)) if individuals else 0
    slots = rng.sample(range(n), min(n, n_tm + n_nm))
    planted_tm = planted_nm = 0
    for j, slot in enumerate(slots):
        if j < n_tm:
            e = rng.choice(individuals if individuals and rng.random() < 0.75 else pool)
            row, how = plant_true_match(e, rng)
            label = "true_match"
            planted_tm += 1
        else:
            e = rng.choice(individuals)
            res = plant_near_miss(e, rng, today)
            if not res:
                continue
            row, how = res
            label = "near_miss"
            planted_nm += 1
        c = customers[slot]
        c.update(row)
        if row["party_type"] == "entity":
            c.update({"segment": "corporate", "industry": "shipping" if e.party_type == PartyType.vessel else c["industry"] if c["industry"] != "n/a" else "trading"})
        labels[slot] = {"customer_id": c["customer_id"], "label": label, "list_uid": e.uid, "method": how}

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    _write(out / "customers.csv", CUSTOMER_COLUMNS, customers)
    _write(out / "customers_labels.csv", LABEL_COLUMNS, labels)
    rep = GenerationReport(customers=n, planted_true_matches=planted_tm, planted_near_misses=planted_nm, method=method,
                           sdv_quality_score=quality, seed_rows=3000, list_source=list_source, path=str(out / "customers.csv"))
    (out / "generation_report.json").write_text(json.dumps(rep.__dict__, indent=2), encoding="utf-8")
    return rep


def _write(path: Path, cols: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def load_customers(path: str | Path) -> tuple[list[dict], dict[str, dict]]:
    path = Path(path)
    if not path.exists():
        return [], {}
    with path.open(newline="", encoding="utf-8") as fh:
        customers = list(csv.DictReader(fh))
    labels: dict[str, dict] = {}
    lp = path.with_name("customers_labels.csv")
    if lp.exists():
        with lp.open(newline="", encoding="utf-8") as fh:
            labels = {r["customer_id"]: r for r in csv.DictReader(fh)}
    return customers, labels
