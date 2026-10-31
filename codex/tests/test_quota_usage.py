"""Synthetic native quota journals only; no operator history."""
import copy
import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest

from tools import cu_auto_telemetry as auto
from tools.quota_usage import build_quota_usage, _window_total, _merge_reset_variants
from tools.work_units import load_rates


BASE=dt.datetime(2026,10,21,12,tzinfo=dt.timezone.utc)


def stamp(seconds):
    return (BASE+dt.timedelta(seconds=seconds)).isoformat()


def event(kind, seconds, **payload):
    return {'type':'event_msg','timestamp':stamp(seconds),'payload':{'type':kind,**payload}}


def counter(n, seconds, reset=3600):
    payload={'info':{'total_token_usage':{'input_tokens':n,'cached_input_tokens':n//2,'output_tokens':n//10}}}
    if reset is not None:
        payload['rate_limits']={'limit_id':'codex','primary':{'window_minutes':300,
            'resets_at':int((BASE+dt.timedelta(seconds=reset)).timestamp())}}
    return event('token_count',seconds,**payload)


class QuotaUsageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=Path(__file__).parents[1]);self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);(self.root/'.cd5').mkdir();(self.root/'sessions').mkdir()
        (self.root/'.cd5/config.json').write_text(json.dumps({'control_units':{'telemetry':{'session_roots':['sessions']}}}))

    def session(self, identity='hq', rows=None, parent=None, path=None):
        meta={'id':identity,'timestamp':stamp(1),'creator_account_id':'synthetic-account'}
        if parent:
            meta.update(parent_thread_id=parent,agent_path=path,timestamp=stamp(8),
                source={'subagent':{'thread_spawn':{'parent_thread_id':parent,'agent_path':path}}})
        file=self.root/'sessions'/(identity+'.jsonl')
        file.write_text('\n'.join(json.dumps(row) for row in [{'type':'session_meta','payload':meta},*(rows or [])])+'\n')
        return file

    def turn(self, name='one', start=5, end=40, snapshots=None):
        rows=[event('task_started',start,turn_id=name),
            {'type':'turn_context','timestamp':stamp(start),'payload':{'model':'gpt-6.1-sol','effort':'low'}},
            *(snapshots or [counter(120,10),counter(140,20)])]
        if end is not None:rows.append(event('task_complete',end,turn_id=name,duration_ms=1000))
        return rows

    def marks(self, file, cu='cu'):
        s=auto._read(file);turn=s['turns'][0]
        anchor={'thread_id':'hq','turn_id':turn['id'],'source_file':str(file.resolve()),
            'start_position':turn['start']['_position'],'start_sha256':turn['start']['_sha256'],
            'prefix_sha256':turn['start']['_prefix_sha256']}
        return [{'payload':{'type':'control_unit_event','action':'open','cu_id':cu,'auto_anchor':anchor},
                 'provenance':{'caller_thread_id':'hq'}}]

    def report(self, events):
        ids=list(dict.fromkeys(row['payload']['cu_id'] for row in events))
        data={'units':[{'cu_id':cu,'title':'Synthetic task','goal':'Inspect synthetic cases','result':'Synthetic result',
                        'participants':[],'usage':dict.fromkeys(auto.FIELDS),'usage_status':'unknown'} for cu in ids]}
        return auto.enrich_report(self.root,data,events)

    def run_report(self, file):
        events=self.marks(file);return build_quota_usage(self.root,self.report(events),events)

    def test_observed_reset_exact_delta_conservation_readonly(self):
        file=self.session(rows=[counter(100,0),*self.turn()])
        before={p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        events=self.marks(file);data=self.report(events);original=copy.deepcopy(data)
        result=build_quota_usage(self.root,data,events)
        self.assertEqual(len(result['windows']),1)
        row=result['windows'][0]['assignments'][0]
        self.assertEqual(row['usage'],{'cached_input':20,'uncached_input':20,'output':4})
        self.assertEqual(row['request_count'],2)
        self.assertEqual(result['windows'][0]['ends_at'],stamp(3600))
        self.assertEqual(result['windows'][0]['starts_at'],stamp(3600-18000))
        self.assertIsNone(result['account_total']);self.assertEqual(data,original)
        self.assertEqual(before,{p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_requested_dates_filter_recorded_observations_without_window_extrapolation(self):
        file=self.session(rows=[counter(100,0),*self.turn()])
        events=self.marks(file);data=self.report(events)
        data['scope']={'since':'2026-10-22','until':'2026-10-22'}
        result=build_quota_usage(self.root,data,events)
        self.assertEqual(result['windows'],[])
        self.assertEqual(result['unassigned'],[])
        data['scope']={'since':'2026-10-21','until':'2026-10-21'}
        result=build_quota_usage(self.root,data,events)
        self.assertEqual(len(result['windows']),1)
        self.assertEqual(result['windows'][0]['assignments'][0]['request_count'],2)

    def test_missing_reset_never_extrapolated_from_other_snapshot(self):
        file=self.session(rows=[counter(100,0),*self.turn(snapshots=[counter(120,10,None),counter(140,20)])])
        result=self.run_report(file)
        assigned=result['windows'][0]['assignments'][0];unknown=result['unassigned'][0]
        self.assertEqual(assigned['usage']['output'],2);self.assertEqual(unknown['usage']['output'],2)
        self.assertIn('native_reset_boundary_unavailable',unknown['diagnostics'])

    def test_cross_reset_span_unassigned_then_new_requests_attributed(self):
        file=self.session(rows=[counter(100,0),*self.turn(end=4000,snapshots=[counter(120,3590,3600),
            counter(140,3610,21600),counter(160,3620,21600)])])
        result=self.run_report(file)
        self.assertEqual(len(result['windows']),2)
        self.assertEqual(result['unassigned'][0]['usage']['output'],2)
        self.assertIn('request_span_crosses_or_lacks_reset_boundary',result['unassigned'][0]['diagnostics'])
        self.assertEqual(sum(r['usage']['output'] for w in result['windows'] for r in w['assignments'])+
            sum(r['usage']['output'] for r in result['unassigned']),6)

    def test_unchanged_counter_cannot_move_request_start_across_reset(self):
        file=self.session(rows=[counter(100,0),*self.turn(end=4000,snapshots=[
            counter(120,3590,3600),counter(120,3601,21600),counter(140,3610,21600)])])
        result=self.run_report(file)
        self.assertEqual(len(result['windows']),1)
        self.assertEqual(result['unassigned'][0]['usage']['output'],2)
        self.assertIn('request_span_crosses_or_lacks_reset_boundary',result['unassigned'][0]['diagnostics'])

    def test_shared_turn_reset_or_model_mix_not_allocated(self):
        file=self.session(rows=[counter(100,0),*self.turn()]);events=self.marks(file,'a')+self.marks(file,'b')
        result=build_quota_usage(self.root,self.report(events),events)
        # Ambiguous CU ownership does not erase measured quota consumption.
        self.assertEqual(len(result['windows']),1);self.assertTrue(result['diagnostics'])
        self.assertTrue(all(r['cu_id'] is None for r in result['windows'][0]['assignments']))
        self.assertEqual(sum(r['request_count'] for r in result['windows'][0]['assignments']),2)
        file=self.session(rows=[counter(200,0),*self.turn()])
        self.assertEqual(self.run_report(file)['windows'],[])

    def test_pending_observed_usage_is_partial_and_repeated_counter_not_request(self):
        file=self.session(rows=[counter(100,0),*self.turn(end=None,snapshots=[counter(120,10),counter(120,11)])])
        result=self.run_report(file);row=result['windows'][0]['assignments'][0]
        self.assertEqual(row['coverage'],'partial');self.assertEqual(row['request_count'],1)
        self.assertIsNone(row['work_units']['value']);self.assertIsNotNone(row['work_units']['known_value'])

    def test_verified_saved_spawn_then_exact_followup_distinct_rows_no_team_sum(self):
        calls=[{'type':'response_item','timestamp':stamp(6),'payload':{'type':'function_call','name':'spawn_agent',
                    'call_id':'call1','arguments':json.dumps({'task_name':'worker','message':'Synthetic inspect brief'})}},
               {'type':'response_item','timestamp':stamp(7),'payload':{'type':'function_call_output','call_id':'call1',
                    'output':json.dumps({'task_name':'/root/worker'})}},
               {'type':'response_item','timestamp':stamp(20),'payload':{'type':'function_call','name':'followup_task',
                    'call_id':'call2','arguments':json.dumps({'target':'/root/worker','message':'Synthetic followup'})}}]
        file=self.session(rows=[counter(100,0),*self.turn(snapshots=[*calls,counter(140,35)])])
        child=self.session('child',[counter(0,1),*self.turn('child-one',8,15,[counter(20,10)]),
            *self.turn('child-two',21,30,[counter(40,25)]),
            *self.turn('child-three',32,34,[counter(60,33)])],parent='hq',path='/root/worker')
        result=self.run_report(file);rows=result['windows'][0]['assignments']
        briefs=[r['assignment']['text'] for r in rows if r['thread_id']=='child']
        self.assertEqual(briefs,['Synthetic inspect brief','Synthetic followup',None])
        self.assertTrue(all(r['role']=='роль не указана' for r in rows if r['thread_id']=='child'))
        self.assertNotIn('usage',result['windows'][0])
        actor=next(a for a in result['windows'][0]['actors'] if a['thread_id']=='child')
        self.assertEqual(actor['usage']['output'],6);self.assertEqual(actor['request_count'],3)
        self.assertEqual(result['windows'][0]['total']['status'],'partial')
        self.assertIsNotNone(result['windows'][0]['total']['known_value'])

    def test_hash_witness_mutation_blocks_stale_report_and_append_is_bounded(self):
        file=self.session(rows=[counter(100,0),*self.turn(end=None)])
        events=self.marks(file);data=self.report(events)
        with file.open('a') as stream:stream.write(json.dumps(counter(160,30))+'\n')
        # New native snapshots beyond the supplied report witness are not read
        # into an old observation selection behind the caller's back.
        result=build_quota_usage(self.root,data,events)
        self.assertEqual(result['windows'][0]['assignments'][0]['usage']['output'],4)
        file.write_text(file.read_text().replace('"input_tokens": 100','"input_tokens": 110'))
        self.assertEqual(build_quota_usage(self.root,data,events)['windows'],[])

    def test_exact_overlapping_reset_variants_preserved_and_marked(self):
        file=self.session(rows=[counter(100,0),*self.turn(snapshots=[counter(120,10,3600),counter(140,20,3601)])])
        result=self.run_report(file)
        self.assertEqual(len(result['windows']),1)
        window=result['windows'][0]
        self.assertEqual([v['ends_at'] for v in window['boundary_variants']],[stamp(3600),stamp(3601)])
        self.assertEqual(sum(r['request_count'] for r in window['assignments']),2)
        self.assertIn('native_reset_jitter_coalesced',window['diagnostics'])
        self.assertEqual(sum(row['usage']['output'] for row in window['assignments']),4)

    def test_one_total_does_not_add_parent_inclusive_child_counts(self):
        def row(thread, value, exclusive=False):
            return {'thread_id':thread,'exclusive_scope':exclusive,
                    'work_units':{'known_value':value,'status':'complete'}}
        total=_window_total([row('parent','10'),row('child','7')])
        self.assertEqual(total['known_value'],'10')
        self.assertEqual(total['status'],'partial')
        total=_window_total([row('parent','10',True),row('child','7',True)])
        self.assertEqual(total['value'],'17')
        self.assertEqual(total['method'],'exclusive_sum')
        total=_window_total([row('parent','10'),row('a','7',True),row('b','6',True)])
        self.assertEqual(total['known_value'],'13')

    def test_reset_jitter_does_not_chain_or_merge_accounts(self):
        def window(end, account='a', verified=True):
            return {'window_id':account+str(end),'starts_at':stamp(end-18000),'ends_at':stamp(end),
                    'account_scope_key':account,'account_identity_verified':verified,'limit_id':'codex',
                    'assignments':[],'reset_evidence':[],'diagnostics':[]}
        result=_merge_reset_variants([window(3600),window(3602),window(3604),window(3601,'b'),window(3601,'c',False)])
        self.assertEqual(len(result),4)
        self.assertEqual(len(result[0]['boundary_variants']),2)

    def test_custom_tariff_path_and_duplicate_input_conservation(self):
        file=self.session(rows=[counter(100,0),*self.turn()]);events=self.marks(file);data=self.report(events)
        data['units'][0]['participants']*=2
        rates=load_rates();rates['rates_per_million']['gpt-6.1-sol']={k:'100' for k in auto.FIELDS}
        tariff=self.root/'rates.json';tariff.write_text(json.dumps(rates))
        result=build_quota_usage(self.root,data,events,rate_path=tariff)
        row=result['windows'][0]['assignments'][0]
        self.assertEqual(row['usage']['output'],4);self.assertEqual(row['work_units']['value'],'0.0044')

    def test_only_explicit_native_final_answer_exposed_not_analysis(self):
        rows=self.turn();rows[-1]['payload']['last_agent_message']='Synthetic completed inspection'
        rows.insert(2,{'type':'response_item','timestamp':stamp(6),'payload':{'type':'message','role':'assistant',
            'phase':'analysis','content':[{'type':'output_text','text':'Private synthetic analysis'}]}})
        file=self.session(rows=[counter(100,0),*rows]);row=self.run_report(file)['windows'][0]['assignments'][0]
        self.assertEqual(row['agent_result']['text'],'Synthetic completed inspection')
        self.assertNotIn('Private synthetic analysis',json.dumps(row['agent_result']))


if __name__=='__main__':unittest.main()
