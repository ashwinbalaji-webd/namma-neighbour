Now I have all the necessary context. Let me generate the comprehensive section-09-testing.md content based on the TDD plan and implementation plan.

# Comprehensive Testing Strategy for 09-fintech-unified-billing

## Overview

Section 09-testing provides a complete test suite covering all aspects of the unified billing system: models, API endpoints, Celery tasks, webhook handlers, settlement logic, edge cases, concurrency, performance, and end-to-end workflows.

**Dependencies:** This section depends on all implementation sections (01–08) being complete.

**Framework:** pytest + pytest-django (existing codebase convention)  
**Location:** `apps/fintech/tests/`  
**Test Support Libraries:** factory-boy, freezegun, moto[s3], unittest.mock  
**Coverage Target:** >90% for fintech app

---

## 1. Test Organization & Structure

### Directory Layout

```
apps/fintech/tests/
├── __init__.py
├── conftest.py                           # Shared fixtures (Community, Resident, etc.)
├── factories.py                          # Factory-boy definitions
├── test_rent_agreement_model.py
├── test_maintenance_ledger_model.py
├── test_virtual_account_model.py
├── test_unified_bill_model.py
├── test_api_rent_agreement_setup.py
├── test_api_autopay_activation.py
├── test_api_virtual_account_setup.py
├── test_api_maintenance_setup.py
├── test_api_bill_list.py
├── test_api_bill_detail.py
├── test_api_bill_payment.py
├── test_api_bill_statement_pdf.py
├── test_api_maintenance_report.py
├── test_task_bill_generation.py
├── test_task_send_notifications.py
├── test_task_settlement_retry.py
├── test_task_overdue_reminders.py
├── test_webhook_penny_drop.py
├── test_webhook_subscription_charged.py
├── test_webhook_subscription_halted.py
├── test_webhook_payment_captured_bill.py
├── test_perform_bill_settlement.py
├── test_bank_account_encryption.py
├── test_edge_case_no_rent.py
├── test_edge_case_no_orders.py
├── test_edge_case_no_virtual_account.py
├── test_edge_case_deactivated_resident.py
├── test_idempotency_webhooks.py
├── test_concurrency_bill_status.py
├── test_concurrency_account_freeze.py
├── test_perf_bill_generation.py
├── test_perf_pdf_generation.py
├── test_integration_resident_flow.py
├── test_integration_rwa_admin_flow.py
└── test_integration_payment_failure_recovery.py
```

### Shared Fixtures (conftest.py)

**Key fixtures to define:**
- `community_factory` — Factory for creating test communities
- `community_with_virtual_account` — Community with VA pre-configured
- `resident_profile_factory` — Factory for resident profiles
- `rent_agreement_factory` — Factory for rent agreements (with defaults: monthly_rent=25000, due_day=1)
- `rent_agreement_verified` — RentAgreement with bank_verified=True
- `unified_bill_factory` — Factory for bills (with various status choices)
- `maintenance_ledger_factory` — Factory for ledger entries
- `mock_razorpay_client` — Mocked Razorpay SDK
- `s3_mocked` — moto S3 fixture for PDF caching tests
- `freezer` — freezegun for time-dependent tests

**Fixture imports and setup patterns:**
```python
# Example pattern (not full implementation)
import pytest
from unittest.mock import Mock, patch, MagicMock
from factory import DjangoModelFactory, SubFactory
from freezegun import freeze_time

@pytest.fixture
def community_factory():
    class CommunityFactory(DjangoModelFactory):
        class Meta:
            model = "communities.Community"
        name = "Test Community"
        slug = "test-community"
    return CommunityFactory

@pytest.fixture
def resident_profile_factory(community_factory):
    class ResidentProfileFactory(DjangoModelFactory):
        class Meta:
            model = "communities.ResidentProfile"
        community = SubFactory(community_factory)
        user = SubFactory("django.contrib.auth.models.User")
    return ResidentProfileFactory
```

---

## 2. Unit Tests: Models (70+ tests)

### 2.1 RentAgreement Model Tests

**File:** `apps/fintech/tests/test_rent_agreement_model.py`

Core test cases:
- `test_rent_agreement_unique_on_resident` — OneToOneField prevents duplicate agreements for same resident; attempting to create second should raise IntegrityError
- `test_rent_agreement_bank_verified_defaults_false` — bank_verified=False for newly created agreements
- `test_rent_agreement_payouts_frozen_lifecycle` — When account details change, payouts_frozen transitions True→False after successful penny drop
- `test_rent_agreement_autopay_subscription_stored` — razorpay_subscription_id persists from webhook handler
- `test_rent_agreement_is_active_filters` — Query for is_active=True returns correct subset; is_active=False excludes
- `test_rent_agreement_monthly_rent_decimal_precision` — Monthly rent stored as Decimal (₹25000.00); verify no float conversion
- `test_rent_agreement_due_day_range_validation` — Validate due_day 1-28; out-of-range rejected (or document default)
- `test_rent_agreement_bank_account_encrypted` — landlord_bank_account field encrypted at rest
- `test_rent_agreement_verification_pending_since_timestamp` — verification_pending_since set when bank_verified=False

