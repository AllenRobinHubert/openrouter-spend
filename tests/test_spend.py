import importlib.util
import os
import sqlite3
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("spend", Path(__file__).parents[1] / "spend.py")
spend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(spend)


class SpendTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        fx = patch.object(spend, "get_fx_json", return_value={"rate": "96.17", "date": "2026-10-04", "source": "Frankfurter"})
        self.fx_fetch = fx.start()
        self.addCleanup(fx.stop)
        self.plugin = spend.SpendPlugin(self.temp.name)
        self.meta = dict(provider="openrouter", base_url="https://openrouter.ai/api/v1",
                         api_request_id="request-1", api_call_count=1, session_id="s1", model="m1",
                         started_at=1780000000)

    def response(self, gid="gen-1", cost="0.000001", **extra):
        return NS(id=gid, model="m1", usage=NS(cost=cost, prompt_tokens=100,
                  completion_tokens=20, prompt_tokens_details=NS(cached_tokens=50)), **extra)

    def execute(self, response, meta=None):
        meta = meta or self.meta
        self.plugin.on_pre_request(**meta)
        calls = []
        def call(req):
            calls.append(req)
            return response
        req = {"messages": [{"role": "user", "content": "private prompt"}]}
        result = self.plugin.on_execution(**{**meta, "request": req, "next_call": call})
        self.assertIs(result, response)
        self.assertEqual(calls, [req])

    def test_exact_cost_not_upstream_cost_and_no_content_storage(self):
        response = self.response()
        response.usage.cost_details = {"upstream_inference_cost": 99}
        response.content = "secret completion"
        self.execute(response)
        row = self.plugin.ledger.rows()[0]
        self.assertEqual(Decimal(row["cost"]), Decimal("0.000001"))
        self.assertEqual(row["prompt_tokens"], 100)
        self.assertEqual(row["cached_tokens"], 50)
        data = self.plugin.ledger.path.read_bytes()
        self.assertNotIn(b"private prompt", data)
        self.assertNotIn(b"secret completion", data)

    def test_zero_is_confirmed(self):
        self.execute(self.response(cost=0))
        self.assertIn("Unresolved costs: 0", self.plugin.ledger_report())

    def test_image_cost_total_only_and_repeated_observer_count_once(self):
        result = dict(provider='openrouter', model='recraft/recraft-v4.1', cost_usd=0.035,
                      total_tokens=4323, prompt='PRIVATE IMAGE PROMPT', image='PRIVATE IMAGE')
        for _ in range(2):
            self.plugin.on_image_tool(tool_name='image_generate', result=spend.json.dumps(result),
                                      tool_call_id='image-1', session_id='s1', occurred=1780000000)
        rows = self.plugin.ledger.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['model'], 'recraft/recraft-v4.1')
        self.assertEqual(rows[0]['cost'], '0.035')
        self.assertEqual(rows[0]['total_tokens'], 4323)
        self.assertIsNone(rows[0]['prompt_tokens'])
        self.assertIsNone(rows[0]['key_fingerprint'])
        data = self.plugin.ledger.path.read_bytes()
        self.assertNotIn(b'PRIVATE IMAGE', data)

    def test_image_fallback_records_each_paid_attempt_and_actual_key(self):
        billing = [dict(provider='openrouter', model=model, generation_id=gid,
                        key_fingerprint='actual-image-key', usage=dict(cost=cost, prompt_tokens=10,completion_tokens=20))
                   for model,gid,cost in [('image-first','gen-first','0.01'),('image-fallback','gen-fallback','0.03')]]
        result = dict(success=False, billing_records=billing)
        self.plugin.on_image_tool(tool_name='image_generate',result=result,tool_call_id='fallback',session_id='s1')
        rows = self.plugin.ledger.rows()
        self.assertEqual({r['model']:r['cost'] for r in rows}, {'image-first':'0.01','image-fallback':'0.03'})
        self.assertEqual({r['key_fingerprint'] for r in rows}, {'actual-image-key'})
        self.plugin.on_image_tool(tool_name='image_generate',result=result,tool_call_id='fallback',session_id='s1')
        self.assertEqual(len(self.plugin.ledger.rows()),2)

    def test_image_other_provider_and_invalid_results_do_not_record(self):
        for result in ['bad json', {}, dict(provider='fal',cost_usd='99'),
                       dict(provider='openrouter',cost_usd=True),dict(provider='openrouter',cost_usd='NaN')]:
            self.plugin.on_image_tool(tool_name='image_generate',result=result,tool_call_id='nope')
        self.assertEqual(self.plugin.ledger.rows(), [])

    def test_missing_cost_is_not_zero(self):
        self.execute(NS(id="gen-missing", usage=NS(prompt_tokens=3), model="m1"))
        report = self.plugin.ledger_report()
        self.assertIn("Unresolved costs: 1", report)
        self.assertIn("PARTIAL", report)

    def test_generation_dedup_across_sessions(self):
        self.execute(self.response())
        self.execute(self.response(), {**self.meta, "session_id": "s2", "started_at": 1780000001})
        self.assertEqual(len(self.plugin.ledger.rows()), 1)

    def test_real_retries_with_different_generations_count_separately(self):
        self.execute(self.response())
        self.execute(self.response(gid="gen-2"), {**self.meta, "started_at": 1780000001})
        self.assertEqual(len(self.plugin.ledger.rows()), 2)

    def test_provider_error_propagates_and_not_retried(self):
        calls = []
        def fail(req):
            calls.append(1)
            raise RuntimeError("provider failure")
        with self.assertRaisesRegex(RuntimeError, "provider failure"):
            self.plugin.on_execution(**self.meta, request={}, next_call=fail)
        self.assertEqual(len(calls), 1)
        self.plugin.on_error(**self.meta)
        self.assertEqual(self.plugin.ledger.rows()[0]["outcome"], "error")
        self.assertIsNone(self.plugin.ledger.rows()[0]["cost"])

    def test_storage_failure_preserves_response_and_single_call(self):
        with patch.object(self.plugin.ledger, "upsert", side_effect=OSError("disk full")):
            self.execute(self.response())

    def test_other_providers_are_ignored(self):
        self.execute(self.response(), {**self.meta, "provider": "custom", "base_url": "https://example.com"})
        self.assertEqual(self.plugin.ledger.rows(), [])
        self.assertFalse(spend.is_openrouter({"provider": "openrouter", "base_url": "https://openrouter.ai.evil.test"}))

    def test_auxiliary_missing_usage_counts_as_gap(self):
        self.plugin.on_auxiliary(**self.meta, aux_task="compression", usage=None, response=None, streaming=True)
        self.assertEqual(self.plugin.ledger.rows()[0]["category"], "auxiliary:compression")
        self.assertIn("Unresolved costs: 1", self.plugin.ledger_report())

    def test_auxiliary_retry_attempts_do_not_collapse(self):
        for retry in range(2):
            self.plugin.on_auxiliary(**self.meta, retry_count=retry, aux_task="vision", error="failed")
        self.assertEqual(len(self.plugin.ledger.rows()), 2)

    def test_invalid_costs_rejected(self):
        for value in (True, -1, "NaN", "Infinity", "bad", None):
            self.assertIsNone(spend.amount(value))

    def test_decimal_summation_and_persistence(self):
        for i in range(10):
            self.execute(self.response(gid=f"gen-{i}", cost="0.1"), {**self.meta, "started_at": 1780000000 + i})
        reopened = spend.SpendPlugin(self.temp.name)
        self.assertIn("Confirmed cost: $1.000000", reopened.ledger_report())

    def test_concurrent_writers_do_not_lose_records(self):
        def write(i):
            plugin = spend.SpendPlugin(self.temp.name)
            plugin.record({**self.meta, "started_at": 1780000000 + i}, self.response(gid=f"gen-{i}"))
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(write, range(20)))
        self.assertEqual(len(self.plugin.ledger.rows()), 20)

    def test_legacy_ledger_migration_preserves_costs(self):
        con = sqlite3.connect(self.plugin.ledger.path)
        con.execute('CREATE TABLE requests(attempt TEXT PRIMARY KEY,generation_id TEXT UNIQUE,occurred REAL NOT NULL,session TEXT NOT NULL,model TEXT NOT NULL,category TEXT NOT NULL,outcome TEXT NOT NULL,cost TEXT,source TEXT,prompt_tokens INTEGER,completion_tokens INTEGER,cached_tokens INTEGER)')
        con.execute("INSERT INTO requests VALUES('legacy','gen-legacy',1,'s1','m1','main','success','0.2','response',100,20,0)")
        con.commit();con.close()
        rows=self.plugin.ledger.rows()
        self.assertEqual(rows[0]['cost'],'0.2')
        self.assertIsNone(rows[0]['key_fingerprint'])
        self.execute(self.response())
        self.assertEqual(len(self.plugin.ledger.rows()),2)

    @patch.dict(os.environ, {"OPENROUTER_API_KEY": "secret-test-key"})
    def test_key_report_cache_and_private_snapshot(self):
        raw = {"usage": "12.500001", "usage_daily": 0, "usage_monthly": "2.1", "usage_weekly": None,
               "label": "secret-test-key", "byok_usage": "100"}
        with patch.object(spend, "get_json", return_value=raw) as get:
            report = self.plugin.command("")
            self.plugin.command("total")
            self.assertEqual(get.call_count, 1)
            self.assertIn("Total: $12.500001", report)
            self.assertIn("Today: $0.000000", report)
            self.assertIn("Week: unavailable", report)
            self.assertIn("not added to spend", report)
            self.assertNotIn("secret-test-key", report)
            self.assertNotIn(b"secret-test-key", self.plugin.ledger.path.read_bytes())
            self.plugin.command("refresh")
            self.assertEqual(get.call_count, 2)

    @patch.dict(os.environ, {"OPENROUTER_API_KEY": "key-1"})
    def test_stale_snapshot_labelled_and_key_rotation_separated(self):
        with patch.object(spend, "get_json", return_value={"usage": "1"}):
            self.plugin.command("")
        with patch.object(spend, "get_json", side_effect=ValueError("HTTP 401")):
            self.assertIn("STALE", self.plugin.command("refresh"))
            with patch.dict(os.environ, {"OPENROUTER_API_KEY": "key-2"}):
                self.assertTrue(self.plugin.command("refresh").startswith("Error:"))

    @patch.dict(os.environ, {}, clear=True)
    def test_missing_key_does_not_block_local_report(self):
        self.assertTrue(self.plugin.command("").startswith("Error:"))
        self.assertIn("Confirmed cost", self.plugin.command("ledger"))

    @patch.dict(os.environ, {"OPENROUTER_API_KEY": "secret"})
    def test_reconcile_updates_not_double_counts(self):
        self.execute(self.response(cost=None))
        with patch.object(spend, "get_json", return_value={"total_cost": "0.023"}) as get:
            self.assertIn("Resolved 1/1", self.plugin.command("reconcile"))
            self.assertEqual(get.call_count, 1)
        self.assertIn("Confirmed cost: $0.023000", self.plugin.command("ledger"))
        self.assertEqual(len(self.plugin.ledger.rows()), 1)

    def test_command_validation(self):
        for command in ("ledger nope", "total surprise", "models today extra", "unknown", "'unterminated"):
            self.assertTrue(self.plugin.command(command).startswith("Error:"))

    def test_redirect_disabled(self):
        self.assertIsNone(spend.NoRedirect().redirect_request(None, None, 302, None, {}, "https://example.com"))

    @patch.dict(os.environ, {"OPENROUTER_API_KEY": "key"})
    def test_summary_converts_usd_to_inr_and_caches_fx(self):
        with patch.object(spend, "get_json", return_value={"usage": "0.395125", "usage_daily": "0.025910"}):
            data = self.plugin.summary()
            self.assertEqual(Decimal(data["periods"]["total"]["inr"]), Decimal("0.395125") * Decimal("96.17"))
            self.assertEqual(data["fx"]["date"], "2026-10-04")
            self.assertIn("≈₹38.00", self.plugin.key_report())
            self.assertEqual(self.fx_fetch.call_count, 1)

    def test_fx_failure_never_invents_inr_value(self):
        self.fx_fetch.side_effect = ValueError("unavailable")
        fx = self.plugin.exchange_rate()
        self.assertIsNone(fx["rate"])
        self.assertIn("INR unavailable", self.plugin.dual_money(Decimal(1), fx))

    def test_manual_fx_rate_skips_external_api(self):
        self.plugin.get_config = lambda name, default=None: "100" if name == "usd_inr_rate" else default
        fx = self.plugin.exchange_rate()
        self.assertEqual(fx["source"], "manual")
        self.assertIn("₹100.00", self.plugin.dual_money(Decimal(1), fx))
        self.fx_fetch.assert_not_called()

    def test_cached_fx_is_marked_stale_on_refresh_failure(self):
        self.plugin.ledger.save_snapshot("usd-inr-reference", {"rate": "96", "date": "2026-10-03", "source": "Frankfurter"})
        self.plugin.get_config = lambda name, default=None: 300 if name == "fx_cache_seconds" else default
        with patch.object(spend.time, "time", return_value=99999999999):
            self.fx_fetch.side_effect = ValueError("offline")
            fx = self.plugin.exchange_rate()
        self.assertTrue(fx["stale"])
        self.assertEqual(fx["rate"], "96")


if __name__ == "__main__":
    unittest.main()
