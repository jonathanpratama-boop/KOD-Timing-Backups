import datetime as dt
import unittest

from capacity_watchdog_r2 import (CONFIG_SHA256, DETAILED_SYMBOLS, END, ORIGINAL_COMMIT,
                                 PRIMARY_SYMBOLS, START, TRIAL_ID, UTC, inspect)

NOW = dt.datetime(2026, 11, 5, 10, 32, 30, tzinfo=UTC)


def fixture(at=NOW):
    minutes = max(0, min(2880, int((at - START).total_seconds() // 60) - 1))
    stamp = at.isoformat()
    return {
        "schema": "KOD_CAPACITY_HEALTH_V1", "trial_id": TRIAL_ID,
        "config_sha256": CONFIG_SHA256, "emitted_at": stamp,
        "issues": [], "pause_latched": False, "phase": "RUNNING",
        "automatically_promotes_30_day_study": False,
        "service_actual_status": {"ActiveState": "active", "SubState": "running", "MainPID": "27250"},
        "preservation": {"status": "OK", "unchanged": True, "source_commit": ORIGINAL_COMMIT,
                         "source_files_checked": 527, "static_invariants_checked": 34, "problems": []},
        "resource_check": {"status": "OK", "issues": [], "unknown": []},
        "collector": {
            "trial_id": TRIAL_ID, "config_hash": CONFIG_SHA256, "as_of": stamp,
            "phase": "RUNNING", "pid": 27250, "worker_closing": False, "queue_overflows": 0,
            "capacity_trial_only": True, "scientific_enrollment": False,
            "last_minute_commit_at": stamp,
            "stream": {"connected": True, "reader_alive": True, "events_dropped": 0,
                       "closed_dropped": 0, "invalid_messages": 0, "clock_anomalies": 0},
            "coverage": {
                "settled_minutes": minutes, "fixed_primary_asset_count": 130,
                "full_48h_expected_closed_total": 374400,
                "expected_closed_total": 130 * minutes, "on_time_closed_total": 130 * minutes,
                "closed_bars": {s: {"expected": minutes, "on_time": minutes, "eventual": minutes}
                                for s in PRIMARY_SYMBOLS},
                "broad_bbo": {s: {"expected": minutes, "valid_received": minutes} for s in PRIMARY_SYMBOLS},
                "detailed_five": {s: {"expected": minutes * 12, "valid_received": minutes * 12}
                                  for s in DETAILED_SYMBOLS},
            }
        }
    }


class CapacityWatchdogTests(unittest.TestCase):
    def test_complete_running_sample(self):
        result = inspect(fixture(), NOW)
        self.assertEqual(result["issues"], [])
        self.assertEqual(result["status"], "COLLECTION_HEALTHY_SO_FAR")
        self.assertEqual(result["capacity_acceptance"], "NOT_ESTABLISHED")

    def test_actual_1732_false_green_is_degraded(self):
        health = fixture()
        health.update(status="OK", issues=[])
        coverage = health["collector"]["coverage"]
        coverage.update(pooled_at_least_99pct=True, every_detailed_at_least_99pct=True)
        for row in coverage["detailed_five"].values():
            row.update(valid_received=1255, coverage=1.0)
        result = inspect(health, NOW)
        self.assertEqual(result["status"], "DEGRADED")
        self.assertIn("detailed_five: below 99% coverage for 5 assets", result["issues"])
        self.assertAlmostEqual(result["summary"]["detailed_five"]["coverage"], 1255 / 1488)

    def test_exact_99pct_boundary(self):
        at = START + dt.timedelta(minutes=101, seconds=5)
        health = fixture(at)
        for row in health["collector"]["coverage"]["detailed_five"].values():
            row["valid_received"] = 1188  # 99% of 1200
        self.assertEqual(inspect(health, at)["issues"], [])
        health["collector"]["coverage"]["detailed_five"]["BTCUSDT"]["valid_received"] = 1187
        self.assertTrue(inspect(health, at)["issues"])

    def test_wrong_trial_or_config(self):
        for key in ("trial_id", "config_sha256"):
            with self.subTest(key=key):
                health = fixture()
                health[key] = "wrong"
                self.assertTrue(inspect(health, NOW)["issues"])

    def test_clock_and_staleness(self):
        for value in ("not-a-date", "2026-11-05T10:32:30", "2026-11-05T09:00:00Z",
                      "2026-11-05T11:00:00Z"):
            with self.subTest(value=value):
                health = fixture()
                health["collector"]["as_of"] = value
                self.assertTrue(inspect(health, NOW)["issues"])

    def test_stale_heartbeat_1800_boundary(self):
        health = fixture()
        self.assertEqual(inspect(health, NOW + dt.timedelta(seconds=1800))["issues"], [])
        self.assertTrue(inspect(health, NOW + dt.timedelta(seconds=1801))["issues"])

    def test_fresh_heartbeat_cannot_hide_stopped_minute_writer(self):
        health = fixture()
        health["collector"]["last_minute_commit_at"] = (NOW - dt.timedelta(minutes=4)).isoformat()
        self.assertIn("Minute commits are not progressing near collector heartbeat",
                      inspect(health, NOW)["issues"])

    def test_member_replacement_same_count_fails(self):
        health = fixture()
        rows = health["collector"]["coverage"]["closed_bars"]
        rows["UNREGISTEREDUSDT"] = rows.pop("BTCUSDT")
        self.assertTrue(inspect(health, NOW)["issues"])

    def test_denominator_tampering_fails(self):
        health = fixture()
        coverage = health["collector"]["coverage"]
        coverage["settled_minutes"] = 100
        for row in coverage["detailed_five"].values():
            row.update(expected=1200, valid_received=1200)
        self.assertTrue(inspect(health, NOW)["issues"])

    def test_bool_or_overfull_count_fails(self):
        for value in (True, -1, 1489, "1488", None):
            with self.subTest(value=value):
                health = fixture()
                health["collector"]["coverage"]["detailed_five"]["BTCUSDT"]["valid_received"] = value
                self.assertTrue(inspect(health, NOW)["issues"])

    def test_missing_required_sections_fail(self):
        for section in ("collector", "preservation", "resource_check", "service_actual_status"):
            with self.subTest(section=section):
                health = fixture()
                del health[section]
                self.assertTrue(inspect(health, NOW)["issues"])

    def test_resource_or_preservation_failure(self):
        health = fixture()
        health["resource_check"]["issues"] = ["memory exceeded"]
        health["preservation"]["unchanged"] = False
        result = inspect(health, NOW)
        self.assertGreaterEqual(len(result["issues"]), 2)

    def test_stopped_service_fails(self):
        health = fixture()
        health["service_actual_status"]["ActiveState"] = "inactive"
        self.assertTrue(inspect(health, NOW)["issues"])

    def test_window_end_never_infers_acceptance(self):
        at = END + dt.timedelta(minutes=1)
        result = inspect(fixture(at), at)
        self.assertEqual(result["status"], "TRIAL_WINDOW_ENDED_REVIEW_REQUIRED")
        self.assertTrue(result["issues"])
        self.assertEqual(result["capacity_acceptance"], "NOT_ESTABLISHED")

    def test_non_object_fails(self):
        self.assertTrue(inspect([], NOW)["issues"])

    def test_unknown_or_changed_scope_fails(self):
        health = fixture()
        del health["collector"]["scientific_enrollment"]
        result = inspect(health, NOW)
        self.assertTrue(result["issues"])
        self.assertEqual(result["scientific_enrollment"], "UNKNOWN")
        health["collector"]["scientific_enrollment"] = True
        self.assertTrue(inspect(health, NOW)["issues"])


if __name__ == "__main__":
    unittest.main()

