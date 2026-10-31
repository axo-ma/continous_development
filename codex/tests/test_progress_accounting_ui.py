import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import types
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).parents[1] / 'skills' / 'cd5' / 'scripts' / 'control_unit_report.py'
SPEC = importlib.util.spec_from_file_location('source_control_unit_report', SOURCE)
report = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(report)


class ProgressAccountingUITests(unittest.TestCase):
    def fixture(self):
        return {
            'units': [
                {'cu_id': 'cu-a', 'cu_number': 'З-001', 'title': 'Done', 'status': 'completed',
                 'accounting_reasons': ['Нет назначения хода'],
                 'work_units': {'value': None, 'known_value': '1.25', 'status': 'partial'}},
                {'cu_id': 'cu-b', 'title': 'Legacy', 'status': 'open'},
            ],
            'accounting': {
                'events': [{'source_key': 'journal:turn-7', 'thread_id': 'thread-1', 'turn_id': 'turn-7',
                            'cu_id': None, 'reason': 'Нет назначения хода',
                            'explanation': 'Для этого хода не сохранено подтверждённое назначение.',
                            'model': 'gpt-6.1-sol', 'usage': {}, 'coverage': 'complete',
                            'exclusive_scope': True,
                            'work_units': {'value': '1.25', 'known_value': '1.25', 'status': 'complete'}}],
                'totals': {
                    'project': {'value': None, 'known_value': '1.25', 'status': 'partial'},
                    'allocated': {'value': '0', 'known_value': '0', 'status': 'complete'},
                    'unallocated': {'value': '1.25', 'known_value': '1.25', 'status': 'complete'},
                },
            },
        }

    def render(self, data):
        with patch.dict(sys.modules, {'work_units': types.SimpleNamespace(annotate_report=lambda value, rate_path=None: value)}):
            html = report.render_report(data)
        payload = html.split('<script id="report-data" type="application/json">')[1].split('</script>')[0]
        return html, json.loads(payload)

    def test_permanent_number_and_unallocated_schema_are_serialized(self):
        html, payload = self.render(self.fixture())
        self.assertEqual(payload['units'][0]['cu_number'], 'З-001')
        self.assertIsNone(payload['accounting']['events'][0]['cu_id'])
        self.assertEqual(payload['accounting']['totals']['unallocated']['known_value'], '1.25')
        self.assertIn("unit.cu_number||unit.cu_id||'—'", html)
        self.assertNotIn('String(index+1)', html)
        self.assertIn('Не распределено · ${events.length} измерений', html)
        self.assertIn('accounting_reasons?.[0]', html)
        self.assertIn('независимость части счётчиков не доказана', html)

    @unittest.skipUnless(shutil.which('node'), 'Node is optional for browser-renderer verification')
    def test_unallocated_summary_renders_reasons_and_keeps_totals_non_exact(self):
        template = SOURCE.with_suffix('.html').read_text(encoding='utf-8')
        function = 'function renderAccounting()' + template.split('function renderAccounting()', 1)[1].split('function renderView(', 1)[0]
        script = r'''
const assert=require('node:assert/strict');
function element(tag,text,cls){return {tag,text:text===undefined?'':String(text),cls,children:[],append(...items){this.children.push(...items);},replaceChildren(...items){this.children=[];this.append(...items);}};}
const host=element('section');const byId=id=>host;let data;
function formatWU(value){return value==null?'—':Number(value).toFixed(2);}
function texts(node){return [node.text,...node.children.flatMap(texts)];}
''' + function + r'''
data={accounting:{events:[{reason:'Нет назначения хода',explanation:'Назначение не сохранено',thread_id:'t1',turn_id:'u1',model:'gpt-6.1-sol',exclusive_scope:false,work_units:{known_value:'1.25',status:'partial'}}],totals:{project:{status:'partial'},unallocated:{known_value:'1.25',status:'partial'}}}};
renderAccounting();assert.equal(host.hidden,false);assert(texts(host).includes('Не распределено · 1 измерений'));assert(texts(host).includes('Назначение не сохранено'));assert(texts(host).some(t=>t.includes('независимость части счётчиков не доказана')));assert(texts(host).includes('Не менее 1.25 WU'));
data={accounting:{events:[],totals:{}}};renderAccounting();assert.equal(host.hidden,true);
data={accounting:{events:[{cu_id:'confirmed',reason:'assigned'}],totals:{}}};renderAccounting();assert.equal(host.hidden,true);
'''
        result = subprocess.run([shutil.which('node'), '-e', script], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
