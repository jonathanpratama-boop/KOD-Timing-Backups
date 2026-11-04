#!/usr/bin/env python3
"""Read-only deployment/cohort status, suitable for an independent reviewer."""
import collections
import datetime as dt
import hashlib
import json
from pathlib import Path
import subprocess

plan=json.loads(Path('/etc/kod/observation-plan.json').read_text())
now=dt.datetime.now(dt.timezone.utc)
rows=[]
for number,slot in enumerate(plan['slots'],1):
    directory=Path('/var/lib/kod/schedule')/f'slot-{number:02d}'
    if (directory/'end.json').exists():
        row=json.loads((directory/'end.json').read_text())
    elif (directory/'begin.json').exists():
        row={'slot':number,'scheduled_at':slot,'status':'STARTED_WITHOUT_COMPLETION'}
    else:
        due=dt.datetime.fromisoformat(slot.replace('Z','+00:00'))
        row={'slot':number,'scheduled_at':slot,'status':'DUE_UNRECORDED' if due<=now else 'PENDING'}
    rows.append(row)
print(json.dumps({'as_of':now.isoformat(),'server':'159.65.2.145','source_commit':plan['source_commit'],
    'scope':'Operational collection diagnostic only; no detector, account strategy or real orders',
    'plan_semantic_sha256':hashlib.sha256(json.dumps(plan,sort_keys=True).encode()).hexdigest(),
    'plan_file_sha256':hashlib.sha256(Path('/etc/kod/observation-plan.json').read_bytes()).hexdigest(),
    'clock_offset_warning':'Frozen collector offset_seconds is invalid; use additive CLOCK-CORRECTIONS.json in the private backup repository',
    'safeguards_repository':'https://github.com/jonathanpratama-boop/KOD-Timing-Backups',
    'symbols':plan['symbols'],'interval':plan['interval'],'bars':plan['bars'],
    'counts':dict(collections.Counter(x['status'] for x in rows)),
    'halted':Path('/var/lib/kod/schedule/HALTED.json').exists(),'slots':rows},indent=2))
for args in [
    ['systemctl','show','kod-observe.timer','-p','ActiveState','-p','NextElapseUSecRealtime'],
    ['systemctl','show','kod-observe.service','-p','ActiveState','-p','Result','-p','ExecMainStatus'],
    ['/opt/kod/venv/bin/python','/opt/kod/bin/check-source.py'],
    ['chronyc','tracking']
]:
    result=subprocess.run(args,text=True,capture_output=True)
    print(json.dumps({'command':args,'returncode':result.returncode,'stdout':result.stdout,'stderr':result.stderr}))
if Path('/var/lib/kod/timing-forward/timing/attempts.jsonl').exists():
    result=subprocess.run(['/opt/kod/venv/bin/python','/opt/kod/current/tools/kod.py','runtime','--root','/var/lib/kod/timing-forward','timing-status'],text=True,capture_output=True)
    if result.returncode==0:
        data=json.loads(result.stdout)
        integrity=data['integrity']
        evidence=integrity['linked_evidence']
        print(json.dumps({'timing_status_exit':0,'integrity_ok':integrity['ok'],
            'journal_attempts_including_source_requests':integrity['attempts'],
            'linked_evidence_counts':evidence['counts'],'external_verification':integrity['external_verification'],
            'summary':data['summary']}))
    else:
        print(json.dumps({'timing_status_exit':result.returncode,'error':result.stderr}))
