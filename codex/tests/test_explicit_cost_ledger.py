import copy
from decimal import Decimal
import json
import unittest
from unittest.mock import patch
from tests import test_cu_auto_telemetry as native_fixture
snapshot,turn,stamp=native_fixture.snapshot,native_fixture.turn,native_fixture.stamp
from tests import test_control_units as catalogue_fixture
from tools import cu_auto_telemetry as auto, control_units as cu
from tools.work_units import annotate_report
from tools import cu_attribution_api as api


class ExplicitLedgerTests(unittest.TestCase):
    def setUp(self):
        self.f=native_fixture.AutoTelemetryTests();self.f.setUp();self.addCleanup(self.f.tearDown)

    def report(self,events,*ids):
        data={'units':[self.f.data(i)['units'][0] for i in ids]}
        return auto.enrich_report(self.f.root,data,events)

    def test_old_open_cu_does_not_take_new_or_unmarked_turns_and_total_keeps_them(self):
        f=self.f;p=f.session(rows=[snapshot(100,0),*turn('old',5,140),*turn('unknown',15,180),*turn('new',25,220),*turn('tail',35,260)])
        events=[f.cu_event(cu='old',anchor=f.anchor(p,'old')),*f.bounded(p,first='new',last='new',cu='new')]
        result=self.report(events,'old','new')
        mapping={r['turn_id']:r['cu_id'] for r in result['accounting']['events']}
        self.assertEqual(mapping,dict(old='old',new='new',unknown=None,tail=None))
        priced=annotate_report(result)
        totals=priced['accounting']['totals']
        self.assertEqual(totals['project']['status'],'complete')
        self.assertEqual(Decimal(totals['project']['value']),Decimal(totals['allocated']['value'])+Decimal(totals['unallocated']['value']))
        self.assertEqual(result,self.report(events,'old','new'))
        duplicated=copy.deepcopy(result);duplicated['accounting']['events']*=2
        self.assertEqual(annotate_report(duplicated)['accounting']['totals'],totals)

    def test_conflicting_one_turn_is_not_billed_to_two_cus(self):
        f=self.f;p=f.session(rows=[snapshot(100,0),*turn('one',5)])
        result=self.report(f.bounded(p,cu='a')+f.bounded(p,cu='b'),'a','b')
        event=result['accounting']['events'][0]
        self.assertIsNone(event['cu_id'])
        self.assertEqual(event['reason'],'conflicting_assignments')
        priced=annotate_report(result)
        self.assertTrue(all(u['work_units']['value'] is None for u in priced['units']))
        self.assertGreater(Decimal(priced['accounting']['totals']['unallocated']['value']),0)

    def test_late_worker_and_reused_chat_are_bound_to_separate_assignments(self):
        f=self.f
        hq=f.session(rows=[snapshot(100,0),*turn('job-a-parent',5,140),*turn('job-b-parent',30,180)])
        child=f.session('child',rows=[snapshot(0,5),*turn('job-a',6,20),*turn('job-b',35,40),*turn('job-b-followup',55,60)],parent='hq',created=6)
        a=f.anchor(child,'job-a');b=f.anchor(child,'job-b')
        events=f.bounded(hq,first='job-a-parent',last='job-a-parent',cu='a')+f.bounded(hq,first='job-b-parent',last='job-b-parent',cu='b')
        events += [f.cu_event(cu='a',action='participant',participant=dict(thread_id='child',parent_thread_id='hq',role='executor'),
            assignment=dict(assignment_id='a-job',start_anchor=a,thread_id='child',operation='start')),
            f.cu_event(cu='b',action='participant',participant=dict(thread_id='child',parent_thread_id='hq',role='executor'),
            assignment=dict(assignment_id='b-job',start_anchor=b,thread_id='child',operation='start',previous_assignment_id='a-job',previous_end_anchor=a))]
        result=self.report(events,'a','b')
        mapping={r['turn_id']:r['cu_id'] for r in result['accounting']['events'] if r['thread_id']=='child'}
        self.assertEqual(mapping,{'job-a':'a','job-b':'b','job-b-followup':'b'})
        # Parent finishes before the worker; the worker's late source cost remains.
        self.assertEqual(next(r for r in result['accounting']['events'] if r['turn_id']=='job-b-followup')['usage']['output'],2)

    def test_closed_cu_gets_confirmed_cost_without_reopening_work(self):
        f=self.f;p=f.session(rows=[snapshot(100,0),*turn('done',5)])
        result=self.report(f.bounded(p,first='done',last='done'),'cu')
        unit=result['units'][0]
        self.assertEqual(unit['usage_status'],'complete')
        self.assertGreater(Decimal(annotate_report(result)['units'][0]['work_units']['value']),0)

    def test_one_participant_keeps_confirmed_cost_when_another_turn_is_disputed(self):
        f=self.f;p=f.session(rows=[snapshot(100,0),*turn('known',5,140),*turn('disputed',30,180)])
        events=f.bounded(p,first='known',last='known',cu='a')+f.bounded(p,first='disputed',last='disputed',cu='a')+f.bounded(p,first='disputed',last='disputed',cu='b')
        result=self.report(events,'a','b')
        participant=result['units'][0]['participants']
        self.assertEqual(len(participant),1)
        self.assertIsNotNone(participant[0]['usage']['output'])
        priced=annotate_report(result)
        self.assertGreater(Decimal(priced['accounting']['totals']['allocated']['value']),0)
        self.assertGreater(Decimal(priced['accounting']['totals']['unallocated']['value']),0)

    def test_assignment_validation_keeps_identity_and_requires_completed_finish(self):
        f=self.f;p=f.session('child',rows=[snapshot(0,0),*turn('first',5,20),*turn('second',25,40,complete=False)],parent='hq')
        start=dict(assignment_id='job',operation='start',thread_id='child',start_anchor=f.anchor(p,'first'))
        self.assertEqual(api.validate_assignment(f.root,start,'a',[]),start)
        history=[f.cu_event(cu='a',action='assignment',assignment=start)]
        finish=dict(assignment_id='job',operation='finish',thread_id='child',end_anchor=f.anchor(p,'first'))
        api.validate_assignment(f.root,finish,'a',history)
        with self.assertRaises(ValueError):api.validate_assignment(f.root,finish,'b',history)
        with self.assertRaises(ValueError):api.validate_assignment(f.root,dict(finish,thread_id='other'),'a',history)
        with self.assertRaises(ValueError):api.validate_assignment(f.root,dict(finish,end_anchor=f.anchor(p,'second')),'a',history)

    def test_allocation_correction_is_append_only_and_preserves_previous_events(self):
        f=self.f;p=f.session(rows=[snapshot(100,0),*turn('one',5)])
        events=f.bounded(p,cu='a')+f.bounded(p,cu='b');before=copy.deepcopy(events)
        correction=dict(turn_anchor=f.anchor(p,'one'),reason='Verified original dispatch',supports=[events[0]['id']])
        api.validate_allocation(f.root,correction,events)
        corrected=events+[f.cu_event(cu='b',action='allocation',**correction)]
        self.assertEqual(self.report(corrected,'a','b')['accounting']['events'][0]['cu_id'],'b')
        self.assertEqual(events,before)
        bad=copy.deepcopy(correction);bad['turn_anchor']['prefix_sha256']='wrong'
        with self.assertRaises(ValueError):api.validate_allocation(f.root,bad,events)

    def test_mixed_manual_sources_do_not_become_a_false_exact_project_total(self):
        f=self.f;p=f.session(rows=[snapshot(100,0),*turn('one',5)])
        events=f.bounded(p,cu='native')+[f.cu_event(cu='manual',action='measurement')]
        result=annotate_report(self.report(events,'native','manual'))
        self.assertEqual(result['accounting']['manual_units_requiring_reconciliation'],['manual'])
        self.assertEqual(result['work_units']['total']['status'],'partial')
        self.assertIsNone(result['work_units']['total']['value'])


