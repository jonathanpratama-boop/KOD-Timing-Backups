"""GitHub incident notifications tested entirely with a mocked API."""
import copy
import unittest
from unittest.mock import patch

import watchdog

ENV = {
    'GITHUB_SERVER_URL': 'https://github.com',
    'GITHUB_REPOSITORY': 'owner/private-backups',
    'GITHUB_RUN_ID': '123',
}
STALE_OLD = 'No fresh off-server heartbeat for 2.1 hours; server or backup may be down'
STALE_LATER = 'No fresh off-server heartbeat for 3.2 hours; server or backup may be down'


class FakeAPI:
    def __init__(self, body=None):
        self.issue = None if body is None else {'number': 7, 'title': watchdog.TITLE, 'body': body}
        self.calls = []
        self.fail_comment = False

    def __call__(self, method, path, data=None):
        self.calls.append((method, path, copy.deepcopy(data)))
        if method == 'GET':
            return [copy.deepcopy(self.issue)] if self.issue else []
        if path.endswith('/comments'):
            if self.fail_comment:
                raise RuntimeError('simulated notification delivery failure')
            return {'id': 101}
        if method == 'POST' and path == '/issues':
            self.issue = dict(data, number=7)
            return {'html_url': 'https://github.com/owner/private-backups/issues/7'}
        if method == 'PATCH':
            self.issue.update(data)
            return copy.deepcopy(self.issue)
        raise AssertionError((method, path, data))

    def comments(self):
        return [data['body'] for method, path, data in self.calls if path.endswith('/comments')]


class EscalationTests(unittest.TestCase):
    def send(self, api, issues):
        with patch.dict(watchdog.os.environ, ENV), patch.object(watchdog, 'api', api):
            watchdog.notify(issues)

    def test_first_problem_creates_assigned_issue_with_state_marker(self):
        api = FakeAPI()
        self.send(api, ['Slot 1: MISSED'])
        self.assertEqual(api.issue['assignees'], ['jonathanpratama-boop'])
        self.assertEqual(watchdog.previous_incidents(api.issue['body']), {'Slot 1: MISSED'})
        self.assertEqual(api.comments(), [])

    def test_new_stale_heartbeat_notifies_despite_historical_missed_slot(self):
        api = FakeAPI('- Slot 1: MISSED\n\n[Check details](https://example.test)')
        self.send(api, ['Slot 1: MISSED', STALE_OLD])
        self.assertEqual(len(api.comments()), 1)
        self.assertIn('@jonathanpratama-boop', api.comments()[0])
        self.assertIn(STALE_OLD, api.comments()[0])
        self.assertNotIn('Slot 1: MISSED', api.comments()[0])
        self.assertEqual(set(watchdog.previous_incidents(api.issue['body'])),
                         {'Slot 1: MISSED', watchdog.incident_key(STALE_OLD)})

    def test_repeated_state_and_increasing_stale_age_do_not_notify_again(self):
        api = FakeAPI('- Slot 1: MISSED')
        self.send(api, ['Slot 1: MISSED', STALE_OLD])
        self.send(api, ['Slot 1: MISSED', STALE_LATER])
        self.send(api, [STALE_LATER, 'Slot 1: MISSED'])
        self.assertEqual(len(api.comments()), 1)
        self.assertIn(STALE_LATER, api.issue['body'])

    def test_new_halt_is_notified_once_while_other_incident_remains(self):
        api = FakeAPI('- Slot 1: MISSED')
        issues = ['Slot 1: MISSED', 'Collector HALTED; operator review required']
        self.send(api, issues)
        self.send(api, issues)
        self.assertEqual(len(api.comments()), 1)
        self.assertIn('Collector HALTED', api.comments()[0])

    def test_legacy_escaped_body_migrates_without_false_repeat_notification(self):
        api = FakeAPI('- Slot 1: MISSED\\n- '+STALE_OLD+'\\n\\n[Check details](https://example.test)')
        self.send(api, ['Slot 1: MISSED', STALE_LATER])
        self.assertEqual(api.comments(), [])
        self.assertIn(watchdog.INCIDENT_MARKER, api.issue['body'])
        self.assertEqual(watchdog.previous_incidents(api.issue['body']),
                         {'Slot 1: MISSED', watchdog.incident_key(STALE_OLD)})

    def test_partial_recovery_is_quiet_but_recurrence_notifies(self):
        api = FakeAPI('- Slot 1: MISSED\n- '+STALE_OLD)
        self.send(api, ['Slot 1: MISSED'])
        self.assertEqual(api.comments(), [])
        self.send(api, ['Slot 1: MISSED', STALE_LATER])
        self.assertEqual(len(api.comments()), 1)

    def test_full_recovery_still_comments_and_closes(self):
        api = FakeAPI('- '+STALE_OLD)
        self.send(api, [])
        self.assertEqual(len(api.comments()), 1)
        self.assertIn('now pass', api.comments()[0])
        self.assertEqual(api.issue['state'], 'closed')

    def test_failed_escalation_comment_does_not_acknowledge_new_state(self):
        api = FakeAPI('- Slot 1: MISSED')
        api.fail_comment = True
        with self.assertRaisesRegex(RuntimeError, 'delivery failure'):
            self.send(api, ['Slot 1: MISSED', STALE_OLD])
        self.assertEqual(api.issue['body'], '- Slot 1: MISSED')
        self.assertFalse(any(method == 'PATCH' for method, _, _ in api.calls))
        api.fail_comment = False
        self.send(api, ['Slot 1: MISSED', STALE_LATER])
        self.assertEqual(watchdog.previous_incidents(api.issue['body']),
                         {'Slot 1: MISSED', watchdog.incident_key(STALE_LATER)})

    def test_invalid_marker_falls_back_to_legacy_bullets(self):
        api = FakeAPI('- Slot 1: MISSED\n\n'+watchdog.INCIDENT_MARKER+'not-json -->')
        self.send(api, ['Slot 1: MISSED'])
        self.assertEqual(api.comments(), [])
        self.assertEqual(watchdog.previous_incidents(api.issue['body']), {'Slot 1: MISSED'})

    def test_marker_roundtrip_handles_html_delimiters(self):
        keys = {'Unable to verify snapshot: unexpected --> contents <tag>'}
        self.assertEqual(watchdog.previous_incidents(watchdog.incident_marker(keys)), keys)


if __name__ == '__main__':
    unittest.main()
