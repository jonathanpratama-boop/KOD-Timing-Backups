#!/usr/bin/env python3
"""Independent operational health and off-server recovery copy. Never invokes collector."""
import collections
import datetime as dt
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import time
from clock_corrections import report
from cohort_report import build_report

UTC=dt.timezone.utc
BASE=Path('/var/lib/kod-ops')
REPO=BASE/'repository'
PLAN=Path('/etc/kod/observation-plan.json')
EXPECTED_PLAN='bffe919924e56a48d49e92045f86e3ee4678ac5ae03aad8287ae8d6e6af6af6b'
ROOTS=[Path('/var/lib/kod/timing-forward'),Path('/var/lib/kod/commissioning/real-capture')]

def run(args, **kw):
    return subprocess.run(args, capture_output=True, text=True, timeout=120, **kw)

def unit(name):
    r=run(['systemctl','show',name,'-p','ActiveState','-p','Result','-p','ExecMainStatus'])
    if r.returncode: raise RuntimeError(r.stderr)
    return dict(line.split('=',1) for line in r.stdout.splitlines() if '=' in line)

def assess(plan, state, now):
    issues=[]; rows=[]
    if (state/'HALTED.json').exists(): issues.append('Collector HALTED; operator review required')
    for n,s in enumerate(plan['slots'],1):
        folder=state/f'slot-{n:02d}'; due=dt.datetime.fromisoformat(s.replace('Z','+00:00'))
        row={'slot':n,'scheduled_at':s,'status':'PENDING'}
        if (folder/'end.json').exists():
            row=json.loads((folder/'end.json').read_text())
            if row['status']!='CAPTURED': issues.append(f"Slot {n}: {row['status']}")
        elif (now-due).total_seconds()>900:
            row['status']='OVERDUE'; issues.append(f'Slot {n}: no completion after 15 minutes')
        elif due<=now: row['status']='IN_PROGRESS_OR_DUE'
        rows.append(row)
    return rows,issues

def check_cohort_evidence(rows, state, timing):
    issues=[]
    if timing.get('integrity',{}).get('ok') is not True:
        return ['Collected evidence integrity verification failed']
    identities={r['id'] for r in timing.get('summary',{}).get('records',[]) if 'id' in r}
    for row in rows:
        if row['status'] not in ('CAPTURED','PARTIAL','BLOCKED','MISSED'):
            continue
        path=state/f"slot-{row['slot']:02d}"/'result.json'
        try:
            result=json.loads(path.read_text())
            identity=result.get('attempt_id') or result.get('id')
            if not identity or identity not in identities:
                issues.append(f"Slot {row['slot']}: completed receipt lacks retained timing evidence")
        except (OSError, ValueError):
            issues.append(f"Slot {row['slot']}: completed receipt lacks readable result evidence")
    return issues


def included_files():
    # Explicit allowlist; excludes SSH credentials, environment files, and unrelated host files.
    bases=[Path('/var/lib/kod/timing-forward'),Path('/var/lib/kod/schedule'),
           Path('/var/lib/kod/commissioning'),Path('/opt/kod/current').resolve(),Path('/opt/kod/bin')]
    singles=[PLAN,Path('/etc/kod/DEPLOYMENT.json'),Path('/opt/kod/HANDOFF.md'),
             Path('/opt/kod/CLOCK-ERRATUM-20261104.md'),
             Path('/etc/systemd/system/kod-observe.service'),Path('/etc/systemd/system/kod-observe.timer'),
             Path('/etc/systemd/system/kod-guard.service'),Path('/etc/systemd/system/kod-guard.timer')]
    paths=set(singles)
    for base in bases:
        paths.update(p for p in base.rglob('*') if p.is_file() and not p.is_symlink())
    return sorted(p for p in paths if p.is_file() and not p.is_symlink()
                  and not any(x.startswith('.') or x=='__pycache__' for x in p.parts)
                  and not p.name.endswith(('.pyc','.lock')))

def digest_files(paths):
    return {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}

def git(*args):
    r=run(['git','-C',str(REPO),*args])
    if r.returncode: raise RuntimeError(f'git {args[0]}: {r.stderr[-1200:]}')
    return r.stdout.strip()

