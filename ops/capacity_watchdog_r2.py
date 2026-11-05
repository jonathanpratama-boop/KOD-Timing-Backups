#!/usr/bin/env python3
"""Read-only external quality check for the finite November 2026 capacity trial."""
import argparse
import datetime as dt
import json
from pathlib import Path

UTC = dt.timezone.utc
TRIAL_ID = "capacity-r2-20261105T082700Z"
CONFIG_SHA256 = "d227f37507a93e47377e1b94fbe6e8520aab1d8d2361c7ee756b7cafc36f5739"
ORIGINAL_COMMIT = "dbb27ea5c6a16c5b37c6f94b938a1509c2a9148e"
START = dt.datetime(2026, 11, 5, 8, 27, tzinfo=UTC)
END = dt.datetime(2026, 11, 7, 8, 27, tzinfo=UTC)
MONITOR_END = END + dt.timedelta(minutes=31)
PRIMARY_SYMBOLS = frozenset(["AAVEUSDT","ACEUSDT","ADAUSDT","AEROUSDT","ALGOUSDT","ALTUSDT","AMPUSDT","APEUSDT","APTUSDT","ARBUSDT","ARUSDT","ASTERUSDT","ATOMUSDT","AVAUSDT","AVAXUSDT","AXSUSDT","BATUSDT","BCHUSDT","BEAMXUSDT","BLURUSDT","BMTUSDT","BNBUSDT","BOMEUSDT","BONKUSDT","BTCUSDT","CAKEUSDT","CFGUSDT","CFXUSDT","CHIPUSDT","COTIUSDT","CRVUSDT","CVXUSDT","DASHUSDT","DEXEUSDT","DODOUSDT","DOGEUSDT","DOTUSDT","ENAUSDT","ERAUSDT","ETCUSDT","ETHFIUSDT","ETHUSDT","FETUSDT","FFUSDT","FILUSDT","FLOKIUSDT","GALAUSDT","GIGGLEUSDT","GRAMUSDT","GTCUSDT","HBARUSDT","HUMAUSDT","ICPUSDT","INITUSDT","INJUSDT","IOUSDT","JSTUSDT","JTOUSDT","JUPUSDT","KAIAUSDT","KITEUSDT","LDOUSDT","LINKUSDT","LSKUSDT","LTCUSDT","LUMIAUSDT","LUNCUSDT","MAGICUSDT","MEGAUSDT","METUSDT","MINAUSDT","MOVRUSDT","MUBARAKUSDT","NEARUSDT","NIGHTUSDT","NILUSDT","OGNUSDT","ONDOUSDT","ONEUSDT","OPUSDT","ORCAUSDT","PARTIUSDT","PENDLEUSDT","PENGUUSDT","PEPEUSDT","PHAUSDT","PLUMEUSDT","POLUSDT","PROMUSDT","PUMPUSDT","PYTHUSDT","QNTUSDT","RADUSDT","RAYUSDT","RENDERUSDT","RLCUSDT","RUNEUSDT","SAGAUSDT","SANDUSDT","SEIUSDT","SENTUSDT","SHIBUSDT","SKYUSDT","SOLUSDT","STRKUSDT","STXUSDT","SUIUSDT","SUSDT","SYNUSDT","SYRUPUSDT","TAOUSDT","TIAUSDT","TRUMPUSDT","TRXUSDT","UNIUSDT","VETUSDT","VIRTUALUSDT","WIFUSDT","WLDUSDT","WLFIUSDT","WUSDT","XLMUSDT","XPLUSDT","XRPUSDT","ZAMAUSDT","ZECUSDT","ZENUSDT","ZKUSDT","ZROUSDT","币安人生USDT"])
DETAILED_SYMBOLS = frozenset(("BTCUSDT", "ETHUSDT", "GMXUSDT", "SOLUSDT", "ZECUSDT"))
MAX_AGE_SECONDS = 1800


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError("timestamp missing or not a string")
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp lacks timezone")
    return parsed.astimezone(UTC)


def integer(value):
    return type(value) is int and value >= 0