### 2.2 MaintenanceLedger Model Tests

**File:** `apps/fintech/tests/test_maintenance_ledger_model.py`

- `test_maintenance_ledger_unique_together` — (community, resident, due_date) constraint prevents duplicate entries
- `test_maintenance_ledger_is_paid_defaults_false` — New entries created with is_paid=False
- `test_maintenance_ledger_paid_at_null_until_paid` — paid_at remains null until is_paid=True
- `test_maintenance_ledger_razorpay_payment_id_stored` — payment_id stored from unified bill payment
- `test_maintenance_ledger_query_by_community_month` — Filter (community, due_date month) returns correct entries
- `test_maintenance_ledger_amount_decimal_precision` — Amount stored as Decimal(₹500.00)
- `test_maintenance_ledger_query_pending` — Filter is_paid=False returns unpaid entries for reporting

### 2.3 CommunityVirtualAccount Model Tests

**File:** `apps/fintech/tests/test_virtual_account_model.py`

- `test_virtual_account_one_to_one_community` — Each community has at most one VA (OneToOneField)
- `test_virtual_account_razorpay_va_id_unique` — razorpay_va_id unique across all communities
- `test_virtual_account_is_active_filter` — Query is_active=True returns only active accounts
- `test_virtual_account_account_number_display_format` — account_number stored as CharField, displayable to residents

### 2.4 UnifiedBill Model Tests

**File:** `apps/fintech/tests/test_unified_bill_model.py`

- `test_unified_bill_unique_together_resident_month` — (resident, bill_month) constraint; duplicate bills rejected
- `test_unified_bill_status_defaults_to_generated` — New bills created with status='generated'
- `test_unified_bill_rent_defaults_to_zero` — Residents without RentAgreement have rent_amount=0
- `test_unified_bill_total_calculation_accuracy` — total = rent + maintenance + marketplace + fee + GST (Decimal precision, no float arithmetic)
- `test_unified_bill_indexes_on_status_queries` — Verify db_index on fields used in (resident, status) lookups
- `test_unified_bill_razorpay_idempotency_key_unique` — razorpay_idempotency_key constraint prevents duplicate payment links
- `test_unified_bill_settlement_attempts_counter` — settlement_attempts increments on each retry; defaults to 0
- `test_unified_bill_settlement_retry_until_deadline` — settlement_retry_until prevents retries beyond 72h window
- `test_unified_bill_statement_s3_key_caching` — statement_s3_key stores S3 path; null until generated

---

## 3. Integration Tests: API Endpoints (60+ tests)

### 3.1 Rent Agreement Setup Endpoint

**File:** `apps/fintech/tests/test_api_rent_agreement_setup.py`

**Endpoint:** `POST /api/v1/fintech/rent-agreement/`

Test cases:
- `test_post_rent_agreement_creates_model` — POST request with valid data creates RentAgreement in DB
- `test_post_rent_agreement_creates_razorpay_contact` — Contact created on Razorpay API (mocked)
- `test_post_rent_agreement_triggers_penny_drop` — Fund account validation request sent to Razorpay
- `test_post_rent_agreement_requires_resident_permission` — Anonymous/non-resident users receive 403 Forbidden
- `test_post_rent_agreement_returns_pending_verification_status` — Response includes status='pending_verification' and bank_verified=False
- `test_post_rent_agreement_validates_phone_format` — Invalid phone number format rejected with 400 Bad Request
- `test_post_rent_agreement_validates_ifsc_format` — Invalid IFSC code rejected with 400
- `test_post_rent_agreement_response_includes_contact_id` — Response includes razorpay_contact_id for reference

### 3.2 UPI Autopay Activation Endpoint

**File:** `apps/fintech/tests/test_api_autopay_activation.py`

**Endpoint:** `POST /api/v1/fintech/rent-agreement/{id}/activate-autopay/`

- `test_post_autopay_requires_bank_verified_true` — Cannot activate if bank_verified=False; returns 400 with error message
- `test_post_autopay_creates_razorpay_subscription` — Subscription created on Razorpay (mocked) with monthly_interval
- `test_post_autopay_returns_mandate_url` — Response includes mandate_url for resident to click
- `test_post_autopay_stores_subscription_id` — razorpay_subscription_id persisted on RentAgreement
- `test_post_autopay_requires_resident_permission` — Non-resident cannot activate
- `test_post_autopay_already_active_returns_error` — Cannot activate twice; returns 400 if autopay_active=True

### 3.3 Virtual Account Setup Endpoint

**File:** `apps/fintech/tests/test_api_virtual_account_setup.py`

**Endpoint:** `POST /api/v1/communities/{slug}/virtual-account/`

- `test_post_virtual_account_calls_razorpay_create` — Razorpay VA creation API called (mocked)
- `test_post_virtual_account_stores_account_number` — Account number persisted in DB
- `test_post_virtual_account_requires_admin_permission` — Only community admins can create; 403 for others
- `test_post_virtual_account_prevents_duplicates` — If community already has VA, returns 400
- `test_post_virtual_account_returns_account_details` — Response includes account_number, ifsc for display

