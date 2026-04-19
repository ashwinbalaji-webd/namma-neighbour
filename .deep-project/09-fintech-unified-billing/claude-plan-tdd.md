# TDD Plan: 09-fintech-unified-billing

**Version:** 1.0  
**Testing Framework:** pytest + pytest-django (existing codebase convention, from research Section 4)  
**Test Location:** `apps/fintech/tests/`  
**Factories:** factory-boy (existing codebase standard)  
**Mocking:** unittest.mock + @patch (existing pattern)  
**Timezone Testing:** freezegun (existing codebase)  
**AWS Mocking:** moto[s3] (existing pattern)  

---

## 1. Model Tests (Unit Level)

### 1.1 RentAgreement Model

**File:** `apps/fintech/tests/test_rent_agreement_model.py`

Tests for model validation, lifecycle, and state management:

- `test_rent_agreement_unique_on_resident` — OneToOneField prevents duplicate agreements for same resident
- `test_rent_agreement_bank_verified_defaults_false` — New agreements start with bank_verified=False
- `test_rent_agreement_payouts_frozen_lifecycle` — payouts_frozen=True when account changes, False after verification
- `test_rent_agreement_autopay_subscription_stored` — razorpay_subscription_id persists from webhook
- `test_rent_agreement_is_active_filters` — Query for active agreements returns correct subset
- `test_rent_agreement_monthly_rent_decimal_precision` — Monthly rent ₹25000.00 stored as Decimal, not float
- `test_rent_agreement_due_day_range` — Due day must be 1-28

### 1.2 MaintenanceLedger Model

**File:** `apps/fintech/tests/test_maintenance_ledger_model.py`

- `test_maintenance_ledger_unique_together` — Cannot create duplicate (community, resident, due_date)
- `test_maintenance_ledger_is_paid_defaults_false` — New ledger entries start unpaid
- `test_maintenance_ledger_paid_at_null_until_paid` — paid_at null until is_paid=True
- `test_maintenance_ledger_razorpay_payment_id_stored` — Payment link ID stored for tracking
- `test_maintenance_ledger_query_by_community_month` — Filter by community + month returns correct entries
- `test_maintenance_ledger_amount_decimal_precision` — Amount ₹500.00 stored as Decimal

### 1.3 CommunityVirtualAccount Model

**File:** `apps/fintech/tests/test_virtual_account_model.py`

- `test_virtual_account_one_to_one_community` — Each community has at most one virtual account
- `test_virtual_account_razorpay_va_id_unique` — VA ID unique across all communities
- `test_virtual_account_is_active_filter` — Query active accounts only
- `test_virtual_account_account_number_display_format` — Account number stored as CharField, displayable

### 1.4 UnifiedBill Model

**File:** `apps/fintech/tests/test_unified_bill_model.py`

- `test_unified_bill_unique_together_resident_month` — Cannot create (resident, bill_month) twice
- `test_unified_bill_status_fsm_transitions` — Status transitions use django-fsm, prevent invalid paths
- `test_unified_bill_status_defaults_to_generated` — New bills start in 'generated' state
- `test_unified_bill_rent_defaults_to_zero` — Residents without rent agreement have rent_amount=0
- `test_unified_bill_total_calculation_accuracy` — total = rent + maintenance + marketplace + fee + GST (Decimal precision)
- `test_unified_bill_indexes_on_status_queries` — Bills queried by (resident, status) are indexed for performance
- `test_unified_bill_razorpay_idempotency_key_unique` — Idempotency key prevents duplicate payment links
- `test_unified_bill_settlement_attempts_counter` — Retry counter increments on each attempt

---

## 2. API Endpoint Tests (Integration Level)

### 2.1 Resident: Rent Agreement Setup

**File:** `apps/fintech/tests/test_api_rent_agreement_setup.py`

- `test_post_rent_agreement_creates_model` — POST creates RentAgreement with provided fields
- `test_post_rent_agreement_creates_razorpay_contact` — Contact created on Razorpay (mocked)
- `test_post_rent_agreement_triggers_penny_drop` — Fund account validation request sent
- `test_post_rent_agreement_requires_resident_permission` — Non-resident cannot set up
- `test_post_rent_agreement_returns_pending_verification_status` — Initial status is pending
- `test_post_rent_agreement_validates_phone_format` — Invalid phone rejected with 400
- `test_post_rent_agreement_validates_ifsc_format` — Invalid IFSC rejected with 400

