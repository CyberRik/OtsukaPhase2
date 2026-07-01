"""In-memory data store — the single source of truth for tools and front ends.

Loads the committed seed JSON once (module-level cache) and exposes small,
pure-Python query helpers. The four production tables (deals, sales_activities,
quotes, orders) mirror the real SPR schema (see Schema.md); reps/customers/
products/environments/playbook are supplementary reference data the SPR tables
reference. Everything downstream (scoring, tools, dashboard, chat) reads through
here, so the data model lives in exactly one place.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from typing import Literal

from senpai import config

_FILES = ["reps", "customers", "products", "environments", "playbook",
          "deals", "sales_activities", "quotes", "orders", "coaching_threads"]


@lru_cache(maxsize=1)
def _load() -> dict[str, list[dict]]:
    data: dict[str, list[dict]] = {}
    for name in _FILES:
        path = config.SEED_DIR / f"{name}.json"
        rows = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        # Overlay any runtime-ingested rows (daily reports, etc.) ON TOP of the
        # committed seed. The seed stays canonical/byte-stable; ingested rows live
        # in a separate gitignored dir and are demo-only (see config.INGESTED_DIR).
        over = config.INGESTED_DIR / f"{name}.json"
        if over.exists():
            extra = json.loads(over.read_text(encoding="utf-8"))
            if isinstance(extra, list):
                rows = rows + extra
        data[name] = rows
    return data


def append_activity(record: dict) -> None:
    """Persist one ingested sales_activity to the gitignored overlay file, then
    drop the cache so the next read includes it. Never touches the committed seed.
    Build records with senpai.ingestion.persist.build_activity_record so the shape
    matches the seed exactly."""
    config.INGESTED_DIR.mkdir(parents=True, exist_ok=True)
    path = config.INGESTED_DIR / "sales_activities.json"
    rows = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    rows.append(record)
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    reload()


def next_employee_id() -> str:
    """The next free employee id (R01, R02, … → R25). Ids are 'R' + a number."""
    nums = [int(re.sub(r"\D", "", r["employee_id"]) or 0) for r in all_reps()]
    return f"R{(max(nums) + 1) if nums else 1:02d}"


def append_rep(record: dict) -> None:
    """Persist one new rep (a signup) to the gitignored overlay, then drop the
    cache so the next read includes it. Never touches the committed seed — same
    additive-overlay pattern as append_activity. `record` must match the seed rep
    shape (employee_id, name, role, department, division, specialty_tags,
    is_top_performer) plus the optional reports_to link."""
    config.INGESTED_DIR.mkdir(parents=True, exist_ok=True)
    path = config.INGESTED_DIR / "reps.json"
    rows = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    rows.append(record)
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    reload()


@lru_cache(maxsize=1)
def customer_aliases() -> dict[str, list[str]]:
    """English / romaji / known-alias forms per customer_id (customer_aliases.json).
    Keys starting with '_' (e.g. '_comment') are metadata and skipped."""
    path = config.SEED_DIR / "customer_aliases.json"
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {k: v for k, v in raw.items() if not k.startswith("_") and isinstance(v, list)}


def reload() -> None:
    """Drop the cache (used by tests / after regenerating seed)."""
    _load.cache_clear()
    _index.cache_clear()
    customer_aliases.cache_clear()
    _alias_index.cache_clear()


# --- indexes ---------------------------------------------------------------
# The relational accessors below (activities_for_deal, quote_for_deal, …) used to
# linear-scan the full table on every call. Hot paths like coach.cases call them
# tens of thousands of times → O(rows × calls). Build the lookups ONCE here,
# memoized against the loaded store and dropped on reload(), so each accessor is
# an O(1) dict hit. Pure performance — identical results.
@lru_cache(maxsize=1)
def _index() -> dict:
    acts_by_deal: dict[str, list[dict]] = {}
    for a in all_activities():
        did = a.get("deal_id")
        if did is not None:
            acts_by_deal.setdefault(did, []).append(a)
    for rows in acts_by_deal.values():
        rows.sort(key=lambda a: a.get("activity_date", ""), reverse=True)

    orders_by_cust: dict[str, list[dict]] = {}
    for o in all_orders():
        orders_by_cust.setdefault(o.get("customer_id"), []).append(o)
    for rows in orders_by_cust.values():
        rows.sort(key=lambda o: o.get("ordered_at", ""), reverse=True)

    quotes_by_cust: dict[str, list[dict]] = {}
    for q in all_quotes():
        quotes_by_cust.setdefault(q.get("customer_id"), []).append(q)
    for rows in quotes_by_cust.values():
        rows.sort(key=lambda q: q.get("quoted_at", ""), reverse=True)

    deals_by_cust: dict[str, list[dict]] = {}
    deals_by_rep: dict[str, list[dict]] = {}
    for d in all_deals():
        deals_by_cust.setdefault(d.get("customer_id"), []).append(d)
        deals_by_rep.setdefault(deal_rep_id(d), []).append(d)

    return {
        "acts_by_deal": acts_by_deal,
        "orders_by_cust": orders_by_cust,
        "quotes_by_cust": quotes_by_cust,
        "deals_by_cust": deals_by_cust,
        "deals_by_rep": deals_by_rep,
        "deal_by_id": {d["deal_id"]: d for d in all_deals()},
        "customer_by_id": {c["customer_id"]: c for c in all_customers()},
        "rep_by_id": {r["employee_id"]: r for r in all_reps()},
        "product_by_id": {p["product_code"]: p for p in all_products()},
        "quote_by_id": {q["quote_id"]: q for q in all_quotes()},
        "order_by_id": {o["order_id"]: o for o in all_orders()},
    }


# --- collections -----------------------------------------------------------
def all_deals() -> list[dict]:
    return _load()["deals"]


def all_reps() -> list[dict]:
    return _load()["reps"]


def all_customers() -> list[dict]:
    return _load()["customers"]


def all_products() -> list[dict]:
    return _load()["products"]


def all_activities() -> list[dict]:
    return _load()["sales_activities"]


def all_quotes() -> list[dict]:
    return _load()["quotes"]


def all_orders() -> list[dict]:
    return _load()["orders"]


def all_playbook() -> list[dict]:
    return _load()["playbook"]


def open_deals() -> list[dict]:
    """Live pipeline = deals whose order_rank is in the open band (2_A+ … 6_P)."""
    return [d for d in all_deals() if config.is_open_rank(d.get("order_rank"))]


# --- field accessors -------------------------------------------------------
def deal_rep_id(deal: dict) -> str:
    """Employee ID owning a deal (from sales_info)."""
    return (deal.get("sales_info") or {}).get("employee_id", "")


# --- lookups ---------------------------------------------------------------
def get_deal(deal_id: str) -> dict | None:
    # IDs are uppercase by schema; exact-match first (fast internal path), then an
    # uppercase fallback so user input like "d128" resolves the same as "D128".
    idx = _index()["deal_by_id"]
    return idx.get(deal_id) or (idx.get(deal_id.upper()) if isinstance(deal_id, str) else None)


def get_customer(customer_id: str) -> dict | None:
    idx = _index()["customer_by_id"]
    return idx.get(customer_id) or (idx.get(customer_id.upper()) if isinstance(customer_id, str) else None)


def get_rep(employee_id: str) -> dict | None:
    return _index()["rep_by_id"].get(employee_id)


def get_product(product_code: str) -> dict | None:
    return _index()["product_by_id"].get(product_code)


def get_environment(customer_id: str) -> dict | None:
    return next((e for e in _load()["environments"]
                 if e["customer_id"] == customer_id), None)


# --- relations -------------------------------------------------------------
def deals_for_rep(employee_id: str) -> list[dict]:
    return _index()["deals_by_rep"].get(employee_id, [])


def deals_for_customer(customer_id: str) -> list[dict]:
    return _index()["deals_by_cust"].get(customer_id, [])


def activities_for_deal(deal_id: str) -> list[dict]:
    """All sales activities for a deal, newest first (the deal's interaction log)."""
    return _index()["acts_by_deal"].get(deal_id, [])


def activities_for_customer(customer_id: str) -> list[dict]:
    """All activities across a customer's deals, newest first."""
    rows: list[dict] = []
    for d in deals_for_customer(customer_id):
        rows.extend(activities_for_deal(d["deal_id"]))
    return sorted(rows, key=lambda a: a.get("activity_date", ""), reverse=True)


def daily_reports_for_rep(employee_id: str) -> list[dict]:
    """002_Daily Report activities authored by a rep."""
    return [a for a in all_activities()
            if (a.get("sales_info") or {}).get("employee_id") == employee_id
            and a.get("activity_type") == "002_Daily Report"]


def all_coaching_threads() -> list[dict]:
    """Manager↔rep coaching threads (coaching_threads.json; [] if absent)."""
    return _load().get("coaching_threads", [])


def coaching_threads_for_rep(employee_id: str) -> list[dict]:
    """Coaching threads owned by a rep, newest first."""
    rows = [t for t in all_coaching_threads() if t.get("employee_id") == employee_id]
    return sorted(rows, key=lambda t: t.get("created_at", ""), reverse=True)


def coaching_threads_for_deal(deal_id: str) -> list[dict]:
    """Coaching threads raised on a specific deal, newest first."""
    rows = [t for t in all_coaching_threads() if t.get("deal_id") == deal_id]
    return sorted(rows, key=lambda t: t.get("created_at", ""), reverse=True)


def coachees_of(manager_id: str) -> set[str]:
    """Employee ids this manager coaches — the reps in any thread where they are
    the manager_id. This is the only explicit 'who I coach' relationship in the
    data (there's no org/reporting chart), so it defines a manager's team."""
    return {t["employee_id"] for t in all_coaching_threads()
            if t.get("manager_id") == manager_id and t.get("employee_id")}


def team_of(manager_id: str) -> set[str]:
    """A manager's full team: reps they coach in threads (coachees_of) plus reps
    assigned to them at signup (reports_to). Existing managers get their
    thread-based team; freshly-created juniors join via reports_to even before
    they have any deals or threads."""
    assigned = {r["employee_id"] for r in all_reps() if r.get("reports_to") == manager_id}
    return coachees_of(manager_id) | assigned


def quote_for_deal(deal_id: str) -> dict | None:
    """A deal's quote, resolved via the quote_id linked on its activities."""
    qid = next((a.get("quote_id") for a in activities_for_deal(deal_id)
                if a.get("quote_id")), None)
    return _index()["quote_by_id"].get(qid) if qid else None


def orders_for_deal(deal_id: str) -> list[dict]:
    """Order lines for a deal, resolved via the order_id linked on its activities."""
    order_by_id = _index()["order_by_id"]
    seen: set[str] = set()
    out: list[dict] = []
    for a in activities_for_deal(deal_id):
        oid = a.get("order_id")
        if oid and oid not in seen and oid in order_by_id:
            seen.add(oid)
            out.append(order_by_id[oid])
    return out


def orders_for_customer(customer_id: str) -> list[dict]:
    """All orders for a customer, newest first (the account's purchase history)."""
    return _index()["orders_by_cust"].get(customer_id, [])


def quotes_for_customer(customer_id: str) -> list[dict]:
    """All quotes for a customer, newest first (the account's quoting history)."""
    return _index()["quotes_by_cust"].get(customer_id, [])


# --- display helpers -------------------------------------------------------
def customer_name(customer_id: str) -> str:
    c = get_customer(customer_id)
    return c["name"] if c else customer_id


def rep_name(employee_id: str) -> str:
    r = get_rep(employee_id)
    return r["name"] if r else employee_id


# --- backward-compat shims (for the friend-owned web-app / coach experiment) ---
# Our pipeline reads sales_activities directly; the experiment still calls the old
# notes/report API. These derive old-shaped data from sales_activities so that code
# keeps working unchanged. They are NOT used by our pipeline.
def notes_for_deal(deal_id: str) -> list[dict]:
    """Old 'notes' shape, derived from sales_activities (newest first). Each row
    carries both the new keys and the legacy aliases (date/text/channel/rep_id)."""
    out = []
    for a in activities_for_deal(deal_id):
        out.append({**a,
                    "date": a.get("activity_date"),
                    "text": a.get("daily_report"),
                    "channel": a.get("activity_type"),
                    "rep_id": (a.get("sales_info") or {}).get("employee_id")})
    return out


def report_for_deal(deal_id: str) -> dict | None:
    """No standalone report object exists in the SPR schema (daily_report lives on
    activities). Returned as None for compat; callers tolerate it."""
    return None


def reports_for_rep(employee_id: str) -> list[dict]:
    """Compat alias — daily-report activities for a rep."""
    return daily_reports_for_rep(employee_id)


def find_customer_by_name(name: str) -> dict | None:
    """Loose JA match: exact, then substring (handles 'アクメ商事' vs '株式会社アクメ商事').
    For cross-language resolution (English/romaji/alias) use resolve_customer."""
    if not name:
        return None
    n = name.strip()
    for c in all_customers():
        if c["name"] == n:
            return c
    for c in all_customers():
        if n in c["name"] or c["name"] in n:
            return c
    return None


# --- alias-aware customer resolution ---------------------------------------
# Resolves Japanese, English, romaji and known-alias forms to the canonical
# customer record — BEFORE any retrieval. Built so a name that maps to more than
# one customer is treated as ambiguous and never guessed (we'd rather miss than
# fabricate the wrong customer's facts).
_CORP_TOKENS = ["株式会社", "有限会社", "合同会社", "(株)", "（株）", "(有)", "（有）"]


def _norm(s: str) -> str:
    """Case/space-insensitive key. JA text is unaffected by lower()."""
    return " ".join((s or "").split()).lower()


def name_forms(name: str) -> list[str]:
    """A customer name plus its bare form (corporate prefix/suffix removed), so
    '有限会社村田印刷' is found from text that just says '村田印刷'."""
    forms = {name}
    bare = name
    for tok in _CORP_TOKENS:
        bare = bare.replace(tok, "")
    bare = bare.strip()
    if len(bare) >= 2:
        forms.add(bare)
    return [f for f in forms if f]


@lru_cache(maxsize=1)
def _alias_index() -> dict[str, set[str]]:
    """Map a normalized name/alias key -> set of customer_ids that answer to it.
    A key owned by >1 customer is ambiguous (callers must not guess)."""
    aliases = customer_aliases()
    idx: dict[str, set[str]] = {}
    for c in all_customers():
        cid = c["customer_id"]
        keys = set(name_forms(c.get("name", ""))) | set(aliases.get(cid, []))
        for k in keys:
            kk = _norm(k)
            if len(kk) >= 2:
                idx.setdefault(kk, set()).add(cid)
    return idx


@dataclass
class CustomerCandidate:
    customer_id: str
    name: str
    matched_aliases: list[str] = field(default_factory=list)


@dataclass
class CustomerResolution:
    status: Literal["resolved", "ambiguous", "not_found"]
    query: str
    customer: dict | None = None
    candidates: list[CustomerCandidate] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "query": self.query,
            "customer": self.customer,
            "candidates": [asdict(c) for c in self.candidates],
        }


