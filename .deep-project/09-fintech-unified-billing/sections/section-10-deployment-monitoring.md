Now I have all the context. Let me create the comprehensive section content for section-10-deployment-monitoring.

# Deployment & Monitoring: Fintech Unified Billing

## Overview

This section establishes feature flags, monitoring infrastructure, operational runbooks, and a gradual rollout strategy for the unified billing system. It ensures safe deployment, visibility into system health, and clear procedures for operational teams to manage the system in production.

## Dependencies

This section depends on:
- **section-09-testing** — All tests must pass before deployment
- **All implementation sections (01-08)** — Complete implementation required

This section is terminal (nothing depends on it) and does not block any other work.

## Feature Flags Configuration

### Purpose

Feature flags enable:
1. Global kill switch for unified billing (if critical issues detected)
2. Per-community gradual rollout (start with 1, expand to all)
3. A/B testing (future: billing vs. legacy payment flows)
4. Operational control without code deployment

### Implementation

**File:** `apps/fintech/features.py`

Define feature flags using Django's existing feature flag library (e.g., `django-feature-flag`, `waffle`, or custom Redis-backed flags):

```python
# apps/fintech/features.py

class FintechFeatureFlags:
    """
    Feature flags for unified billing system.
    """
    
    # Global toggle: enable/disable unified billing entirely
    UNIFIED_BILLING_ENABLED = "fintech_unified_billing_enabled"
    
    # Per-community toggle: enable unified billing for specific community
    UNIFIED_BILLING_COMMUNITY = "fintech_unified_billing_community_{community_id}"
    
    # Advanced: separate toggles for sub-features (future)
    PENNY_DROP_ENABLED = "fintech_penny_drop_enabled"
    AUTOPAY_ENABLED = "fintech_autopay_enabled"
    SETTLEMENT_ENABLED = "fintech_settlement_enabled"
    
    @classmethod
    def is_billing_enabled_for_community(cls, community_id: int) -> bool:
        """
        Check if unified billing is enabled for a specific community.
        Falls back to global flag if per-community flag not set.
        """
        # Implementation: check both per-community and global flag
        # Return True only if both are enabled (or if per-community flag exists)
        pass
    
    @classmethod
    def is_global_billing_enabled(cls) -> bool:
        """Check global kill switch."""
        pass
```

### Usage in Code

**In API endpoints:**
```python
def list_bills(request):
    if not FintechFeatureFlags.is_billing_enabled_for_community(request.user.resident.community_id):
        return Response({"error": "Unified billing not enabled for your community"}, status=403)
    # ... proceed with bill listing
```

**In Celery tasks:**
```python
@app.task(name='fintech.generate_monthly_bills')
def generate_monthly_bills():
    if not FintechFeatureFlags.is_global_billing_enabled():
        logger.info("Unified billing disabled globally; skipping bill generation")
        return
    # ... proceed
```

**In webhook handlers:**
```python
def handle_payment_captured(payload):
    # Always validate webhook signature, but only route if enabled
    if not FintechFeatureFlags.is_billing_enabled_for_community(bill.community_id):
        logger.info(f"Billing disabled for community {bill.community_id}; marking bill paid but skipping settlement")
        bill.status = 'paid'
        bill.save()
        return
    # ... proceed with settlement
```

### Admin Interface for Flags

**File:** `apps/fintech/admin.py` (extend)

Add a read-only section to show active flags:

```python
# In FintechAdmin or similar
def show_active_flags(self, request):
    """Display which feature flags are currently active."""
    context = {
        'global_enabled': FintechFeatureFlags.is_global_billing_enabled(),
        'communities_enabled': Community.objects.filter(
            id__in=get_enabled_community_ids()
        ),
    }
    return render(request, 'fintech/admin/flags.html', context)
```

---

## Monitoring & Alerting

### Metrics to Track

#### 1. Bill Generation Success Rate

**Metric:** `fintech.bill_generation.count` (by status)

**Alert Threshold:** If `count(status='generated') < count(total_residents) * 0.95` (i.e., >5% of residents lack bills)

