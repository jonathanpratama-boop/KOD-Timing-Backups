import datetime as dt
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from clock_corrections import canonical, derive
from guard import assess
from watchdog import inspect

RAW='334FA8DC,51.79.168.220,3,1793795343.592268319,0.002434953,-0.001220258,0.004042143,-100.449,-0.144,5.471,0.003564034,0.012801948,65.0,Normal'
class Guards(unittest.TestCase):
    def correction(self,stdout=RAW,rc=0):
        with tempfile.TemporaryDirectory() as folder:
            obj={'command':'chronyc -c tracking','returncode':rc,'stdout':stdout,'observed_at':'2026-11-04T12:30:00Z','stderr':''}
            path=Path(folder)/('clock_'+hashlib.sha256(canonical(obj)).hexdigest()+'.json')
            path.write_text(json.dumps(obj)); before=path.read_bytes(); result=derive(path)
            self.assertEqual(before,path.read_bytes()); return result
    def test_real_14_column_offset(self):
        self.assertEqual(self.correction()['system_correction_seconds'],'0.002434953')
    def test_old_fake_13_columns_rejected(self):
        self.assertEqual(self.correction(RAW.replace('51.79.168.220,',''))['status'],'UNVERIFIED')
    def test_nonfinite_rejected(self):
        for value in ['NaN','Infinity','-Infinity']:
            self.assertEqual(self.correction(RAW.replace('0.002434953',value))['status'],'UNVERIFIED')
    def test_unsynced_and_error_rejected(self):
        self.assertEqual(self.correction(RAW.replace('Normal','Not synchronised'))['status'],'UNVERIFIED')
        self.assertEqual(self.correction(rc=1)['status'],'UNVERIFIED')
    def test_reference_epoch_not_used(self):
        self.assertEqual(self.correction()['reference_time_epoch'],'1793795343.592268319')
        self.assertEqual(self.correction()['conditional_error_bound_seconds'],'0.017018918')
    def test_evidence_tamper_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'clock_wrong.json'; p.write_text(json.dumps({'stdout':RAW}))
            self.assertEqual(derive(p)['status'],'UNVERIFIED')
    def test_grace_then_overdue(self):
        with tempfile.TemporaryDirectory() as folder:
            plan={'slots':['2026-11-04T13:00:00Z']}; root=Path(folder)
            self.assertEqual(assess(plan,root,dt.datetime(2026,11,4,13,5,tzinfo=dt.timezone.utc))[1],[])
            self.assertTrue(assess(plan,root,dt.datetime(2026,11,4,13,16,tzinfo=dt.timezone.utc))[1])
    def test_failed_partial_missed_halt_alert(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); (root/'slot-01').mkdir(); (root/'HALTED.json').write_text('{}')
            for status in ['FAILED','PARTIAL','BLOCKED','MISSED','INTERRUPTED']:
                (root/'slot-01/end.json').write_text(json.dumps({'status':status}))
                rows,issues=assess({'slots':['2026-11-04T13:00:00Z']},root,dt.datetime.now(dt.timezone.utc))
                self.assertEqual(len(issues),2)
    def test_missing_offsite_heartbeat_alert(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertTrue(inspect(Path(folder),dt.datetime.now(dt.timezone.utc)))
    def test_stale_heartbeat_and_missing_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); (root/'HEALTH.json').write_text(json.dumps({'as_of':'2026-11-04T10:00:00+00:00','snapshot':'absent'}))
            self.assertEqual(len(inspect(root,dt.datetime(2026,11,4,13,tzinfo=dt.timezone.utc))),2)
if __name__=='__main__': unittest.main()