class CatalogueTests(unittest.TestCase):
    def setUp(self):
        self.f=catalogue_fixture.ControlUnitTests();self.f.setUp();self.addCleanup(self.f.doCleanups)

    def test_numbers_persist_and_ignore_sorting_regeneration_and_page_limit(self):
        f=self.f;f.open('first',at='2026-10-01T10:00:00+03:00');f.open('second',at='2026-10-02T10:00:00+03:00')
        all_rows=cu.report_data(f.root,all_units=True,auto_telemetry=False)['units']
        self.assertEqual({u['cu_id']:u['cu_number'] for u in all_rows},{'first':'З-001','second':'З-002'})
        self.assertEqual(cu.report_data(f.root,limit=1,auto_telemetry=False)['units'][0]['cu_number'],'З-002')
        f.record('catalog_number','first',event_id='number-first',cu_number='З-001')
        with self.assertRaises(ValueError):f.record('catalog_number','first',event_id='renumber',cu_number='З-099')
        self.assertEqual({u['cu_id']:u['cu_number'] for u in cu.report_data(f.root,all_units=True,auto_telemetry=False)['units']},{u['cu_id']:u['cu_number'] for u in all_rows})

    def test_existing_number_is_reserved_and_new_catalogue_never_reuses_it(self):
        f=self.f;f.open('first')
        # Existing numbers are preserved; a duplicate or changed number is rejected.
        with self.assertRaises(ValueError):f.record('catalog_number','first',event_id='change',cu_number='З-007')
        f.open('second')
        self.assertEqual(cu._units(cu._events(f.root))['second']['cu_number'],'З-002')
