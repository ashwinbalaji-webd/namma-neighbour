<!-- PROJECT_CONFIG
runtime: python-uv
test_command: uv run pytest
END_PROJECT_CONFIG -->

<!-- SECTION_MANIFEST
section-01-models-migrations
section-02-resident-endpoints
section-03-admin-endpoints
section-04-celery-tasks
section-05-webhook-handlers
section-06-payment-routing
section-07-services-utilities
section-08-pdf-statements
section-09-testing
section-10-deployment-monitoring
END_MANIFEST -->

# Implementation Sections Index: 09-fintech-unified-billing

## Dependency Graph

| Section | Depends On | Blocks | Parallelizable |
|---------|------------|--------|----------------|
| section-01-models-migrations | - | all | Yes |
| section-02-resident-endpoints | 01 | 06, 08, 09 | Yes |
| section-03-admin-endpoints | 01 | 09 | Yes |
| section-04-celery-tasks | 01 | 06, 09 | Yes |
| section-05-webhook-handlers | 01 | 09 | Yes |
| section-06-payment-routing | 01, 02, 04 | 09 | No |
| section-07-services-utilities | 01 | 09 | Yes |
| section-08-pdf-statements | 01, 02 | 09 | No |
| section-09-testing | 01, 02, 03, 04, 05, 06, 07, 08 | 10 | No |
| section-10-deployment-monitoring | 09 | - | No |

## Execution Order

1. **Batch 1** — section-01-models-migrations (foundation, no dependencies)
2. **Batch 2** — section-02-resident-endpoints, section-03-admin-endpoints, section-04-celery-tasks, section-05-webhook-handlers (parallel after 01)
3. **Batch 3** — section-06-payment-routing, section-07-services-utilities (after 01, 02, 04)
4. **Batch 4** — section-08-pdf-statements (after 01, 02)
5. **Batch 5** — section-09-testing (after all implementation sections)
6. **Batch 6** — section-10-deployment-monitoring (final, after testing)

## Section Summaries

### section-01-models-migrations
Create RentAgreement, MaintenanceLedger, CommunityVirtualAccount, UnifiedBill models with indexes, constraints, and initial migrations. Django admin registration for all models.

**Files:** apps/fintech/models.py, apps/fintech/migrations/0001_initial.py, apps/fintech/admin.py

**Deliverables:**
- 4 core models with TimestampedModel base
- Unique constraints (resident, community+resident+due_date, resident+bill_month)
- Database indexes for query optimization
- Encrypted landlord_bank_account field
- Django admin with readonly fields for Razorpay IDs
- All money fields use DecimalField(10, 2)

### section-02-resident-endpoints
REST endpoints for rent setup, UPI autopay activation, bill viewing, payment initiation, and statement downloads. Serializers and permission checks included.

**Endpoints:**
- POST /api/v1/fintech/rent-agreement/ — Create rent agreement, trigger penny drop
- POST /api/v1/fintech/rent-agreement/{id}/activate-autopay/ — UPI autopay setup (requires bank_verified)
- GET /api/v1/fintech/bills/ — List all bills for resident
- GET /api/v1/fintech/bills/{bill_month}/ — Get single bill detail
- POST /api/v1/fintech/bills/{bill_month}/pay/ — Create payment link with idempotency key
- GET /api/v1/fintech/bills/{bill_month}/statement.pdf — Download PDF statement (cached)

**Files:** apps/fintech/serializers.py, apps/fintech/views.py (ResidentBillViewSet, RentAgreementViewSet), apps/fintech/urls.py

**Deliverables:**
- RentAgreementSerializer, UnifiedBillSerializer, PaymentLinkResponseSerializer
- IsResidentOfCommunity permission for all endpoints
- Razorpay Contact + Fund Account API calls (mocked in tests)
- Payment link includes idempotency_key in reference_id
- PDF download checks S3 cache first, regenerates if needed

### section-03-admin-endpoints
Community admin endpoints for virtual account creation, maintenance amount setting, and collection reporting.

**Endpoints:**
- POST /api/v1/communities/{slug}/virtual-account/ — Create VA, call Razorpay API
- POST /api/v1/communities/{slug}/maintenance/ — Set maintenance, bulk-create ledger entries
- GET /api/v1/communities/{slug}/maintenance/report/?month=2026-04 — Collection report

