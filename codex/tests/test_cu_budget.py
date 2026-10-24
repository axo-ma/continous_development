import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import control_units as cu
import cu_budget as budget
import project_memory as pm
from work_units import annotate_report
from cu_archive import archive_evidence
from tests.cd5_fixtures import configure


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(tempfile.mkdtemp(prefix='.budget-test-',dir=ROOT))
        self.addCleanup(lambda:shutil.rmtree(self.root))
        configure(self.root)
        self.base=self.root/'coordination/cd5';self.base.mkdir(parents=True)
        self.cp={'schema_version':3,'memory':{k:'coordination/cd5/'+v for k,v in pm.FILES.items()},
                 'owner':{'role':'hq','thread_id':'owner'},'user_stop':{'active':True}}
        for name in pm.FILES.values():(self.base/name).write_text('',encoding='utf-8')
        (self.base/'CHECKPOINT.json').write_text(json.dumps(self.cp))
        self.capture=patch('cu_auto_telemetry.capture_anchor',return_value=None);self.capture.start()
        self.addCleanup(self.capture.stop)

    def record(self,action='open',**values):
        data={'action':action,'cu_id':'cu','event_id':values.pop('event_id',action),**values}
        if action=='open':
            data.update(title='Existing work',goal='Existing expected result')
            if not values.get('historical') and not values.get('forecast'):
                data.setdefault('forecast_unknown_reason','Synthetic fixture has no calibrated forecast')
        return cu.record(self.root,data,'owner')

    def unit(self):return cu.report_data(self.root,auto_telemetry=False)['units'][0]

    def test_forecast_limit_are_separate_revisioned_and_archive_replays(self):
        original={'low':'3','high':'6','confidence':'medium'}
        first=self.record(forecast=original,limit='8',at='2026-10-21T10:00:00+00:00')
        self.assertEqual(first,self.record(forecast=original,limit='8',at='2026-10-21T10:00:00+00:00'))
        revision={'forecast':{'low':'5','high':'9','confidence':'low'},'limit':'10','reason':'Scope increased',
                  'at':'2026-10-21T11:00:00+00:00'}
        second=self.record('budget',**revision)
        self.assertEqual(second,self.record('budget',**revision))
        value=self.unit()['budget']
        self.assertEqual(value['original_forecast']['low'],'3')
        self.assertEqual(value['forecast']['low'],'5');self.assertEqual(value['limit'],'10')
        self.assertEqual(len(value['history']),2)
        self.assertEqual(value['history'][1]['reason'],'Scope increased')
        archive_evidence(self.root,keep_records=0,max_bytes=0,cu_only=True,apply=True)
        self.assertEqual(self.unit()['budget'],value)
        self.assertEqual(json.loads((self.base/'CHECKPOINT.json').read_text()),self.cp)

    def test_missing_forecast_not_invented_and_late_prediction_not_original(self):
        self.record()
        before=self.unit()['budget']
        self.assertIsNone(before['forecast']);self.assertIsNone(before['limit']);self.assertEqual(before['history'],[])
        self.record('budget',forecast={'low':'2','high':'4'},reason='New information')
        self.assertIsNone(self.unit()['budget']['original_forecast'])
        self.assertEqual(self.unit()['budget']['forecast']['confidence'],'low')

    def test_current_unknown_reason_revision_is_visible_and_never_original(self):
        import contextlib
        import io
        self.record(historical=True)
        args=['--root',str(self.root),'budget','--cu','cu','--caller-thread','owner',
              '--event-id','current-reason','--reason','Prospective review of remaining work',
              '--forecast-unknown-reason','No comparable measured work for remaining scope']
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cu.main(args),0)
            self.assertEqual(cu.main(args),0)
        value=self.unit()['budget']
        self.assertEqual(value['forecast_unknown_reason'],'No comparable measured work for remaining scope')
        self.assertIsNone(value['original_forecast'])
        self.assertIsNone(value['forecast'])
        self.assertEqual(len(value['history']),1)
        self.record('budget',event_id='later-plan',forecast={'low':'1','high':'3'},reason='New prospective estimate')
        value=self.unit()['budget']
        self.assertIsNone(value['original_forecast'])
        self.assertNotIn('forecast_unknown_reason',value)

    def test_begin_requires_plan_or_explicit_unknown_without_a_limit(self):
        import contextlib
        import io
        args=['--root',str(self.root),'begin','--cu','cu','--title','Synthetic task','--caller-thread','owner']
        with contextlib.redirect_stderr(io.StringIO()) as errors, self.assertRaises(SystemExit):
            cu.main(args)
        self.assertIn('--forecast-unknown-reason', errors.getvalue())
        self.assertEqual(cu._events(self.root), [])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cu.main(args+['--forecast-unknown-reason','No comparable completed work']),0)
        value=self.unit()['budget']
        self.assertEqual(value['forecast_unknown_reason'],'No comparable completed work')
        self.assertIsNone(value['forecast']);self.assertIsNone(value['limit'])
        with self.assertRaises(ValueError):
            self.record(event_id='conflict',forecast={'low':1,'high':2},forecast_unknown_reason='Conflict')

    def test_limit_does_not_create_forecast_and_zero_is_not_missing(self):
        self.record(limit=0)
        self.assertEqual(self.unit()['budget']['limit'],'0')
        self.assertIsNone(self.unit()['budget']['forecast'])
        self.record('budget',limit=None,reason='Remove explicit limit')
        self.assertIsNone(self.unit()['budget']['limit'])
        self.assertEqual(len(self.unit()['budget']['history']),2)

    def test_semantic_retries_keep_original_tariff_date(self):
        from work_units import load_rates
        original={'forecast':{'low':3,'high':6},'limit':8}
        first=self.record(**original)
        revision={'forecast':{'low':5,'high':9},'limit':10,'reason':'More work'}
        second=self.record('budget',**revision)
        rates=load_rates();rates['rate_date']='2026-10-22'
        with patch('work_units.load_rates',return_value=rates):
            self.assertEqual(first,self.record(**original))
            self.assertEqual(second,self.record('budget',**revision))
            with self.assertRaises(ValueError):
                self.record(**{**original,'forecast':{**original['forecast'],'rate_date':'2026-10-22'}})

    def test_validation_owner_order_and_closed_budget_are_enforced(self):
        for value in [True,-1,'NaN','Infinity','-Infinity','1e100',None]:
            with self.subTest(value=value),self.assertRaises(ValueError):budget.amount(value)
        for value in [{'low':6,'high':3},{'low':None,'high':3},{'low':1,'high':3,'confidence':'certain'}]:
            with self.assertRaises(ValueError):budget.normalize_patch({'forecast':value})
        self.record(at='2026-10-21T10:00:00+00:00')
        with self.assertRaises(ValueError):self.record('budget',limit=4,reason='')
        with self.assertRaises(ValueError):self.record('budget',limit=4,reason='Before work',at='2026-10-20T00:00:00Z')
        with self.assertRaises(ValueError):cu.record(self.root,{'action':'budget','event_id':'wrong','cu_id':'cu','limit':4,'reason':'Change'},'wrong')
        self.record('status',status='completed',result='Existing outcome',at='2026-10-21T12:00:00Z')
        with self.assertRaises(ValueError):self.record('budget',limit=4,reason='After observing result')

    def priced(self,actual='4.814348',status='completed'):
        self.record(forecast={'low':3,'high':6,'confidence':'medium'},limit=8)
        unit=self.unit();unit['status']=status
        unit['work_units']={'status':'complete','value':actual,'basis':'standard_short_context_estimate','rate_date':'2026-10-21'}
        return unit

    def test_comparison_original_prediction_not_revised_target(self):
        unit=self.priced(actual='7')
        self.record('budget',forecast={'low':6,'high':10},reason='More work')
        unit['budget']=self.unit()['budget']
        result=budget.compare_budget(unit)
        self.assertEqual(result['forecast_status'],'above');self.assertEqual(result['forecast_difference'],'1')
        self.assertEqual(result['limit_status'],'below');self.assertEqual(result['limit_remaining'],'1')
        self.assertEqual(self.unit()['status'],'open')

    def test_partial_incomparable_and_open_cu_no_false_success(self):
        unit=self.priced(status='open')
        self.assertEqual(budget.compare_budget(unit)['forecast_status'],'unknown')
        unit['status']='completed'
        self.assertEqual(budget.compare_budget(unit)['forecast_status'],'within')
        unit['work_units']['status']='partial';unit['work_units']['known_value']='9'
        result=budget.compare_budget(unit)
        self.assertEqual(result['forecast_status'],'unknown');self.assertEqual(result['limit_status'],'unknown')
        unit['work_units']['status']='complete';unit['work_units']['rate_date']='2026-10-22'
        self.assertEqual(budget.compare_budget(unit)['forecast_status'],'unknown')
        self.assertEqual(budget.compare_budget(unit)['limit_status'],'unknown')

    def test_limit_exceeded_is_information_and_does_not_stop_work(self):
        unit=self.priced(actual='8.000001',status='open')
        result=budget.compare_budget(unit)
        self.assertEqual(result['limit_status'],'exceeded');self.assertEqual(result['limit_remaining'],'-0.000001')
        self.assertEqual(self.unit()['status'],'open')
        self.assertEqual(json.loads((self.base/'CHECKPOINT.json').read_text()),self.cp)

    def test_annotation_computes_comparison_without_mutating_actual_or_budget(self):
        self.record(forecast={'low':0,'high':0},limit=0)
        unit=self.unit();unit['status']='completed';unit['usage_status']='complete'
        unit['participants']=[{'participant_id':'owner','thread_id':'owner','model':'gpt-6.1-sol',
            'coverage':'complete','exclusive_scope':True,'usage':{'cached_input':0,'uncached_input':0,'output':0}}]
        data={'units':[unit]};saved=copy.deepcopy(data)
        out=annotate_report(data)['units'][0]
        self.assertEqual(out['work_units']['value'],'0')
        self.assertEqual(out['budget_comparison']['forecast_status'],'within')
        self.assertEqual(out['budget_comparison']['limit_status'],'at')
        self.assertEqual(data,saved)

    def test_cli_begin_and_revision_use_explicit_fields(self):
        with patch('builtins.print'):
            self.assertEqual(cu.main(['--root',str(self.root),'begin','--cu','cu','--title','Existing task',
                '--caller-thread','owner','--forecast-low','3','--forecast-high','6','--confidence','medium','--limit-wu','8']),0)
            args=['--root',str(self.root),'budget','--cu','cu','--caller-thread','owner','--event-id','rev-one',
                  '--reason','Scope increased','--limit-wu','10']
            self.assertEqual(cu.main(args),0);self.assertEqual(cu.main(args),0)
        self.assertEqual(self.unit()['budget']['limit'],'10')
        self.assertEqual(self.unit()['budget']['original_forecast']['high'],'6')
        self.assertEqual(len(cu._events(self.root)),2)


if __name__=='__main__':unittest.main()