def inspect(health, now):
    """Return a deterministic assessment; never equate a live process with good data."""
    now = now.astimezone(UTC)
    issues = []
    summary = {}
    if not isinstance(health, dict):
        return {"status": "UNKNOWN", "issues": ["Health payload is not an object"], "summary": {}}

    def require(condition, message):
        if not condition:
            issues.append(message)

    def mapping(parent, key):
        value = parent.get(key)
        if not isinstance(value, dict):
            issues.append(f"Missing or invalid object: {key}")
            return {}
        return value

    def empty_list(parent, key, label):
        value = parent.get(key)
        require(isinstance(value, list) and not value, f"{label}: {key} missing, invalid, or nonempty")

    def clock(parent, key, label):
        try:
            value = timestamp(parent.get(key))
        except (ValueError, TypeError, OverflowError):
            issues.append(f"{label}: invalid {key}")
            return None
        age = (now - value).total_seconds()
        require(age >= -60, f"{label}: {key} is in the future")
        # A stopped trial requires explicit final review, not indefinitely fresh heartbeats.
        if now < END:
            require(age <= MAX_AGE_SECONDS, f"{label}: {key} is stale (over 30 minutes)")
        return value

    collector = mapping(health, "collector")
    coverage = mapping(collector, "coverage")
    require(health.get("schema") == "KOD_CAPACITY_HEALTH_V1", "Unexpected health schema")
    require(health.get("trial_id") == TRIAL_ID and collector.get("trial_id") == TRIAL_ID,
            "Trial identity mismatch")
    require(health.get("config_sha256") == CONFIG_SHA256 and collector.get("config_hash") == CONFIG_SHA256,
            "Frozen configuration hash mismatch")
    report_at = clock(health, "emitted_at", "report")
    collected_at = clock(collector, "as_of", "collector")
    if report_at and collected_at:
        require(-5 <= (report_at - collected_at).total_seconds() <= 120,
                "Report and collector timestamps disagree")
    empty_list(health, "issues", "health")
    require(health.get("pause_latched") is False, "Pause state unknown or latched")
    require(collector.get("capacity_trial_only") is True,
            "Capacity-only scope is unknown or changed")
    require(collector.get("scientific_enrollment") is False,
            "Scientific enrollment is unknown or enabled")
    require(health.get("automatically_promotes_30_day_study") is False,
            "Automatic promotion is unknown or enabled")

    if now < END:
        require(now >= START, "Trial has not reached its declared start")
        require(health.get("phase") == "RUNNING" and collector.get("phase") == "RUNNING",
                "Collector is not reporting RUNNING")
        service = mapping(health, "service_actual_status")
        require(service.get("ActiveState") == "active" and service.get("SubState") == "running",
                "System service is not active/running")
        try:
            pid = int(service.get("MainPID", 0))
        except (ValueError, TypeError):
            pid = 0
        require(pid > 0 and collector.get("pid") == pid, "Collector process identity unavailable or inconsistent")
        require(collector.get("worker_closing") is False, "Collector is closing or worker state is unknown")
        stream = mapping(collector, "stream")
        require(stream.get("connected") is True and stream.get("reader_alive") is True,
                "Market stream is disconnected or reader state is unknown")
        for key in ("queue_overflows",):
            require(collector.get(key) == 0, f"Collector {key} is nonzero or unknown")
        for key in ("events_dropped", "closed_dropped", "invalid_messages", "clock_anomalies"):
            require(stream.get(key) == 0, f"Stream {key} is nonzero or unknown")
        if collected_at:
            try:
                last_commit = timestamp(collector.get("last_minute_commit_at"))
                require(0 <= (collected_at - last_commit).total_seconds() <= 180,
                        "Minute commits are not progressing near collector heartbeat")
            except (ValueError, TypeError, OverflowError):
                issues.append("Minute commit timestamp is unknown")

    preservation = mapping(health, "preservation")
    require(preservation.get("status") == "OK" and preservation.get("unchanged") is True,
            "Original experiment preservation not verified")
    require(preservation.get("source_commit") == ORIGINAL_COMMIT,
            "Original source commit mismatch")
    require(preservation.get("source_files_checked") == 527 and
            preservation.get("static_invariants_checked") == 34,
            "Original preservation check coverage incomplete")
    empty_list(preservation, "problems", "preservation")
    resource_check = mapping(health, "resource_check")
    require(resource_check.get("status") == "OK", "Resource check not OK")
    empty_list(resource_check, "issues", "resources")
    empty_list(resource_check, "unknown", "resources")

    # Settled rows exclude the current minute and its one-minute receipt grace.
    # The denominator is independently derived from the collector's timestamp.
    expected_minutes = None
    if collected_at:
        expected_minutes = max(0, min(2880, int((collected_at - START).total_seconds() // 60) - 1))
        require(coverage.get("settled_minutes") == expected_minutes, "Settled-minute denominator mismatch")
        require(expected_minutes > 0, "No settled observations yet")
    require(coverage.get("fixed_primary_asset_count") == len(PRIMARY_SYMBOLS), "Fixed universe count mismatch")
    require(coverage.get("full_48h_expected_closed_total") == 2880 * len(PRIMARY_SYMBOLS),
            "Full-trial denominator mismatch")

    def lane(name, symbols, expected_per_asset, received_key, expected_key="expected"):
        rows = mapping(coverage, name)
        require(set(rows) == symbols, f"{name}: frozen membership mismatch")
        valid_total = 0
        deficient = []
        malformed = []
        for symbol in sorted(symbols):
            row = rows.get(symbol, {})
            if not isinstance(row, dict):
                malformed.append(symbol)
                continue
            expected = row.get(expected_key)
            valid = row.get(received_key)
            if (not integer(expected) or not integer(valid) or expected_per_asset is None or
                    expected != expected_per_asset or valid > expected):
                malformed.append(symbol)
                continue
            valid_total += valid
            if expected == 0 or valid * 100 < expected * 99:
                deficient.append(symbol)
            if name == "closed_bars":
                eventual = row.get("eventual")
                if not integer(eventual) or not valid <= eventual <= expected:
                    malformed.append(symbol)
        if malformed:
            issues.append(f"{name}: invalid numerator/denominator for {len(set(malformed))} assets")
        if deficient:
            issues.append(f"{name}: below 99% coverage for {len(deficient)} assets")
        denominator = len(symbols) * expected_per_asset if expected_per_asset is not None else None
        summary[name] = {"valid": valid_total, "expected": denominator,
                         "coverage": valid_total / denominator if denominator else None,
                         "deficient_assets": deficient, "invalid_assets": sorted(set(malformed))}
        return valid_total, denominator

    closed, expected_closed = lane("closed_bars", PRIMARY_SYMBOLS, expected_minutes, "on_time")
    lane("broad_bbo", PRIMARY_SYMBOLS, expected_minutes, "valid_received")
    lane("detailed_five", DETAILED_SYMBOLS,
         expected_minutes * 12 if expected_minutes is not None else None, "valid_received")
    require(coverage.get("expected_closed_total") == expected_closed, "Pooled closed denominator mismatch")
    require(coverage.get("on_time_closed_total") == closed, "Pooled closed numerator mismatch")
    # The producer's status, coverage fractions and aggregate booleans are not acceptance inputs.
    if now >= END:
        issues.append("Trial window ended; final receipt and acceptance review required")
        status = "TRIAL_WINDOW_ENDED_REVIEW_REQUIRED"
    else:
        status = "DEGRADED" if issues else "COLLECTION_HEALTHY_SO_FAR"
    return {"status": status, "issues": issues, "summary": summary,
            "checked_at": now.isoformat(), "report_at": health.get("emitted_at"),
            "trial_id": TRIAL_ID, "capacity_acceptance": "NOT_ESTABLISHED",
            "scientific_enrollment": collector.get("scientific_enrollment", "UNKNOWN")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("health", type=Path)
    args = parser.parse_args()
    try:
        result = inspect(json.loads(args.health.read_text(encoding="utf-8")), dt.datetime.now(UTC))
    except (OSError, ValueError, TypeError) as exc:
        result = {"status": "UNKNOWN", "issues": [f"Unable to inspect health: {exc}"]}
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 1 if result["issues"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

