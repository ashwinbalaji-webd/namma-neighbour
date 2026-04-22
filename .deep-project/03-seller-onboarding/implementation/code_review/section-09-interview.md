# Code Review Interview: section-09-celery-tasks

## User Decisions

### C1 — Atomic claim guard for mid-flight steps
**Decision:** Add mid-flight steps to the terminal guard.  
Including `'claiming'` (and `'account_created'`, `'stakeholder_added'`) in the terminal guard means a second concurrent worker sees a non-empty step and exits immediately. The first worker already owns execution.

### C4 / I2 / M3 — Rejected state consistency
**Decision:** Fix all three together.  
On `RazorpayError`: set both `razorpay_account_status='rejected'` AND `razorpay_onboarding_step='rejected'`. Add `'rejected'` to the terminal guard. Add `on_failure` to `verify_fssai` that logs and leaves `fssai_status='pending'` (explicit intent, not accidental).

---

## Auto-fixes (applied without user input)

- **C2/M4:** Fix FSSAI_CLIENT and RAZORPAY_CLIENT patch targets from `services.*` to `apps.vendors.tasks.*`
- **M2:** Change `fssai_expiry_date__lt=today` to `fssai_expiry_date__lte=today` in Pass 2 so vendors expiring today are caught
- **M5:** Add `.iterator(chunk_size=50)` to `auto_delist_missed_windows` queryset
- **I4:** Add `acks_late=True` to `create_razorpay_linked_account` (consistent with `verify_fssai`)
- **I3:** Add `missed_window_count__gte=F('delist_threshold')` to per-row atomic filter to re-evaluate threshold at update time

## Let go

- **M1:** Undocumented 'claiming' fall-through — no comments per project style
- **I1:** TransientAPIError swallowed in cron — acceptable for MVP, monitoring can surface the warnings
- **I5:** Weak batch test — minor, not worth added complexity
- **I6:** Fragile mock setup in atomic claim test — proves the early-return branch, acceptable for now
- **C3:** No Pass 2 notification — UX gap acknowledged, out of scope for this section