### 2.2 Resident: Activate UPI Autopay

**File:** `apps/fintech/tests/test_api_autopay_activation.py`

- `test_post_autopay_requires_bank_verified_true` — Cannot activate if bank_verified=False (returns 400)
- `test_post_autopay_creates_razorpay_subscription` — Subscription created with correct amount + monthly interval
- `test_post_autopay_returns_mandate_url` — Response includes short_url for resident to click
- `test_post_autopay_stores_subscription_id` — razorpay_subscription_id persisted
- `test_post_autopay_requires_resident_permission` — Non-resident cannot activate
- `test_post_autopay_already_active_returns_error` — Cannot activate twice (returns 400 if already active)

### 2.3 Community Admin: Setup Virtual Account

**File:** `apps/fintech/tests/test_api_virtual_account_setup.py`

- `test_post_virtual_account_calls_razorpay_create` — Virtual account created on Razorpay (mocked)
- `test_post_virtual_account_stores_account_number` — Account number from Razorpay persisted
- `test_post_virtual_account_requires_admin_permission` — Non-admin cannot create
- `test_post_virtual_account_prevents_duplicates` — Community already with VA gets 400
- `test_post_virtual_account_returns_account_details` — Response includes account_number, ifsc for display

### 2.4 Community Admin: Set Maintenance Amount

**File:** `apps/fintech/tests/test_api_maintenance_setup.py`

- `test_post_maintenance_creates_ledger_entries` — For each active resident, MaintenanceLedger created
- `test_post_maintenance_returns_resident_count` — Response indicates how many residents billed
- `test_post_maintenance_validates_amount_positive` — Amount must be > 0 (returns 400 if not)
- `test_post_maintenance_validates_month_format` — Invalid month format rejected
- `test_post_maintenance_requires_admin_permission` — Non-admin cannot set
- `test_post_maintenance_idempotent_on_duplicate_call` — Calling twice for same month doesn't create duplicates

### 2.5 Resident: View Bills List

**File:** `apps/fintech/tests/test_api_bill_list.py`

- `test_get_bills_returns_all_months` — Lists all UnifiedBill for resident, ordered by bill_month desc
- `test_get_bills_includes_payment_link` — Bills with status='sent' include razorpay_payment_link_url
- `test_get_bills_includes_breakdown` — Response breakdown includes rent, maintenance, marketplace, fee
- `test_get_bills_requires_resident_permission` — Non-resident cannot view
- `test_get_bills_filters_by_resident` — Resident only sees their own bills
- `test_get_bills_pagination` — Large bill lists paginated

### 2.6 Resident: View Single Bill

**File:** `apps/fintech/tests/test_api_bill_detail.py`

- `test_get_bill_detail_includes_all_line_items` — Returns rent, maintenance, marketplace, fee, GST, total
- `test_get_bill_detail_includes_status` — Bill status included (generated, sent, paid, etc.)
- `test_get_bill_detail_includes_payment_link` — If status='sent' or 'pending_settlement', payment_link included
- `test_get_bill_detail_includes_paid_at` — If paid, paid_at timestamp included
- `test_get_bill_detail_includes_pdf_url` — PDF statement URL included (downloads cached PDF)
- `test_get_bill_detail_requires_ownership` — Resident can only view their own bills

### 2.7 Resident: Initiate Payment

**File:** `apps/fintech/tests/test_api_bill_payment.py`

- `test_post_bill_pay_creates_payment_link` — Razorpay Payment Link created (mocked)
- `test_post_bill_pay_sets_status_sent` — Bill status updated to 'sent' after link creation
- `test_post_bill_pay_stores_link_id` — razorpay_payment_link_id persisted
- `test_post_bill_pay_stores_idempotency_key` — razorpay_idempotency_key stored for webhook matching
- `test_post_bill_pay_returns_link_url` — Response includes short_url for resident to visit
- `test_post_bill_pay_prevents_double_payment_link` — If bill already paid, returns 400
- `test_post_bill_pay_requires_resident_permission` — Non-resident cannot pay

### 2.8 Resident: Download Bill Statement (PDF)

**File:** `apps/fintech/tests/test_api_bill_statement_pdf.py`