def main():
    now=dt.datetime.now(UTC); plan=json.loads(PLAN.read_bytes())
    collector=unit('kod-observe.service')
    # No locks or writes in collector state. Never overlap known active collection or its immediate lead-in.
    if collector['ActiveState'] in ('activating','active','deactivating'):
        print('Collection active; defer independent backup to next check'); return
    if any(0 <= (dt.datetime.fromisoformat(s.replace('Z','+00:00'))-now).total_seconds() < 120 for s in plan['slots']):
        print('Collection imminent; defer independent backup'); return
    rows,issues=assess(plan,Path('/var/lib/kod/schedule'),now)
    plan_sha=hashlib.sha256(PLAN.read_bytes()).hexdigest()
    if plan_sha != EXPECTED_PLAN: issues.append('Frozen plan bytes changed')
    timer=unit('kod-observe.timer')
    if any(r['status']=='PENDING' for r in rows) and timer['ActiveState']!='active': issues.append('Collector timer not active')
    if collector.get('Result')!='success': issues.append('Collector service result: '+collector.get('Result','unknown'))
    source=run(['/opt/kod/venv/bin/python','/opt/kod/bin/check-source.py'])
    if source.returncode: issues.append('Frozen source integrity failed')
    timing={'integrity':{'ok':False},'summary':{}}
    if source.returncode == 0:
        checked=run(['/opt/kod/venv/bin/python','/opt/kod/current/tools/kod.py','runtime','--root',str(ROOTS[0]),'timing-status'])
        try:
            if checked.returncode != 0: raise ValueError('Verifier command failed')
            timing=json.loads(checked.stdout)
            issues.extend(check_cohort_evidence(rows,Path('/var/lib/kod/schedule'),timing))
        except (ValueError,KeyError):
            issues.append('Collected evidence integrity verification failed')
    else:
        issues.append('Evidence verification skipped because frozen source integrity failed')
    corrections=report(ROOTS)
    if any(r['status']=='UNVERIFIED' for r in corrections['records']): issues.append('At least one retained clock correction is unverified')
    clock=run(['chronyc','-c','tracking'])
    if clock.returncode or not clock.stdout.strip().endswith(',Normal'): issues.append('Current host clock not synchronized')
    if shutil.disk_usage('/').free < 1024**3: issues.append('Less than 1 GiB free disk')
    paths=included_files(); hashes=digest_files(paths)
    signature=hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest()
    previous=json.loads((BASE/'last-push.json').read_text()) if (BASE/'last-push.json').exists() else {}
    if previous.get('signature')==signature and previous.get('issues')==issues and time.time()-previous.get('epoch',0)<3600:
        print('No evidence or health change; next heartbeat within one hour'); return
    git('pull','--ff-only','origin','main')
    snapshot=REPO/'snapshots'/f'{signature}.tar.gz'
    snapshot.parent.mkdir(exist_ok=True)
    if not snapshot.exists():
        fd,name=tempfile.mkstemp(dir=BASE,suffix='.tar.gz'); os.close(fd)
        try:
            with tarfile.open(name,'w:gz') as archive:
                for p in paths: archive.add(p,arcname=str(p).lstrip('/'),recursive=False)
                manifest=json.dumps(hashes,sort_keys=True,indent=2).encode()
                info=tarfile.TarInfo('MANIFEST.json'); info.size=len(manifest)
                archive.addfile(info,io.BytesIO(manifest))
            if digest_files(included_files())!=hashes or unit('kod-observe.service')['ActiveState'] in ('activating','active'):
                print('Evidence changed during backup; retry next check'); return
            with tarfile.open(name) as archive:
                for path,sha in hashes.items():
                    if hashlib.sha256(archive.extractfile(path.lstrip('/')).read()).hexdigest()!=sha:
                        raise RuntimeError('Backup archive hash mismatch: '+path)
            os.replace(name,snapshot)
        finally:
            if os.path.exists(name): os.unlink(name)
    health={'schema':'KOD_CLOUD_GUARD_V1','as_of':now.isoformat(),'issues':issues,
            'counts':dict(collections.Counter(r['status'] for r in rows)),'slots':rows,
            'plan_file_sha256':plan_sha,'plan_semantic_sha256':hashlib.sha256(json.dumps(plan,sort_keys=True).encode()).hexdigest(),
            'source_check':json.loads(source.stdout) if source.returncode==0 else {'ok':False},
            'snapshot':str(snapshot.relative_to(REPO)),'snapshot_sha256':hashlib.sha256(snapshot.read_bytes()).hexdigest(),
            'snapshot_files':len(hashes),'clock_corrections':'CLOCK-CORRECTIONS.json',
            'evidence_integrity_ok':timing.get('integrity',{}).get('ok') is True,
            'cohort_report':'COHORT-REPORT.json',
            'experiment_changed':False,'collector_service':collector,'collector_timer':timer}
    (REPO/'HEALTH.json').write_text(json.dumps(health,sort_keys=True,indent=2)+'\n')
    (REPO/'CLOCK-CORRECTIONS.json').write_text(json.dumps(corrections,sort_keys=True,indent=2)+'\n')
    cohort=build_report(plan,rows,timing,corrections,now)
    (REPO/'COHORT-REPORT.json').write_text(json.dumps(cohort,sort_keys=True,indent=2)+'\n')
    git('add','HEALTH.json','CLOCK-CORRECTIONS.json','COHORT-REPORT.json','snapshots')
    if git('status','--porcelain'): git('commit','-m','KOD recovery snapshot and operational heartbeat '+now.isoformat())
    git('push','origin','main')
    head=git('rev-parse','HEAD')
    if git('ls-remote','origin','refs/heads/main').split()[0]!=head: raise RuntimeError('Remote acknowledgement mismatch')
    (BASE/'last-push.json').write_text(json.dumps({'epoch':time.time(),'signature':signature,'issues':issues,'commit':head,'snapshot':health['snapshot']},indent=2)+'\n')
    print(json.dumps({'offsite_commit':head,'issues':issues,'counts':health['counts'],'snapshot_files':len(hashes)}))

if __name__=='__main__': main()
