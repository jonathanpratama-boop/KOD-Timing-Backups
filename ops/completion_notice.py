"""Bounded collection-window notification. No strategy promotion or collection mutation."""
import datetime as dt
import json
from pathlib import Path

TITLE='KOD 30-slot collection window ended — review results'

def maybe_notify(root, now, api, run_url, issues):
    path=Path(root)/'HEALTH.json'
    if not path.exists(): return False
    health=json.loads(path.read_text())
    slots=health.get('slots',[])
    if len(slots)!=30: return False
    final=max(dt.datetime.fromisoformat(r['scheduled_at'].replace('Z','+00:00')) for r in slots)
    if now < final+dt.timedelta(minutes=15): return False
    existing=api('GET','/issues?state=all&per_page=100')
    if any(x['title']==TITLE and 'pull_request' not in x for x in existing): return False
    base=run_url.split('/actions/runs/')[0]
    captured=sum(r['status']=='CAPTURED' for r in slots)
    body=(f"@jonathanpratama-boop The scheduled collection window has ended. Last reported capture count: **{captured}/30**. "
          f"Latest server snapshot: {health.get('as_of','unknown')}.\n\n"
          + ('**Needs review:** '+ '; '.join(issues)+'\n\n' if issues else '')
          + f"[Descriptive cohort report]({base}/blob/main/COHORT-REPORT.json) · [Health and recovery copy]({base}/blob/main/HEALTH.json) · [Check run]({run_url})\n\n"
          + 'This notice is not a success verdict. Missing, failed and partial slots remain in the denominator; stale status may be incomplete. Review evidence and unknown stages before deciding the next experiment. No detector, strategy or live trading has been promoted.')
    api('POST','/issues',{'title':TITLE,'body':body,'assignees':['jonathanpratama-boop']})
    return True