### 3.4 Maintenance Amount Setup Endpoint

**File:** `apps/fintech/tests/test_api_maintenance_setup.py`

**Endpoint:** `POST /api/v1/communities/{slug}/maintenance/`

- `test_post_maintenance_creates_ledger_entries` — For each active resident, MaintenanceLedger created with specified amount
- `test_post_maintenance_returns_resident_count` — Response indicates residents_billed count
- `test_post_maintenance_validates_amount_positive` — Negative/zero amount rejected with 400
- `test_post_maintenance_validates_month_format` — Invalid month format (not YYYY-MM) rejected
- `test_post_maintenance_requires_admin_permission` — Non-admin returns 403
- `test_post_maintenance_idempotent_on_duplicate_call` — Calling twice for same month doesn't create duplicates (unique constraint)

### 3.5 Bill List Endpoint

**File:** `apps/fintech/tests/test_api_bill_list.py`

**Endpoint:** `GET /api/v1/fintech/bills/`

- `test_get_bills_returns_all_months` — Lists all UnifiedBill for authenticated resident, ordered by bill_month descending
- `test_get_bills_includes_payment_link` — Bills with status='sent' include razorpay_payment_link_url
- `test_get_bills_includes_breakdown` — Response breakdown includes rent_amount, maintenance_amount, marketplace_amount, convenience_fee, gst_on_fee, total
- `test_get_bills_requires_resident_permission` — Non-resident returns 403
- `test_get_bills_filters_by_resident` — Resident only sees their own bills (no cross-resident leakage)
- `test_get_bills_pagination` — Large bill lists paginated (test with 50+ bills)

### 3.6 Bill Detail Endpoint

**File:** `apps/fintech/tests/test_api_bill_detail.py`

**Endpoint:** `GET /api/v1/fintech/bills/{bill_month}/`

- `test_get_bill_detail_includes_all_line_items` — Response includes rent, maintenance, marketplace, fee, GST, total
- `test_get_bill_detail_includes_status` — Bill status field included (generated, sent, paid, overdue, etc.)
- `test_get_bill_detail_includes_payment_link` — If status='sent' or 'pending_settlement', payment_link_url included
- `test_get_bill_detail_includes_paid_at` — If status='paid', paid_at timestamp included
- `test_get_bill_detail_includes_pdf_url` — PDF statement URL included (for download)
- `test_get_bill_detail_requires_ownership` — Resident can only view their own bills; 403 if accessing other's bill

### 3.7 Bill Payment Initiation Endpoint

**File:** `apps/fintech/tests/test_api_bill_payment.py`

**Endpoint:** `POST /api/v1/fintech/bills/{bill_month}/pay/`

- `test_post_bill_pay_creates_payment_link` — Razorpay Payment Link created (mocked)
- `test_post_bill_pay_sets_status_sent` — Bill status updated from 'generated' to 'sent'
- `test_post_bill_pay_stores_link_id` — razorpay_payment_link_id persisted
- `test_post_bill_pay_stores_idempotency_key` — razorpay_idempotency_key stored for webhook matching
- `test_post_bill_pay_returns_link_url` — Response includes short_url for resident to visit
- `test_post_bill_pay_prevents_double_payment_link` — If bill already paid (status='paid'), returns 400
- `test_post_bill_pay_requires_resident_permission` — Non-resident returns 403

### 3.8 Bill Statement PDF Download Endpoint

**File:** `apps/fintech/tests/test_api_bill_statement_pdf.py`

**Endpoint:** `GET /api/v1/fintech/bills/{bill_month}/statement.pdf`

- `test_get_statement_pdf_returns_pdf_file` — Response is valid PDF binary (Content-Type: application/pdf)
- `test_get_statement_pdf_includes_breakdown` — PDF includes rent, maintenance, marketplace, fee, GST, total lines
- `test_get_statement_pdf_caches_to_s3` — First generation uploads to S3; subsequent downloads fetch from cache (moto[s3])
- `test_get_statement_pdf_cache_key_pattern` — S3 key follows pattern `bills/{year}/{month}/{resident_id}.pdf`
- `test_get_statement_pdf_regenerates_if_bill_updated` — If bill total changes, cache invalidated and regenerated
- `test_get_statement_pdf_requires_ownership` — Resident can only download their own statement; 403 for others

### 3.9 Maintenance Report Endpoint

**File:** `apps/fintech/tests/test_api_maintenance_report.py`

**Endpoint:** `GET /api/v1/communities/{slug}/maintenance/report/?month=2026-04`

- `test_get_report_returns_summary` — Summary includes total_residents, expected_collection, collected, pending, collection_rate
- `test_get_report_calculates_collection_rate` — collection_rate = (collected / expected) * 100 as percentage
- `test_get_report_lists_pending_residents` — pending_residents includes resident name, amount due, days overdue
- `test_get_report_filters_by_month` — Report for April shows only April maintenance entries
- `test_get_report_requires_admin_permission` — Non-admin returns 403
- `test_get_report_community_filter` — Admin only sees their community's report (community isolation)

---

