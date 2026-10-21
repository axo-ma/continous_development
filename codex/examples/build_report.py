"""Build an offline synthetic example with the canonical CD5 report generator."""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

CODEX=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(CODEX/'skills/cd5/scripts'))
from control_unit_report import write_report
from cu_budget import initial_budget, normalize_patch, apply_patch
from work_units import annotate_report


def participant(identity,name,role,cached,uncached,output,elapsed=120000):
    return {'participant_id':identity,'thread_id':identity,'name':name,'role':role,
        'model':'gpt-6.1-sol','reasoning':'low' if role=='hq' else 'high','elapsed_ms':elapsed,
        'coverage':'complete','exclusive_scope':True,
        'usage':{'cached_input':cached,'uncached_input':uncached,'output':output}}


def demo_data():
    definitions=[
        ('CU-012','Подготовить отчёт','Отчёт готов',3,6,8,[
            participant('demo-hq','Штаб','hq',2458368,16308,3233),
            participant('demo-review','Проверяющий','reviewer',418560,42553,4369,40000)]),
        ('CU-011','Проверить сбор расхода','Проверки пройдены',2,4,None,[participant('demo-11','Штаб','hq',400000,60000,8000)]),
        ('CU-010','Обновить документацию','Инструкция обновлена',1,2,None,[participant('demo-10','Штаб','hq',250000,15000,8000)]),
        ('CU-009','Проверить крайние случаи','Найдена и исправлена ошибка',2,3,None,[participant('demo-9','Штаб','hq',600000,100000,10000)])]
    units=[]
    for index,(identity,title,result,low,high,limit,people) in enumerate(definitions):
        at=f'2026-10-21T{14-index:02d}:00:00+03:00'
        plan={'forecast':{'low':low,'high':high,'confidence':'medium'}}
        if limit is not None:plan['limit']=limit
        budget=apply_patch(initial_budget(),normalize_patch(plan),at=at,event_id='demo-plan-'+identity,initial=True)
        usage={key:sum(p['usage'][key] for p in people) for key in ('cached_input','uncached_input','output')}
        units.append({'cu_id':identity,'title':title,'goal':title,'description':'Вымышленный пример для документации. Реальные журналы не используются.',
            'result':result,'result_detail':'Сохранённые подробности открываются без нового обращения к модели.',
            'status':'completed','started_at':at,'ended_at':(dt.datetime.fromisoformat(at)+dt.timedelta(minutes=2)).isoformat(),
            'elapsed_ms':120000,'reported_ms':120000,
            'participants':people,'usage':usage,'usage_status':'complete','budget':budget,
            'sources':[{'label':'Демонстрационный пример','text':'Синтетические задачи и счётчики; это не история пользователя.'}]})
    return {'schema_version':1,'title':'Пример прогресса · демонстрационные данные','generated_at':'2026-10-21T15:00:00+03:00',
            'units':units,'page_size':10,'scope':{'label':'Демонстрационные данные','usage_label':'Факт по всем четырём примерам'}}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=CODEX/'docs/examples/progress-report.html')
    args=parser.parse_args()
    data=demo_data();priced=annotate_report(data)
    assert priced['units'][0]['work_units']['value']=='4.814348'
    assert priced['work_units']['total']['value']=='12.164348'
    write_report(data,args.output)
    args.output.with_suffix('.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'Built synthetic offline report: {args.output}')


if __name__=='__main__':main()