def _candidate(customer_id: str, match_key: str = "") -> CustomerCandidate:
    c = get_customer(customer_id) or {"customer_id": customer_id, "name": customer_id}
    aliases = []
    for form in name_forms(c.get("name", "")) + customer_aliases().get(customer_id, []):
        if not match_key or _norm(form) == match_key:
            aliases.append(form)
    return CustomerCandidate(
        customer_id=customer_id,
        name=c.get("name", customer_id),
        matched_aliases=sorted(set(aliases)),
    )


def resolve_customer_detailed(query: str) -> CustomerResolution:
    """Resolve one customer, preserving ambiguity as a first-class state."""
    q = (query or "").strip()
    if not q:
        return CustomerResolution(status="not_found", query=query or "")

    by_id = get_customer(q)
    if by_id:
        return CustomerResolution(status="resolved", query=q, customer=by_id)

    key = _norm(q)
    ids = _alias_index().get(key)
    if ids:
        if len(ids) == 1:
            return CustomerResolution(
                status="resolved", query=q, customer=get_customer(next(iter(ids))))
        return CustomerResolution(
            status="ambiguous",
            query=q,
            candidates=[_candidate(cid, key) for cid in sorted(ids)],
        )

    loose = find_customer_by_name(q)
    if loose:
        return CustomerResolution(status="resolved", query=q, customer=loose)

    return CustomerResolution(status="not_found", query=q)