## 4. Integration Tests: Celery Tasks (40+ tests)

### 4.1 Monthly Bill Generation Task

**File:** `apps/fintech/tests/test_task_bill_generation.py`

**Task:** `generate_monthly_bills()`  
**Trigger:** 25th of each month, 09:00 IST (Celery Beat)

Core test cases (use freezegun for time control):
- `test_generate_monthly_bills_runs_on_25th` — Celery Beat schedule correct
- `test_generate_monthly_bills_for_next_month` — Running on April 25 generates May (next month) bills
- `test_generate_monthly_bills_includes_all_residents` — All active residents get bills (not just those with rent)
- `test_generate_monthly_bills_resident_with_rent` — Bill includes monthly_rent from RentAgreement
- `test_generate_monthly_bills_resident_without_rent` — Bill has rent_amount=0 if no RentAgreement
- `test_generate_monthly_bills_includes_maintenance` — Sums MaintenanceLedger.amount for bill month
- `test_generate_monthly_bills_includes_marketplace` — Sums Order.subtotal for CONFIRMED/DELIVERED orders this month
- `test_generate_monthly_bills_calculates_fee_flat_29` — Convenience fee always ₹29.00
- `test_generate_monthly_bills_calculates_gst_18_percent` — GST = fee * 0.18
- `test_generate_monthly_bills_total_accuracy` — total = rent + maintenance + marketplace + fee + GST (Decimal precision)
- `test_generate_monthly_bills_bulk_creates_for_performance` — Uses bulk_create, not individual saves
- `test_generate_monthly_bills_idempotent_on_rerun` — Running twice doesn't create duplicates (unique constraint)
- `test_generate_monthly_bills_schedules_notifications` — send_bill_notifications queued with 1h delay (countdown=3600)
- `test_generate_monthly_bills_only_active_communities` — Skips inactive communities

### 4.2 Send Bill Notifications Task

**File:** `apps/fintech/tests/test_task_send_notifications.py`

**Task:** `send_bill_notifications(bill_month)`  
**Trigger:** 1h after bill generation

- `test_send_notifications_creates_payment_link` — Razorpay Payment Link created for each bill (mocked)
- `test_send_notifications_stores_link_id` — razorpay_payment_link_id persisted
- `test_send_notifications_sets_status_sent` — Bill status 'generated' → 'sent'
- `test_send_notifications_sends_sms` — SMS dispatched to resident with payment link (mocked)
- `test_send_notifications_sms_includes_amount` — SMS includes bill total and breakdown
- `test_send_notifications_processes_all_pending_bills` — Loops through all bills with status='generated'
- `test_send_notifications_idempotent` — Sending twice is safe (bills already 'sent')

### 4.3 Settlement Retry Task

**File:** `apps/fintech/tests/test_task_settlement_retry.py`

**Task:** `retry_failed_settlements()`  
**Trigger:** Hourly at :00 minute (Celery Beat)

- `test_retry_failed_settlements_runs_hourly` — Celery Beat schedule: every hour
- `test_retry_settlements_retries_pending_settlement_bills` — Processes bills with status='pending_settlement'
- `test_retry_settlements_calls_perform_settlement` — Attempts Route split (mocked)
- `test_retry_settlements_marks_paid_on_success` — Bill status='pending_settlement' → 'paid'
- `test_retry_settlements_increments_attempt_counter` — settlement_attempts counter incremented
- `test_retry_settlements_respects_hourly_rate_limit` — No more than one retry per hour per bill
- `test_retry_settlements_initiates_refund_at_72_attempts` — After 72 failed attempts, status='refund_pending'
- `test_retry_settlements_respects_deadline` — Stops retrying if settlement_retry_until passed
- `test_retry_settlements_handles_frozen_account` — If payouts_frozen=True, skips rent payout but retries maintenance

### 4.4 Overdue Reminders Task

**File:** `apps/fintech/tests/test_task_overdue_reminders.py`

**Task:** `send_overdue_reminders()`  
**Trigger:** 5th of month, 10:00 IST (Celery Beat)

- `test_send_overdue_reminders_runs_on_5th` — Celery Beat schedule correct
- `test_send_overdue_reminders_queries_previous_month` — Finds unpaid bills from last month
- `test_send_overdue_reminders_includes_sent_and_pending` — Processes status='sent' or 'pending_settlement' bills
- `test_send_overdue_reminders_calculates_days_overdue` — Days calculated correctly (today - bill_month)
- `test_send_overdue_reminders_sends_sms` — SMS dispatched to resident with payment link and days overdue
- `test_send_overdue_reminders_marks_overdue` — Bill status → 'overdue'
- `test_send_overdue_reminders_idempotent` — Running twice is safe

---

## 5. Integration Tests: Webhook Handlers (30+ tests)

### 5.1 Penny Drop Webhook

**File:** `apps/fintech/tests/test_webhook_penny_drop.py`

**Event:** `fund_account.validation.completed`