**Files:** Extend apps/fintech/serializers.py, apps/fintech/views.py (CommunityVirtualAccountViewSet, MaintenanceViewSet)

**Deliverables:**
- CommunityVirtualAccountSerializer, MaintenanceAmountSerializer, MaintenanceReportSerializer
- IsCommunityAdmin permission checks
- Razorpay VA creation and ID storage
- Maintenance ledger bulk creation (idempotent via unique constraint)
- Collection report: total_expected, total_collected, collection_rate, pending_residents list

### section-04-celery-tasks
Scheduled Celery tasks for monthly bill generation, notification sending, settlement retries, and overdue reminders. Includes beat schedule configuration.

**Tasks:**
- generate_monthly_bills() — 25th of month, 09:00 IST
- send_bill_notifications(bill_month) — 1h after generation
- retry_failed_settlements() — Every hour at :00 minute
- send_overdue_reminders() — 5th of month, 10:00 IST

**Files:** apps/fintech/tasks.py, config/celery.py (beat schedule)

**Deliverables:**
- Bill generation: query rent, maintenance, marketplace; bulk_create (idempotent)
- Notifications: create payment links, send SMS
- Settlement retry: hourly polling, attempt counter, 72h deadline
- Overdue reminders: SMS with payment link and days overdue
- Graceful error handling (log, don't crash)
- Rate limiting for retries (>1h between attempts)

### section-05-webhook-handlers
Razorpay webhook handlers for penny drop validation, UPI autopay lifecycle, and unified bill payment capture.

**Webhook Events:**
- fund_account.validation.completed — Penny drop result
- subscription.charged — UPI autopay debit succeeded
- subscription.halted — UPI autopay failed 3×
- payment.captured (for bills) — Unified bill payment captured

**Files:** Extend apps/payments/views.py RazorpayWebhookView

**Deliverables:**
- Penny drop: fuzzy name matching, bank_verified flag, payouts_frozen flag
- Subscription events: autopay tracking, halt notification
- Payment capture: status='pending_settlement', retry deadline, settlement task queueing
- Idempotency: event_id deduplication, safe to process twice
- Signature verification (existing pattern)
- HTTP 200 responses (for Razorpay gateway)

### section-06-payment-routing
Atomic settlement logic with Route transfers to landlord, RWA, and marketplace escrow.

**Functions:**
- perform_bill_settlement(bill) — Atomic split routing

**Files:** apps/fintech/services.py

**Logic:**
1. Validate payment_id exists
2. If rent > 0: Route to landlord (requires bank_verified)
3. If maintenance > 0: Route to RWA VA
4. If marketplace > 0: Route to seller escrow (on_hold=True)
5. All succeed or none — atomic unit
6. On success: status='paid', paid_at=now
7. On failure: raise SettlementError, bill stays PENDING_SETTLEMENT

**Key Design Points:**
- Frozen account check (payouts_frozen=True blocks rent)
- No partial success (all-or-nothing)
- Reuse Order settlement logic for marketplace
- Comprehensive error messages for debugging

### section-07-services-utilities
Helper functions for convenience fee calculation, payment link creation, Razorpay API wrappers.

**Functions:**
- calculate_convenience_fee(subtotal) → ₹29.00
- calculate_gst_on_fee(fee) → fee * 0.18
- create_razorpay_contact(name, phone) → contact_id
- create_razorpay_fund_account(contact_id, account, ifsc, vpa) → fund_account_id
- create_payment_link(bill) → { id, short_url }
- parse_razorpay_webhook_signature(headers, body) → bool

**Files:** apps/fintech/services.py

**Deliverables:**
- Thin wrappers around Razorpay SDK
- Graceful exception handling
- Logging for debugging (success, failures, latencies)
- No business logic (just helpers)

### section-08-pdf-statements
WeasyPrint template for bill statements, S3 caching logic, and PDF download endpoint optimization.

**Template:** apps/fintech/templates/fintech/bill_statement.html

**Helper:** generate_bill_pdf(bill) → bytes

**Endpoint:** GET /api/v1/fintech/bills/{bill_month}/statement.pdf

**Files:** apps/fintech/templates/fintech/bill_statement.html, extend apps/fintech/services.py, extend apps/fintech/views.py

**Logic:**
1. Check S3 cache (statement_s3_key)
2. If cached and bill.updated_at < cache time: fetch from S3, return
3. Else: generate PDF, upload to S3 (key pattern: bills/{year}/{month}/{resident_id}.pdf), update cache, return

**Deliverables:**
- Itemized HTML template (rent, maintenance, marketplace, fee, GST, total)
- WeasyPrint PDF generation (~2s first time, <100ms cache hit)
- S3 caching with invalidation logic
- Cache expiry: 1 year (old bills don't change)
- Cache miss regeneration

### section-09-testing
Comprehensive test suite covering models, API endpoints, Celery tasks, webhook handlers, settlement logic, edge cases, idempotency, and E2E flows.

**Test Categories:**
- Model tests: uniqueness, defaults, transitions, indexes
- API tests: happy path, permissions, validation, idempotency
- Task tests: data fetching, queueing, error handling
- Webhook tests: parsing, idempotency, side effects
- Settlement tests: atomic routing, errors, retries
- Edge cases: no rent, no orders, no VA, deactivated resident
- Concurrency: FSM, concurrent updates, race conditions
- E2E: resident journey (setup → autopay → bill → payment → statement), admin journey

**Files:** apps/fintech/tests/ directory with 10+ test files

**Coverage:** >90% for fintech app

**Fixtures:** Community, Resident, RentAgreement, UnifiedBill factories (factory-boy)

**Mocking:** Razorpay SDK, WeasyPrint, S3, SMS gateway (unittest.mock + moto)

**Timing:** freezegun for date-dependent tests

**Deliverables:**
- ~150+ test functions
- conftest.py with shared fixtures
- All test files passing locally
- CI integration ready (existing pytest pipeline)

### section-10-deployment-monitoring
Feature flags, monitoring/alerting setup, runbooks, and gradual rollout strategy.

**Features:**
- fintech_unified_billing_enabled (global toggle)
- fintech_unified_billing_community (per-community)

**Monitoring:**
- Bill generation: alert if >5% residents lack bills
- Webhook processing: fund_account validation success rate
- Settlement: alert if >10% bills in PENDING_SETTLEMENT >24h
- PDF generation: WeasyPrint latency, S3 cache hit rate
- SMS delivery: MSG91 webhook tracking

**Runbooks:**
- Manual settlement retry
- Freeze/unfreeze landlord payouts
- Re-trigger penny drop
- Refund request handling
- Disable billing for community (feature flag)

**Rollout Plan:**
- Week 1: Deploy to staging, E2E testing
- Week 2: Pilot (1 community, 10 residents)
- Week 3: Monitor, fix issues
- Week 4: Expand (5 communities, 50 residents)
- Week 5: Monitor, refine
- Week 6+: Full rollout, gradual ramp

**Files:** apps/fintech/features.py, apps/fintech/monitoring.py, docs/fintech/runbooks.md, docs/fintech/rollout-plan.md

**Deliverables:**
- Feature flag definitions and usage
- Monitoring dashboards (if using Datadog, Sentry, etc.)
- Operational runbooks (markdown)
- Rollout checklist and communication plan

---

## Quality Gates

Each section must pass:
1. **Code review** — Per-section peer review
2. **Unit tests** — >90% coverage for that section
3. **Linting** — black, flake8, isort
4. **Type checking** — mypy (if used)
5. **Documentation** — Docstrings, inline comments
6. **Integration** — Links correctly to prior sections

---

## Timeline Estimate

| Batch | Sections | Duration | Start | End |
|-------|----------|----------|-------|-----|
| 1 | 01 | 1-2 days | Week 1 | Week 1 |
| 2 | 02-05 | 5-7 days (parallel) | Week 1 | Week 2 |
| 3 | 06-07 | 3-4 days | Week 3 | Week 3 |
| 4 | 08 | 1-2 days | Week 3 | Week 4 |
| 5 | 09 | 3-4 days | Week 4 | Week 5 |
| 6 | 10 | 1-2 days | Week 5 | Week 5 |

**Total:** 12-16 weeks (matches implementation plan estimate)