def resolve_customer(query: str) -> dict | None:
    """Resolve a customer from an id, JA name, English/romaji name or known alias.
    Returns None when the query is empty, unknown, or ambiguous (maps to >1
    customer) — never a guess. This is the single entry point tools and the coach
    use before retrieval."""
    return resolve_customer_detailed(query).customer


def _key_in_text(key: str, low_text: str) -> bool:
    """Whether an alias `key` occurs in `low_text`. ASCII/romaji keys require WORD
    boundaries so 'new' does not match inside 'news' and 'canon' would not match
    'canonical' — latin words run together with spaces, so bare substring matching
    produces false customers. Japanese keys keep substring matching (JA has no word
    boundaries, and names are contiguous), e.g. '村田印刷' inside '村田印刷さん'."""
    if key.isascii():
        return re.search(r"\b" + re.escape(key) + r"\b", low_text) is not None
    return key in low_text


_CUSTOMER_ID_RE = re.compile(r"\bC\d{1,4}\b", re.IGNORECASE)


def _customer_id_in_text(text: str) -> str | None:
    """A single, unambiguous customer id (e.g. 'C14') named anywhere in the text.
    Returns the canonical id when exactly one VALID id appears, else None (0 ids,
    or several different ids → defer to name matching / ambiguity). Mirrors how the
    research bridge already extracts deal ids ('D027') from a phrased request."""
    seen = list(dict.fromkeys(m.group(0).upper()
                              for m in _CUSTOMER_ID_RE.finditer(text or "")))
    valid = [cid for cid in seen if get_customer(cid)]
    return valid[0] if len(valid) == 1 else None