**Implementation:**
```python
# In generate_monthly_bills task, post-generation
total_residents = ResidentProfile.objects.filter(is_active=True, community__in=active_communities).count()
bills_created = UnifiedBill.objects.filter(bill_month=next_month, status='generated').count()
success_rate = bills_created / total_residents if total_residents > 0 else 0

if success_rate < 0.95:
    logger.warning(
        f"Bill generation success rate low: {success_rate:.2%} "
        f"({bills_created}/{total_residents})"
    )
    # Send alert via Sentry, Datadog, or custom webhook
```

**Tools:** Datadog APM, Prometheus/Grafana, or cloud provider's built-in monitoring

#### 2. Webhook Processing Success Rate

**Metric:** `fintech.webhook.penny_drop.success_rate`

**Alert Threshold:** If success rate < 90% over rolling 24h

**Implementation:**
```python
# In webhook handler for fund_account.validation.completed
import datadog_monitoring  # or equivalent

@datadog_monitoring.track_metric('fintech.webhook.penny_drop.processed')
def handle_penny_drop_webhook(payload):
    try:
        # Process webhook
        bank_verified = validate_name_match(...)
        if bank_verified:
            datadog_monitoring.track_metric('fintech.webhook.penny_drop.success')
        else:
            datadog_monitoring.track_metric('fintech.webhook.penny_drop.failure')
    except Exception as e:
        logger.error(f"Penny drop webhook error: {e}")
        datadog_monitoring.track_metric('fintech.webhook.penny_drop.error')
```

#### 3. Settlement Retry Backlog

**Metric:** `fintech.settlement.pending_count` (count of bills in PENDING_SETTLEMENT state)

**Alert Threshold:** If `pending_count > (total_paid_bills_this_month * 0.1)` (i.e., >10% in pending state >24h)

**Implementation:**
```python
# In settlement_retry task or via background job
pending_bills = UnifiedBill.objects.filter(
    status='pending_settlement',
    last_settlement_attempt_at__lt=timezone.now() - timedelta(hours=24)
).count()

if pending_bills > expected_threshold:
    logger.warning(f"Settlement backlog growing: {pending_bills} bills pending >24h")
    send_alert(f"Settlement backlog alert: {pending_bills} bills")
```

#### 4. PDF Generation Performance

**Metrics:**
- `fintech.pdf.generation_time` — Latency of WeasyPrint generation
- `fintech.pdf.s3_cache_hit_rate` — % of downloads served from cache vs. regenerated

**Alert Threshold:** If generation_time > 5s (SLA violation)

**Implementation:**
```python
# In generate_bill_pdf function
import time

start = time.time()
try:
    html = render_to_string('fintech/bill_statement.html', {'bill': bill})
    pdf = HTML(string=html).write_pdf()
    elapsed = time.time() - start
    logger.info(f"PDF generated in {elapsed:.2f}s")
    
    if elapsed > 5.0:
        logger.warning(f"PDF generation slow: {elapsed:.2f}s for bill {bill.id}")
        send_alert(f"PDF generation SLA breach: {elapsed:.2f}s")
    
    # Track cache hit
    if statement_s3_key_exists:
        track_metric('fintech.pdf.cache_hit')
    else:
        track_metric('fintech.pdf.cache_miss')
        
except Exception as e:
    logger.error(f"PDF generation failed: {e}")
    send_alert(f"PDF generation error: {e}")
```

#### 5. SMS Delivery Tracking

**Metric:** `fintech.sms.delivery_status` (by status: sent, delivered, failed)

**Implementation:**
```python
# In send_bill_notifications and send_overdue_reminders tasks
response = sms_gateway.send(
    to=resident.phone,
    message=f"Your bill of ₹{bill.total} is due. Pay: {link.short_url}",
    reference_id=bill.id  # Tie back to bill
)

if response['status'] == 'success':
    logger.info(f"SMS sent for bill {bill.id}")
    track_metric('fintech.sms.sent')
else:
    logger.error(f"SMS failed for bill {bill.id}: {response['error']}")
    track_metric('fintech.sms.failed')
```

### Monitoring Dashboard (Recommended)

Use Datadog, Grafana, or equivalent to visualize:

