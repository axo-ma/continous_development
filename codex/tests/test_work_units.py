import copy
import json
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import work_units as wu


class WorkUnitTests(unittest.TestCase):
    def test_duplicate_thread_and_contradictory_model_rejected(self):
        with self.assertRaises(ValueError):
            wu.annotate_report(self.report([self.person('a',thread_id='same'),self.person('b',thread_id='same')]))
        result=wu.annotate_report(self.report([self.person(models_observed=['gpt-6-luna'])]))
        self.assertIsNone(result['work_units']['total']['value'])

    def person(self,key='hq',model='gpt-6.1-sol',**changes):
        return {'participant_id':key,'name':key,'model':model,'reasoning':'low','coverage':'complete',
                'exclusive_scope':True,'usage':{'cached_input':2458368,'uncached_input':16308,'output':3233},**changes}

    def report(self,people=None,**changes):
        return {'title':'fixture','units':[{'cu_id':'CU-9','usage_status':'complete',
                                          'participants':people if people is not None else [self.person()],**changes}]}

    def test_two_participant_exact_cost(self):
        reviewer=self.person('reviewer',usage={'cached_input':418560,'uncached_input':42553,'output':4369})
        data=wu.annotate_report(self.report([self.person(),reviewer]))
        team=data['units'][0]
        self.assertEqual(Decimal(team['participants'][0]['work_units']['value']),Decimal('3.107828'))
        self.assertEqual(Decimal(team['participants'][1]['work_units']['value']),Decimal('1.706520'))
        self.assertEqual(Decimal(team['work_units']['value']),Decimal('4.814348'))
        self.assertEqual(data['work_units']['total']['value'],'4.814348')

    def test_rates_order_and_legacy_sol_cache_difference(self):
        for model,expected in [('gpt-6-luna','0.1'),('gpt-6.1-sol','1'),('gpt-6-sol','2'),('gpt-6-astra','10')]:
            result=wu.price_usage(model,{'cached_input':1000000,'uncached_input':0,'output':0})
            self.assertEqual(result['value'],expected)
        self.assertEqual(wu.price_usage('gpt-6-luna',{'cached_input':0,'uncached_input':1000000,'output':0})['value'],'1')

    def test_effort_no_multiplier_reasoning_not_added_twice(self):
        original=self.person(usage={'cached_input':100,'uncached_input':50,'output':20,'reasoning':15})
        changed={**original,'reasoning':'high'}
        low=wu.annotate_report(self.report([original]))['work_units']['total']['value']
        high=wu.annotate_report(self.report([changed]))['work_units']['total']['value']
        self.assertEqual(low,high);self.assertEqual(low,'0.0031')

    def test_unknown_invalid_and_zero_are_distinct(self):
        for model,usage in [(None,{'cached_input':0,'uncached_input':0,'output':0}),
                            ('unpriced-model',{'cached_input':1,'uncached_input':1,'output':1}),
                            ('gpt-6.1-sol',{'cached_input':None,'uncached_input':1,'output':1}),
                            ('gpt-6.1-sol',{'cached_input':True,'uncached_input':1,'output':1}),
                            ('gpt-6.1-sol',{'cached_input':-1,'uncached_input':1,'output':1})]:
            self.assertIsNone(wu.price_usage(model,usage)['value'])
        self.assertEqual(wu.price_usage('gpt-6.1-sol',{'cached_input':0,'uncached_input':0,'output':0})['value'],'0')
        self.assertIsNone(wu.annotate_report({'units':[]})['work_units']['total']['value'])

    def test_partial_team_not_falsely_priced_and_known_subtotal_retained(self):
        data=self.report([self.person(),self.person('unknown',model=None)],usage_status='partial')
        out=wu.annotate_report(data)
        self.assertIsNone(out['work_units']['total']['value'])
        self.assertEqual(out['work_units']['total']['known_value'],'3.107828')
        data['units'][0]['participants'][0]['exclusive_scope']=False
        self.assertIsNone(wu.annotate_report(data)['work_units']['total']['known_value'])

    def test_observed_pending_usage_is_partial_and_only_independent_subtotal(self):
        data=self.report([self.person(coverage='partial')],usage_status='partial')
        result=wu.annotate_report(data)['units'][0]
        self.assertEqual(result['participants'][0]['work_units']['status'],'partial')
        self.assertEqual(result['work_units']['known_value'],'3.107828')
        self.assertIsNone(result['work_units']['value'])
        data['units'][0]['participants'][0]['exclusive_scope']=False
        result=wu.annotate_report(data)['units'][0]
        self.assertEqual(result['participants'][0]['work_units']['known_value'],'3.107828')
        self.assertIsNone(result['work_units']['known_value'])

    def test_parent_inclusion_unknown_is_not_summed(self):
        out=wu.annotate_report(self.report([self.person(exclusive_scope=False)],usage_status='unknown'))
        self.assertIsNone(out['units'][0]['work_units']['value'])
        self.assertIsNone(out['work_units']['total']['value'])
        p=self.person();p.pop('exclusive_scope')
        self.assertIsNone(wu.annotate_report(self.report([p]))['work_units']['total']['value'])

    def test_mixed_models_without_split_is_unknown(self):
        p=self.person(models_observed=['gpt-6-luna','gpt-6.1-sol'])
        self.assertIsNone(wu.annotate_report(self.report([p]))['units'][0]['work_units']['value'])

    def test_does_not_mutate_evidence_or_trust_precomputed_wu(self):
        data=self.report();data['units'][0]['work_units']={'value':'999999'}
        before=copy.deepcopy(data)
        out=wu.annotate_report(data)
        self.assertEqual(data,before);self.assertEqual(out['units'][0]['work_units']['value'],'3.107828')

    def test_no_duplicate_participant_or_control_unit_double_count(self):
        with self.assertRaisesRegex(ValueError,'duplicate participant'):
            wu.annotate_report(self.report([self.person(),self.person()]))
        data=self.report();data['units']*=2
        with self.assertRaisesRegex(ValueError,'unique'):
            wu.annotate_report(data)

    def test_total_uses_unrounded_values(self):
        p=self.person(usage={'cached_input':4999,'uncached_input':0,'output':0})
        data=self.report([p]);data['units'].append({**copy.deepcopy(data['units'][0]),'cu_id':'CU-next'})
        value=wu.annotate_report(data)['work_units']['total']['value']
        self.assertEqual(value,'0.009998')

    def test_window_view_costs_recompute_from_raw_tokens(self):
        data=self.report()
        actor={'thread_id':'actor','model':'gpt-6.1-sol','coverage':'complete',
               'usage':{'cached_input':1000000,'uncached_input':0,'output':0},
               'work_units':{'value':'999999'}}
        data['quota_usage']={'windows':[{'actors':[actor], 'assignments':[copy.deepcopy(actor)]}],
                             'unassigned':[copy.deepcopy(actor)]}
        priced=wu.annotate_report(data)
        self.assertEqual(priced['quota_usage']['windows'][0]['actors'][0]['work_units']['value'],'1')
        self.assertEqual(priced['quota_usage']['windows'][0]['assignments'][0]['work_units']['value'],'1')
        self.assertEqual(priced['quota_usage']['unassigned'][0]['work_units']['value'],'1')
        self.assertEqual(actor['work_units']['value'],'999999')

    def test_custom_dated_rates_and_invalid_rate(self):
        rates=wu.load_rates();rates['rates_per_million']['gpt-6-luna']['output']='7'
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            path=Path(directory)/'rates.json';path.write_text(json.dumps(rates),encoding='utf-8')
            p=self.person(model='gpt-6-luna',usage={'cached_input':0,'uncached_input':0,'output':1000000})
            self.assertEqual(wu.annotate_report(self.report([p]),path)['work_units']['total']['value'],'7')
            rates['rates_per_million']['gpt-6-luna']['output']='NaN'
            path.write_text(json.dumps(rates),encoding='utf-8')
            with self.assertRaises(ValueError):wu.load_rates(path)

    def test_views_keep_independent_totals_and_share_tariff_version(self):
        data=self.report();data['default_view']='earlier'
        data['views']=[{'id':'earlier','label':'Первый срез',**self.report()},
                       {'id':'latest','label':'Другой срез',**self.report([self.person(model=None)])}]
        out=wu.annotate_report(data)
        self.assertEqual(out['work_units']['total']['value'],'3.107828')
        self.assertEqual(out['views'][0]['work_units']['total']['value'],'3.107828')
        self.assertIsNone(out['views'][1]['work_units']['total']['value'])
        self.assertEqual(out['views'][0]['work_units']['rate_date'],out['work_units']['rate_date'])


if __name__=='__main__':unittest.main()