- `test_get_statement_pdf_returns_pdf_file` — Response is valid PDF binary
- `test_get_statement_pdf_includes_breakdown` — PDF includes rent, maintenance, marketplace, fee, GST lines
- `test_get_statement_pdf_caches_to_s3` — First generation uploads to S3; subsequent downloads fetch from S3
- `test_get_statement_pdf_cache_key_pattern` — S3 key follows `bills/{year}/{month}/{resident_id}.pdf`
- `test_get_statement_pdf_regenerates_if_bill_updated` — If bill total changes, cache invalidated
- `test_get_statement_pdf_requires_ownership` — Resident can only download their own statement

### 2.9 Community Admin: Maintenance Report

**File:** `apps/fintech/tests/test_api_maintenance_report.py`

- `test_get_report_returns_summary` — Summary includes total_residents, expected_collection, collected, pending
- `test_get_report_calculates_collection_rate` — collection_rate = collected / expected * 100
- `test_get_report_lists_pending_residents` — pending_residents includes resident name, amount due, days overdue
- `test_get_report_filters_by_month` — Report for April 2026 shows April maintenance only
- `test_get_report_requires_admin_permission` — Non-admin cannot view
- `test_get_report_community_filter` — Admin only sees their community's report

---

## 3. Celery Task Tests (Integration Level)

### 3.1 Bill Generation Task

**File:** `apps/fintech/tests/test_task_bill_generation.py`

- `test_generate_monthly_bills_runs_on_25th` — Celery Beat executes at correct time
- `test_generate_monthly_bills_for_next_month` — Running on April 25 generates May bills
- `test_generate_monthly_bills_includes_all_residents` — All active residents get bills (not just those with rent)
- `test_generate_monthly_bills_resident_with_rent` — Bill includes monthly_rent from RentAgreement
- `test_generate_monthly_bills_resident_without_rent` — Bill has rent_amount=0 if no RentAgreement
- `test_generate_monthly_bills_includes_maintenance` — Sums MaintenanceLedger for the month
- `test_generate_monthly_bills_includes_marketplace` — Sums Order.subtotal for CONFIRMED/DELIVERED orders
- `test_generate_monthly_bills_calculates_fee_flat_29` — Convenience fee always ₹29.00
- `test_generate_monthly_bills_calculates_gst_18_percent` — GST = fee * 0.18
- `test_generate_monthly_bills_total_accuracy` — total = rent + maintenance + marketplace + fee + GST (Decimal)
- `test_generate_monthly_bills_bulk_creates_for_performance` — Uses bulk_create, not individual saves
- `test_generate_monthly_bills_idempotent_on_rerun` — Running twice doesn't create duplicates
- `test_generate_monthly_bills_schedules_notifications` — send_bill_notifications queued with 1h delay
- `test_generate_monthly_bills_only_active_communities` — Skips inactive communities

### 3.2 Send Bill Notifications Task

**File:** `apps/fintech/tests/test_task_send_notifications.py`

- `test_send_notifications_creates_payment_link` — Razorpay Payment Link created for each bill (mocked)
- `test_send_notifications_stores_link_id` — razorpay_payment_link_id persisted
- `test_send_notifications_sets_status_sent` — Bill status changed from 'generated' to 'sent'
- `test_send_notifications_sends_sms` — SMS dispatched to resident with payment link (mocked)
- `test_send_notifications_sms_includes_amount` — SMS includes bill total and component breakdown
- `test_send_notifications_processes_all_pending_bills` — Loops through all bills with status='generated'
- `test_send_notifications_idempotent` — Sending twice (e.g., on retry) is safe

### 3.3 Settlement Retry Task

**File:** `apps/fintech/tests/test_task_settlement_retry.py`

- `test_retry_failed_settlements_runs_hourly` — Celery Beat executes at 00:00 each hour
- `test_retry_settlements_retries_pending_settlement_bills` — Processes bills with status='pending_settlement'
- `test_retry_settlements_calls_perform_settlement` — Attempts Route split (mocked)
- `test_retry_settlements_marks_paid_on_success` — Bill status='paid' if settlement succeeds
- `test_retry_settlements_increments_attempt_counter` — settlement_attempts incremented each attempt
- `test_retry_settlements_respects_hourly_rate_limit` — No more than one retry per hour per bill
- `test_retry_settlements_initiates_refund_at_72_attempts` — After 72 failed attempts, status='refund_pending'
- `test_retry_settlements_respects_deadline` — Stops retrying if settlement_retry_until passed
- `test_retry_settlements_handles_frozen_account` — If payouts_frozen=True, skips rent payout but retries maintenance

### 3.4 Overdue Reminders Task

**File:** `apps/fintech/tests/test_task_overdue_reminders.py`

