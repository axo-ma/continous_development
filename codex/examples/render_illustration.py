"""Draw a labelled report illustration as SVG; --png additionally requires Pillow."""
import argparse
from html import escape
import os
from pathlib import Path

CODEX=Path(__file__).resolve().parents[1]
WIDTH,HEIGHT=1800,1150
BG,SURFACE,SOFT,INK,MUTED,LINE,LINK='#171d26','#202936','#253247','#e8edf5','#a7b3c6','#3a475b','#9bc0ff'


def render(png=False):
    output=CODEX/'docs/images';output.mkdir(parents=True,exist_ok=True)
    svg=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-labelledby="title desc">',
         '<title id="title">Пример отчёта о прогрессе CD5</title>',
         '<desc id="desc">Иллюстрация на вымышленных данных: четыре CU, раскрытая команда и KNOWLEDGE, ATTENTION и план–факт WU. Не скриншот пользовательского проекта.</desc>']
    image=draw=None
    if png:
        from PIL import Image,ImageDraw,ImageFont
        image=Image.new('RGB',(WIDTH,HEIGHT),BG);draw=ImageDraw.Draw(image)
    fonts={}
    def font(size):
        if size not in fonts:
            choices=['DejaVuSans.ttf',str(Path(os.environ.get('WINDIR',''))/'Fonts/segoeui.ttf')]
            for choice in choices:
                try:fonts[size]=ImageFont.truetype(choice,size);break
                except OSError:pass
            else:raise RuntimeError('A Unicode font is needed to redraw PNG; SVG has no such dependency')
        return fonts[size]
    def rect(x,y,w,h,fill):
        svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}"/>')
        if draw:draw.rectangle((x,y,x+w,y+h),fill=fill)
    def line(y,x1=50,x2=1750):
        svg.append(f'<path d="M{x1} {y}H{x2}" stroke="{LINE}"/>')
        if draw:draw.line((x1,y,x2,y),fill=LINE,width=1)
    def text(x,y,value,size=24,color=INK):
        svg.append(f'<text x="{x}" y="{y}" fill="{color}" font-family="Segoe UI,DejaVu Sans,sans-serif" font-size="{size}">{escape(str(value))}</text>')
        if draw:draw.text((x,y-size),str(value),font=font(size),fill=color)
    rect(0,0,WIDTH,HEIGHT,BG)
    text(50,70,'Прогресс проекта',38)
    text(50,111,'Иллюстрация интерфейса · вымышленные данные · 23.10.2026',23,MUTED)
    text(50,148,'Время — измеренные ходы штаба, включая ожидания',22,MUTED)
    rect(50,179,180,46,SURFACE);text(65,211,'← Новее',23,MUTED)
    text(258,211,'Записи 1–4 из 4',23)
    rect(520,179,190,46,SURFACE);text(535,211,'Раньше →',23,MUTED)
    for left,label,width in [(770,'План проекта',240),(1030,'KNOWLEDGE · Знания',360),(1410,'ATTENTION · Внимание',340)]:
        rect(left,179,width,46,SURFACE);text(left+12,211,label,22,LINK)
    x=[65,190,430,850,1260,1395,1570]
    rect(50,250,1700,52,SURFACE)
    for pos,label in zip(x,['№','Запуск МСК','Задача','Результат','Время','Agents','План / Факт']):text(pos,285,label,23,MUTED)
    def task(y,identity,date,title,result,forecast,actual,expanded=False):
        rect(50,y,1700,110,SURFACE);rect(1540,y,210,110,SOFT)
        for pos,value in zip(x[:6],[identity,date,title,result,'2 мин','↓ Agents' if expanded else '› Agents']):
            text(pos,y+47,value,22,LINK if pos in (430,850,1395) else INK)
        text(1570,y+40,'План '+forecast,21);text(1570,y+82,'Факт '+actual,23)
        line(y+110)
    task(302,'1','21.10 · 14:00','Подготовить отчёт','Отчёт готов','3–6','4,81',True)
    rect(50,412,1700,250,SOFT)
    text(82,453,'Команда · CU-012',25)
    tx=[82,310,500,720,850,1010,1230,1450,1620]
    for pos,label in zip(tx,['Участник','Роль','Модель','Effort','Время','Из кэша','Вне кэша','Выход','WU']):text(pos,497,label,21,MUTED)
    people=[['Planner','hq','Sol 6.1','low','2 мин','2 458 368','16 308','3 233','3,11'],
            ['Reviewer','reviewer','Sol 6.1','high','40 с','418 560','42 553','4 369','1,71']]
    for row,values in enumerate(people):
        for pos,value in zip(tx,values):text(pos,539+row*42,value,22)
    text(82,627,'Итого команды · время ходов штаба',22)
    for pos,value in zip(tx[4:],['2 мин','2 876 928','58 861','7 602','4,81']):text(pos,627,value,22)
    task(662,'2','21.10 · 13:00','Проверить сбор расхода','Проверки пройдены','2–4','2,40')
    task(772,'3','21.10 · 12:00','Обновить документацию','Инструкция обновлена','1–2','1,35')
    task(882,'4','21.10 · 11:00','Проверить крайние случаи','Ошибка исправлена','2–3','3,60')
    text(65,1040,'Факт по всей выбранной истории · 4 CU',25);text(1570,1040,'12,16',25)
    text(50,1100,'WU — базовая оценка стоимости токенов; не остаток подписки.',22,MUTED)
    svg.append('</svg>')
    (output/'progress-report.svg').write_text('\n'.join(svg)+'\n',encoding='utf-8')
    if image:image.save(output/'progress-report.png')
    print('Rendered labelled report illustration'+(' (SVG and PNG)' if png else ' (SVG)'))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--png',action='store_true')
    render(parser.parse_args().png)
