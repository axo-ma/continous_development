import importlib.util
import json
from pathlib import Path
import tempfile
import sys
import types
import unittest
import shutil
import subprocess
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location('control_unit_report', Path(__file__).parents[1] / 'tools' / 'control_unit_report.py')
report = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(report)


class ReportTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node is optional for safe Markdown checks')
    def test_markdown_blocks_are_structured_and_never_execute_html_or_schemes(self):
        template = Path(report.__file__).with_suffix('.html').read_text(encoding='utf-8')
        functions = 'function safeLink(' + template.split('function safeLink(', 1)[1].split('let returnFocus=', 1)[0]
        script = r'''
const assert=require('node:assert/strict');
class Node{constructor(tag,text=''){this.tag=tag;this.own=String(text);this.children=[];this.style={};this.attributes={};this.listeners={};}append(...nodes){for(let node of nodes){if(typeof node==='string')node=new Node('#text',node);node.parentElement=this;this.children.push(node);}}set textContent(value){this.own=String(value);this.children=[];}get textContent(){return this.own+this.children.map(n=>n.textContent).join('');}setAttribute(key,value){this.attributes[key]=value;}replaceChildren(...nodes){this.children=[];this.own='';this.append(...nodes);}addEventListener(key,fn){this.listeners[key]=fn;}remove(){}focus(){this.focused=true;}}
const document={createElement:tag=>new Node(tag),createTextNode:text=>new Node('#text',text)};
function element(tag,text,cls){const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(cls)node.className=cls;return node;}
function time(value){return value||'—';}
function find(node,tag){return [...(node.tag===tag?[node]:[]),...node.children.flatMap(child=>find(child,tag))];}
''' + functions + r'''
const rendered=markdown(__MARKDOWN__);
assert.equal(find(rendered,'h1').length,1);
assert(find(rendered,'p').some(p=>p.textContent==='A soft wrapped strong and e safe.'));
assert.equal(find(rendered,'strong').length,1);assert.equal(find(rendered,'em').length,1);
assert.equal(find(rendered,'ol')[0].children.length,2);assert.equal(find(rendered,'ul').length,1);
assert.equal(find(rendered,'table').length,1);assert.equal(find(rendered,'th').length,2);assert.equal(find(rendered,'td').length,2);
assert.equal(find(rendered,'pre')[0].textContent,'<script>alert(1)</script>');
assert.equal(find(rendered,'script').length,0);
assert.equal(find(rendered,'a')[0].href,'https://example.com');
const hostile=markdown('[run](javascript:alert(1)) [data](data:text/html,evil) ![remote](https://example.com/image.png) <img src=x onerror=alert(1)>');
assert.equal(find(hostile,'a').length,0);assert.equal(find(hostile,'img').length,0);
assert(hostile.textContent.includes('<img src=x onerror=alert(1)>'));
assert.equal(humanText(false),'Нет');assert.equal(humanText(0),'0');assert.equal(humanText({internal_secret:'not for display'}),'');
const record=projectRecord({title:'Saved',text:'**Finding**\ncontinued',limitations:'[bad](javascript:alert(1))',sources:[{id:'E1'}]},'knowledge');
assert.equal(find(record,'strong').filter(n=>n.textContent==='Finding').length,1);assert.equal(find(record,'a').length,0);assert(record.textContent.includes('E1'));
let overview=null;const root={querySelector(selector){if(selector==='.project-overview')return overview;if(selector==='header')return {after(node){overview=node;}};throw Error(selector);}};
let data={checkpoint:{status:'available',state:{user_stop:false,milestone:0}},attention:{status:'available',open:[{id:'old',title:'Old unresolved',question:'Still waiting',created_at:'2000-01-01',requires_user:null}],history:[{title:'Closed',status:'closed'}]},knowledge:{status:'available',entries:Array.from({length:12},(_,i)=>({title:'Finding '+i,text:'Saved text '+i}))}};
__PAGE_STATE__
renderProject();
assert(overview.textContent.includes('Still waiting'));assert(overview.textContent.includes('Закрыто'));
assert(!overview.textContent.includes('Нужен ответ пользователя'));assert(overview.textContent.includes('Нет'));assert(overview.textContent.includes('0'));
const knowledge=overview.children[2];assert.equal(find(knowledge,'article').length,10);
const pager=find(knowledge,'nav')[0];assert.equal(pager.children[0].disabled,true);assert.equal(pager.children[2].disabled,false);
pager.children[2].listeners.click();assert.equal(find(knowledge,'article').length,2);assert(knowledge.textContent.includes('Finding 11'));assert.equal(pager.children[2].disabled,true);
const search=find(knowledge,'input')[0];search.value='Finding 11';search.listeners.input();assert.equal(find(knowledge,'article').length,1);search.value='missing';search.listeners.input();assert.equal(find(knowledge,'article').length,0);
assert.equal(knowledge.hidden,true);const controls=overview.children[3];controls.children[1].listeners.click();assert.equal(knowledge.hidden,false);assert.equal(controls.children[1].attributes['aria-expanded'],'true');
const panelNodes=Object.fromEntries(['panel-title','panel-content','panel','shade','close'].map(id=>[id,new Node('div')]));
const byId=id=>panelNodes[id];let returnFocus=null;const trigger=new Node('button');
openOutline(trigger);assert(panelNodes['panel-content'].textContent.includes('План проекта не приложен'));assert.equal(panelNodes.close.focused,true);
data={outline_snapshot:{status:'available',markdown:'# Legacy plan'}};
openOutline(trigger);assert.equal(find(panelNodes['panel-content'],'h1')[0].textContent,'Legacy plan');
'''
        sample = "# Heading\n\nA soft\nwrapped **strong** and *e* [safe](https://example.com).\n\n1. first\n   - nested\n2. second\n\n| Name | Value |\n| --- | ---: |\n| item | `code` |\n\n```html\n<script>alert(1)</script>\n```"
        script = script.replace('__MARKDOWN__', json.dumps(sample))
        page_helper = 'function pageState(' + template.split('function pageState(', 1)[1].split('function renderView(', 1)[0]
        script = script.replace('__PAGE_STATE__', page_helper)
        result = subprocess.run([shutil.which('node'), '-e', script], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_utc_z_dates_work_with_python310_parser_contract(self):
        base_datetime = report.dt.datetime
        class StrictISO(base_datetime):
            @classmethod
            def fromisoformat(cls, value):
                if value.endswith('Z'):
                    raise ValueError('Python 3.10 requires an explicit UTC offset')
                return base_datetime.fromisoformat(value)
        data = self.fixture()
        data['units'][0].update(cu_id='old',started_at='2026-10-20T10:00:00Z',ended_at='2026-10-20T11:00:00Z')
        data['units'].append({**data['units'][0],'cu_id':'new','started_at':'2026-10-21T10:00:00Z','ended_at':'2026-10-21T11:00:00Z'})
        with patch.object(report.dt,'datetime',StrictISO):
            self.assertEqual(len(report.select_data(data,since='2026-10-20',until='2026-10-21')['units']),2)
            with tempfile.TemporaryDirectory(dir=Path(__file__).parents[1]) as directory:
                source=Path(directory)/'data.json';source.write_text(json.dumps(data),encoding='utf-8')
                output=Path(directory)/'report.html'
                self.assertEqual(report.main(['--data-file',str(source),'--output',str(output)]),0)
                payload=json.loads(output.read_text(encoding='utf-8').split('<script id="report-data" type="application/json">')[1].split('</script>')[0])
                self.assertEqual([unit['cu_id'] for unit in payload['units']],['new','old'])

    @unittest.skipUnless(shutil.which('node'), 'Node is optional')
    def test_panel_duplicate_text_is_shown_once(self):
        template=Path(report.__file__).with_suffix('.html').read_text(encoding='utf-8')
        helper='function panelTexts('+template.split('function panelTexts(',1)[1].split('function openPanel(',1)[0]
        script=helper+'''
const assert=require('node:assert/strict');
assert.deepEqual(panelTexts({goal:'Full task',description:'Full task'},'goal','Title'),['Full task']);
assert.deepEqual(panelTexts({goal:'Full task',description:'  Full   task  '},'goal','Title'),['Full task']);
assert.deepEqual(panelTexts({result:'Done',result_detail:'Done'},'result','Done'),[]);
assert.deepEqual(panelTexts({goal:'Summary',description:'Actual details'},'goal','Title'),['Summary','Actual details']);
'''
        result=subprocess.run([shutil.which('node'),'-e',script],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def fixture(self):
        return {'schema_version': 1, 'title': 'Прогресс', 'generated_at': '2026-10-21T12:00:00Z', 'units': [
            {'cu_id': 'CU-1', 'title': '</script><script>alert(1)</script>', 'goal': '<img src=x onerror=alert(1)>',
             'result': 'Готово cd5-wu-report', 'status': 'completed', 'elapsed_ms': None, 'usage_status': 'partial',
             'usage': {'cached_input': 0, 'uncached_input': None, 'output': 12}, 'participants': [],
             'sources': [{'label': 'unsafe', 'path': 'javascript:alert(1)', 'text': '<b>raw</b>'}]}]}

    def test_embedded_data_is_inert_and_lossless(self):
        data = self.fixture()
        html = report.render_report(data)
        payload = html.split('<script id="report-data" type="application/json">', 1)[1].split('</script>', 1)[0]
        self.assertNotIn('<', payload)
        decoded = json.loads(payload)
        for key in data:
            if key != 'units':
                self.assertEqual(decoded[key], data[key])
        for key, value in data['units'][0].items():
            self.assertEqual(decoded['units'][0][key], value)
        self.assertIn('work_units', decoded)
        self.assertIn('work_units', decoded['units'][0])
        self.assertNotIn('work_units', data)
        self.assertNotIn('<script>alert(1)</script>', html)
        self.assertIn('el.textContent=text', html)
        self.assertNotIn('innerHTML', html)

    def test_null_and_zero_are_preserved(self):
        html = report.render_report(self.fixture())
        payload = html.split('<script id="report-data" type="application/json">')[1].split('</script>')[0]
        unit = json.loads(payload)['units'][0]
        self.assertIsNone(unit['elapsed_ms'])
        self.assertIsNone(unit['usage']['uncached_input'])
        self.assertEqual(unit['usage']['cached_input'], 0)
        self.assertIn("typeof value==='number'", html)
        self.assertIn("return '—'", html)

    def test_structure_and_accessibility(self):
        html = report.render_report(self.fixture())
        for expected in ['aria-expanded', 'aria-controls', "row.hidden=true", "byId('units').append(row,detail)",
                         'aria-modal="true"', "event.key==='Escape'", 'returnFocus?.focus()', "event.key==='Tab'"]:
            self.assertIn(expected, html)
        self.assertNotIn('fetch(', html)
        self.assertNotIn('src="http', html)

    def test_cli_atomic_output_and_limit(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parents[1]) as directory:
            root = Path(directory)
            data = self.fixture()
            data['units'] = [{**data['units'][0], 'cu_id': f'CU-{index}', 'started_at': f'2026-10-{index+1:02d}T12:00:00Z'} for index in range(21)]
            source = root / 'data.json'
            source.write_text(json.dumps(data), encoding='utf-8')
            output = root / 'out' / 'report.html'
            self.assertEqual(report.main(['--data-file', str(source), '--output', str(output), '--limit', '1']), 0)
            rendered = output.read_text(encoding='utf-8')
            payload = rendered.split('<script id="report-data" type="application/json">')[1].split('</script>')[0]
            decoded = json.loads(payload)
            self.assertEqual(len(decoded['units']), 21)
            self.assertEqual(decoded['page_size'], 1)
            self.assertEqual(decoded['units'][0]['cu_id'], 'CU-20')
            self.assertEqual(list(output.parent.glob('*.tmp')), [])

    def test_fragment_preserves_data_without_document_wrapper(self):
        html = report.render_report(self.fixture(), fragment=True)
        self.assertRegex(html, r'^<section id="cd5-wu-report-[a-f0-9]{32}" class="cu-report">')
        self.assertNotEqual(html, report.render_report(self.fixture(), fragment=True))
        for tag in ['<html', '<head>', '<body>', '<!doctype']:
            self.assertNotIn(tag, html)
        self.assertIn('.cu-report{color-scheme', html)
        self.assertIn('id="report-data"', html)

    def test_root_selection_forwarded(self):
        calls = []
        def report_data(root, **options):
            calls.append((root, options))
            return self.fixture()
        fake = types.SimpleNamespace(report_data=report_data, _events=lambda root: [])
        with tempfile.TemporaryDirectory(dir=Path(__file__).parents[1]) as directory:
            output = Path(directory) / 'report.html'
            with patch.dict(sys.modules, {'control_units': fake}):
                report.main(['--root', directory, '--output', str(output), '--since', '2026-10-01', '--until', '2026-10-21'])
        self.assertEqual(calls[0][1], {'all_units': True, 'since': '2026-10-01', 'until': '2026-10-21'})

    def test_root_default_loads_history_and_sets_page_size(self):
        calls = []
        def report_data(root, **options):
            calls.append(options)
            data = self.fixture()
            data['units'] = [{**data['units'][0], 'cu_id': f'CU-{index}'} for index in range(21)]
            return data
        with tempfile.TemporaryDirectory(dir=Path(__file__).parents[1]) as directory:
            output = Path(directory) / 'report.html'
            with patch.dict(sys.modules, {'control_units': types.SimpleNamespace(report_data=report_data, _events=lambda root: [])}):
                report.main(['--root', directory, '--output', str(output)])
            payload = json.loads(output.read_text(encoding='utf-8').split('<script id="report-data" type="application/json">')[1].split('</script>')[0])
        self.assertTrue(calls[0]['all_units'])
        self.assertEqual(len(payload['units']), 21)
        self.assertEqual(payload['page_size'], 10)

    @unittest.skipUnless(shutil.which('node'), 'Node is optional for pagination verification')
    def test_js_pagination_covers_21_rows_and_clamps_boundaries(self):
        template = Path(report.__file__).with_suffix('.html').read_text(encoding='utf-8')
        helper = 'function pageState(' + template.split('function pageState(', 1)[1].split('function renderView(', 1)[0]
        script = helper + '''
const assert=require('node:assert/strict');const seen=[];
for(let page=0;page<3;page++){const state=pageState(21,10,page);assert.equal(state.count,3);for(let i=state.start;i<state.end;i++)seen.push(i);}
assert.deepEqual(seen,Array.from({length:21},(_,i)=>i));
assert.equal(new Set(seen).size,21);
assert.deepEqual(pageState(21,10,-1),{page:0,count:3,start:0,end:10});
assert.deepEqual(pageState(21,10,99),{page:2,count:3,start:20,end:21});
assert.deepEqual(pageState(0,10,1),{page:0,count:1,start:0,end:0});
for(const total of [0,1,10,11,41]){const all=[];const count=Math.max(1,Math.ceil(total/10));for(let page=0;page<count;page++){const state=pageState(total,10,page);assert.equal(state.count,count);assert.equal(state.page===0,page===0);assert.equal(state.page===state.count-1,page===count-1);for(let i=state.start;i<state.end;i++)all.push(i);}assert.deepEqual(all,Array.from({length:total},(_,i)=>i));}
'''
        result = subprocess.run([shutil.which('node'), '-e', script], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_all_direct_data_has_no_default_cap(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parents[1]) as directory:
            source, output = Path(directory) / 'input.json', Path(directory) / 'output.html'
            data = self.fixture()
            data['units'] = [{**data['units'][0], 'cu_id': f'CU-{index}'} for index in range(15)]
            source.write_text(json.dumps(data), encoding='utf-8')
            report.main(['--data-file', str(source), '--output', str(output), '--all'])
            payload = output.read_text(encoding='utf-8').split('<script id="report-data" type="application/json">')[1].split('</script>')[0]
            self.assertEqual(len(json.loads(payload)['units']), 15)

    def test_moscow_inclusive_dates_and_lifetime_overlap(self):
        data = self.fixture()
        def unit(cu_id, start, end):
            return {**data['units'][0], 'cu_id': cu_id, 'started_at': start, 'ended_at': end}
        data['units'] = [
            unit('ended-before', '2026-10-19T00:00:00Z', '2026-10-20T20:59:59Z'),
            unit('ends-at-start', '2026-10-19T00:00:00Z', '2026-10-20T21:00:00Z'),
            unit('last-second', '2026-10-21T20:59:59Z', '2026-10-21T21:00:01Z'),
            unit('next-day', '2026-10-21T21:00:00Z', None),
            unit('ongoing', '2026-10-19T00:00:00Z', None),
        ]
        selected = report.select_data(data, since='2026-10-21', until='2026-10-21', limit=1)
        self.assertEqual([u['cu_id'] for u in selected['units']], ['ends-at-start', 'last-second', 'ongoing'])
        self.assertEqual(selected['scope']['total_units'], 3)
        self.assertIn('за всё выполнение', selected['scope']['usage_label'])
        with self.assertRaises(ValueError):
            report.select_data(data, since='2026-10-22', until='2026-10-21')

    def test_selection_applies_to_every_optional_view(self):
        unit = self.fixture()['units'][0]
        units = [{**unit, 'cu_id': 'early', 'started_at': '2026-10-20T12:00:00Z', 'ended_at': '2026-10-20T13:00:00Z'},
                 {**unit, 'cu_id': 'late', 'started_at': '2026-10-21T12:00:00Z', 'ended_at': '2026-10-21T13:00:00Z'}]
        data = {**self.fixture(), 'units': units, 'default_view': 'saved',
                'views': [{'id': 'saved', 'label': 'Сохранённый срез', 'units': units}]}
        selected = report.select_data(data, since='2026-10-21', until='2026-10-21')
        self.assertEqual([u['cu_id'] for u in selected['units']], ['late'])
        self.assertEqual([u['cu_id'] for u in selected['views'][0]['units']], ['late'])
        self.assertEqual(selected['views'][0]['scope']['total_units'], 1)
        self.assertEqual(selected['default_view'], 'saved')
        self.assertEqual(len(data['views'][0]['units']), 2)

    def test_main_duration_uses_measured_hq_turns(self):
        html = report.render_report(self.fixture())
        self.assertIn("const elapsed=element('td',duration(unit.reported_ms)", html)
        self.assertIn('Длительность существования CU:', html)
        self.assertIn('включая ожидания; не активное вычисление', html)

    @unittest.skipUnless(shutil.which('node'), 'Node is optional for formatting verification')
    def test_js_wu_formatting_and_partial_cells(self):
        template = Path(report.__file__).with_suffix('.html').read_text(encoding='utf-8')
        functions = template.split('function formatWU', 1)[1].split('function renderMethod', 1)[0]
        script = '''
const assert=require('node:assert/strict');
function element(tag,text,cls){return {tag,text,cls,children:[],attributes:{},listeners:{},setAttribute(k,v){this.attributes[k]=v;},addEventListener(k,v){this.listeners[k]=v;},append(...children){this.children.push(...children);}};}
function formatWU''' + functions + '''
assert.equal(formatWU('4.814348'),'4,81');
assert.equal(formatWU('0'),'0,00');
assert.equal(formatWU(null),'—');
assert.equal(formatWU(''),'—');
assert.equal(formatWU('NaN'),'—');
const partial=costCell({value:null,status:'partial',known_value:'4.814348'});
assert.equal(partial.text,'—');
assert.equal(partial.children[0].text,'Частично · известно 4,81');
const unknown=costCell({value:null,status:'unknown',known_value:null});
assert.equal(unknown.text,'—');
assert.equal(unknown.children[0].text,'Нет данных');
const exact=costCell({value:'4.814348',status:'complete'});
assert.equal(exact.text,'4,81');
assert.equal(exact.children.length,0);
'''
        result = subprocess.run([shutil.which('node'), '-e', script], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        full_script = template.split('</script><script>', 1)[1].rsplit('</script>', 1)[0]
        syntax = subprocess.run([shutil.which('node'), '--check'], input=full_script, capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(syntax.returncode, 0, syntax.stderr)

    def test_wu_main_columns_and_upstream_selected_total(self):
        template = Path(report.__file__).with_suffix('.html').read_text(encoding='utf-8')
        heading = template.split('<table aria-label="Control Units">', 1)[1].split('</thead>', 1)[0]
        self.assertEqual(heading.count('<th>') + heading.count('<th '), 7)
        self.assertIn('Plan / Actual<br>WU</th>', heading)
        self.assertNotIn('Вход из кэша', heading)
        self.assertIn("costCell(data.work_units?.total,'td','Actual ')", template)
        self.assertNotIn('const sums=', template)

    @unittest.skipUnless(shutil.which('node'), 'Node is optional for budget cell verification')
    def test_budget_cell_values_unknowns_partial_and_safe_history(self):
        template = Path(report.__file__).with_suffix('.html').read_text(encoding='utf-8')
        functions = 'function formatWU' + template.split('function formatWU', 1)[1].split('function renderMethod', 1)[0]
        script = '''
const assert=require('node:assert/strict');
function element(tag,text,cls){return {tag,text,cls,children:[],attributes:{},listeners:{},setAttribute(k,v){this.attributes[k]=v;},addEventListener(k,v){this.listeners[k]=v;},append(...children){this.children.push(...children);}};}
function time(value){return value||'—';}
function texts(node){return [node.text??'',...node.children.flatMap(texts)];}
''' + functions + '''
const unit={budget:{forecast:{low:'3',high:'6',confidence:'medium'},limit:'8',original_forecast:{low:'2',high:'5',confidence:'low'},history:[]},work_units:{value:'4.814348',status:'complete'},budget_comparison:{forecast_status:'within',limit_status:'below',forecast_basis:'original'}};
assert.deepEqual(budgetCell(unit).children[0].children.map(n=>n.text),['Plan 3–6','Actual 4,81','All agents']);
assert.deepEqual(budgetCell({}).children[0].children.map(n=>n.text),['Plan: not estimated','Actual —','Unknown']);const longReason='Long reason '.repeat(200);assert(!texts(budgetCell({budget:{forecast_unknown_reason:longReason}})).includes(longReason));assert(budgetDescription({budget:{forecast_unknown_reason:longReason}}).some(text=>text.includes(longReason)));
assert.deepEqual(budgetCell({budget:{forecast:{low:'0',high:'0'},limit:'0'},work_units:{value:'0',status:'complete'}}).children[0].children.map(n=>n.text),['Plan 0–0','Actual 0,00','All agents']);
const knownHQ={work_units:{status:'unknown'},participants:[{role:'hq',work_units:{known_value:'75.791588',status:'complete'}},{role:'helper',work_units:{known_value:'12',status:'complete'}}]};
assert.equal(budgetCell(knownHQ).children[0].children[1].text,'Actual 75,79');
assert.equal(budgetCell(knownHQ).children[0].children[2].text,'Planner only');
knownHQ.participants[0].work_units.status='partial';assert.equal(budgetCell(knownHQ).children[0].children[1].text,'Actual ≥ 75,79');
assert(!texts(budgetCell(knownHQ)).some(text=>text.includes('87,79')));
assert.equal(formatBudget('0.001'),'0,001');
assert.equal(formatBudget(null),'—');
const complete=budgetDescription(unit);
assert(complete.includes('Факт относительно исходного прогноза: в диапазоне'));
assert(complete.includes('Исходный прогноз: 2–5 WU · уверенность низкая'));
assert(complete.includes('Уверенность прогноза: средняя'));
const partial={...unit,work_units:{value:null,status:'partial',known_value:'4.814348'},budget_comparison:{forecast_status:'above',limit_status:'exceeded',forecast_basis:'original'}};
assert(!budgetDescription(partial).some(line=>line.includes('превышен')||line.includes('относительно')));
assert.equal(budgetCell(partial).children[0].children[1].text,'Actual ≥ 4,81');
assert.equal(budgetCell(partial).children[0].children[2].text,'Partial');let opened=false;function openBudget(value,trigger){assert.equal(value,unit);opened=true;}budgetCell(unit).children[0].listeners.click();assert(opened);
assert(!texts(budgetDetails(unit)).includes('История изменений'));assert(!texts(budgetDetails(unit)).some(line=>/лимит/i.test(line)));assert(budgetDescription({budget:{forecast_unknown_reason:'No comparable history'}}).includes('Почему нет плана: No comparable history'));
const hostile='<img src=x onerror=alert(1)>';
const revised={...unit,budget:{...unit.budget,history:[{at:'2026-10-21',event_id:'revision-1',forecast:{low:'3',high:'6',confidence:'medium'},limit:'8',reason:hostile}]}};
const detail=budgetDetails(revised);
assert(texts(detail).includes('История изменений'));
const list=detail.children.find(n=>n.tag==='ul');
assert.equal(list.children.length,1);
assert.equal(list.children[0].tag,'li');
assert(list.children[0].text.includes(hostile));
assert.equal(list.children[0].children.length,0);
'''
        result = subprocess.run([shutil.which('node'), '-e', script], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which('node'), 'Node is optional for view routing verification')
    def test_js_saved_view_default_and_switch_use_precomputed_totals(self):
        template = Path(report.__file__).with_suffix('.html').read_text(encoding='utf-8')
        routing = 'const views=' + template.split('const views=', 1)[1].split('})();', 1)[0]
        script = '''
const assert=require('node:assert/strict');
const snapshots=[];let toolbar;
const root={querySelector(){return {after(node){toolbar=node;}};}};
function element(tag,text,cls){return {tag,text,cls,children:[],attributes:{},listeners:{},append(node){this.children.push(node);},setAttribute(key,value){this.attributes[key]=value;},addEventListener(key,fn){this.listeners[key]=fn;}};}
function renderView(dataset){snapshots.push(dataset);}
const reportData={title:'Root',units:[],work_units:{total:{value:'999'}},default_view:'earlier',views:[
{id:'latest',label:'Последние',title:'Latest',units:[{cu_id:'CU-2'}],work_units:{total:{value:'2.123456'}}},
{id:'earlier',label:'Ранее',title:'Earlier',units:[{cu_id:'CU-1'}],work_units:{total:{value:'1.234567'}}}]};
''' + routing + '''
assert.equal(snapshots.length,1);assert.equal(snapshots[0].title,'Earlier');
assert.equal(snapshots[0].work_units.total.value,'1.234567');
assert.equal(toolbar.children[1].attributes['aria-pressed'],'true');
toolbar.children[0].listeners.click();
assert.equal(snapshots.length,2);assert.equal(snapshots[1].title,'Latest');
assert.equal(snapshots[1].work_units.total.value,'2.123456');
assert.equal(snapshots[1].units[0].cu_id,'CU-2');
assert.equal(toolbar.children[0].attributes['aria-pressed'],'true');
assert.equal(toolbar.children[1].attributes['aria-pressed'],'false');
'''
        result = subprocess.run([shutil.which('node'), '-e', script], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_custom_rates_forwarded_without_mutating_input(self):
        data = self.fixture()
        with patch.dict(sys.modules, {'work_units': types.SimpleNamespace(annotate_report=lambda value, rate_path=None: {**value, 'rate_path_seen': str(rate_path)})}):
            html = report.render_report(data, rate_path=Path('fixture-rates.json'))
        payload = html.split('<script id="report-data" type="application/json">')[1].split('</script>')[0]
        self.assertEqual(json.loads(payload)['rate_path_seen'], 'fixture-rates.json')
        self.assertNotIn('rate_path_seen', data)

    def test_render_enriches_exact_cost_from_raw_counters(self):
        data = self.fixture()
        usage = {'cached_input': 814348, 'uncached_input': 200000, 'output': 0}
        unit = data['units'][0]
        unit.update(usage=usage.copy(), usage_status='complete', work_units={'value': '999999'}, participants=[
            {'participant_id': 'hq', 'model': 'gpt-6.1-sol', 'coverage': 'complete',
             'exclusive_scope': True, 'usage': usage.copy()}])
        html = report.render_report(data)
        payload = json.loads(html.split('<script id="report-data" type="application/json">')[1].split('</script>')[0])
        self.assertEqual(payload['units'][0]['work_units']['value'], '4.814348')
        self.assertEqual(payload['work_units']['total']['value'], '4.814348')
        self.assertEqual(unit['work_units']['value'], '999999')


if __name__ == '__main__':
    unittest.main()