```
+---------------------------------------------+
| Fintech Unified Billing Dashboard           |
+---------------------------------------------+
| Bill Generation                              |
|  - Last run: 2026-04-25 09:15 IST            |
|  - Bills created: 482/485 (99.4%)           |
|  - Success rate: 99% (24h rolling)          |
|                                              |
| Payment Processing                           |
|  - Pending settlement: 12 bills (24h+)      |
|  - Settlement success rate: 94% (24h)      |
|                                              |
| Penny Drop Verification                      |
|  - Success rate: 91% (24h)                  |
|  - Pending verification: 5 landlords        |
|                                              |
| PDF Generation                               |
|  - Cache hit rate: 87% (24h)                |
|  - Avg generation time: 2.1s                |
|  - Max generation time: 5.8s (SLA breach)   |
|                                              |
| SMS Delivery                                 |
|  - Delivered: 145/147 (24h)                 |
|  - Failed: 2                                |
+---------------------------------------------+
```

### Alert Configuration

**File:** `config/monitoring.py` or equivalent

```python
ALERT_RULES = {
    'fintech_bill_generation_low': {
        'condition': 'bills_created < total_residents * 0.95',
        'threshold': 0.95,
        'window': '5m',
        'severity': 'high',
        'notify': ['slack:#fintech-ops', 'pagerduty:fintech-on-call'],
    },
    'fintech_settlement_backlog': {
        'condition': 'pending_bills > expected * 0.1',
        'window': '24h',
        'severity': 'medium',
        'notify': ['slack:#fintech-ops'],
    },
    'fintech_pdf_generation_slow': {
        'condition': 'generation_time > 5000ms',
        'window': '5m',
        'severity': 'low',
        'notify': ['slack:#fintech-engineering'],
    },
    'fintech_penny_drop_low_success': {
        'condition': 'success_rate < 0.9',
        'window': '24h',
        'severity': 'high',
        'notify': ['slack:#fintech-ops', 'pagerduty:fintech-on-call'],
    },
}
```

---

## Operational Runbooks

Runbooks provide step-by-step procedures for common operational tasks.

**File:** `docs/fintech/runbooks.md`

### Runbook 1: Manual Settlement Retry

**Trigger:** Settlement backlog alert (>10% of bills in PENDING_SETTLEMENT >24h)

**Steps:**

1. **Assess the situation:**
   ```bash
   # Check how many bills are stuck in pending settlement
   python manage.py shell
   >>> from apps.fintech.models import UnifiedBill
   >>> import datetime
   >>> pending_bills = UnifiedBill.objects.filter(
   ...     status='pending_settlement',
   ...     last_settlement_attempt_at__lt=datetime.datetime.now() - datetime.timedelta(hours=24)
   ... )
   >>> pending_bills.count()
   # If count > 10, proceed to next step
   ```

2. **Identify the root cause:**
   ```bash
   # Check settlement attempt logs
   >>> from apps.fintech.models import UnifiedBill
   >>> bills = UnifiedBill.objects.filter(status='pending_settlement')[:5]
   >>> for bill in bills:
   ...     print(f"Bill {bill.id}: {bill.settlement_attempts} attempts, last: {bill.last_settlement_attempt_at}")
   
   # Check if Razorpay API is experiencing issues
   # Check if specific landlords have frozen accounts (bank_verified=False)
   ```

3. **If Razorpay API recovered:**
   ```bash
   # Manually trigger retry task
   python manage.py shell
   >>> from apps.fintech.tasks import retry_failed_settlements
   >>> retry_failed_settlements.apply_async()
   
   # Monitor task execution
   >>> tail -f /var/log/fintech/celery_tasks.log | grep "retry_failed_settlements"
   ```

4. **If specific bills have frozen landlord accounts:**
   ```bash
   # Contact landlord to re-verify bank account (see Runbook 2)
   # Or manually unfreeze if verified offline
   >>> from apps.fintech.models import RentAgreement
   >>> agreement = RentAgreement.objects.get(id=X)
   >>> agreement.payouts_frozen = False
   >>> agreement.bank_verified = True
   >>> agreement.save()
   
   # Then retry
   >>> retry_failed_settlements.apply_async()
   ```

5. **If backlog still exists after retry:**
   ```bash
   # Escalate: check if full refund needed (>72 attempts)
   # See Runbook 4: Refund Request Handling
   ```

### Runbook 2: Freeze/Unfreeze Landlord Payouts

**Trigger:** Security incident (account compromise) or fraud detection

**Steps:**

