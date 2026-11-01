"""One per-user Windows Scheduled Task: logon, failure recovery and missing-process recovery."""
import argparse
import datetime as dt
from pathlib import Path
import xml.etree.ElementTree as ET

NS = 'http://schemas.microsoft.com/windows/2004/02/mit/task'


def task_xml(home, runner, pythonw, user_sid, now=None):
    home, runner, pythonw = (Path(p).resolve() for p in (home, runner, pythonw))
    if not user_sid or any(c in str(home)+str(runner)+str(pythonw) for c in '\r\n"'):
        raise ValueError('explicit safe task paths and current user SID required')
    ET.register_namespace('', NS)
    root = ET.Element('{'+NS+'}Task', version='1.4')
    def add(parent, tag, text=None, **attrs):
        node=ET.SubElement(parent, '{'+NS+'}'+tag, **attrs)
        if text is not None: node.text=str(text)
        return node
    info=add(root,'RegistrationInfo')
    add(info,'Description','CD5 Continuator: one user process; recover by Windows, never by a model.')
    triggers=add(root,'Triggers')
    logon=add(triggers,'LogonTrigger');add(logon,'Enabled','true');add(logon,'UserId',user_sid)
    timer=add(triggers,'TimeTrigger')
    repetition=add(timer,'Repetition');add(repetition,'Interval','PT1M');add(repetition,'StopAtDurationEnd','false')
    start=(now or dt.datetime.now().astimezone())+dt.timedelta(seconds=3)
    add(timer,'StartBoundary',start.isoformat(timespec='seconds'));add(timer,'Enabled','true')
    principal=add(add(root,'Principals'),'Principal',id='CurrentUser')
    add(principal,'UserId',user_sid);add(principal,'LogonType','InteractiveToken');add(principal,'RunLevel','LeastPrivilege')
    settings=add(root,'Settings')
    for tag,text in [('MultipleInstancesPolicy','IgnoreNew'),('DisallowStartIfOnBatteries','false'),
                     ('StopIfGoingOnBatteries','false'),('AllowHardTerminate','true'),('StartWhenAvailable','true'),
                     ('RunOnlyIfNetworkAvailable','false'),('Enabled','true'),('Hidden','true'),
                     ('RunOnlyIfIdle','false'),('WakeToRun','false'),('ExecutionTimeLimit','PT0S'),('Priority','7')]:
        add(settings,tag,text)
    restart=add(settings,'RestartOnFailure');add(restart,'Interval','PT1M');add(restart,'Count','999')
    action=add(add(root,'Actions',Context='CurrentUser'),'Exec')
    add(action,'Command',str(pythonw));add(action,'Arguments',f'"{runner}" --home "{home}"')
    add(action,'WorkingDirectory',str(home))
    return ET.tostring(root, encoding='unicode')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for flag in ('home','runner','pythonw','user-sid'):parser.add_argument('--'+flag,required=True)
    args=parser.parse_args()
    print(task_xml(args.home,args.runner,args.pythonw,args.user_sid))
