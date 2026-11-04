import copy
import datetime as dt
import unittest
from cohort_report import build_report

UTC=dt.timezone.utc
FIRST=dt.datetime(2026,11,4,13,tzinfo=UTC)
PLAN={'slots':[(FIRST+dt.timedelta(hours=4*i)).isoformat() for i in range(30)],
      'symbols':['BTCUSDT','ETHUSDT'],'interval':'1m','bars':60}
LAST=FIRST+dt.timedelta(hours=116)

def receipts(status='CAPTURED'):
    return [{'slot':i+1,'scheduled_at':s,'status':status} for i,s in enumerate(PLAN['slots'])]

class CohortReportTests(unittest.TestCase):
    def test_pending_slots_keep_fixed_denominator(self):
        result=build_report(PLAN,[receipts()[0]],None,None,FIRST+dt.timedelta(minutes=1))
        self.assertEqual(result['planned_slots'],30)
        self.assertEqual(result['status_counts'],{'CAPTURED':1,'PENDING':29})
        self.assertFalse(result['complete']); self.assertFalse(result['review_ready'])
        self.assertFalse(result['timing']['available'])
    def test_failed_timing_status_stub_is_unavailable(self):
        report=build_report(PLAN,[],{'integrity':{'ok':False},'summary':{}},None,FIRST)
        self.assertFalse(report['timing']['available'])
        self.assertEqual(report['timing']['integrity'],{'ok':False})

    def test_closed_incomplete_does_not_wait_forever_or_fake_misses(self):
        result=build_report(PLAN,[receipts()[0]],None,None,LAST+dt.timedelta(minutes=15))
        self.assertTrue(result['collection_closed']); self.assertTrue(result['review_ready'])
        self.assertFalse(result['complete']); self.assertEqual(result['status_counts']['OVERDUE'],29)
        self.assertEqual(result['outcome'],'CLOSED_INCOMPLETE_REVIEW_REQUIRED')
    def test_terminal_failures_count_as_terminal_not_success(self):
        rows=receipts(); rows[-1]['status']='MISSED'; rows[2]['status']='FAILED'
        result=build_report(PLAN,rows,{},None,LAST+dt.timedelta(minutes=1))
        self.assertTrue(result['complete']); self.assertEqual(result['terminal_slots'],30)
        self.assertEqual(result['captured_slots'],28)
        self.assertEqual(result['noncaptured_terminal_slots'],[3,30])
        self.assertEqual(result['outcome'],'COMPLETE_WITH_NONCAPTURED_SLOTS')
        self.assertFalse(result['strategy_promotion']); self.assertFalse(result['entry_permission'])
    def test_request_counts_and_durations_not_main_observations(self):
        timing={'summary':{'attempts':9,'cohorts':[
            {'evidence_kind':'prospective','detector_version':'INTRADAY_OBSERVATION_V1','attempts':1,'stages':{'threshold':{'known':0,'unknown':1}}},
            {'evidence_kind':'prospective','detector_version':'SOURCE_REQUEST_V1','attempts':8}],
            'records':[{'id':'main','monotonic_seconds':{'invocation':99}}]+[
                {'id':f'main:request:{i}','monotonic_seconds':{'request':v}} for i,v in enumerate([1,2,3,4,5,6,None,-1])]}}
        result=build_report(PLAN,[receipts()[0]],timing,None,FIRST+dt.timedelta(minutes=1))
        self.assertEqual(result['timing']['main_attempts'],1)
        self.assertEqual(result['timing']['source_request_attempts'],8)
        stats=result['timing']['request_monotonic_duration']
        self.assertEqual((stats['known'],stats['unknown_or_invalid']),(6,2))
        self.assertEqual((stats['median_seconds'],stats['p95_seconds'],stats['worst_seconds']),(3.5,6,6))
        self.assertEqual(result['timing']['main_cohorts'][0]['stages']['threshold']['known'],0)
    def test_mixed_request_cohorts_are_not_pooled(self):
        timing={'summary':{'cohorts':[
            {'evidence_kind':'prospective','detector_version':'SOURCE_REQUEST_V1','attempts':1},
            {'evidence_kind':'synthetic','detector_version':'SOURCE_REQUEST_V1','attempts':1}],
            'records':[{'id':'a:request:0','monotonic_seconds':{'request':1}},
                       {'id':'b:request:0','monotonic_seconds':{'request':100}}]}}
        report=build_report(PLAN,[],timing,None,FIRST)
        self.assertFalse(report['timing']['request_duration_scope_verified'])
        self.assertIsNone(report['timing']['request_monotonic_duration']['median_seconds'])
        self.assertEqual(report['timing']['source_request_attempts'],1)

    def test_deterministic_and_no_input_mutation(self):
        rows=receipts()[:1]; args=[PLAN,rows,{'summary':{}},{'records':[]},FIRST]
        before=copy.deepcopy(args)
        one=build_report(*args); two=build_report(*args)
        self.assertEqual(one,two); self.assertEqual(before,args)
    def test_bad_schedule_and_duplicate_receipts_rejected(self):
        with self.assertRaises(ValueError): build_report({'slots':PLAN['slots'][:29]},[],None,None,FIRST)
        with self.assertRaises(ValueError): build_report(PLAN,[receipts()[0],receipts()[0]],None,None,FIRST)
        with self.assertRaises(ValueError): build_report(PLAN,receipts(),None,None,FIRST)
    def test_corrected_clock_keeps_commissioning_separate(self):
        corrections={'schema':'KOD_CHRONY_CSV_CORRECTION_V1','records':[
            {'original_file':'/var/lib/kod/timing-forward/timing/clocks/a.json','status':'DERIVED_FROM_RETAINED_RAW','system_correction_seconds':'0.002'},
            {'original_file':'/var/lib/kod/commissioning/real-capture/timing/clocks/b.json','status':'UNVERIFIED'}]}
        report=build_report(PLAN,[],None,corrections,FIRST)
        self.assertEqual(report['corrected_clock']['cohort_record_count'],1)
        self.assertEqual(report['corrected_clock']['other_record_count'],1)
        self.assertFalse(report['corrected_clock']['legacy_offset_used'])

if __name__=='__main__': unittest.main()