1. **Immediate freeze (on account compromise alert):**
   ```bash
   python manage.py shell
   >>> from apps.fintech.models import RentAgreement
   >>> agreement = RentAgreement.objects.get(id=X)  # From alert
   >>> agreement.payouts_frozen = True
   >>> agreement.verification_pending_since = timezone.now()
   >>> agreement.save()
   
   # Notify landlord
   >>> # Send SMS: "Your account is frozen due to security concerns. Contact support."
   ```

2. **Verify account manually (offline process):**
   - Contact landlord via phone
   - Confirm current bank account details
   - Verify no unauthorized changes

3. **Re-enable payouts after verification:**
   ```bash
   python manage.py shell
   >>> agreement.payouts_frozen = False
   >>> agreement.bank_verified = True
   >>> agreement.bank_verified_at = timezone.now()
   >>> agreement.save()
   
   # Retry pending settlements for this landlord
   >>> from apps.fintech.tasks import retry_failed_settlements
   >>> retry_failed_settlements.apply_async()
   ```

### Runbook 3: Re-trigger Penny Drop Verification

**Trigger:** Landlord reports account not verified despite correct details

**Steps:**

1. **Check current state:**
   ```bash
   python manage.py shell
   >>> agreement = RentAgreement.objects.get(id=X)
   >>> print(f"bank_verified: {agreement.bank_verified}")
   >>> print(f"verification_pending_since: {agreement.verification_pending_since}")
   >>> print(f"razorpay_contact_id: {agreement.razorpay_contact_id}")
   ```

2. **Trigger re-verification:**
   ```bash
   python manage.py shell
   >>> from apps.fintech.services import trigger_penny_drop
   >>> trigger_penny_drop(agreement)
   # This calls Razorpay's fund_account.validate endpoint again
   
   # Monitor webhook for validation.completed event
   >>> tail -f /var/log/fintech/webhooks.log | grep "fund_account.validation.completed"
   ```

3. **If verification continues to fail:**
   - Check if landlord_name matches bank account name exactly
   - Suggest landlord update name in system to match bank record
   - Contact Razorpay support for penny drop issues

### Runbook 4: Refund Request Handling

**Trigger:** Resident requests refund (payment never settled)

**Steps:**

1. **Identify the bill and payment:**
   ```bash
   python manage.py shell
   >>> bill = UnifiedBill.objects.get(id=X)
   >>> print(f"Status: {bill.status}")
   >>> print(f"Razorpay Payment ID: {bill.razorpay_payment_id}")
   >>> print(f"Settlement attempts: {bill.settlement_attempts}")
   ```

2. **If bill is still PENDING_SETTLEMENT:**
   ```bash
   # Option A: Try settlement one more time
   >>> from apps.fintech.services import perform_bill_settlement
   >>> perform_bill_settlement(bill)
   
   # Option B: If >72 attempts, initiate refund
   >>> if bill.settlement_attempts >= 72:
   ...     bill.status = 'refund_pending'
   ...     bill.save()
   ...     # Razorpay refund API call (see next step)
   ```

3. **Process refund via Razorpay:**
   ```bash
   python manage.py shell
   >>> from apps.payments.services import razorpay_client
   >>> refund = razorpay_client.payment.refund(bill.razorpay_payment_id, {
   ...     'amount': int(bill.total * 100),  # Amount in paise
   ...     'notes': {'bill_id': bill.id, 'reason': 'Settlement failed after retries'}
   ... })
   >>> print(f"Refund ID: {refund['id']}")
   
   # Update bill status
   >>> bill.status = 'refunded'
   >>> bill.save()
   ```

4. **Notify resident:**
   - Send SMS: "Your payment of ₹{amount} has been refunded to your card."
   - Provide refund reference ID

### Runbook 5: Disable Billing for Community (Emergency)

**Trigger:** System-wide outage or critical bug affecting community

**Steps:**

1. **Immediate disable via feature flag:**
   ```bash
   python manage.py shell
   >>> from apps.fintech.features import FintechFeatureFlags
   >>> # Disable globally
   >>> set_feature_flag(FintechFeatureFlags.UNIFIED_BILLING_ENABLED, False)
   
   # Or disable per-community
   >>> set_feature_flag(
   ...     f"{FintechFeatureFlags.UNIFIED_BILLING_COMMUNITY}_123",
   ...     False
   ... )
   ```

