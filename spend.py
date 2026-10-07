"""Standard-library-only accounting. Amounts are Decimal strings, not price estimates."""
from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
import shlex
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode, urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError

LOG = logging.getLogger(__name__)
API = "https://openrouter.ai/api/v1"
PERIODS = {"today": "usage_daily", "week": "usage_weekly",
           "month": "usage_monthly", "total": "usage"}
HELP = """/spend — OpenRouter-reported API-key spend (USD)
/spend today|week|month|total — provider's reporting periods
/spend refresh — bypass the 30-second default cache
/spend ledger [today|week|month|total] — locally observed requests (UTC)
/spend models [today|week|month|total] — ledger grouped by model
/spend reconcile — resolve up to 20 missing costs using generation IDs
/spend status — local accounting coverage
Key totals include ALL applications using that key. Local ledger starts at installation.
Auxiliary cost/ID fields are absent on the tested Hermes build; coverage reports this.
No model calls. No prompts, outputs, or API keys saved."""


def field(obj, name, default=None):
    return obj.get(name, default) if isinstance(obj, dict) else getattr(obj, name, default)


def amount(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
        return result if result.is_finite() and result >= 0 else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def money(value):
    return "unavailable" if value is None else f"${value:,.6f}"


def is_openrouter(meta):
    # A custom OpenAI-compatible route is accepted only for OpenRouter's exact host.
    host = urlparse(str(meta.get("base_url") or "")).hostname
    if host:
        return host.lower() == "openrouter.ai"
    return str(meta.get("provider") or "").lower() == "openrouter"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward a credential to a redirect target.


def get_fx_json(timeout):
    # Public reference-rate request: never include an OpenRouter credential or spend data.
    request = Request("https://api.frankfurter.dev/v2/rate/usd/inr", headers={
        "Accept": "application/json", "User-Agent": "Hermes-OpenRouterSpend/0.2"})
    try:
        with build_opener(NoRedirect).open(request, timeout=timeout) as response:
            payload = response.read(65537)
        if len(payload) > 65536:
            raise ValueError("Exchange-rate response too large")
        data = json.loads(payload, parse_float=Decimal)
        rate = amount(data.get("rate"))
        date = data.get("date")
        datetime.strptime(date, "%Y-%m-%d")
        if data.get("base") != "USD" or data.get("quote") != "INR" or not rate or rate > 1000:
            raise ValueError("Invalid USD/INR reference rate")
        return {"rate": str(rate), "date": date, "source": "Frankfurter"}
    except Exception:
        raise ValueError("USD/INR reference rate unavailable") from None


def get_json(path, key, timeout):
    request = Request(API + path, headers={"Authorization": "Bearer " + key,
                                          "Accept": "application/json"})
    try:
        with build_opener(NoRedirect).open(request, timeout=timeout) as response:
            content = response.read(1024 * 1024 + 1)
        if len(content) > 1024 * 1024:
            raise ValueError("Accounting response exceeded 1 MiB")
        parsed = json.loads(content, parse_float=Decimal)
        data = parsed.get("data") if isinstance(parsed, dict) else None
        if not isinstance(data, dict):
            raise ValueError("OpenRouter returned an invalid accounting response")
        return data
    except HTTPError as exc:
        # Do not surface provider error bodies or request headers.
        raise ValueError(f"OpenRouter accounting HTTP {exc.code}") from None
    except (URLError, TimeoutError, OSError):
        raise ValueError("OpenRouter accounting could not be reached") from None
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ValueError("OpenRouter returned invalid JSON") from None


class Ledger:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.path = self.directory / "spend.sqlite3"
        self.lock = threading.RLock()

    @contextmanager
    def connect(self):
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        con = sqlite3.connect(self.path, timeout=2)
        try:
            con.row_factory = sqlite3.Row
            # Two profiles/tasks can initialize the same ledger simultaneously.
            # SQLite's journal-mode change can return SQLITE_BUSY immediately,
            # even with a connection timeout; give the first writer time to finish.
            deadline = time.monotonic() + 2
            while True:
                try:
                    if con.execute('PRAGMA journal_mode').fetchone()[0] != 'wal':
                        con.execute('PRAGMA journal_mode=WAL')
                    break
                except sqlite3.OperationalError as exc:
                    if 'locked' not in str(exc).lower() or time.monotonic() >= deadline:
                        raise
                    time.sleep(0.02)
            con.execute("""CREATE TABLE IF NOT EXISTS requests (
            attempt TEXT PRIMARY KEY, generation_id TEXT UNIQUE, occurred REAL NOT NULL,
            session TEXT NOT NULL, model TEXT NOT NULL, category TEXT NOT NULL,
            outcome TEXT NOT NULL, cost TEXT, source TEXT,
            prompt_tokens INTEGER, completion_tokens INTEGER, cached_tokens INTEGER,
            key_fingerprint TEXT, profile TEXT)""")
            con.execute("""CREATE TABLE IF NOT EXISTS snapshots (
            key_fingerprint TEXT PRIMARY KEY, fetched REAL NOT NULL, data TEXT NOT NULL)""")
            columns = {r[1] for r in con.execute('PRAGMA table_info(requests)')}
            for name in ('key_fingerprint', 'profile', 'total_tokens'):
                if name not in columns:
                    try:
                        kind = 'INTEGER' if name == 'total_tokens' else 'TEXT'
                        con.execute(f'ALTER TABLE requests ADD COLUMN {name} {kind}')
                    except sqlite3.OperationalError:
                        # Another profile worker may have migrated this file concurrently.
                        if name not in {r[1] for r in con.execute('PRAGMA table_info(requests)')}:
                            raise
            con.commit()
            with con:
                yield con
        finally:
            con.close()

    def upsert(self, row):
        row = dict(row, key_fingerprint=row.get('key_fingerprint'), profile=row.get('profile'),
                   total_tokens=row.get('total_tokens'))
        with self.lock, self.connect() as con:
            existing = None
            if row["generation_id"]:
                existing = con.execute("SELECT attempt FROM requests WHERE generation_id=?",
                                       (row["generation_id"],)).fetchone()
            if existing:
                row = dict(row, attempt=existing["attempt"])
            con.execute("""INSERT INTO requests (attempt,generation_id,occurred,session,model,category,
                outcome,cost,source,prompt_tokens,completion_tokens,cached_tokens,key_fingerprint,profile,total_tokens) VALUES (
                :attempt, :generation_id, :occurred, :session, :model, :category,
                :outcome, :cost, :source, :prompt_tokens, :completion_tokens, :cached_tokens,:key_fingerprint,:profile,:total_tokens)
                ON CONFLICT(attempt) DO UPDATE SET
                generation_id=COALESCE(excluded.generation_id, requests.generation_id),
                cost=COALESCE(excluded.cost, requests.cost),
                source=COALESCE(excluded.source, requests.source),
                outcome=excluded.outcome,
                prompt_tokens=COALESCE(excluded.prompt_tokens, requests.prompt_tokens),
                completion_tokens=COALESCE(excluded.completion_tokens, requests.completion_tokens),
                cached_tokens=COALESCE(excluded.cached_tokens, requests.cached_tokens),
                total_tokens=COALESCE(excluded.total_tokens, requests.total_tokens),
                key_fingerprint=COALESCE(excluded.key_fingerprint, requests.key_fingerprint),
                profile=COALESCE(excluded.profile, requests.profile)""", row)

    def rows(self, period="total"):
        now = datetime.now(timezone.utc)
        start = {"total": 0, "today": now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp(),
                 "week": (now - timedelta(days=now.weekday())).replace(
                     hour=0, minute=0, second=0, microsecond=0).timestamp(),
                 "month": now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()}[period]
        with self.lock, self.connect() as con:
            return [dict(row) for row in con.execute(
                "SELECT * FROM requests WHERE occurred>=? ORDER BY occurred", (start,))]

    def snapshot(self, fingerprint):
        with self.lock, self.connect() as con:
            row = con.execute("SELECT * FROM snapshots WHERE key_fingerprint=?", (fingerprint,)).fetchone()
            return None if row is None else (row["fetched"], json.loads(row["data"]))

    def save_snapshot(self, fingerprint, data):
        with self.lock, self.connect() as con:
            con.execute("INSERT OR REPLACE INTO snapshots VALUES (?, ?, ?)",
                        (fingerprint, time.time(), json.dumps(data)))

    def resolve(self, generation_id, cost):
        with self.lock, self.connect() as con:
            con.execute("UPDATE requests SET cost=?, source='generation_api' WHERE generation_id=?",
                        (str(cost), generation_id))


class SpendPlugin:
    def __init__(self, directory, get_config=lambda key, default=None: default, profile=None):
        self.ledger = Ledger(directory)
        self.get_config = get_config
        self.profile = profile
        self.attempts = {}
        self.lock = threading.RLock()

    def config_int(self, name, default, low, high):
        try:
            return max(low, min(high, int(self.get_config(name, default))))
        except (TypeError, ValueError):
            return default

    def key(self):
        name = str(self.get_config("api_key_env", "OPENROUTER_API_KEY"))
        try:
            from agent.secret_scope import get_secret
        except ImportError:  # Standalone accounting outside a Hermes runtime.
            get_secret = os.environ.get
        key = (get_secret(name, "") or "").strip()
        if not key:
            raise ValueError(f"Set {name} in Hermes's profile .env to query OpenRouter spend")
        return key

    def on_pre_request(self, **meta):
        if not is_openrouter(meta):
            return
        with self.lock:
            ident = (str(meta.get("api_request_id")), meta.get("api_call_count"))
            # Only numeric/identifier metadata, never prompt content.
            self.attempts[ident] = {k: meta.get(k) for k in (
                "api_request_id", "api_call_count", "started_at", "session_id", "model")}
            if len(self.attempts) > 1024:
                self.attempts.pop(next(iter(self.attempts)))

    def attempt_meta(self, meta):
        with self.lock:
            ident = (str(meta.get("api_request_id")), meta.get("api_call_count"))
            return {**self.attempts.pop(ident, {}), **meta}

    def record(self, meta, response=None, category="main", outcome="success"):
        usage = field(response, "usage") or meta.get("usage") or {}
        billed = amount(field(usage, "cost"))
        gid = field(response, "id")
        # Stream stubs and Hermes request IDs cannot be used with OpenRouter /generation.
        gid = gid if isinstance(gid, str) and gid.startswith("gen-") else None
        started = meta.get("started_at") or time.time()
        attempt = meta.get('accounting_attempt') or json.dumps([
            meta.get("session_id") or "", meta.get("api_request_id") or "",
            meta.get("api_call_count"), meta.get("retry_count"), started])

        def tokens(name, alternate=None):
            value = field(usage, name, field(usage, alternate) if alternate else None)
            return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None

        details = field(usage, "prompt_tokens_details") or {}
        cached = field(details, "cached_tokens", field(usage, "cache_read_tokens"))
        fingerprint = meta.get('key_fingerprint')
        if not fingerprint and not meta.get('image_accounting'):
            try:
                fingerprint = hashlib.sha256(self.key().encode()).hexdigest()
            except (ValueError, RuntimeError):
                # Keep confirmed costs even when credentials are unavailable to observers.
                fingerprint = None
        self.ledger.upsert({
            "attempt": attempt, "generation_id": gid, "occurred": float(started),
            "session": str(meta.get("session_id") or ""),
            "model": str(field(response, "model") or meta.get("response_model") or meta.get("model") or "unknown"),
            "category": category, "outcome": outcome,
            "cost": None if billed is None else str(billed),
            "source": None if billed is None else "response",
            "prompt_tokens": tokens("prompt_tokens", "input_tokens"),
            "completion_tokens": tokens("completion_tokens", "output_tokens"),
            "total_tokens": tokens("total_tokens"),
            "cached_tokens": cached if isinstance(cached, int) and not isinstance(cached, bool) and cached >= 0 else None,
            "profile": self.profile,
            "key_fingerprint": fingerprint,
        })

    def safely_record(self, **kwargs):
        try:
            self.record(**kwargs)
        except Exception:
            # Accounting must never fail or repeat an inference request; no sensitive payload in log.
            LOG.warning("OpenRouter Spend could not persist accounting metadata")

    def on_execution(self, **meta):
        response = meta["next_call"](meta["request"])  # Exactly once; original errors propagate.
        if is_openrouter(meta):
            self.safely_record(meta=self.attempt_meta(meta), response=response)
        return response  # Preserve Hermes's response object, streaming reassembly, and prompt cache.

    def on_error(self, **meta):
        if is_openrouter(meta):
            self.safely_record(meta=self.attempt_meta(meta), outcome="error")

    def on_auxiliary(self, **meta):
        if is_openrouter(meta):
            self.safely_record(meta=meta, response=meta.get("response"),
                               category="auxiliary:" + str(meta.get("aux_task") or "unknown"),
                               outcome="error" if meta.get("error") else "success")

    def on_image_tool(self, tool_name=None, result=None, **meta):
        if tool_name != 'image_generate':
            return
        try:
            payload = json.loads(result) if isinstance(result, str) else result
            if not isinstance(payload, dict):
                return
            entries = payload.get('billing_records')
            if not isinstance(entries, list):
                # Older Hermes retains only these fields for the dedicated Image API.
                if payload.get('provider') != 'openrouter' or amount(payload.get('cost_usd')) is None:
                    return
                entries = [dict(provider='openrouter', model=payload.get('model'),
                                usage=dict(cost=payload['cost_usd'], total_tokens=payload.get('total_tokens')))]
            for index, entry in enumerate(entries):
                if not isinstance(entry, dict) or not is_openrouter(entry):
                    continue
                identity = meta.get('tool_call_id')
                if not identity:
                    # Without an identity a repeated observer cannot be deduplicated safely.
                    continue
                observed = dict(meta, api_request_id='image:' + str(identity), api_call_count=index,
                                started_at=meta.get('occurred') or time.time(),
                                image_accounting=True, key_fingerprint=entry.get('key_fingerprint'))
                response = dict(id=entry.get('generation_id'), model=entry.get('model'),
                                usage=entry.get('usage') or {})
                # Stable identity even when an older response omitted the generation ID.
                observed['accounting_attempt'] = json.dumps([
                    'image', meta.get('session_id') or '', str(identity), index])
                self.safely_record(meta=observed, response=response, category='tool:image_generation',
                                   outcome='success')
        except (ValueError, TypeError):
            LOG.warning('OpenRouter Spend could not read image accounting metadata')

    def key_data(self, refresh=False):
        key = self.key()
        fingerprint = hashlib.sha256(key.encode()).hexdigest()
        snapshot = self.ledger.snapshot(fingerprint)
        ttl = self.config_int("cache_seconds", 30, 0, 300)
        stale = False
        if not refresh and snapshot and time.time() - snapshot[0] < ttl:
            fetched, data = snapshot
        else:
            try:
                raw = get_json("/key", key, self.config_int("timeout_seconds", 8, 1, 30))
                # Whitelist numeric accounting fields. OpenRouter's label can contain part of a key.
                fields = list(PERIODS.values()) + ["limit", "limit_remaining", "byok_usage"]
                data = {name: None if amount(raw.get(name)) is None else str(amount(raw[name]))
                        for name in fields}
                if not any(data.get(name) is not None for name in PERIODS.values()):
                    raise ValueError("OpenRouter returned no spend counters")
                self.ledger.save_snapshot(fingerprint, data)
                fetched = time.time()
            except ValueError:
                if not snapshot:
                    raise
                fetched, data = snapshot
                stale = True
        return fetched, data, stale

    def exchange_rate(self):
        override = amount(self.get_config("usd_inr_rate", None))
        if override and override <= 1000:
            return {"rate": str(override), "date": None, "source": "manual", "stale": False}
        snapshot = self.ledger.snapshot("usd-inr-reference")
        ttl = self.config_int("fx_cache_seconds", 43200, 300, 86400)
        if snapshot and time.time() - snapshot[0] < ttl:
            return dict(snapshot[1], stale=False)
        try:
            data = get_fx_json(self.config_int("timeout_seconds", 8, 1, 30))
            self.ledger.save_snapshot("usd-inr-reference", data)
            return dict(data, stale=False)
        except ValueError:
            if snapshot:
                return dict(snapshot[1], stale=True)
            return {"rate": None, "date": None, "source": "unavailable", "stale": True}

    def dual_money(self, value, fx):
        rate = amount(fx.get("rate"))
        inr = "INR unavailable" if value is None or rate is None else f"≈₹{value * rate:,.2f}"
        return f"{money(value)} / {inr}"

    def summary(self, refresh=False):
        fetched, data, stale = self.key_data(refresh)
        fx = self.exchange_rate()
        rate = amount(fx.get("rate"))
        periods = {}
        for period, name in PERIODS.items():
            value = amount(data.get(name))
            periods[period] = {"usd": None if value is None else str(value),
                               "inr": None if value is None or rate is None else str(value * rate)}
        return {"scope": "api_key", "periods": periods, "fetched_at": fetched,
                "stale": stale, "fx": fx}

    def key_report(self, period=None, refresh=False):
        fetched, data, stale = self.key_data(refresh)
        fx = self.exchange_rate()
        when = datetime.fromtimestamp(fetched, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        lines = ["OpenRouter API-key spend — USD / INR", "Scope: ALL applications using this API key."]
        if period:
            lines.append(f"{period.capitalize()}: {self.dual_money(amount(data.get(PERIODS[period])), fx)}")
        else:
            for p in ("today", "week", "month", "total"):
                lines.append(f"{p.capitalize()}: {self.dual_money(amount(data.get(PERIODS[p])), fx)}")
        if data.get("limit_remaining") is not None:
            lines.append("Key budget remaining: " + self.dual_money(amount(data["limit_remaining"]), fx))
        byok = amount(data.get("byok_usage"))
        if byok is not None and byok > 0:
            lines.append("BYOK usage reported separately: " + money(byok) + " (not added to spend)")
        lines.append(f"{'STALE — refresh failed; last successful fetch' if stale else 'Fetched'}: {when}")
        if fx.get("rate"):
            lines.append(f"INR reference: ₹{fx['rate']} per USD · {fx.get('date') or 'manual rate'} · "
                         f"{fx['source']}" + (" (STALE)" if fx.get("stale") else ""))
        lines.append("Periods follow OpenRouter's counters. Purchase fees are outside this report.")
        return "\n".join(lines)

    def ledger_report(self, period="total", models=False):
        rows = self.ledger.rows(period)
        fx = self.exchange_rate()
        confirmed = [row for row in rows if amount(row["cost"]) is not None]
        total = sum((amount(row["cost"]) for row in confirmed), Decimal(0))
        lines = [f"Hermes observed ledger — {period} (UTC)",
                 f"Confirmed cost: {self.dual_money(total, fx)}", f"Recorded attempts: {len(rows)}",
                 f"Unresolved costs: {len(rows) - len(confirmed)}"]
        groups = {}
        for row in confirmed:
            name = row["model"] if models else row["category"]
            groups[name] = groups.get(name, Decimal(0)) + amount(row["cost"])
        for name, cost in sorted(groups.items(), key=lambda item: item[1], reverse=True):
            lines.append(f"{name}: {self.dual_money(cost, fx)}")
        if len(confirmed) < len(rows):
            lines.append("PARTIAL: unresolved requests are excluded, not assumed free.")
        lines.append("Starts at installation; /spend reports the API key's fuller totals.")
        return "\n".join(lines)

    def reconcile(self):
        key = self.key()
        pending = [row for row in self.ledger.rows() if row["cost"] is None and row["generation_id"]][:20]
        resolved = 0
        for row in pending:
            try:
                data = get_json("/generation?" + urlencode({"id": row["generation_id"]}), key,
                                self.config_int("timeout_seconds", 8, 1, 30))
                billed = amount(data.get("total_cost"))
                if billed is not None:
                    self.ledger.resolve(row["generation_id"], billed)
                    resolved += 1
            except ValueError:
                continue
        return (f"Resolved {resolved}/{len(pending)} generation costs.\n"
                "Requests without a generation ID cannot be reconciled individually.")

    def command(self, raw_args):
        try:
            parts = shlex.split(raw_args)
            if not parts:
                return self.key_report()
            action = parts[0]
            if action == "help" and len(parts) == 1:
                return HELP
            if action in PERIODS and len(parts) == 1:
                return self.key_report(action)
            if action == "refresh" and len(parts) == 1:
                return self.key_report(refresh=True)
            if action in ("ledger", "models") and len(parts) <= 2:
                period = parts[1] if len(parts) == 2 else "total"
                if period not in PERIODS:
                    return "Error: choose today, week, month, or total.\n" + HELP
                return self.ledger_report(period, models=action == "models")
            if action == "status" and len(parts) == 1:
                rows = self.ledger.rows()
                aux = sum(row["category"].startswith("auxiliary:") for row in rows)
                errors = sum(row["outcome"] == "error" for row in rows)
                recoverable = sum(row["cost"] is None and bool(row["generation_id"]) for row in rows)
                return (f"Local ledger: {self.ledger.path}\nRecorded attempts: {len(rows)}\n"
                        f"Auxiliary attempts: {aux}\nError attempts (billing unknown): {errors}\n"
                        f"Missing costs with generation ID: {recoverable}\n"
                        "Main responses are captured by execution middleware.\n"
                        "Auxiliary costs/IDs may be unavailable; key totals include their billed spend.")
            if action == "reconcile" and len(parts) == 1:
                return self.reconcile()
            return "Error: unknown /spend options.\n" + HELP
        except ValueError as exc:
            return "Error: " + str(exc)
        except Exception:
            return "Error: accounting unavailable; check ledger permissions and plugin settings."
