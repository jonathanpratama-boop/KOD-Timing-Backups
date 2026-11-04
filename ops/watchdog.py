#!/usr/bin/env python3
"""GitHub-side stale-heartbeat, archive integrity, and operational alert check."""
import datetime as dt
import hashlib
import json
import os
import re
from pathlib import Path
import sys
import tarfile
import urllib.request
from completion_notice import maybe_notify

TITLE='KOD timing experiment needs attention'
UTC=dt.timezone.utc

def inspect(root, now):
    issues=[]
    path=root/'HEALTH.json'
    if not path.exists(): return ['No off-server heartbeat has arrived yet']
    health=json.loads(path.read_text())
    age=(now-dt.datetime.fromisoformat(health['as_of'])).total_seconds()
    if age>7200: issues.append(f'No fresh off-server heartbeat for {age/3600:.1f} hours; server or backup may be down')
    if age < -300: issues.append('Server heartbeat is in the future')
    issues.extend(health.get('issues',[]))
    snapshot=root/health['snapshot']
    if not snapshot.is_file(): issues.append('Snapshot file missing'); return issues
    if hashlib.sha256(snapshot.read_bytes()).hexdigest()!=health['snapshot_sha256']:
        issues.append('Snapshot archive hash mismatch'); return issues
    with tarfile.open(snapshot) as archive:
        manifest=json.load(archive.extractfile('MANIFEST.json'))
        for path,expected in manifest.items():
            if hashlib.sha256(archive.extractfile(path.lstrip('/')).read()).hexdigest()!=expected:
                issues.append('Snapshot member hash mismatch: '+path)
    return issues

def api(method,path,data=None):
    request=urllib.request.Request('https://api.github.com/repos/'+os.environ['GITHUB_REPOSITORY']+path,
        data=json.dumps(data).encode() if data is not None else None,method=method,
        headers={'Authorization':'Bearer '+os.environ['GH_TOKEN'],'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'})
    with urllib.request.urlopen(request,timeout=30) as result: return json.load(result)

INCIDENT_MARKER='<!-- KOD_WATCHDOG_INCIDENTS_V1 '

def incident_key(issue):
    """Keep an ongoing stale heartbeat stable as its displayed age increases."""
    return re.sub(r'^(No fresh off-server heartbeat) for [0-9.]+ hours;', r'\1;', issue)

def previous_incidents(body):
    """Read persisted keys, or migrate the original unmarked bullet-list format."""
    body=body or ''
    if INCIDENT_MARKER in body:
        encoded=body.split(INCIDENT_MARKER,1)[1].split(' -->',1)[0]
        try:
            value=json.loads(encoded)
            if value.get('schema')==1 and isinstance(value.get('keys'),list) and all(isinstance(x,str) for x in value['keys']):
                return set(value['keys'])
        except (ValueError,TypeError,AttributeError):
            pass
    # Original deployed bodies used literal backslash-n separators; also accept
    # ordinary Markdown newlines and manually edited legacy issues.
    lines=body.replace('\\n','\n').splitlines()
    return {incident_key(line[2:].strip()) for line in lines if line.startswith('- ')}

def incident_marker(keys):
    encoded=json.dumps({'schema':1,'keys':sorted(keys)},sort_keys=True)
    encoded=encoded.replace('<','\\u003c').replace('>','\\u003e')
    return INCIDENT_MARKER+encoded+' -->'

def notify(issues,test=False):
    opened=api('GET','/issues?state=open&per_page=100')
    existing=next((x for x in opened if x['title']==TITLE and 'pull_request' not in x),None)
    link=os.environ['GITHUB_SERVER_URL']+'/'+os.environ['GITHUB_REPOSITORY']+'/actions/runs/'+os.environ['GITHUB_RUN_ID']
    if issues:
        current={incident_key(issue):issue for issue in issues}
        body=('**DELIVERY TEST — no experiment failure was induced.**\n\n' if test else '')+'\n'.join('- '+x for x in current.values())+'\n\n[Check details]('+link+'). The collector has not been restarted or modified. Review HEALTH.json and the latest recovery snapshot.'+'\n\n'+incident_marker(current)
        if existing:
            new_keys=set(current)-previous_incidents(existing.get('body'))
            if new_keys:
                comment='@jonathanpratama-boop New KOD safeguard problem detected while this issue is open:\n\n'+'\n'.join('- '+current[key] for key in sorted(new_keys))+'\n\n[Check details]('+link+'). The collector has not been restarted or modified.'
                # Notify before persisting the new state: a failed notification
                # must not be marked delivered. A partial API failure may retry.
                api('POST','/issues/'+str(existing['number'])+'/comments',{'body':comment})
            # Repeated states and removal of a subset of issues update quietly.
            api('PATCH','/issues/'+str(existing['number']),{'body':body})
        else:
            result=api('POST','/issues',{'title':TITLE,'body':body,'assignees':['jonathanpratama-boop']})
            print('Alert created: '+result['html_url'])
    elif existing:
        api('POST','/issues/'+str(existing['number'])+'/comments',{'body':'Health and backup verification now pass. '+link+' . Historical observations and the experiment schedule were not changed.'})
        api('PATCH','/issues/'+str(existing['number']),{'state':'closed'})
        print('Previous alert resolved')

if __name__=='__main__':
    now=dt.datetime.now(UTC)
    if now>=dt.datetime(2026,11,10,10,tzinfo=UTC) and os.getenv('TEST_ALERT')!='true':
        print('Bounded monitoring window ended; snapshots remain in repository'); sys.exit(0)
    test=os.getenv('TEST_ALERT')=='true'
    try: issues=inspect(Path('.'),now)
    except Exception as exc: issues=['Unable to verify recovery snapshot: '+str(exc)]
    if test: issues.append('Synthetic alert delivery test requested during commissioning')
    notify(issues,test)
    if not test:
        run_url=os.environ['GITHUB_SERVER_URL']+'/'+os.environ['GITHUB_REPOSITORY']+'/actions/runs/'+os.environ['GITHUB_RUN_ID']
        maybe_notify(Path('.'),now,api,run_url,issues)
    print(json.dumps({'issues':issues,'test':test}))
    sys.exit(1 if issues else 0)
