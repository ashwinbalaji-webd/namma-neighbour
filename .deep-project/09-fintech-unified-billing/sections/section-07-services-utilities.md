Now I have all the necessary context. Let me extract the relevant content for section-07-services-utilities from the plan and TDD document.

Based on the files I've read, I can now generate the section content for section-07-services-utilities. This section covers helper functions for convenience fee calculation, payment link creation, and Razorpay API wrappers.

# Section 07: Services & Utilities

## Overview

This section implements helper functions and Razorpay API wrappers that support the unified billing system. These utilities are used throughout the other sections (payment routing, notification sending, API endpoints) but contain no business logic themselves—they are thin, well-tested wrappers.

**Dependencies:** section-01-models-migrations (UnifiedBill, RentAgreement models)

**Files to Create/Modify:**
- `apps/fintech/services.py` — All utility functions and Razorpay wrappers

## Core Utilities to Implement

### 1. Convenience Fee Calculation

**Function Signature:**
```python
def calculate_convenience_fee(subtotal: Decimal) -> Decimal:
    """
    Calculate flat convenience fee for bill payment.
    
    Returns fixed ₹29.00 regardless of subtotal.
    
    Args:
        subtotal: Decimal amount (unused, but kept for clarity in function intent)
    
    Returns:
        Decimal: ₹29.00
    """
```

**Key Points:**
- Always returns `Decimal('29.00')`
- Used during bill generation (UnifiedBill.convenience_fee)
- No validation needed; amount is always fixed

### 2. GST on Convenience Fee

**Function Signature:**
```python
def calculate_gst_on_fee(fee: Decimal) -> Decimal:
    """
    Calculate 18% GST on convenience fee.
    
    Args:
        fee: Convenience fee amount (typically ₹29.00)
    
    Returns:
        Decimal: fee * 0.18, rounded to 2 decimal places
    """
```

**Key Points:**
- Multiplies fee by 0.18 for 18% GST
- Must return Decimal (never float) to preserve precision
- Example: ₹29.00 * 0.18 = ₹5.22

### 3. Razorpay Contact Creation

**Function Signature:**
```python
def create_razorpay_contact(name: str, phone: str) -> str:
    """
    Create a Razorpay Contact for landlord/RWA.
    
    Contacts are used to create Fund Accounts for penny drop verification.
    
    Args:
        name: Contact name (e.g., "Rajesh Kumar")
        phone: 10-digit phone number (e.g., "9876543210")
    
    Returns:
        str: Razorpay contact_id (e.g., "cont_ABCDabcd1234")
    
    Raises:
        RazorpayException: If API call fails
    """
```

**Key Points:**
- Calls `razorpay.client.contact.create(...)` with payload `{name, phone}`
- Returns `contact_id` from response
- Called during RentAgreement setup endpoint
- Logs success/failure for debugging

### 4. Razorpay Fund Account Creation

**Function Signature:**
```python
def create_razorpay_fund_account(
    contact_id: str,
    account_number: str,
    ifsc: str,
    vpa: str = None,
) -> str:
    """
    Create a Fund Account for penny drop validation.
    
    Fund accounts can be bank accounts or UPI VPAs. Used before transfers.
    
    Args:
        contact_id: Razorpay contact_id (from create_razorpay_contact)
        account_number: Bank account number (e.g., "1112220061746457")
        ifsc: Bank IFSC code (e.g., "HDFC0000001")
        vpa: UPI VPA if available (e.g., "name@okhdfcbank"); optional
    
    Returns:
        str: Razorpay fund_account_id (e.g., "fa_ABCDabcd1234")
    
    Raises:
        RazorpayException: If API call fails
    """
```

**Key Points:**
- Calls `razorpay.client.fund_account.create(...)` with payload
- Initiates penny drop validation in background (Razorpay)
- Returns `fund_account_id` immediately (validation asynchronous via webhook)
- Logs operation and latency

### 5. Payment Link Creation

**Function Signature:**
```python
def create_payment_link(bill: UnifiedBill) -> dict:
    """
    Create a Razorpay Payment Link for a unified bill.
    
    Payment link is shareable URL sent to resident via SMS.
    
    Args:
        bill: UnifiedBill instance with total amount set
    
    Returns:
        dict: {
            'id': razorpay_payment_link_id (str),
            'short_url': shareable URL (str),
            'expires_at': expiry timestamp (datetime or str)
        }
    
    Raises:
        RazorpayException: If API call fails
    """
```