2. **Stop scheduled tasks:**
   ```bash
   # If using Celery Beat, disable via admin or manually
   python manage.py shell
   >>> from django_celery_beat.models import PeriodicTask
   >>> PeriodicTask.objects.filter(name='fintech.generate_monthly_bills').update(enabled=False)
   >>> PeriodicTask.objects.filter(name='fintech.retry_failed_settlements').update(enabled=False)
   ```

3. **Communicate with residents:**
   - Send SMS: "Billing temporarily disabled. Your payment is safe. We'll notify you when restored."

4. **Investigate & fix:**
   - Check logs: `tail -f /var/log/fintech/tasks.log`
   - Roll back code if needed
   - Run tests

5. **Re-enable:**
   ```bash
   >>> set_feature_flag(FintechFeatureFlags.UNIFIED_BILLING_ENABLED, True)
   >>> PeriodicTask.objects.filter(name='fintech.generate_monthly_bills').update(enabled=True)
   ```

---

## Gradual Rollout Plan

### Overview

Rolling out unified billing across all communities in phases minimizes risk and allows for issue detection at each stage.

**Timeline:** 6 weeks from deployment to full rollout

### Phase 0: Staging (Week 1)

**Scope:** Staging environment, internal team

**Activities:**
1. Deploy all code to staging
2. Run full test suite (>90% coverage)
3. Manual E2E testing: resident full flow (setup → bill → payment → statement)
4. Manual RWA admin testing: VA setup → maintenance → report
5. Chaos testing: simulate failures (Razorpay API down, webhook delays, settlement failures)

**Success Criteria:**
- All tests passing
- No critical bugs found
- Team confidence high

**Exit Gate:** Code review + sign-off from 2 senior engineers

### Phase 1: Pilot (Week 2)

**Scope:** Production, 1 community, ~10 residents

**Rollout Procedure:**
1. Choose pilot community: low-risk, tech-savvy RWA admin
2. Enable feature flag for community:
   ```python
   set_feature_flag(f"fintech_unified_billing_community_123", True)
   ```
3. Inform community: "You're now testing unified billing. Contact support for any issues."
4. Enable bill generation for this community only (manual trigger via task command)

**Monitoring:**
- Daily check: bills generated, payments captured, settlements successful
- SMS delivery rate
- PDF generation latency
- Resident feedback via support tickets

**Duration:** 1 week

**Success Criteria:**
- 100% bill generation rate
- >95% settlement success rate
- 0 critical bugs
- Positive resident feedback

**Exit Gate:** Ops team sign-off

### Phase 2: Early Expansion (Week 3)

**Scope:** Production, 5 communities, ~50 residents

**Rollout Procedure:**
1. Enable feature flag for 4 additional communities
2. Repeat bill generation & monitoring
3. Monitor for cumulative issues (e.g., Razorpay rate limits)

**Monitoring:** Same metrics as Phase 1, aggregate view

**Duration:** 1 week

**Success Criteria:**
- >99% bill generation rate
- >98% settlement success rate
- 0 critical bugs in new communities
- Sub-2s PDF generation (p99)

**Exit Gate:** Ops + business sign-off

### Phase 3: Scaled Expansion (Week 4-5)

**Scope:** Production, 20-30 communities, ~200-300 residents

**Rollout Procedure:**
1. Enable for multiple communities in batches (5 communities per day)
2. Stagger bill generation to avoid Razorpay rate limits
3. Monitor carefully for emerging patterns

**Monitoring:**
- Same metrics
- Razorpay API usage (calls/min, rate limit headroom)
- Database query performance (bill queries, settlement updates)
- Redis usage (Celery queue depth)

**Contingency:**
- If settlement success drops below 98%, pause expansion
- If PDF generation p99 > 3s, investigate WeasyPrint + S3 bottlenecks
- If any critical bug discovered, disable flag and roll back

**Exit Gate:** Ops + engineering sign-off

### Phase 4: Full Rollout (Week 6+)

**Scope:** Production, all communities

**Rollout Procedure:**
1. Enable global feature flag: `fintech_unified_billing_enabled = True`
2. Ensure all communities with residents have bills generated for next month
3. Announce to all users

**Monitoring:** Ongoing, same metrics as before

**Communication:**
- Email: "Unified billing is now live. Your rent, maintenance, and marketplace purchases are on one bill."
- In-app notification: Bill view now shows unified breakdown

---

## Deployment Checklist

