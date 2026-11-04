#!/usr/bin/env python3
"""Pure descriptive closeout builder for the fixed 30-slot KOD collection cohort.

No reads, writes, network calls, collector invocation or strategy promotion.
All inputs are supplied by the caller; ``now`` must be timezone aware.
"""
import copy
import datetime as dt
import math
import statistics
from collections import Counter

SCHEMA = 'KOD_OPERATIONAL_COHORT_REPORT_V1'
TERMINAL = frozenset({'CAPTURED', 'PARTIAL', 'BLOCKED', 'MISSED', 'INTERRUPTED', 'FAILED'})
UTC = dt.timezone.utc


def _time(value):
    parsed = value if isinstance(value, dt.datetime) else dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.utcoffset() is None:
        raise ValueError('timezone-aware time required')
    return parsed.astimezone(UTC)


def _stats(values, expected=None):
    """Nearest-rank p95, with missing/invalid measurements explicitly excluded."""
    numbers = []
    for value in values:
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0:
            numbers.append(value)
    numbers.sort()
    total = max(len(values), expected or 0)
    return {'known': len(numbers), 'unknown_or_invalid': total - len(numbers),
            'median_seconds': statistics.median(numbers) if numbers else None,
            'p95_seconds': numbers[math.ceil(.95 * len(numbers))-1] if numbers else None,
            'worst_seconds': numbers[-1] if numbers else None,
            'p95_method': 'nearest rank; descriptive only'}