**Key Points:**
- Calculates description: "{resident.phone} - ₹{bill.total} (rent+maintenance+marketplace+fee)"
- Sets reference_id = bill.razorpay_idempotency_key (UUID) for webhook matching
- Amount in smallest unit (paise): int(bill.total * 100)
- Expires in 3 days (default Razorpay expiry)
- Returns id, short_url, expires_at
- Logs for debugging; includes latency measurement

### 6. Webhook Signature Parsing

**Function Signature:**
```python
def parse_razorpay_webhook_signature(headers: dict, body: bytes) -> bool:
    """
    Verify Razorpay webhook signature.
    
    Validates webhook is truly from Razorpay (not spoofed).
    
    Args:
        headers: HTTP request headers dict
        body: Raw request body bytes
    
    Returns:
        bool: True if signature valid, False otherwise
    
    Note:
        Existing pattern in codebase; reuse if available.
    """
```

**Key Points:**
- Extracts X-Razorpay-Event-ID and X-Razorpay-Signature headers
- Computes HMAC-SHA256(body, webhook_secret)
- Compares with header signature
- Returns True only if exact match
- Does not raise exception; returns bool for conditional logic

## Implementation Details

### Error Handling

All functions must handle Razorpay API errors gracefully:

```python
import logging
from razorpay.errors import RazorpayException

logger = logging.getLogger(__name__)

def create_razorpay_contact(name: str, phone: str) -> str:
    try:
        contact = razorpay.client.contact.create({
            'name': name,
            'phone': phone
        })
        logger.info(f"Created Razorpay contact {contact['id']} for {name}")
        return contact['id']
    except RazorpayException as e:
        logger.error(f"Failed to create contact: {e.getMessage()}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error creating contact: {e}")
        raise
```

### Logging & Monitoring

Log every operation:
- **Success:** Log contact_id, fund_account_id, link_id created
- **Failure:** Log exception details and request payload (redacted sensitive data)
- **Latency:** Measure time from request to response; alert if >2s for contact/fund account, >5s for payment link

### Decimal Precision

All money calculations must use `Decimal`, never float:

```python
from decimal import Decimal

def calculate_gst_on_fee(fee: Decimal) -> Decimal:
    return (fee * Decimal('0.18')).quantize(Decimal('0.01'))
```

## Tests (Extracted from claude-plan-tdd.md)

### Test File: `apps/fintech/tests/test_services_utilities.py`

Tests for all utility functions:

#### Convenience Fee Tests
- `test_calculate_convenience_fee_returns_29` — Always returns ₹29.00
- `test_calculate_convenience_fee_returns_decimal` — Returns Decimal type, not float
- `test_calculate_gst_on_fee_calculates_18_percent` — 18% of ₹29 = ₹5.22
- `test_calculate_gst_on_fee_decimal_precision` — Uses Decimal, rounded to 2 places

#### Razorpay Contact Tests
- `test_create_razorpay_contact_calls_api` — Mocked Razorpay API called with correct payload
- `test_create_razorpay_contact_returns_id` — Returns contact_id string
- `test_create_razorpay_contact_logs_success` — Logs contact creation at info level
- `test_create_razorpay_contact_handles_api_error` — Raises RazorpayException on API failure
- `test_create_razorpay_contact_logs_error` — Logs error details on failure

#### Razorpay Fund Account Tests
- `test_create_razorpay_fund_account_bank_account` — Creates fund account for bank account
- `test_create_razorpay_fund_account_upi_vpa` — Creates fund account for UPI VPA (if provided)
- `test_create_razorpay_fund_account_calls_api` — API called with correct payload
- `test_create_razorpay_fund_account_returns_id` — Returns fund_account_id string
- `test_create_razorpay_fund_account_initiates_penny_drop` — Logs that validation will occur asynchronously
- `test_create_razorpay_fund_account_handles_api_error` — Raises RazorpayException on failure

#### Payment Link Tests
- `test_create_payment_link_calls_razorpay_api` — Mocked API called with correct amount
- `test_create_payment_link_amount_in_paise` — Amount passed as int(total * 100)
- `test_create_payment_link_reference_id_is_idempotency_key` — reference_id = bill.razorpay_idempotency_key
- `test_create_payment_link_returns_dict_with_required_fields` — Returns {id, short_url, expires_at}
- `test_create_payment_link_includes_description` — Description includes resident phone and breakdown
- `test_create_payment_link_handles_api_error` — Raises RazorpayException on failure
- `test_create_payment_link_logs_latency` — Logs time taken for API call
- `test_create_payment_link_decimal_precision_in_description` — Description uses Decimal, not float