- `test_webhook_penny_drop_success` — bank_verified=True when beneficiary name matches landlord_name
- `test_webhook_penny_drop_name_mismatch` — bank_verified=False if name doesn't match
- `test_webhook_penny_drop_match_fuzzy` — Name matching fuzzy (handles "Mr." prefix, case-insensitive)
- `test_webhook_penny_drop_validation_failed` — payouts_frozen=True if active=false in webhook
- `test_webhook_penny_drop_updates_verified_at` — bank_verified_at timestamp set on success
- `test_webhook_penny_drop_idempotent` — Processing same webhook twice is safe (event_id deduplication)
- `test_webhook_penny_drop_requires_valid_signature` — Webhook signature verification required
- `test_webhook_penny_drop_returns_200` — HTTP 200 response (for Razorpay gateway)

### 5.2 Subscription Charged Webhook

**File:** `apps/fintech/tests/test_webhook_subscription_charged.py`

**Event:** `subscription.charged` (UPI Autopay debit)

- `test_webhook_subscription_charged_finds_rent_agreement` — Uses subscription_id to find RentAgreement
- `test_webhook_subscription_charged_marks_rent_collected` — Updates bill.rent_amount_paid (if applicable)
- `test_webhook_subscription_charged_stores_payment_id` — razorpay_payment_id stored on bill
- `test_webhook_subscription_charged_idempotent` — Processing twice is safe
- `test_webhook_subscription_charged_requires_signature` — Signature verification required
- `test_webhook_subscription_charged_returns_200` — HTTP 200 response

### 5.3 Subscription Halted Webhook

**File:** `apps/fintech/tests/test_webhook_subscription_halted.py`

**Event:** `subscription.halted` (UPI Autopay failed 3×)

- `test_webhook_subscription_halted_finds_rent_agreement` — Uses subscription_id to find RentAgreement
- `test_webhook_subscription_halted_disables_autopay` — autopay_active=False
- `test_webhook_subscription_halted_sends_sms` — Notifies resident to retry or pay manually
- `test_webhook_subscription_halted_idempotent` — Processing twice is safe
- `test_webhook_subscription_halted_requires_signature` — Signature verification required
- `test_webhook_subscription_halted_returns_200` — HTTP 200 response

### 5.4 Payment Captured Webhook for UnifiedBill

**File:** `apps/fintech/tests/test_webhook_payment_captured_bill.py`

**Event:** `payment.captured` (differentiated from Order payment via reference_id)

- `test_webhook_payment_captured_matches_bill_by_reference_id` — Uses reference_id to find UnifiedBill
- `test_webhook_payment_captured_stores_payment_id` — razorpay_payment_id persisted
- `test_webhook_payment_captured_sets_status_pending_settlement` — Bill status='pending_settlement'
- `test_webhook_payment_captured_sets_retry_deadline` — settlement_retry_until = now + 72h
- `test_webhook_payment_captured_queues_settlement_task` — Celery task queued to perform splits
- `test_webhook_payment_captured_idempotent` — Processing twice is safe
- `test_webhook_payment_captured_distinguishes_from_order` — Different handling than Order payment_captured
- `test_webhook_payment_captured_requires_signature` — Signature verification required
- `test_webhook_payment_captured_returns_200` — HTTP 200 response

---

## 6. Integration Tests: Settlement & Routing (15+ tests)

**File:** `apps/fintech/tests/test_perform_bill_settlement.py`

**Function:** `perform_bill_settlement(bill)`

Core test cases:
- `test_settlement_transfers_rent_to_landlord` — Route transfer to landlord Linked Account with rent_amount
- `test_settlement_rent_requires_bank_verified` — Raises FrozenAccountError if bank_verified=False
- `test_settlement_rent_uses_correct_account_id` — landlord.razorpay_account_id used
- `test_settlement_transfers_maintenance_to_rwa` — Route transfer to RWA Linked Account with maintenance_amount
- `test_settlement_maintenance_skipped_if_zero` — No transfer if maintenance_amount=0
- `test_settlement_transfers_marketplace_to_escrow` — Marketplace portion routed to seller escrow (existing Order logic)
- `test_settlement_marketplace_on_hold_until_delivery` — on_hold=True for marketplace transfers
- `test_settlement_fee_stays_in_platform` — Fee and GST not transferred
- `test_settlement_atomic_all_or_nothing` — If any transfer fails, entire settlement fails
- `test_settlement_failure_preserves_bill_state` — Bill stays pending_settlement on failure
- `test_settlement_success_updates_paid_at` — paid_at timestamp set on success
- `test_settlement_handles_frozen_landlord` — Detects frozen account and raises error
- `test_settlement_handles_missing_maintenance_account` — Graceful error if RWA VA not created

---

## 7. Unit Tests: Encryption & Security (5+ tests)

**File:** `apps/fintech/tests/test_bank_account_encryption.py`

- `test_landlord_bank_account_encrypted_at_rest` — Account number encrypted using django-encrypted-model-fields
- `test_landlord_bank_account_not_queryable` — Cannot query by encrypted value
- `test_landlord_bank_account_displayed_as_encrypted_in_admin` — Admin interface shows [ENCRYPTED]
- `test_bank_account_decrypts_correctly` — Stored value decrypts to original input
- `test_bank_account_secure_against_db_dump` — Database dump does not expose plaintext

