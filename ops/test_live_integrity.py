import json
from pathlib import Path
import tempfile
import unittest
from guard import check_cohort_evidence

class EvidenceChecks(unittest.TestCase):
    def test_false_integrity_alerts(self):
        self.assertTrue(check_cohort_evidence([],Path('/unused'),{'integrity':{'ok':False}}))
    def test_receipt_cannot_hide_deleted_journal(self):
        with tempfile.TemporaryDirectory() as temp:
            state=Path(temp); (state/'slot-01').mkdir()
            (state/'slot-01/result.json').write_text(json.dumps({'attempt_id':'original'}))
            rows=[{'slot':1,'status':'CAPTURED'}]
            empty={'integrity':{'ok':True},'summary':{'records':[]}}
            self.assertTrue(check_cohort_evidence(rows,state,empty))
            empty['summary']['records']=[{'id':'original'}]
            self.assertEqual(check_cohort_evidence(rows,state,empty),[])
    def test_missing_result_alerts(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertTrue(check_cohort_evidence([{'slot':1,'status':'CAPTURED'}],Path(temp),{'integrity':{'ok':True}}))
    def test_pending_not_misclassified_as_corrupt(self):
        self.assertEqual(check_cohort_evidence([{'slot':1,'status':'PENDING'}],Path('/unused'),{'integrity':{'ok':True}}),[])