#### Webhook Signature Tests
- `test_parse_razorpay_webhook_signature_valid` — Returns True for valid signature
- `test_parse_razorpay_webhook_signature_invalid` — Returns False for invalid/tampered signature
- `test_parse_razorpay_webhook_signature_missing_header` — Returns False if signature header missing
- `test_parse_razorpay_webhook_signature_extracts_event_id` — Extracts X-Razorpay-Event-ID for logging

## Test Setup Fixtures

**File:** `apps/fintech/tests/conftest.py` (extend or create)

Fixtures needed:
- `@pytest.fixture` for mock Razorpay client with canned responses
- `@patch('apps.fintech.services.razorpay.client')` for all service tests
- Example responses: contact creation, fund account creation, payment link

```python
@pytest.fixture
def mock_razorpay_client(monkeypatch):
    """Mock Razorpay client for tests."""
    from unittest.mock import Mock, patch
    
    client = Mock()
    client.contact.create.return_value = {'id': 'cont_test123', 'phone': '9876543210'}
    client.fund_account.create.return_value = {'id': 'fa_test123', 'account_id': 'acc_test123'}
    client.payment_link.create.return_value = {
        'id': 'plink_test123',
        'short_url': 'https://rzp.io/test',
        'expire_by': 1234567890,
    }
    
    monkeypatch.setattr('apps.fintech.services.razorpay.client', client)
    return client
```

## Mocking Strategy

Use `unittest.mock` and `@patch` decorator:

```python
from unittest.mock import patch, Mock

@patch('apps.fintech.services.razorpay.client')
def test_create_razorpay_contact(mock_client):
    mock_client.contact.create.return_value = {
        'id': 'cont_ABCDabcd1234'
    }
    
    contact_id = create_razorpay_contact('Rajesh Kumar', '9876543210')
    
    assert contact_id == 'cont_ABCDabcd1234'
    mock_client.contact.create.assert_called_once_with({
        'name': 'Rajesh Kumar',
        'phone': '9876543210'
    })
```

## Code Organization

All functions belong in `apps/fintech/services.py`. This file will also contain:
- Section 06 functions: `perform_bill_settlement()` (payment routing logic)
- Section 08 functions: `generate_bill_pdf()` (PDF generation helper)

Keep utilities separate from business logic—no imports of tasks, views, or models in service functions (only model type hints).

## Dependencies & Imports

Required imports for services.py:

```python
import logging
from datetime import datetime, timedelta
from decimal import Decimal

from django.conf import settings
from razorpay import Client
from razorpay.errors import RazorpayException

from apps.fintech.models import UnifiedBill, RentAgreement

logger = logging.getLogger(__name__)

# Initialize Razorpay client
razorpay = Client(
    auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
)
```

Ensure settings contain:
- `RAZORPAY_KEY_ID` — Razorpay API key
- `RAZORPAY_KEY_SECRET` — Razorpay API secret
- `RAZORPAY_WEBHOOK_SECRET` — For signature verification

## Quality Checklist

- [ ] All functions have docstrings with Args, Returns, Raises
- [ ] Convenience fee always returns ₹29.00 (Decimal)
- [ ] All money calculations use Decimal type
- [ ] Every Razorpay API call wrapped in try/except
- [ ] Errors logged before raising exception
- [ ] Latency logged for external API calls
- [ ] Tests mock Razorpay client entirely (no real API calls)
- [ ] Tests >90% coverage for services.py
- [ ] Reference_id in payment link uses bill.razorpay_idempotency_key
- [ ] Webhook signature verification works for all event types

## Integration Points

These utilities are called by:
- **Section 02 (Resident Endpoints):** `create_payment_link()` in bill payment endpoint
- **Section 02 (Resident Endpoints):** `create_razorpay_contact()`, `create_razorpay_fund_account()` in rent agreement endpoint
- **Section 03 (Admin Endpoints):** Razorpay VA creation (similar pattern)
- **Section 04 (Celery Tasks):** `create_payment_link()` in send_bill_notifications
- **Section 05 (Webhooks):** `parse_razorpay_webhook_signature()` in webhook validation
- **Section 06 (Payment Routing):** Razorpay Route transfer wrappers (in same file)
- **Section 08 (PDF Statements):** PDF generation helper (in same file)

None of these utilities contain business logic—they are purely technical wrappers. This makes them highly reusable and testable in isolation.