def _best_alias_matches(text: str) -> tuple[tuple[int, set[str]] | None,
                                            tuple[int, set[str]] | None]:
    """Scan the alias index for the most specific name/alias present in `text`,
    tracked separately for UNIQUELY-resolving keys and AMBIGUOUS (multi-customer)
    keys. Returns (best_unique, best_ambiguous) as (key_len, ids) or None.

    A unique full name must beat a shared stem even when the stem is "longer" by
    raw character count — character length is not comparable across scripts, so a
    4-char exact kanji name ('松田運輸' → one customer) would otherwise lose to a
    7-char romaji stem ('matsuda' → four 松田 companies) and re-trigger ambiguity
    forever. Callers prefer `best_unique` when present; ambiguity is only real
    when NO unique alias is in the text."""
    low = (text or "").lower()
    best_uniq: tuple[int, set[str]] | None = None
    best_amb: tuple[int, set[str]] | None = None
    for key, ids in _alias_index().items():
        if not _key_in_text(key, low):
            continue
        if len(ids) == 1:
            if best_uniq is None or len(key) > best_uniq[0]:
                best_uniq = (len(key), ids)
        elif best_amb is None or len(key) > best_amb[0]:
            best_amb = (len(key), ids)
    return best_uniq, best_amb


def match_customer_in_text(text: str) -> dict | None:
    """Find the customer named anywhere in free text — across JA, English, romaji
    and alias forms. A uniquely-resolving name wins (so 'Aozora Services' beats
    'Aozora', and an exact '松田運輸' beats the shared 'matsuda' stem); an ambiguous
    stem with no unique name present resolves to None so we never attribute the
    wrong customer's history. An explicit customer id ('C14') is the most precise,
    unambiguous signal and wins over any name match."""
    cid = _customer_id_in_text(text)
    if cid:
        return get_customer(cid)
    best_uniq, _ = _best_alias_matches(text)
    if best_uniq:
        return get_customer(next(iter(best_uniq[1])))
    return None


