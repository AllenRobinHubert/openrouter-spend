import importlib.util
from pathlib import Path
import sqlite3
from decimal import Decimal
from contextlib import closing
from tempfile import TemporaryDirectory
import unittest

def module(name):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).parents[1]/(name+'.py'))
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod

analytics=module('analytics')
spend=module('spend')

class AnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.profile('default')
        self.profile('coder')

    def profile(self,name):
        home=self.root if name=='default' else self.root/'profiles'/name
        home.mkdir(parents=True,exist_ok=True);(home/'config.yaml').write_text('')
        c=sqlite3.connect(home/'state.db')
        c.execute('CREATE TABLE sessions(id TEXT, profile_name TEXT, billing_provider TEXT, billing_base_url TEXT,input_tokens INTEGER, output_tokens INTEGER,cache_read_tokens INTEGER,cache_write_tokens INTEGER,last_activity_at REAL)')
        c.execute('CREATE TABLE session_model_usage(session_id TEXT,model TEXT,billing_provider TEXT,billing_base_url TEXT,task TEXT,input_tokens INTEGER,output_tokens INTEGER,cache_read_tokens INTEGER,cache_write_tokens INTEGER,last_seen REAL)')
        c.close();return home

    def history(self,home_name='default',sid='s1',profile='default',provider='openrouter',tokens=100,cached=50,output=20,stamp=1,model='m1',residual=0):
        home=self.root if home_name=='default' else self.root/'profiles'/home_name
        c=sqlite3.connect(home/'state.db')
        c.execute('INSERT INTO sessions VALUES(?,?,?,?,?,?,?,?,?)',(sid,profile,provider,'',tokens+residual,output,cached,0,stamp))
        c.execute('INSERT INTO session_model_usage VALUES(?,?,?,?,?,?,?,?,?,?)',(sid,model,provider,'','',tokens,output,cached,0,stamp))
        c.commit();c.close()

    def request(self,gid='gen-1',tokens=100,cost='0.01',key='key',profile='coder',session='',category='main'):
        home=self.root/'profiles'/'coder'
        ledger=spend.Ledger(home/'plugin-data/openrouter-spend')
        ledger.upsert(dict(attempt=gid,generation_id=gid if gid.startswith('gen-') else None,occurred=1,session=session,model='m1',category=category,
                          outcome='success',cost=cost,source='response',prompt_tokens=tokens,completion_tokens=0,cached_tokens=None,key_fingerprint=key,profile=profile))

    def build(self):
        return analytics.build_analytics(self.root,Decimal('100'),spend.is_openrouter,spend.amount)

    def test_cached_tokens_count_once_and_profile_model_sum_match(self):
        self.history();self.history('coder','s2','coder',tokens=10,cached=0,output=2)
        data=self.build()
        self.assertEqual(data['total_tokens'],182)
        self.assertEqual(sum(r['tokens'] for r in data['models']),182)
        self.assertEqual({r['name']:r['tokens'] for r in data['profiles']},{'default':170,'coder':12,'Other':0})

    def test_unknown_profile_and_unattributed_model_go_to_other(self):
        self.history(profile='deleted-profile',residual=30)
        data=self.build()
        self.assertEqual(next(r for r in data['profiles'] if r['name']=='Other')['tokens'],200)
        self.assertEqual(next(r for r in data['models'] if r['name']=='Other')['tokens'],30)

    def test_other_providers_excluded(self):
        self.history(provider='anthropic')
        self.assertEqual(self.build()['total_tokens'],0)

    def test_duplicate_cross_profile_session_uses_newest_snapshot(self):
        self.history(stamp=1)
        self.history('coder','s1','coder',tokens=200,stamp=2)
        data=self.build()
        self.assertEqual(data['total_tokens'],270)
        self.assertEqual(next(r for r in data['profiles'] if r['name']=='coder')['tokens'],270)

    def test_average_pairs_cost_and_tokens_across_recorded_keys(self):
        self.request(tokens=100,cost='0.01')
        self.request('gen-2',tokens=900,cost=None)
        self.request('gen-3',tokens=None,cost='99')
        self.request('gen-4',tokens=100,cost='0.03',key='different-key')
        data=self.build()
        self.assertEqual(data['average']['usd'],'200.00')
        self.assertEqual(data['average']['inr'],'20000.00')
        self.assertEqual(data['paired_tokens'],200)
        self.assertEqual(data['unresolved_requests'],2)

    def test_legacy_records_without_key_fingerprint_keep_confirmed_costs(self):
        self.request(tokens=100,cost='0.02',key=None)
        self.request('gen-2',tokens=300,cost='0',key=None)
        data=self.build()
        self.assertEqual(data['average']['usd'],'50.00')
        self.assertEqual(data['paired_tokens'],400)
        coder=next(r for r in data['profiles'] if r['name']=='coder')
        self.assertEqual(coder['cost'],{'usd':'0.02','inr':'2.00'})
        self.assertEqual(data['cost_scope'],'Confirmed plugin costs · all recorded OpenRouter keys')

    def test_plugin_and_history_tokens_not_double_counted(self):
        self.history('coder','s1','coder',tokens=100,cached=0,output=0)
        self.request(tokens=100,session='s1')
        self.assertEqual(self.build()['total_tokens'],100)

    def test_image_cost_and_total_tokens_pair_without_double_counting_history(self):
        self.history('coder','s1','coder',tokens=148,cached=0,output=4175,model='recraft/recraft-v4.1')
        plugin = spend.SpendPlugin(self.root/'profiles/coder/plugin-data/openrouter-spend',profile='coder')
        plugin.on_image_tool(tool_name='image_generate', tool_call_id='image-1', session_id='s1',
                             result=dict(provider='openrouter',model='recraft/recraft-v4.1',cost_usd=0.035,total_tokens=4323))
        data = self.build()
        self.assertEqual(data['total_tokens'],4323)
        self.assertEqual(data['paired_tokens'],4323)
        model=next(r for r in data['models'] if r['name']=='recraft/recraft-v4.1')
        self.assertEqual(model['cost'],dict(usd='0.035',inr='3.500'))
        self.assertEqual(data['average']['usd'],str(Decimal('0.035')*1000000/4323))

    def test_manual_other_adds_tokens_and_paired_cost_without_mutating_history(self):
        self.history();self.request('manual-1',tokens=1000,cost='0.02',category='manual',profile='Other')
        data=self.build()
        self.assertEqual(data['total_tokens'],1170)
        self.assertEqual(next(r for r in data['profiles'] if r['name']=='Other')['tokens'],1000)
        self.assertEqual(data['average']['usd'],'20.00')

    def test_no_costs_is_unknown_and_zero_cost_is_valid(self):
        self.history()
        self.assertIsNone(self.build()['average']['usd'])
        self.request(cost='0')
        self.assertEqual(self.build()['average']['usd'],'0')

    def attributed(self,total):
        return analytics.build_analytics(self.root,Decimal('100'),spend.is_openrouter,spend.amount,
                                         active_key_fingerprint='key',key_total_usd=total)

    def test_paid_spend_without_request_metadata_visible_as_other(self):
        self.request(cost='0',key=None)
        data=self.attributed('0.4')
        self.assertEqual(data['attribution']['other'],{'usd':'0.4','inr':'40.0'})
        self.assertIsNone(data['attribution']['tokens'])
        self.assertEqual(data['average']['usd'],'0')
        self.assertEqual(data['paired_tokens'],100)

    def test_only_confirmed_current_key_charges_reduce_unassigned_spend(self):
        self.request(cost='0.1')
        self.request('gen-2',cost='0.3',key='another-key')
        self.request('gen-3',cost='0.2',key=None)
        self.request('manual-1',cost='0.1',category='manual',profile='Other')
        data=self.attributed('0.5')
        self.assertEqual(data['attribution']['assigned']['usd'],'0.1')
        self.assertEqual(data['attribution']['other']['usd'],'0.4')

    def test_duplicate_generation_subtracted_once_from_key_total(self):
        self.request(cost='0.1')
        source=self.root/'profiles/coder/plugin-data/openrouter-spend/spend.sqlite3'
        target=self.root/'plugin-data/openrouter-spend/spend.sqlite3'
        target.parent.mkdir(parents=True)
        with closing(sqlite3.connect(source)) as original,closing(sqlite3.connect(target)) as copy:
            original.backup(copy)
        original.close();copy.close()
        self.assertEqual(self.attributed('0.5')['attribution']['other']['usd'],'0.4')

    def test_table_key_costs_reconcile_and_legacy_image_is_not_added_twice(self):
        self.request(cost='0.01')
        self.request('gen-image',cost='0.035',key=None)
        data=self.attributed('0.5')
        for kind in ('profiles','models'):
            self.assertEqual(sum(Decimal(row['key_cost']['usd']) for row in data[kind]),Decimal('0.5'))
            self.assertEqual(sum(Decimal(row['outside_key_cost']['usd']) for row in data[kind]),Decimal('0.035'))
            other=next(row for row in data[kind] if row['name']=='Other')
            self.assertEqual(other['key_cost']['usd'],'0.49')

    def test_confirmed_other_and_manual_costs_do_not_double_count_remainder(self):
        self.request(cost='0.1',profile='deleted-profile')
        self.request('manual-entry',cost='0.2',category='manual')
        data=self.attributed('0.5')
        other=next(row for row in data['profiles'] if row['name']=='Other')
        self.assertEqual(other['key_cost']['usd'],'0.5')
        self.assertEqual(other['outside_key_cost']['usd'],'0.2')
        self.assertEqual(other['unassigned_cost']['usd'],'0.4')

    def test_unknown_key_does_not_invent_zero_key_cost(self):
        self.request()
        self.assertTrue(all(row['key_cost']['usd'] is None for row in self.build()['profiles']))

    def test_custom_comparison_baseline_and_fx_conversion(self):
        result=analytics.monthly_comparison({'usd':'20','inr':'2000'},Decimal('100'),'40','','Budget')
        self.assertEqual(result['baseline'],{'usd':'40','inr':'4000'})
        self.assertEqual(result['fraction'],'0.5')
        self.assertEqual(result['label'],'Budget')
        for value in ('0','-1','NaN','Infinity','oops'):
            with self.assertRaises(ValueError):
                analytics.monthly_comparison({'usd':None,'inr':None},None,value)
        self.assertIsNone(analytics.monthly_comparison({'usd':None,'inr':None},None,'40','')['baseline']['inr'])

    def test_stale_provider_total_does_not_create_negative_remainder(self):
        self.request(cost='0.2')
        data=self.attributed('0.1')['attribution']
        self.assertTrue(data['pending'])
        self.assertIsNone(data['other']['usd'])
        self.assertIsNone(self.attributed(None)['attribution']['other']['usd'])

    def test_monthly_baselines_fixed_single_usd_fraction_and_overspend(self):
        result=analytics.monthly_comparison({'usd':'55','inr':'5500'},Decimal('100'))
        self.assertEqual(result['fraction'],'0.5')
        self.assertEqual(result['saved'],{'usd':'55','inr':'5199'})
        self.assertEqual(result['baseline'],{'usd':'110','inr':'10699'})
        over=analytics.monthly_comparison({'usd':'120','inr':'12000'},Decimal('100'))
        self.assertEqual(over['saved'],{'usd':'-10','inr':'-1301'})

    def chat(self, sid='s1'):
        return analytics.chat_cost(self.root,sid,spend.amount)

    def test_chat_counts_confirmed_main_and_image_costs_only_for_selected_chat(self):
        self.history('coder','s1','coder',tokens=100,cached=0,output=0)
        self.request(session='s1',cost='0.02')
        self.request('gen-image',session='s1',category='image',cost='0.035')
        self.request('gen-unrelated',session='s2',cost='99')
        self.request('manual',session='s1',category='manual',cost='99')
        data=self.chat()
        self.assertEqual(data['usd'],'0.055')
        self.assertEqual(data['confirmed_requests'],2)
        self.assertFalse(data['partial'])

    def test_chat_unknown_cost_not_zero_and_known_zero_is_preserved(self):
        self.history('coder','s1','coder',tokens=100,cached=0,output=0)
        self.assertIsNone(self.chat()['usd'])
        self.request(session='s1',cost=None)
        self.assertIsNone(self.chat()['usd'])
        self.assertTrue(self.chat()['partial'])
        self.request(session='s1',cost='0')
        self.assertEqual(self.chat()['usd'],'0')
        self.assertFalse(self.chat()['partial'])
        self.assertEqual(self.chat('')['usd'],'0')

    def test_chat_compression_continues_total_but_branch_and_reset_stay_separate(self):
        home=self.root/'profiles/coder'
        self.history('coder','s1','coder',tokens=100,cached=0,output=0)
        self.history('coder','s2','coder',tokens=100,cached=0,output=0)
        self.history('coder','branch','coder',tokens=100,cached=0,output=0)
        self.history('coder','reset','coder',tokens=100,cached=0,output=0)
        with closing(sqlite3.connect(home/'state.db')) as c:
            c.execute('ALTER TABLE sessions ADD COLUMN parent_session_id TEXT')
            c.execute('ALTER TABLE sessions ADD COLUMN end_reason TEXT')
            c.execute('ALTER TABLE sessions ADD COLUMN model_config TEXT')
            c.execute("UPDATE sessions SET end_reason='compression' WHERE id='s1'")
            c.execute("UPDATE sessions SET parent_session_id='s1' WHERE id!='s1'")
            c.execute('UPDATE sessions SET model_config=? WHERE id=?',('{"_branched_from":"s1"}','branch'))
            c.execute('UPDATE sessions SET model_config=? WHERE id=?',('{"_reset_from":"s1"}','reset'))
            c.commit()
        for sid,cost in [('s1','0.1'),('s2','0.2'),('branch','9'),('reset','8')]:
            self.request('gen-'+sid,session=sid,cost=cost)
        self.assertEqual(self.chat('s1')['usd'],'0.3')
        self.assertEqual(self.chat('s2')['usd'],'0.3')
        self.assertEqual(self.chat('branch')['usd'],'9')
        self.assertEqual(self.chat('reset')['usd'],'8')

    def test_chat_duplicate_handoff_charge_counted_once_and_incomplete_history_marked(self):
        self.history('coder','s1','coder',tokens=200,cached=0,output=0)
        self.request(session='s1',cost='0.1',tokens=100)
        source=self.root/'profiles/coder/plugin-data/openrouter-spend/spend.sqlite3'
        target=self.root/'plugin-data/openrouter-spend/spend.sqlite3'
        target.parent.mkdir(parents=True)
        with closing(sqlite3.connect(source)) as original,closing(sqlite3.connect(target)) as copy:
            original.backup(copy)
        data=self.chat()
        self.assertEqual(data['usd'],'0.1')
        self.assertEqual(data['confirmed_requests'],1)
        self.assertTrue(data['partial'])

if __name__=='__main__':unittest.main()
