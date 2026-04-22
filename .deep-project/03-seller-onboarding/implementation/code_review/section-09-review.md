# Code Review: section-09-celery-tasks

## CRITICAL

### C1 — Atomic claim guard is broken for resumed/retried tasks (tasks.py, lines 87–98)

The atomic claim block fires ONLY when `razorpay_onboarding_step == ''`. If a task crashes mid-run and leaves the step at `'claiming'`, `'account_created'`, or `'stakeholder_added'`, a second concurrent invocation of the same task will skip the claim block entirely (lines 87–92 are never entered), fall through to `vendor.refresh_from_db()`, and then execute whichever steps remain. Two workers will now race through the remaining Razorpay steps simultaneously. The plan's stated goal — "atomic claim prevents concurrent duplicate execution" — is only partially satisfied. The guard should cover ALL non-terminal, non-empty steps.

### C2 — Wrong patch target for mock client in verify_fssai and create_razorpay tests

`FSSAI_CLIENT = "apps.vendors.services.fssai.SurepassFSSAIClient"` patches the class in the services module, but the task imports it with `from apps.vendors.services.fssai import SurepassFSSAIClient` inside the function body (tasks.py line 38). The live reference that gets called is `SurepassFSSAIClient` in the `apps.vendors.tasks` namespace. The correct patch target is `"apps.vendors.tasks.SurepassFSSAIClient"`. Same error for `RAZORPAY_CLIENT`. Every single mock assertion is silently a no-op — the real client is never touched, making all mock assertions pass trivially.

### C3 — No notification when Pass 2 bulk-expires vendors (tasks.py, lines 165–168)

Pass 2 runs an unconditional bulk update setting vendors to EXPIRED with no API confirmation and no notification to the vendor. A vendor who renewed but whose `fssai_expiry_date` was not yet updated will be silently expired. The plan is silent on notifications here, but this is a UX gap that will cause support tickets.

### C4 — Missing `on_failure` handler; max-retries exhaustion leaves status implicit (tasks.py, verify_fssai)

The plan explicitly states an `on_failure` callback should set `fssai_status='pending'` after max retries are exhausted. The implementation has no `on_failure` callback. The vendor stays `pending` by accident (it was never updated), which looks correct but is purely coincidental.

---

## IMPORTANT

### I1 — `recheck_fssai_expiry` swallows `TransientAPIError` silently (tasks.py, line 162)

Both `FSSAIVerificationError` and `TransientAPIError` are caught identically — logged at WARNING and silently skipped. During a Surepass outage, the entire batch of approaching-expiry vendors will skip their check with no alert. At minimum, a failure counter should abort the batch if too many transient failures accumulate.

### I2 — Inconsistent state after `RazorpayError`: status='rejected' but step='claiming' (tasks.py, lines 119–121)

On `RazorpayError`, `razorpay_account_status='rejected'` is set but `razorpay_onboarding_step` stays at `'claiming'`. The two fields are now contradictory. The terminal guard does not cover `'claiming'`, so a future retry will attempt to create the account again despite the account being marked rejected.

### I3 — Stale threshold in `auto_delist_missed_windows` per-row filter (tasks.py, lines 185–188)

The queryset snapshot captures `delist_threshold` at query time. If an admin raised the threshold concurrently, a vendor could be suspended based on stale data. The per-row atomic filter should re-evaluate: `filter(pk=vc.pk, status=APPROVED, missed_window_count__gte=F('delist_threshold'))`.

### I4 — Missing `acks_late=True` on `create_razorpay_linked_account` (tasks.py, line 62)

`verify_fssai` has `acks_late=True` but `create_razorpay_linked_account` does not. A worker crash after claiming the row but before completing API calls would leave the message acknowledged and the vendor stuck in `'claiming'` forever.

### I5 — Batch test only checks call count, not DB state (test_tasks.py, lines 278–290)

`test_processes_all_approaching_vendors` asserts `check_expiry.call_count == 55` but does not verify that all 55 vendors had their `fssai_expiry_warning_sent` flag updated in the DB.

### I6 — `test_atomic_claim_prevents_duplicate` patches Vendor.objects wholesale (test_tasks.py, lines 145–156)

All `.filter()` calls inside the task return the same mock queryset, hiding any bugs in the step-resume DB update path.

---

## MINOR

### M1 — `'claiming'` fall-through is undocumented (tasks.py, line 90)

The intentional fall-through of `'claiming'` to step-resume is surprising to readers and should have a comment.

### M2 — Vendors expiring today fall through both cron passes (tasks.py, lines 143, 165)

Pass 1 uses `fssai_expiry_date__gt=today` (strictly greater than) and Pass 2 uses `fssai_expiry_date__lt=today` (strictly less than). A vendor expiring exactly today is excluded from both passes and stays `VERIFIED` until tomorrow. Pass 2 filter should be `__lte=today`.

### M3 — `'rejected'` step never set on `RazorpayError` (tasks.py, lines 119–121)

The plan lists `'rejected'` as a valid `razorpay_onboarding_step` terminal value. The error handler sets `razorpay_account_status='rejected'` but never sets `razorpay_onboarding_step='rejected'`, so the terminal guard never fires on subsequent task invocations.

### M4 — Same wrong patch targets in skip tests (test_tasks.py, lines 37, 43)

The `test_skips_verified_vendor` and `test_skips_failed_vendor` tests use the same incorrect patch target as C2.

### M5 — `auto_delist_missed_windows` loads all qualifying rows into memory without pagination (tasks.py, lines 180–183)

Unlike `recheck_fssai_expiry` which uses `.iterator(chunk_size=50)`, `auto_delist_missed_windows` uses a plain queryset with `select_related`. For large datasets this is a latent OOM risk.