def ambiguous_match_in_text(text: str) -> list[dict]:
    """When the customer name/alias found in `text` maps to MORE THAN ONE customer
    (e.g. 'marusan' → 丸三クリニック / 丸三食品 / 丸三商事 / 丸三システム) AND no
    unique full name is also present, return those candidate records so callers can
    disambiguate instead of silently failing. Empty when a unique name is present
    (use match_customer_in_text) or no name matches. This is the surface-the-
    ambiguity counterpart to the never-guess resolvers."""
    best_uniq, best_amb = _best_alias_matches(text)
    if best_uniq:  # an exact full name pins it down → not ambiguous
        return []
    if best_amb:
        return [c for cid in sorted(best_amb[1]) if (c := get_customer(cid))]
    return []


def resolve_customer_in_text(text: str) -> CustomerResolution:
    """Resolve the customer NAMED ANYWHERE in free text — preserving ambiguity as
    a first-class state. Unlike resolve_customer_detailed (which treats the whole
    query as the name), this locates the customer token inside an action/verb-
    wrapped message: 'create a quotation for akebono' → ambiguous (3 あけぼの
    companies), not not_found. So callers (e.g. research) reach internal records
    instead of falling through to web search on a phrased request. An explicit
    customer id ('research about C14') resolves directly via match_customer_in_text."""
    uniq = match_customer_in_text(text)
    if uniq:
        return CustomerResolution(status="resolved", query=text, customer=uniq)
    amb = ambiguous_match_in_text(text)
    if amb:
        low = (text or "").lower()
        best_key = ""
        for key, ids in _alias_index().items():
            if _key_in_text(key, low) and len(ids) > 1 and len(key) > len(best_key):
                best_key = key
        return CustomerResolution(
            status="ambiguous", query=text,
            candidates=[_candidate(c["customer_id"], best_key) for c in amb])
    return CustomerResolution(status="not_found", query=text)


