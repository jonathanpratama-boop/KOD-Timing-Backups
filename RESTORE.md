# Supplemental observation recovery

This branch is separate from the original thirty-slot cohort on main. Never
restore supplement files over original controls, plans, source, or evidence.

1. Obtain original frozen source commit dbb27ea5c6a16c5b37c6f94b938a1509c2a9148e
   or the original main-branch recovery snapshot. Verify its source manifest.
   The original guard excludes hidden source files. In staging only, complete
   that recovered source using source-recovery-addendum.json's four base64
   source files (.env.example, .gitattributes, .gitignore, .lfsconfig), each pinned
   to its frozen manifest SHA-256. This contains repository templates/metadata,
   no live credentials. Run the full source checker before using recovered code.
2. Run verify_archive() from backup_supplement.py against each archive listed
   in INDEX.json. All members are regular files with a SHA-256 in MANIFEST.json.
3. Extract verified archives into an empty staging directory, never / directly.
   Restore only /opt/kod/supplement-v1, its four listed unit files, and
   /var/lib/kod/supplement-v1. Configure ownership as in INSTALLATION.json and
   OPERATIONS.md. Preserve the original cohort separately and unchanged.
4. Preserve PIN.json, all begin/end receipts, and HALTED.json. A begun slot must
   never be recollected. Missing historical slots are MISSED; no backfill.
5. Run combined_view.py with the frozen plan hash. Verify retained raw evidence,
   clock corrections, and explicit failed/blocked/interrupted states before any
   operator-reviewed resume. A HALTED supplement stays halted pending review.
6. Reuse existing authorized access only. Never restore keys or credential files
   from these archives; none are included. Source/strategy remains unchanged.

Recovery point: completed slots are delta-archived and pushed hourly, with
earlier pushes for health changes. An outage before acknowledgement can lose
up to one hour of supplemental observations. The original cohort recovery is
independent. No absolute-time or profitability proof is established.