---

## 8. Edge Case Tests (20+ tests)

### 8.1 Residents Without Rent Agreements

**File:** `apps/fintech/tests/test_edge_case_no_rent.py`

- `test_bill_generated_for_resident_without_rent` — Maintenance-only bill created
- `test_bill_rent_amount_zero_if_no_agreement` — rent_amount=0
- `test_bill_payment_link_valid_for_maintenance_only` — Payment link for maintenance + marketplace only
- `test_settlement_skips_rent_payout_if_not_applicable` — No Linked Account lookup if rent_amount=0

### 8.2 Residents Without Orders

**File:** `apps/fintech/tests/test_edge_case_no_orders.py`

- `test_bill_generated_with_zero_marketplace` — Bill created even if no orders
- `test_marketplace_amount_zero_if_no_orders` — marketplace_amount=0
- `test_payment_link_includes_rent_and_maintenance_only` — Bill amount correct

### 8.3 Community Without Virtual Account

**File:** `apps/fintech/tests/test_edge_case_no_virtual_account.py`

- `test_settlement_fails_if_no_virtual_account` — Graceful error if RWA hasn't set up VA
- `test_bill_shows_alert_in_admin` — Operations team alerted
- `test_alert_includes_manual_account_info` — Fallback account shown

### 8.4 Deactivated Resident

**File:** `apps/fintech/tests/test_edge_case_deactivated_resident.py`

- `test_bill_not_generated_for_inactive_resident` — Bill generation excludes is_active=False
- `test_payment_link_invalid_if_deactivated` — If deactivated after creation, link still works (but may be disabled)
- `test_settlement_pauses_if_deactivated_during_settlement` — Settlement completes but future debits blocked

---

## 9. Idempotency & Deduplication Tests (8+ tests)

**File:** `apps/fintech/tests/test_idempotency_webhooks.py`

- `test_penny_drop_webhook_duplicate_ignored` — Second delivery of same event_id doesn't re-verify
- `test_subscription_charged_webhook_duplicate_ignored` — Second delivery doesn't double-mark rent paid
- `test_payment_captured_webhook_duplicate_ignored` — Second delivery doesn't re-initiate settlement
- `test_webhook_event_id_stored` — event_id (X-Razorpay-Event-ID) logged for deduplication
- `test_bill_generation_rerun_idempotent` — Running twice doesn't create duplicates
- `test_maintenance_ledger_creation_rerun_idempotent` — Setting amount twice doesn't duplicate entries

---

## 10. Concurrency & Race Condition Tests (8+ tests)

### 10.1 Bill Status Transitions

**File:** `apps/fintech/tests/test_concurrency_bill_status.py`

- `test_concurrent_status_updates_via_fsm` — django-fsm prevents invalid concurrent transitions
- `test_concurrent_webhook_plus_task_safe` — Simultaneous payment.captured webhook + settlement task is safe
- `test_concurrent_tasks_dont_double_settle` — Two settlement tasks running simultaneously don't split twice

### 10.2 Account Freeze During Settlement

**File:** `apps/fintech/tests/test_concurrency_account_freeze.py`

- `test_account_change_freezes_during_settlement` — If account updated while settlement in progress, freeze takes effect
- `test_frozen_account_blocks_subsequent_settlement` — Pending settlement checks frozen flag before retry

---

## 11. Performance & Scale Tests (5+ tests)

### 11.1 Bill Generation at Scale

**File:** `apps/fintech/tests/test_perf_bill_generation.py`

- `test_generate_monthly_bills_for_1000_residents` — Bulk create performance acceptable (< 5s for 1000)
- `test_generate_monthly_bills_bulk_create_not_loop` — Uses bulk_create, not loop + save
- `test_bill_generation_indexes_efficient` — Queries (status, resident) use indexes

### 11.2 PDF Generation Performance

**File:** `apps/fintech/tests/test_perf_pdf_generation.py`

- `test_statement_pdf_generates_within_5s` — WeasyPrint generation performance acceptable
- `test_statement_pdf_s3_caching_avoids_regeneration` — Subsequent downloads don't regenerate (cache hit)
- `test_statement_pdf_s3_cache_invalidation` — Regenerates if bill amount changes

---

## 12. End-to-End Integration Tests (15+ tests)

### 12.1 Resident Full Lifecycle Journey

**File:** `apps/fintech/tests/test_integration_resident_flow.py`

**Scenario:** Resident from rent setup to payment to statement download

Setup fixtures:
- `community_with_virtual_account` — Pre-configured community with VA
- `resident_profile` — Test resident
- `rent_agreement_verified` — RentAgreement with bank_verified=True

Test sequence:
- `test_resident_sets_up_rent` — POST rent-agreement endpoint
- `test_resident_receives_penny_drop_setup` — Webhook simulates successful validation
- `test_resident_activates_autopay` — POST activate-autopay endpoint
- `test_resident_receives_mandate_url` — Response includes mandate_url
- `test_resident_views_unified_bill` — GET bill detail with all components
- `test_resident_pays_bill` — POST pay endpoint, gets payment link
- `test_resident_downloads_statement` — GET statement.pdf returns PDF file