Before deploying to production, verify:

**Code & Testing:**
- [ ] All tests passing (>90% coverage)
- [ ] Code review completed (2+ approvals)
- [ ] Linting clean (black, flake8, isort)
- [ ] No security vulnerabilities (bandit, pip-audit)
- [ ] Migrations reviewed (no data-destructive changes)

**Infrastructure:**
- [ ] Celery workers ready (beat scheduler enabled)
- [ ] Redis accessible (for Celery + caching)
- [ ] S3 bucket created and accessible (for PDF caching)
- [ ] Razorpay API keys configured (sandbox first, then prod)
- [ ] SMS gateway (MSG91) API keys configured
- [ ] Database backups scheduled

**Monitoring:**
- [ ] Feature flags defined and testable
- [ ] Alert rules configured
- [ ] Dashboards created (Datadog, Grafana, etc.)
- [ ] Logging configured (fintech app logs to separate stream)
- [ ] Error tracking enabled (Sentry, DataDog)

**Documentation:**
- [ ] Runbooks written and reviewed
- [ ] API documentation updated
- [ ] FAQ prepared for residents
- [ ] RWA admin guide written

**Communication:**
- [ ] Pilot community identified and briefed
- [ ] Support team trained on unified billing FAQ
- [ ] Ops team trained on runbooks
- [ ] Leadership briefed on rollout plan

---

## Key Files to Create/Modify

| File | Purpose |
|------|---------|
| `/apps/fintech/features.py` | Feature flag definitions and helpers |
| `/apps/fintech/monitoring.py` | Metrics tracking and alert helpers |
| `/docs/fintech/runbooks.md` | Operational runbooks (5 main ones) |
| `/docs/fintech/rollout-plan.md` | Detailed rollout phases with dates/metrics |
| `/docs/fintech/faq.md` | Resident FAQ (optional, for reference) |
| `/config/celery.py` | Ensure beat schedule is configured (already done in section-04) |
| `/apps/fintech/management/commands/fintech_stats.py` | Optional: command to check billing health |

---

## Testing the Deployment Setup

### Unit Test for Feature Flags

**File:** `apps/fintech/tests/test_feature_flags.py`

```python
def test_feature_flag_global_disable():
    """When global flag disabled, all communities should see billing disabled."""
    set_feature_flag(FintechFeatureFlags.UNIFIED_BILLING_ENABLED, False)
    assert FintechFeatureFlags.is_global_billing_enabled() == False

def test_feature_flag_per_community():
    """Per-community flag should override global when set."""
    set_feature_flag(FintechFeatureFlags.UNIFIED_BILLING_ENABLED, True)
    set_feature_flag(f"{FintechFeatureFlags.UNIFIED_BILLING_COMMUNITY}_123", False)
    assert FintechFeatureFlags.is_billing_enabled_for_community(123) == False
```

### Integration Test for Metrics

**File:** `apps/fintech/tests/test_monitoring.py`

```python
def test_bill_generation_metric_tracked():
    """Bill generation task should emit metrics."""
    with track_metrics() as metrics:
        generate_monthly_bills()
    assert 'fintech.bill_generation.count' in metrics
```

---

## Success Criteria for Deployment

1. Feature flags deployed and testable (toggle on/off without code change)
2. All monitoring metrics emitting data to dashboard
3. All alerts configured and working (test with dummy events)
4. Runbooks reviewed and approved by ops team
5. Rollout plan communicated to stakeholders
6. Pilot community informed and ready for Phase 1

---

## Post-Deployment Operations

### Daily Checklist (First Week)

- [ ] Bills generated on schedule (25th of month)
- [ ] Settlement success rate >98%
- [ ] No critical alerts triggered
- [ ] PDF cache hit rate >80%
- [ ] Penny drop success rate >90%

### Weekly Checklist (Weeks 2-6)

- [ ] Aggregate metrics healthy (bill generation, settlement, SMS delivery)
- [ ] No unusual Razorpay error patterns
- [ ] Database performance stable (queries, slow logs)
- [ ] Celery task queue depth normal (<100 pending)
- [ ] Resident support tickets reviewed

### Ongoing Operations

- Monitor key metrics dashboard daily
- Review alerts and take action per runbooks
- Track refund requests and settlement failures
- Plan capacity for future growth (more communities, more residents)