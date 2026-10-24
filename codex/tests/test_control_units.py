import json
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import control_units as cu
import project_memory as pm
from cu_archive import archive_evidence
from tests.cd5_fixtures import configure


class ControlUnitTests(unittest.TestCase):
    def test_auto_anchor_retry_keeps_original_turn_and_historical_skips(self):
        anchor={'thread_id':'owner','turn_id':'original-turn','recorded_at':'2026-10-21T10:00:00+00:00'}
        with patch('cu_auto_telemetry.capture_anchor', return_value=anchor) as capture:
            first=self.open()
            self.assertEqual(first['payload']['auto_anchor'],anchor)
            capture.return_value={**anchor,'turn_id':'retry-turn'}
            self.assertEqual(first,self.open())
            self.assertEqual(capture.call_count,1)
            self.open('history',historical=True,at='2026-10-01T00:00:00+00:00')
            self.record('status','history',status='completed',result='Historical',at='2026-10-01T01:00:00+00:00')
            self.assertEqual(capture.call_count,1)
        self.assertEqual(json.loads((self.root/'coordination/cd5/CHECKPOINT.json').read_text()),self.cp)

    def test_begin_finish_cli_reuse_short_text_and_are_idempotent(self):
        with patch('cu_auto_telemetry.capture_anchor', return_value=None), patch('builtins.print'):
            begin=['--root',str(self.root),'begin','--cu','simple','--title','Existing brief','--caller-thread','owner',
                   '--forecast-unknown-reason','Synthetic task has no calibrated estimate']
            finish=['--root',str(self.root),'finish','--cu','simple','--result','Existing outcome','--caller-thread','owner']
            self.assertEqual(cu.main(begin),0);self.assertEqual(cu.main(begin),0)
            self.assertEqual(cu.main(finish),0);self.assertEqual(cu.main(finish),0)
        events=cu._events(self.root)
        self.assertEqual(len(events),2)
        self.assertEqual(events[0]['payload']['goal'],'Existing brief')
        self.assertEqual(events[1]['payload']['result'],'Existing outcome')

    def test_new_cu_cannot_silently_share_an_already_claimed_owner_turn(self):
        anchor={'thread_id':'owner','turn_id':'one','recorded_at':'2026-10-21T10:00:00+00:00'}
        with patch('cu_auto_telemetry.capture_anchor', return_value=anchor) as capture:
            first=self.open('first')
            self.assertEqual(first,self.open('first'))

            with self.assertRaisesRegex(ValueError,'new user turn'):
                self.open('second')
            self.assertEqual(len(cu._events(self.root)),1)
            self.record('status','first',status='completed',result='Synthetic result')
            with self.assertRaisesRegex(ValueError,'already belongs to CU first'):
                self.open('second')
            capture.return_value={**anchor,'turn_id':'two'}
            self.open('second')
            self.assertEqual(len(cu._events(self.root)),3)
            # An opening retry keeps its original anchor after the turn changes.
            self.assertEqual(first,self.open('first'))

    def test_closing_mark_also_reserves_current_turn_for_its_original_cu(self):
        anchor={'thread_id':'owner','turn_id':'one','recorded_at':'2026-10-21T10:00:00+00:00'}
        with patch('cu_auto_telemetry.capture_anchor', return_value=anchor) as capture:
            self.open('first')
            capture.return_value={**anchor,'turn_id':'two'}
            self.record('status','first',status='completed',result='Synthetic result')
            with self.assertRaisesRegex(ValueError,'new user turn'):
                self.open('second')
        self.assertEqual(len(cu._events(self.root)),2)

    def test_paused_resume_cannot_claim_another_cus_marked_turn(self):
        anchor={'thread_id':'owner','turn_id':'one','recorded_at':'2026-10-21T10:00:00+00:00'}
        with patch('cu_auto_telemetry.capture_anchor', return_value=anchor) as capture:
            self.open('first')
            self.record('status','first',event_id='pause-first',status='paused')
            capture.return_value={**anchor,'turn_id':'two'}
            self.open('second')
            self.record('status','second',event_id='pause-second',status='paused')
            count=len(cu._events(self.root))
            with self.assertRaisesRegex(ValueError,'already belongs to CU second'):
                self.record('status','first',event_id='resume-first',status='open')
            self.assertEqual(len(cu._events(self.root)),count)
            capture.return_value={**anchor,'turn_id':'three'}
            resumed=self.record('status','first',event_id='resume-first',status='open')
            capture.return_value={**anchor,'turn_id':'two'}
            self.assertEqual(resumed,self.record('status','first',event_id='resume-first',status='open'))

    def test_record_requires_prospective_plan_but_preserves_historical_import(self):
        data={'action':'open','event_id':'bare','cu_id':'bare','title':'Synthetic task','goal':'Synthetic result'}
        with patch('cu_auto_telemetry.capture_anchor', return_value=None):
            with self.assertRaisesRegex(ValueError,'forecast_unknown_reason'):
                cu.record(self.root,data,'owner')
            self.assertEqual(cu._events(self.root),[])
            historical=cu.record(self.root,{**data,'historical':True},'owner')
            self.assertEqual(historical,cu.record(self.root,{**data,'historical':True},'owner'))
            self.assertNotIn('forecast_unknown_reason',historical['payload'])
            planned=cu.record(self.root,{**data,'event_id':'planned','cu_id':'planned',
                'forecast':{'low':'1','high':'2'}},'owner')
            self.assertEqual(planned['payload']['budget']['forecast']['low'],'1')
            self.assertNotIn('limit',planned['payload']['budget'])

    def test_participant_cli_resolves_path_to_native_identity_and_explicit_role(self):
        self.open('first')
        args=['--root',str(self.root),'participant','--cu','first','--caller-thread','owner',
              '--agent-path','/root/worker','--role','executor']
        with patch('cu_auto_telemetry.resolve_agent_identity',return_value='native-worker') as resolve, patch('builtins.print'):
            self.assertEqual(cu.main(args),0)
            self.assertEqual(cu.main(args),0)
        resolve.assert_called_with(self.root.resolve(),'/root/worker','owner')
        person=cu._events(self.root)[-1]['payload']['participant']
        self.assertEqual(person['thread_id'],'native-worker')
        self.assertEqual(person['role'],'executor')
        self.assertEqual(person['parent_thread_id'],'owner')
        self.assertEqual(len(cu._events(self.root)),2)
        with patch('cu_auto_telemetry.resolve_agent_identity',side_effect=ValueError('retry after native session header exists')):
            with self.assertRaisesRegex(ValueError,'retry after'):
                self.record('participant','first',event_id='not-ready',participant={
                    'agent_path':'/root/new','role':'helper'})
        self.assertEqual(len(cu._events(self.root)),2)

    def setUp(self):
        self.root=Path(tempfile.mkdtemp(prefix='.cu-test-',dir=ROOT))
        self.addCleanup(lambda: shutil.rmtree(self.root))
        configure(self.root)
        base=self.root/'coordination/cd5';base.mkdir(parents=True)
        for name in pm.FILES.values(): (base/name).write_text('',encoding='utf-8')
        self.cp={'schema_version':3,'memory':{k:'coordination/cd5/'+v for k,v in pm.FILES.items()},
                 'owner':{'role':'hq','thread_id':'owner'},'user_stop':{'active':True},'next_action':{'kind':'wait_user'}}
        (base/'CHECKPOINT.json').write_text(json.dumps(self.cp))

    def record(self,action,unit='cu-a',**fields):
        return cu.record(self.root,{'cu_id':unit,'event_id':fields.pop('event_id',action+'-'+unit),
                                   'action':action,**fields},'owner')

    def open(self,unit='cu-a',**fields):
        if not fields.get('historical') and not fields.get('forecast'):
            fields.setdefault('forecast_unknown_reason','Synthetic fixture has no calibrated forecast')
        return self.record('open',unit,**{'title':unit,'goal':'Получить проверяемый результат',**fields})

    def person(self,thread='owner',role='hq',parent=None):
        return self.record('participant',event_id='person-'+thread,participant={
            'thread_id':thread,'name':thread,'role':role,'parent_thread_id':parent})

    def test_single_owner_pause_resume_complete_and_stop_preserved(self):
        self.open(at='2026-10-01T10:00:00+03:00');self.person()
        self.record('status',event_id='pause',status='paused',at='2026-10-01T11:00:00+03:00')
        row=cu.report_data(self.root)['units'][0]
        self.assertEqual(row['status'],'paused');self.assertIsNone(row['ended_at'])
        self.record('status',event_id='resume',status='open',at='2026-10-02T10:00:00+03:00')
        self.record('status',event_id='end',status='completed',result='Отрицательный вывод',at='2026-10-02T11:00:00+03:00')
        row=cu.report_data(self.root)['units'][0]
        self.assertEqual(row['result'],'Отрицательный вывод');self.assertEqual(row['status'],'completed')
        cp=json.loads((self.root/'coordination/cd5/CHECKPOINT.json').read_text())
        self.assertEqual(cp,self.cp)
        with self.assertRaisesRegex(ValueError,'reopen'):
            self.record('status',event_id='bad-reopen',status='open')

    def test_owner_identity_idempotence_and_invalid_end(self):
        first=self.open();self.assertEqual(first,self.open())
        with self.assertRaisesRegex(ValueError,'owner'):
            cu.record(self.root,{'action':'open','event_id':'other','cu_id':'other','title':'t','goal':'g'},'wrong')
        with self.assertRaises(ValueError):self.record('status',status='completed')
        with self.assertRaises(ValueError):self.open(title='changed')
        self.assertEqual(len(cu.report_data(self.root)['units']),1)

    def test_linked_task_cannot_be_counted_twice(self):
        self.open();self.open('cu-b')
        self.record('link_task',task_id='task-one')
        with self.assertRaisesRegex(ValueError,'two Control Units'):
            self.record('link_task','cu-b',task_id='task-one')

    def mapping(self,thread='owner',parent=None,role='hq',end=20):
        path=self.root/(thread+'.jsonl')
        meta={'id':thread}
        if parent:meta.update(parent_thread_id=parent,source={'subagent':{'thread_spawn':{'parent_thread_id':parent}}})
        def count(n):return {'type':'token_count','info':{'total_token_usage':{'input_tokens':n,'cached_input_tokens':n//2,'output_tokens':n//5,'reasoning_output_tokens':0}}}
        rows=[{'type':'session_meta','payload':meta},{'type':'event_msg','payload':count(0)},
              {'type':'event_msg','payload':{'type':'task_started','turn_id':'turn'}},
              {'type':'turn_context','payload':{'turn_id':'turn','model':'model','effort':'low'}},
              {'type':'event_msg','payload':count(end)},
              {'type':'event_msg','payload':{'type':'task_complete','turn_id':'turn','duration_ms':1000}}]
        for i,row in enumerate(rows):row['ordinal']=i
        path.write_text('\n'.join(json.dumps(r) for r in rows),encoding='utf-8')
        return {'task_id':'cu-a','owner_thread_id':'owner','participants':[{'thread_id':thread,'role':role,
                'parent_thread_id':parent,'source_file':str(path),'baseline_ordinal':1,'end_ordinal':4}]}

    def test_measurement_unknown_scope_then_verified_sum_and_duplicate(self):
        self.open();self.person();self.person('child','helper','owner')
        a=self.mapping();b=self.mapping('child','owner','helper');a['participants']+=b['participants']
        cu.measure(self.root,'cu-a',a,'measurement-a','owner')
        row=cu.report_data(self.root)['units'][0]
        self.assertEqual(row['participants'][0]['usage']['cached_input'],10)
        self.assertEqual(row['reported_ms'],1000)
        self.assertIsNone(row['usage']['cached_input'])
        # New, explicitly witnessed scope, same source intervals, must replace no data and never double count.
        pm.append(self.root,'evidence',{'id':'scope-proof','kind':'artifact','schema_version':1,
                  'provenance':{'source':'test'},'payload':{'description':'Observed independent session counters'}},'hq')
        # Use a separate CU for the positive total example rather than upgrade an existing ambiguous scope.
        other=self.root/'positive';other.mkdir();configure(other)
        base=other/'coordination/cd5';base.mkdir(parents=True)
        (base/'CHECKPOINT.json').write_text(json.dumps(self.cp))
        for f in ['EVIDENCE.jsonl','KNOWLEDGE.jsonl','ATTENTION.jsonl']:(base/f).write_text('')
        cu.record(other,{'action':'open','event_id':'open','cu_id':'cu-a','title':'t','goal':'g',
                         'forecast_unknown_reason':'Synthetic fixture has no calibrated forecast'},'owner')
        for thread,role,parent in [('owner','hq',None),('child','helper','owner')]:
            cu.record(other,{'action':'participant','event_id':thread,'cu_id':'cu-a','participant':{'thread_id':thread,'role':role,'parent_thread_id':parent}},'owner')
        pm.append(other,'evidence',{'id':'scope-proof','kind':'artifact','schema_version':1,'provenance':{},'payload':{}},'hq')
        cu.measure(other,'cu-a',a,'m','owner','scope-proof');cu.measure(other,'cu-a',a,'m-again','owner','scope-proof')
        row=cu.report_data(other)['units'][0]
        self.assertEqual(row['usage']['cached_input'],20);self.assertEqual(row['usage']['output'],8)

    def test_all_time_archive_and_referenced_evidence_survive(self):
        first=self.open(at='2026-09-01T00:00:00+00:00');self.person()
        self.record('status',status='completed',result='done',at='2026-09-02T00:00:00+00:00')
        pm.append(self.root,'knowledge',{'id':'known-cu','kind':'observation','refs':[{'id':first['id']}]},'hq')
        before=cu.report_data(self.root,all_units=True)['units']
        archive_evidence(self.root,0,0,cu_only=True,apply=True)
        self.assertEqual(before,cu.report_data(self.root,all_units=True)['units'])
        self.assertEqual(pm.select(self.root,'evidence',[first['id']],full=True),[first])
        pm.validate(self.root)
        pm.append(self.root,'knowledge',{'id':'later','kind':'observation','refs':[{'id':first['id']}]},'hq')

    def test_period_includes_long_running_cu_and_uses_moscow_dates(self):
        self.open(at='2026-09-01T10:00:00+03:00')
        self.record('status',status='completed',result='done',at='2026-10-03T10:00:00+03:00')
        self.open('cu-b',at='2026-10-05T00:00:00+03:00')
        result=cu.report_data(self.root,since='2026-10-01',until='2026-10-03')
        self.assertEqual([r['cu_id'] for r in result['units']],['cu-a'])
        with self.assertRaises(ValueError):cu.report_data(self.root,since='2026-10-03',until='2026-10-01')

    def test_automatic_hot_cu_event_limit_keeps_history(self):
        conf=self.root/'.cd5/config.json';data=json.loads(conf.read_text());data['control_units']={'keep_active_events':1,'max_active_bytes':4096};conf.write_text(json.dumps(data))
        self.open();self.person();self.record('status',status='completed',result='done')
        self.assertEqual(len(pm._jsonl(self.root/'coordination/cd5/EVIDENCE.jsonl')),1)
        self.assertEqual(cu.report_data(self.root,all_units=True)['units'][0]['result'],'done')

    def test_latest_uses_instant_not_timezone_string(self):
        self.open('cu-early',at='2026-10-21T12:00:00+03:00')
        self.open('cu-later',at='2026-10-21T10:00:00+00:00')
        self.assertEqual(cu.report_data(self.root,limit=1)['units'][0]['cu_id'],'cu-later')

    def test_copied_rollout_does_not_duplicate_measurement(self):
        self.open();self.person();mapping=self.mapping()
        cu.measure(self.root,'cu-a',mapping,'measure-one','owner')
        original=cu.report_data(self.root)['units'][0]['participants'][0]['usage']
        copied=self.root/'copied.jsonl';shutil.copy2(mapping['participants'][0]['source_file'],copied)
        mapping['participants'][0]['source_file']=str(copied)
        cu.measure(self.root,'cu-a',mapping,'measure-copy','owner')
        self.assertEqual(cu.report_data(self.root)['units'][0]['participants'][0]['usage'],original)

    def test_archived_ids_cannot_be_reused(self):
        first=self.open();archive_evidence(self.root,0,0,apply=True)
        changed={**first,'payload':{'different':True}}
        with self.assertRaisesRegex(ValueError,'duplicate'):
            pm.append(self.root,'evidence',changed,'hq')


if __name__=='__main__':unittest.main()
