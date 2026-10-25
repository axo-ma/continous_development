import json
from pathlib import Path
import shutil
import subprocess
import unittest


class QuotaReportUITests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node is optional for interactive report checks')
    def test_views_role_filter_brief_answer_and_numeric_closed_summary(self):
        template = (Path(__file__).parents[1] / 'tools/control_unit_report.html').read_text(encoding='utf-8')
        helpers = 'function pageState(' + template.split('function pageState(', 1)[1].split('function renderView(', 1)[0]
        roles = 'function roleLabel(' + template.split('function roleLabel(', 1)[1].split('const metric=', 1)[0]
        script = r'''
const assert=require('node:assert/strict');
class Node{constructor(tag,text=''){this.tag=tag;this.own=String(text);this.children=[];this.listeners={};this.attributes={};}append(...nodes){for(const node of nodes){this.children.push(node);if(this.tag==='select'&&this.value===undefined&&node.tag==='option')this.value=node.value;}}set textContent(value){this.own=String(value);this.children=[];}get textContent(){return this.own+this.children.map(n=>n.textContent).join('');}setAttribute(k,v){this.attributes[k]=v;}replaceChildren(...nodes){this.children=[];this.own='';this.append(...nodes);}addEventListener(k,v){this.listeners[k]=v;}}
function element(tag,text,cls){const node=new Node(tag,text===undefined?'':text);node.className=cls;return node;}
function markdown(text){return element('p',text);}function time(value){return value||'—';}function formatWU(value){return value??'—';}function metric(value){return value??'—';}
function costCell(cost,tag){return element(tag,cost?.known_value??'—');}
const nodes=Object.fromEntries(['cu-view','quota-view','mode-cu','mode-quota'].map(id=>[id,new Node('div')]));const byId=id=>nodes[id];let reportMode='cu';function closePanel(){}
function find(node,tag){return [...(node.tag===tag?[node]:[]),...node.children.flatMap(child=>find(child,tag))];}
const planner={thread_id:'hq',role:'hq',name:'Штаб',cu_title:'Synthetic task',model:'gpt-6.1-sol',usage:{cached_input:20,uncached_input:10,output:5},work_units:{known_value:'1.25',status:'complete'},assignment:{text:'Inspect saved synthetic cells'},agent_result:{text:'Synthetic inspection result'},result:'CU-level result'};
const reviewer={...planner,thread_id:'reviewer',role:'reviewer',name:'reviewer',assignment:{text:'Review the synthetic result'},work_units:{known_value:'0.5',status:'complete'}};
let data={quota_usage:{windows:[{starts_at:'2026-10-24T08:00:00Z',ends_at:'2026-10-24T13:00:00Z',actors:[planner,reviewer],assignments:[planner,reviewer]}],unassigned:[{...reviewer,diagnostics:['native_reset_boundary_unavailable']}],diagnostics:[]}};
''' + roles + helpers + r'''
setReportMode('quota');assert.equal(nodes['cu-view'].hidden,true);assert.equal(nodes['quota-view'].hidden,false);assert.equal(nodes['mode-quota'].attributes['aria-pressed'],'true');
renderQuotaView();const host=nodes['quota-view'];assert(host.textContent.includes('Review the synthetic result'));assert(host.textContent.includes('Synthetic inspection result'));assert(host.textContent.includes('Без подтверждённого окна'));
const summary=find(host,'summary').find(n=>n.textContent.includes('МСК'));assert(summary.textContent.includes('Planner · 1.25 WU'));assert(summary.textContent.includes('Reviewer · 0.5 WU'));
const filter=find(host,'select')[0];filter.value='reviewer';filter.listeners.change();assert(!host.textContent.includes('Inspect saved synthetic cells'));assert(host.textContent.includes('Review the synthetic result'));
setReportMode('cu');assert.equal(nodes['cu-view'].hidden,false);assert.equal(nodes['quota-view'].hidden,true);
data={};renderQuotaView();assert(host.textContent.includes('Данные пятичасовых окон отсутствуют'));
'''
        result = subprocess.run([shutil.which('node'), '-e', script], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
