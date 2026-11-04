#!/usr/bin/env python3
"""Additive correction of retained chrony 4.5 CSV evidence; never edits originals."""
import csv
import hashlib
import json
from decimal import Decimal
from pathlib import Path

SCHEMA = 'KOD_CHRONY_CSV_CORRECTION_V1'

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()

def derive(path):
    raw = Path(path).read_bytes()
    value = json.loads(raw)
    out = {'schema': SCHEMA, 'original_file': str(path), 'original_sha256': hashlib.sha256(raw).hexdigest(),
           'evidence_id': Path(path).stem, 'observed_at': value.get('observed_at'),
           'status': 'UNVERIFIED', 'system_correction_seconds': None,
           'legacy_offset_seconds_is_invalid': True,
           'meaning': 'Derived chrony system correction, not independent proof of absolute time'}
    try:
        if Path(path).stem != 'clock_' + hashlib.sha256(canonical(value)).hexdigest():
            raise ValueError('original evidence identity mismatch')
        if value.get('command') != 'chronyc -c tracking' or value.get('returncode') != 0:
            raise ValueError('unsupported or failed measurement')
        rows = list(csv.reader(value['stdout'].strip().splitlines()))
        if len(rows) != 1 or len(rows[0]) != 14:
            raise ValueError('expected exactly one 14-column chrony 4.5 record')
        fields = rows[0]
        if fields[13].strip() != 'Normal' or not 1 <= int(fields[2]) <= 15:
            raise ValueError('clock not synchronized normally')
        if fields[0].upper() in ('00000000', '7F7F0101'):
            raise ValueError('no external reference')
        numbers = [Decimal(x) for x in fields[3:13]]
        if not all(x.is_finite() for x in numbers):
            raise ValueError('nonfinite measurement')
        offset, delay, dispersion = Decimal(fields[4]), Decimal(fields[10]), Decimal(fields[11])
        if delay < 0 or dispersion < 0:
            raise ValueError('negative uncertainty component')
        out.update(status='DERIVED_FROM_RETAINED_RAW', system_correction_seconds=str(offset),
                   root_delay_seconds=str(delay), root_dispersion_seconds=str(dispersion),
                   reference_time_epoch=fields[3],
                   conditional_error_bound_seconds=str(abs(offset) + dispersion + delay / 2))
    except (KeyError, ValueError, ArithmeticError) as exc:
        out['reason'] = str(exc)
    return out

def report(roots):
    return {'schema': SCHEMA, 'originals_modified': False,
            'records': [derive(p) for root in roots for p in sorted(Path(root).glob('timing/clocks/clock_*.json'))]}

if __name__ == '__main__':
    import sys
    print(json.dumps(report(sys.argv[1:]), indent=2, sort_keys=True))