- `test_send_overdue_reminders_runs_on_5th` — Celery Beat executes 5th of each month at 10:00 IST
- `test_send_overdue_reminders_queries_previous_month` — Finds unpaid bills from last month
- `test_send_overdue_reminders_includes_sent_and_pending` — Processes bills with status='sent' or 'pending_settlement'
- `test_send_overdue_reminders_calculates_days_overdue` — Days calculated correctly (today - bill_month)
- `test_send_overdue_reminders_sends_sms` — SMS dispatched to resident with payment link and days overdue
- `test_send_overdue_reminders_marks_overdue` — Bill status set to 'overdue' after SMS sent
- `test_send_overdue_reminders_idempotent` — Running twice is safe (bills already marked 'overdue')

---

## 4. Webhook Handler Tests (Integration Level)

### 4.1 Penny Drop Webhook (fund_account.validation.completed)

**File:** `apps/fintech/tests/test_webhook_penny_drop.py`

- `test_webhook_penny_drop_success` — bank_verified set to True when beneficiary name matches
- `test_webhook_penny_drop_name_mismatch` — bank_verified stays False if name doesn't match landlord_name
- `test_webhook_penny_drop_match_fuzzy` — Name matching uses fuzzy compare (handles "Mr." prefix, case-insensitive)
- `test_webhook_penny_drop_validation_failed` — payouts_frozen=True if active=false in response
- `test_webhook_penny_drop_updates_verified_at` — bank_verified_at timestamp set on success
- `test_webhook_penny_drop_idempotent` — Processing same webhook twice is safe
- `test_webhook_penny_drop_requires_valid_signature` — Webhook signature verification required (existing pattern)
- `test_webhook_penny_drop_returns_200` — Response is HTTP 200 regardless of outcome (for Razorpay gateway)

### 4.2 Subscription Charged Webhook (subscription.charged)

**File:** `apps/fintech/tests/test_webhook_subscription_charged.py`

- `test_webhook_subscription_charged_finds_rent_agreement` — Uses subscription_id to find RentAgreement
- `test_webhook_subscription_charged_marks_rent_collected` — Updates bill.rent_amount_paid = bill.rent_amount (if applicable)
- `test_webhook_subscription_charged_stores_payment_id` — razorpay_payment_id from webhook stored on bill
- `test_webhook_subscription_charged_idempotent` — Processing twice (duplicate delivery) is safe
- `test_webhook_subscription_charged_requires_signature` — Webhook signature verification required
- `test_webhook_subscription_charged_returns_200` — Response HTTP 200

### 4.3 Subscription Halted Webhook (subscription.halted)

**File:** `apps/fintech/tests/test_webhook_subscription_halted.py`

- `test_webhook_subscription_halted_finds_rent_agreement` — Uses subscription_id to find RentAgreement
- `test_webhook_subscription_halted_disables_autopay` — Sets autopay_active=False
- `test_webhook_subscription_halted_sends_sms` — Notifies resident to retry setup or pay manually
- `test_webhook_subscription_halted_idempotent` — Processing twice is safe
- `test_webhook_subscription_halted_requires_signature` — Signature verification required
- `test_webhook_subscription_halted_returns_200` — Response HTTP 200

### 4.4 Payment Captured Webhook (payment.captured for UnifiedBill)

**File:** `apps/fintech/tests/test_webhook_payment_captured_bill.py`

- `test_webhook_payment_captured_matches_bill_by_reference_id` — Uses reference_id to find UnifiedBill
- `test_webhook_payment_captured_stores_payment_id` — razorpay_payment_id from webhook stored
- `test_webhook_payment_captured_sets_status_pending_settlement` — Bill status set to 'pending_settlement'
- `test_webhook_payment_captured_sets_retry_deadline` — settlement_retry_until = now + 72h
- `test_webhook_payment_captured_queues_settlement_task` — Celery task queued to perform splits
- `test_webhook_payment_captured_idempotent` — Processing twice is safe
- `test_webhook_payment_captured_distinguishes_from_order` — Different handling than Order payment_captured (same webhook event, different reference)
- `test_webhook_payment_captured_requires_signature` — Signature verification required
- `test_webhook_payment_captured_returns_200` — Response HTTP 200

---

## 5. Settlement & Routing Tests (Integration Level)

### 5.1 Perform Bill Settlement

**File:** `apps/fintech/tests/test_perform_bill_settlement.py`