### 12.2 RWA Admin Setup Lifecycle

**File:** `apps/fintech/tests/test_integration_rwa_admin_flow.py`

**Scenario:** RWA admin from setup to reporting

Setup fixtures:
- `community` — Test community
- `admin_user` — Community admin

Test sequence:
- `test_rwa_admin_creates_virtual_account` — POST virtual-account endpoint
- `test_rwa_admin_sets_maintenance_amount` — POST maintenance endpoint
- `test_rwa_admin_views_collection_report` — GET maintenance/report with pending/paid breakdown
- `test_rwa_admin_views_collection_rate` — Report includes collection_rate percentage

### 12.3 Payment Failure & Recovery

**File:** `apps/fintech/tests/test_integration_payment_failure_recovery.py`

**Scenario:** Settlement fails, retries hourly, eventually succeeds

- `test_payment_authorized_but_settlement_fails` — Bill status='pending_settlement'
- `test_settlement_retries_hourly` — Subsequent hourly task attempts retry
- `test_settlement_succeeds_on_retry` — After mock delay, settlement succeeds, status='paid'
- `test_customer_notified_on_success` — SMS sent to resident after delayed success

---

## 13. Test Configuration & Fixtures (conftest.py)

### Key Fixture Patterns

```python
# Example patterns (stubs)

@pytest.fixture
def mock_razorpay_client():
    """Mock Razorpay SDK client for all tests."""
    with patch('apps.fintech.services.razorpay.client') as mock:
        yield mock

@pytest.fixture
def s3_mocked():
    """Mock S3 for PDF caching tests."""
    with patch('apps.fintech.services.boto3.client') as mock:
        yield mock

@pytest.fixture
def freezer():
    """Control time in tests using freezegun."""
    with freeze_time("2026-04-25 09:00:00") as frozen:
        yield frozen

@pytest.fixture
def community_with_virtual_account(community_factory):
    """Community with pre-configured virtual account."""
    community = community_factory()
    CommunityVirtualAccount.objects.create(
        community=community,
        razorpay_va_id="va_123456",
        account_number="1234567890",
        ifsc="RAZR0000001"
    )
    return community

@pytest.fixture
def rent_agreement_verified(resident_profile_factory):
    """RentAgreement with bank_verified=True."""
    resident = resident_profile_factory()
    return RentAgreement.objects.create(
        resident=resident,
        landlord_name="Test Landlord",
        monthly_rent=Decimal("25000.00"),
        landlord_bank_account="1234567890",
        landlord_bank_ifsc="SBIN0001234",
        bank_verified=True,
        razorpay_contact_id="cont_123456",
        razorpay_fund_account_id="fa_123456"
    )
```

### pytest.ini Configuration

```ini
[pytest]
DJANGO_SETTINGS_MODULE = config.settings.test
python_files = tests.py test_*.py *_tests.py
testpaths = apps/fintech/tests
addopts = --cov=apps.fintech --cov-report=term-missing --cov-report=html -v
```

---

## 14. Test Execution & Coverage

### Running Tests Locally

```bash
# All tests
uv run pytest apps/fintech/tests/

# Specific test file
uv run pytest apps/fintech/tests/test_api_rent_agreement_setup.py

# Single test
uv run pytest apps/fintech/tests/test_api_rent_agreement_setup.py::test_post_rent_agreement_creates_model

# With coverage
uv run pytest apps/fintech/tests/ --cov=apps.fintech --cov-report=html

# Performance tests only
uv run pytest apps/fintech/tests/test_perf_*.py

# Integration tests only
uv run pytest apps/fintech/tests/test_integration_*.py
```

### Coverage Target

- **Model tests:** 100% (all edge cases covered)
- **API views/serializers:** >95% (all endpoints, permissions, validations)
- **Tasks:** >90% (all task paths, error handling)
- **Webhooks:** >95% (all event types, idempotency)
- **Settlement logic:** 100% (atomic routing critical)
- **Overall fintech app:** >90%

### CI Integration

Tests run automatically on:
- Each commit to any branch (PR checks)
- Merge to main (before deployment)
- Nightly full suite (including performance tests)

Failed coverage drops (>5% drop in overall or >10% drop in any file) block PR merges.

---

## 15. Test Maintenance & Best Practices

### Fixture Naming Convention

- `*_factory` — Factory-boy factory fixtures
- `*_verified` — Pre-configured objects with certain states
- `mock_*` — Mocked external services
- `s3_mocked`, `freezer` — Utility fixtures

### Mocking Strategy

- **Razorpay SDK:** Mock all `razorpay.client` calls (payments, transfers, webhooks)
- **WeasyPrint:** Mock PDF generation (return dummy bytes)
- **S3/boto3:** Use moto[s3] for realistic S3 simulation
- **SMS gateway:** Mock SMS dispatch calls
- **Celery:** Use CELERY_TASK_ALWAYS_EAGER=True in test settings or mock task.delay()

### Avoiding Common Pitfalls

