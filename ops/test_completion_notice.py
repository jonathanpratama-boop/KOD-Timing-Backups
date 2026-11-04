import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from completion_notice import maybe_notify,TITLE

class Completion(unittest.TestCase):
    def test_time_bound_and_single_notice_including_failures(self):
        with tempfile.TemporaryDirectory() as temp:
            now=dt.datetime(2026,11,4,13,tzinfo=dt.timezone.utc)
            rows=[{'scheduled_at':(now+dt.timedelta(hours=4*i)).isoformat(),'status':'CAPTURED' if i<29 else 'FAILED'} for i in range(30)]
            root=Path(temp); (root/'HEALTH.json').write_text(json.dumps({'slots':rows,'as_of':now.isoformat()}))
            calls=[]; opened=[]
            def api(method,path,data=None):
                calls.append((method,path,data))
                if method=='GET': return opened
                opened.append(data); return {'number':2}
            url='https://github.com/owner/repo/actions/runs/1'
            self.assertFalse(maybe_notify(root,now,api,url,[])); self.assertFalse(calls)
            after=now+dt.timedelta(hours=116,minutes=16)
            self.assertTrue(maybe_notify(root,after,api,url,['Slot 30: FAILED']))
            self.assertIn('29/30',opened[0]['body']); self.assertIn('Needs review',opened[0]['body'])
            self.assertFalse(maybe_notify(root,after,api,url,[]))
            self.assertEqual(sum(c[0]=='POST' for c in calls),1)