- `test_settlement_transfers_rent_to_landlord` — Route transfer to landlord Linked Account with rent_amount
- `test_settlement_rent_requires_bank_verified` — Raises FrozenAccountError if bank_verified=False
- `test_settlement_rent_uses_correct_account_id` — landlord.razorpay_account_id used
- `test_settlement_transfers_maintenance_to_rwa` — Route transfer to RWA Linked Account with maintenance_amount
- `test_settlement_maintenance_skipped_if_zero` — No transfer if maintenance_amount=0
- `test_settlement_transfers_marketplace_to_escrow` — Marketplace portion routed to seller escrow (existing Order logic)
- `test_settlement_marketplace_on_hold_until_delivery` — Marketplace transfers use on_hold=True (existing pattern)
- `test_settlement_fee_stays_in_platform` — Convenience fee and GST not transferred (stays in nodal account)
- `test_settlement_atomic_all_or_nothing` — If any transfer fails, entire settlement fails (no partial success)
- `test_settlement_failure_preserves_bill_state` — Bill stays pending_settlement if any transfer fails
- `test_settlement_success_updates_paid_at` — paid_at timestamp set on success
- `test_settlement_handles_frozen_landlord` — Detects frozen account and raises error
- `test_settlement_handles_missing_maintenance_account` — Graceful error if RWA Linked Account not created

---

## 6. Encryption & Security Tests

### 6.1 Bank Account Encryption

**File:** `apps/fintech/tests/test_bank_account_encryption.py`

- `test_landlord_bank_account_encrypted_at_rest` — Account number encrypted using django-encrypted-model-fields
- `test_landlord_bank_account_not_queryable` — Cannot query by encrypted value (no plaintext index)
- `test_landlord_bank_account_displayed_as_encrypted_in_admin` — Admin interface shows [ENCRYPTED] instead of plaintext
- `test_bank_account_decrypts_correctly` — Stored value decrypts to original input
- `test_bank_account_secure_against_db_dump` — Database dump does not expose plaintext account

---

## 7. Edge Cases & Error Handling Tests

### 7.1 Residents Without Rent Agreements

**File:** `apps/fintech/tests/test_edge_case_no_rent.py`

- `test_bill_generated_for_resident_without_rent` — Maintenance-only bill created if RentAgreement doesn't exist
- `test_bill_rent_amount_zero_if_no_agreement` — rent_amount=0 in bill
- `test_bill_payment_link_valid_for_maintenance_only` — Payment link for maintenance + marketplace only (no rent portion)
- `test_settlement_skips_rent_payout_if_not_applicable` — No Linked Account lookup if rent_amount=0

### 7.2 Residents Without Orders

**File:** `apps/fintech/tests/test_edge_case_no_orders.py`

- `test_bill_generated_with_zero_marketplace` — Bill created even if no orders this month
- `test_marketplace_amount_zero_if_no_orders` — marketplace_amount=0 in bill
- `test_payment_link_includes_rent_and_maintenance_only` — If rent + maintenance, bill amount correct

### 7.3 Community Without Virtual Account

**File:** `apps/fintech/tests/test_edge_case_no_virtual_account.py`

- `test_settlement_fails_if_no_virtual_account` — Graceful error if RWA hasn't set up VA
- `test_bill_shows_alert_in_admin` — Operations team alerted to create VA
- `test_alert_includes_manual_account_info` — Bill shows account_number for fallback NEFT/IMPS

### 7.4 Deactivated Resident

**File:** `apps/fintech/tests/test_edge_case_deactivated_resident.py`

- `test_bill_not_generated_for_inactive_resident` — Bill generation excludes is_active=False residents
- `test_payment_link_invalid_if_deactivated` — If resident deactivated after bill creation, payment link still works but may be disabled
- `test_settlement_pauses_if_deactivated_during_settlement` — If deactivated mid-settlement, settlement completes but future debits blocked

### 7.5 Duplicate Webhook Delivery (At-Least-Once Semantics)

**File:** `apps/fintech/tests/test_idempotency_webhooks.py`

- `test_penny_drop_webhook_duplicate_ignored` — Second delivery of same event_id doesn't re-verify
- `test_subscription_charged_webhook_duplicate_ignored` — Second delivery doesn't double-mark rent paid
- `test_payment_captured_webhook_duplicate_ignored` — Second delivery doesn't re-initiate settlement
- `test_webhook_event_id_stored` — event_id (X-Razorpay-Event-ID) logged for deduplication

---