def build_report(plan, rows, timing_status, corrections, now):
    """Return a deterministic, independent report without modifying its inputs.

    ``rows`` contains numbered slot receipts/assessments; omitted slots are derived
    as pending, due, or overdue using a reporting-only 15-minute grace. Terminal
    failures remain in the fixed denominator. ``timing_status`` is the original
    runtime timing-status JSON (or None when unavailable). ``corrections`` is the
    additive clock report; it may also be None. Raw source-clock offsets are never
    used here. ``complete`` means every slot has a terminal receipt, not success.
    ``review_ready`` becomes true on completion or fifteen minutes after the last
    slot, permitting a truthful incomplete closeout rather than indefinite waiting.
    """
    now = _time(now)
    schedule = plan['slots']
    dates = [_time(value) for value in schedule]
    if len(dates) != 30 or len(set(dates)) != 30 or dates != sorted(dates):
        raise ValueError('exactly thirty distinct ordered slots required')
    if any((b-a).total_seconds() != 14400 for a, b in zip(dates, dates[1:])):
        raise ValueError('the frozen cohort must remain four-hourly')
    by_slot = {}
    for original in rows:
        number = original.get('slot')
        if isinstance(number, bool) or not isinstance(number, int) or not 1 <= number <= 30:
            raise ValueError('invalid slot identity')
        if number in by_slot:
            raise ValueError('duplicate slot identity')
        if original.get('scheduled_at') is not None and _time(original['scheduled_at']) != dates[number-1]:
            raise ValueError('receipt schedule differs from frozen plan')
        row = copy.deepcopy(original)
        row['scheduled_at'] = schedule[number-1]
        if row.get('status') in TERMINAL and dates[number-1] > now:
            raise ValueError('terminal receipt for a future planned slot')
        by_slot[number] = row
    normalized = []
    for number, due in enumerate(dates, 1):
        row = by_slot.get(number, {'slot': number, 'scheduled_at': schedule[number-1], 'status': 'PENDING'})
        if row.get('status') not in TERMINAL:
            # Evaluate freshness from the declared schedule, not stale status text.
            previous = row.get('status', 'UNKNOWN')
            if now >= due + dt.timedelta(minutes=15):
                row['status'] = 'OVERDUE'
            elif now >= due:
                row['status'] = 'IN_PROGRESS_OR_DUE'
            else:
                row['status'] = 'PENDING'
            if previous not in ('PENDING', 'IN_PROGRESS_OR_DUE', 'DUE_UNRECORDED', 'OVERDUE'):
                row['reported_status'] = previous
        normalized.append(row)
    counts = dict(sorted(Counter(row['status'] for row in normalized).items()))
    terminal = sum(counts.get(status, 0) for status in TERMINAL)
    complete = terminal == 30
    closed = now >= dates[-1] + dt.timedelta(minutes=15)
    noncaptured = [row['slot'] for row in normalized if row['status'] in TERMINAL and row['status'] != 'CAPTURED']
    unresolved = [row['slot'] for row in normalized if row['status'] not in TERMINAL]
    outcome = ('COMPLETE_WITH_NONCAPTURED_SLOTS' if noncaptured else 'COMPLETE_READY_FOR_REVIEW') if complete else (
        'CLOSED_INCOMPLETE_REVIEW_REQUIRED' if closed else 'IN_PROGRESS')

    timing = copy.deepcopy(timing_status or {})
    summary = timing.get('summary') or {}
    cohorts = summary.get('cohorts') or []
    prospective = [cohort for cohort in cohorts if cohort.get('evidence_kind') == 'prospective']
    main = [cohort for cohort in prospective if cohort.get('detector_version') in ('INTRADAY_OBSERVATION_V1', 'SCHEDULED_OBSERVATION_V1')]
    requests = [cohort for cohort in prospective if cohort.get('detector_version') == 'SOURCE_REQUEST_V1']
    main_count = sum(cohort.get('attempts', 0) for cohort in main)
    request_count = sum(cohort.get('attempts', 0) for cohort in requests)
    details = summary.get('records') or []
    request_details = [row for row in details if ':request:' in str(row.get('id', ''))]
    durations = [(row.get('monotonic_seconds') or {}).get('request') for row in request_details]
    duration_scope_verified = len(request_details) == request_count and not any(
        cohort.get('detector_version') == 'SOURCE_REQUEST_V1' and cohort.get('evidence_kind') != 'prospective'
        for cohort in cohorts)

    correction_data = copy.deepcopy(corrections or {})
    records = correction_data.get('records') or []
    cohort_clocks = [row for row in records if '/timing-forward/timing/clocks/' in row.get('original_file', '')]
    other_clocks = [row for row in records if row not in cohort_clocks]
    return {
        'schema': SCHEMA, 'as_of': now.isoformat(), 'outcome': outcome,
        'complete': complete, 'collection_closed': closed, 'review_ready': complete or closed,
        'entry_permission': False, 'strategy_promotion': False,
        'scope': 'Thirty operational collection slots; no detector, strategy, decision or execution test',
        'source_commit': plan.get('source_commit'),
        'planned_slots': 30, 'terminal_slots': terminal, 'status_counts': counts,
        'captured_slots': counts.get('CAPTURED', 0),
        'noncaptured_terminal_slots': noncaptured, 'unresolved_slots': unresolved,
        'first_scheduled_at': schedule[0], 'last_scheduled_at': schedule[-1],
        'closeout_eligible_at': (dates[-1] + dt.timedelta(minutes=15)).isoformat(),
        'slots': normalized,
        'timing': {
            'available': bool(summary) and timing.get('integrity', {}).get('ok') is not False, 'report_as_of': summary.get('as_of'),
            'integrity': timing.get('integrity'),
            'main_attempts': main_count, 'source_request_attempts': request_count,
            'all_journal_identities': summary.get('attempts'),
            'main_cohorts': main, 'source_request_cohorts': requests,
            'other_cohorts': [cohort for cohort in cohorts if cohort not in main and cohort not in requests],
            'request_monotonic_duration': _stats(durations if duration_scope_verified else [], request_count),
            'request_duration_scope_verified': duration_scope_verified,
            'request_detail_rows': len(request_details),
            'missing_stages': summary.get('missing_stages'),
            'source_lag': summary.get('source_latency'),
        },
        'corrected_clock': {
            'available': bool(corrections), 'schema': correction_data.get('schema'),
            'cohort_record_count': len(cohort_clocks),
            'cohort_status_counts': dict(sorted(Counter(row.get('status', 'UNKNOWN') for row in cohort_clocks).items())),
            'cohort_records': cohort_clocks, 'other_record_count': len(other_clocks),
            'legacy_offset_used': False,
        },
        'coverage': {'symbols': copy.deepcopy(plan.get('symbols')), 'interval': plan.get('interval'),
                     'requested_bars_per_symbol_per_slot': plan.get('bars'),
                     'per_slot_bar_completeness': 'NOT_EVALUATED_BY_THIS_REPORT'},
        'limitations': [
            'Completion counts every terminal receipt, including failed, missed, blocked, partial and interrupted slots.',
            'The 15-minute closeout grace is an operational reporting rule, not a new success threshold.',
            'Thirty slots and individual source requests are not independent market regimes or investment decisions.',
            'No numerical pass threshold or strategy promotion is inferred from these descriptive measurements.',
            'HTTP request duration is not event-to-receipt delay; unknown stages remain unknown.',
            'Request-detail IDs use the frozen producer :request: convention; mixed evidence kinds or count mismatch prevent pooled request-duration statistics.',
            'The frozen legacy integrity verifier contains the known clock-offset parsing defect; use the separate correction.',
            'Corrected clock readings are derived estimates, not independent timestamp certificates.',
            'Sampling is bounded and intermittent; this report does not establish continuous coverage or profitability.',
        ],
    }