- **Do NOT** make real Razorpay API calls in tests
- **Do NOT** make real S3 calls (use moto instead)
- **Do NOT** assume test order (tests must be independent)
- **Do NOT** use hardcoded timestamps (use freezegun)
- **Do NOT** test Razorpay SDK logic (only integration with it)

### Docstring Pattern

```python
def test_unified_bill_total_calculation_accuracy(unified_bill_factory):
    """
    Test that UnifiedBill.total correctly sums all components.
    
    Given: Bill with rent=25000, maintenance=500, marketplace=100, fee=29, gst=5.22
    When: Bill.total is calculated
    Then: total = 25634.22 (Decimal precision, no float rounding errors)
    """
    # Setup
    bill = unified_bill_factory(
        rent_amount=Decimal("25000.00"),
        maintenance_amount=Decimal("500.00"),
        marketplace_amount=Decimal("100.00"),
        convenience_fee=Decimal("29.00"),
        gst_on_fee=Decimal("5.22")
    )
    
    # Execute
    expected_total = Decimal("25634.22")
    
    # Assert
    assert bill.total == expected_total
    assert isinstance(bill.total, Decimal)  # Verify no float conversion
```

---

## 16. Key Test Data Patterns

### Sample Bill Scenarios

**Scenario 1: Resident with Rent, Maintenance, and Orders**
- rent_amount: ₹25000.00
- maintenance_amount: ₹500.00
- marketplace_amount: ₹150.00
- convenience_fee: ₹29.00
- gst_on_fee: ₹5.22
- **total: ₹25684.22**

**Scenario 2: Resident Without Rent (Only Maintenance)**
- rent_amount: ₹0.00
- maintenance_amount: ₹500.00
- marketplace_amount: ₹0.00
- convenience_fee: ₹29.00
- gst_on_fee: ₹5.22
- **total: ₹534.22**

**Scenario 3: Resident Without Maintenance (No Virtual Account)**
- Bill creation should fail gracefully with clear error message

### Mock Razorpay Responses

```python
# Penny drop success
{
    "id": "va_123456",
    "status": "active",
    "fund_account": {
        "id": "fa_123456",
        "contact_id": "cont_123456",
        "account_type": "bank_account",
        "bank_account": {
            "ifsc": "SBIN0001234",
            "bank_name": "State Bank of India",
            "name": "Test Landlord",
            "notes": {},
            "contact_id": "cont_123456"
        },
        "batch_id": null,
        "active": true,
        "created_at": 1234567890
    }
}

# Subscription charged
{
    "id": "sub_123456",
    "entity": "subscription",
    "payment_id": "pay_123456",
    "status": "active",
    "amount": 25000,
    "currency": "INR"
}
```

---

## 17. Implementation Checklist

- [ ] Create conftest.py with all shared fixtures
- [ ] Create factories.py with factory-boy definitions
- [ ] Implement all model tests (70+ tests across 4 files)
- [ ] Implement all API endpoint tests (60+ tests across 9 files)
- [ ] Implement all Celery task tests (40+ tests across 4 files)
- [ ] Implement all webhook handler tests (30+ tests across 4 files)
- [ ] Implement settlement & routing tests (15+ tests)
- [ ] Implement encryption & security tests (5+ tests)
- [ ] Implement edge case tests (20+ tests)
- [ ] Implement idempotency tests (8+ tests)
- [ ] Implement concurrency tests (8+ tests)
- [ ] Implement performance tests (5+ tests)
- [ ] Implement E2E integration tests (15+ tests)
- [ ] Verify all tests passing locally
- [ ] Verify coverage >90% for fintech app
- [ ] Set up CI integration
- [ ] Document test maintenance guidelines

---

## 18. Dependencies on Other Sections

**This section depends on:**
- **section-01-models-migrations** — All models and migrations must exist
- **section-02-resident-endpoints** — API views, serializers, permissions
- **section-03-admin-endpoints** — Admin endpoints
- **section-04-celery-tasks** — Celery task definitions
- **section-05-webhook-handlers** — Webhook view handlers
- **section-06-payment-routing** — Settlement logic
- **section-07-services-utilities** — Helper functions
- **section-08-pdf-statements** — PDF generation and caching

**This section blocks:**
- **section-10-deployment-monitoring** — Cannot deploy without passing test suite

---

## Summary

The section-09-testing provides comprehensive test coverage for the unified billing system across:
- **Models:** Uniqueness, defaults, lifecycle, indexes (70+ tests)
- **API endpoints:** CRUD, permissions, validation, idempotency (60+ tests)
- **Celery tasks:** Generation, notifications, retries, reminders (40+ tests)
- **Webhooks:** All event types, idempotency, side effects (30+ tests)
- **Settlement:** Atomic routing, error handling (15+ tests)
- **Edge cases:** No rent, no orders, no VA, deactivated residents (20+ tests)
- **Concurrency:** Concurrent updates, race conditions (8+ tests)
- **Performance:** Scale testing, caching effectiveness (5+ tests)
- **E2E flows:** Resident journey, admin journey, failure recovery (15+ tests)

**Total:** 150+ test functions, >90% code coverage, all tests passing locally before deployment.