## 8. Concurrency & Race Condition Tests

### 8.1 Concurrent Status Transitions

**File:** `apps/fintech/tests/test_concurrency_bill_status.py`

- `test_concurrent_status_updates_via_fsm` — django-fsm prevents invalid concurrent transitions
- `test_concurrent_webhook_plus_task_safe` — Simultaneous payment.captured webhook + settlement task is safe
- `test_concurrent_tasks_dont_double_settle` — Two settlement tasks running simultaneously don't split twice

### 8.2 Account Freeze During Settlement

**File:** `apps/fintech/tests/test_concurrency_account_freeze.py`

- `test_account_change_freezes_during_settlement` — If account updated while settlement in progress, freeze takes effect
- `test_frozen_account_blocks_subsequent_settlement` — Pending settlement checks frozen flag before retry

---

## 9. Performance & Scale Tests

### 9.1 Bill Generation at Scale

**File:** `apps/fintech/tests/test_perf_bill_generation.py`

- `test_generate_monthly_bills_for_1000_residents` — Bulk create performance acceptable (< 5s for 1000)
- `test_generate_monthly_bills_bulk_create_not_loop` — Uses bulk_create, not loop + save
- `test_bill_generation_indexes_efficient` — Queries (status, resident) use indexes

### 9.2 PDF Generation Performance

**File:** `apps/fintech/tests/test_perf_pdf_generation.py`

- `test_statement_pdf_generates_within_5s` — WeasyPrint generation performance acceptable
- `test_statement_pdf_s3_caching_avoids_regeneration` — Subsequent downloads don't regenerate (cache hit)
- `test_statement_pdf_s3_cache_invalidation` — Regenerates if bill amount changes

---

## 10. Integration Tests (End-to-End Workflows)

### 10.1 Resident Full Lifecycle

**File:** `apps/fintech/tests/test_integration_resident_flow.py`

**Setup fixtures:** community_with_virtual_account, resident_profile, rent_agreement_verified

**Scenario:** Resident from rent setup to payment

- `test_resident_sets_up_rent` → POST to rent-agreement endpoint
- `test_resident_receives_penny_drop_setup_url` → Webhook simulates successful validation
- `test_resident_activates_autopay` → POST to activate-autopay endpoint
- `test_resident_receives_mandate_url` → Response includes mandate_url
- `test_resident_views_unified_bill` → GET bill detail includes all components
- `test_resident_pays_bill` → POST pay endpoint, gets payment link
- `test_resident_downloads_statement` → GET statement.pdf returns PDF file

### 10.2 RWA Admin Setup Lifecycle

**File:** `apps/fintech/tests/test_integration_rwa_admin_flow.py`

**Setup fixtures:** community, admin_user

**Scenario:** RWA admin from setup to reporting

- `test_rwa_admin_creates_virtual_account` → POST virtual-account endpoint
- `test_rwa_admin_sets_maintenance_amount` → POST maintenance endpoint, MaintenanceLedger created
- `test_rwa_admin_views_collection_report` → GET maintenance/report shows pending/paid breakdown
- `test_rwa_admin_views_collection_rate` → Report includes collection_rate percentage

### 10.3 Payment Failure & Recovery

**File:** `apps/fintech/tests/test_integration_payment_failure_recovery.py`

**Scenario:** Settlement fails, retries, eventually succeeds

- `test_payment_authorized_but_settlement_fails` → Bill status='pending_settlement'
- `test_settlement_retries_hourly` → Subsequent hourly task attempts retry
- `test_settlement_succeeds_on_retry` → After mock delay, settlement succeeds, status='paid'
- `test_customer_notified_on_success` → SMS sent to resident after delayed success

---

## Summary of Test Coverage

**Total Test Categories:** 10 (Models, API, Tasks, Webhooks, Settlement, Encryption, Edge Cases, Concurrency, Performance, E2E)

**Estimated Test Count:** 150+ test functions (pytest functions)

**Framework:** pytest + pytest-django, using existing codebase patterns

**Code Coverage Target:** >90% for fintech app (models, tasks, webhooks, API serializers)

**CI Integration:** Tests run on each commit (existing CI pipeline)

**Fixtures:** Community, ResidentProfile, RentAgreement, UnifiedBill factories (factory-boy)

**Mocking:** Razorpay SDK, WeasyPrint, S3, SMS gateway (unittest.mock + moto)

**Timing:** Freezegun for date/time-dependent tests, concurrent tests for FSM validation