# --- fallback resolution: fuzzy matching + company-name extraction ----------

_COMPANY_SUFFIXES = (
    "商事", "商会", "製作所", "印刷", "サービス", "システム",
    "電機", "工業", "建設", "産業", "電子", "情報", "物産", "興業",
)
_COMPANY_PREFIXES_RE = (
    r"株式会社\s*([^\s、。\n]{2,10})",
    r"有限会社\s*([^\s、。\n]{2,10})",
    r"合同会社\s*([^\s、。\n]{2,10})",
    r"([^\s、。\n]{2,10})\s*(?:株式会社|有限会社|合同会社|（株）|\(株\))",
)


def extract_company_names_from_text(text: str) -> list[str]:
    """Pull likely company name tokens from free text using suffix/prefix patterns.
    Returns unique candidates, longest first — callers try each through the
    resolver (exact/alias) to find a match."""
    import re
    found: list[str] = []
    # Explicit legal-form patterns
    for pat in _COMPANY_PREFIXES_RE:
        for m in re.finditer(pat, text):
            cand = m.group(0).strip()
            if len(cand) >= 2:
                found.append(cand)
    # Suffix patterns: e.g. 'アクメ商事', '大和システム'
    for suf in _COMPANY_SUFFIXES:
        for m in re.finditer(rf"([^\s、。\n]{{1,8}}{re.escape(suf)})", text):
            found.append(m.group(0))
    # De-dup, longest first
    seen: set[str] = set()
    out: list[str] = []
    for c in sorted(found, key=len, reverse=True):
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def fuzzy_match_customer_in_text(
    text: str,
    threshold: float = 0.72,
) -> tuple[dict | None, float]:
    """Approximate customer match when exact/alias lookup finds nothing.

    Slides a window the length of each alias key over the normalised note text
    and scores character-level similarity (difflib SequenceMatcher). Only
    unambiguous alias keys (mapping to exactly one customer) are considered.
    Keys shorter than 4 normalised chars are skipped to avoid false positives.

    Returns (customer, best_score). customer is None when best_score < threshold.
    """
    import difflib

    low = (text or "").lower()
    if not low:
        return None, 0.0

    best_c: dict | None = None
    best_score = 0.0

    for key, ids in _alias_index().items():
        if len(key) < 4 or len(ids) != 1:
            continue
        klen = len(key)
        if klen > len(low):
            # Try full note as single window
            r = difflib.SequenceMatcher(None, key, low, autojunk=False).ratio()
            if r > best_score:
                best_score = r
                if r >= threshold:
                    best_c = get_customer(next(iter(ids)))
            continue
        for start in range(len(low) - klen + 1):
            window = low[start: start + klen]
            r = difflib.SequenceMatcher(None, key, window, autojunk=False).ratio()
            if r > best_score:
                best_score = r
                if r >= threshold:
                    best_c = get_customer(next(iter(ids)))

    return (best_c if best_score >= threshold else None), best_score
