Now I have all the context. Let me generate the section-08-pdf-statements.md content with tests first, then implementation details.

---

# PDF Statements & Bill Document Generation

## Overview

This section covers the PDF statement generation system for unified bills. Residents can download itemized bill statements that are rendered to PDF using WeasyPrint and cached to S3 for performance. The implementation includes the HTML template, caching logic, and the download endpoint.

**Files to create/modify:**
- `apps/fintech/templates/fintech/bill_statement.html` — WeasyPrint template
- `apps/fintech/services.py` — Add `generate_bill_pdf()` function
- `apps/fintech/views.py` — Add PDF download endpoint to ResidentBillViewSet
- `apps/fintech/tests/test_api_bill_statement_pdf.py` — PDF endpoint and caching tests
- `apps/fintech/tests/test_perf_pdf_generation.py` — Performance and cache validation tests

**Dependencies:**
- Requires section-01-models-migrations (UnifiedBill model with statement_s3_key field)
- Requires section-02-resident-endpoints (ResidentBillViewSet base)

---

## Tests First

### Test File: `apps/fintech/tests/test_api_bill_statement_pdf.py`

This test file covers the PDF download endpoint, caching behavior, and cache invalidation.

**Test Stubs:**

```python
# apps/fintech/tests/test_api_bill_statement_pdf.py

import pytest
from django.test import TestCase
from django.urls import reverse
from unittest.mock import patch, MagicMock
import io

@pytest.mark.django_db
class TestBillStatementPDFDownload:
    """PDF endpoint and caching tests for bill statements."""

    def test_get_statement_pdf_returns_pdf_file(self, resident_client, unified_bill):
        """Response is valid PDF binary with correct content type."""
        # Implement: GET /api/v1/fintech/bills/{bill_month}/statement.pdf
        # Verify: response.status_code == 200
        # Verify: response['Content-Type'] == 'application/pdf'
        # Verify: response.content is valid PDF (check magic bytes %PDF)
        pass

    def test_get_statement_pdf_includes_breakdown(self, resident_client, unified_bill):
        """PDF content includes itemized breakdown (rent, maintenance, marketplace, fee, GST)."""
        # Implement: Extract PDF text (using PyPDF2 or similar)
        # Verify: PDF contains rent_amount, maintenance_amount, marketplace_amount, convenience_fee, gst_on_fee, total
        pass

    @patch('apps.fintech.services.boto3_client')
    def test_get_statement_pdf_caches_to_s3(self, mock_boto3, resident_client, unified_bill):
        """First generation uploads to S3; subsequent downloads fetch from S3."""
        # First request: S3 put_object called
        # Verify: statement_s3_key populated on bill
        # Second request: S3 get_object called (cache hit)
        # Verify: no PDF generation (WeasyPrint not called)
        pass

    def test_get_statement_pdf_cache_key_pattern(self, resident_client, unified_bill):
        """S3 cache key follows pattern bills/{year}/{month}/{resident_id}.pdf."""
        # Implement: Check statement_s3_key on bill after download
        # Verify: Key matches pattern e.g., 'bills/2026/04/123456.pdf'
        pass

    def test_get_statement_pdf_regenerates_if_bill_updated(self, resident_client, unified_bill):
        """If bill total changes, cache invalidated and PDF regenerated."""
        # First download: caches to S3
        # Update bill.total (e.g., dispute resolved)
        # Second download: S3 cache invalidated, new PDF generated
        # Verify: new PDF differs from first (different total)
        pass

    def test_get_statement_pdf_requires_ownership(self, resident_client, other_resident_bill):
        """Resident can only download their own statement."""
        # Implement: Non-owner attempts GET
        # Verify: response.status_code == 403 (Forbidden)
        pass

    def test_get_statement_pdf_returns_404_if_bill_not_found(self, resident_client):
        """GET for nonexistent bill_month returns 404."""
        # Implement: GET with invalid bill_month
        # Verify: response.status_code == 404
        pass

    def test_get_statement_pdf_not_authenticated(self, client, unified_bill):
        """Unauthenticated access returns 401."""
        # Implement: GET without token
        # Verify: response.status_code == 401
        pass
```

### Test File: `apps/fintech/tests/test_perf_pdf_generation.py`

Performance and optimization tests for PDF generation and caching.

**Test Stubs:**

```python
# apps/fintech/tests/test_perf_pdf_generation.py

import pytest
import time
from unittest.mock import patch

@pytest.mark.django_db
class TestPDFGenerationPerformance:
    """Performance benchmarks for PDF generation and S3 caching."""

    @patch('apps.fintech.services.weasyprint.HTML')
    def test_statement_pdf_generates_within_5s(self, mock_weasyprint, unified_bill):
        """WeasyPrint PDF generation completes within 5 seconds."""
        # Implement: Call generate_bill_pdf(unified_bill)
        # Measure: time.time() before and after
        # Verify: generation_time < 5.0 seconds
        # Note: First-time generation may be slower; acceptable range is ~2-5s
        pass

    @patch('apps.fintech.services.boto3_client')
    def test_statement_pdf_s3_caching_avoids_regeneration(self, mock_boto3, resident_client, unified_bill):
        """Subsequent downloads fetch from S3 cache without regenerating PDF."""
        # Call generate_bill_pdf first time (cache miss)
        # Verify: WeasyPrint called once
        # Call generate_bill_pdf second time (cache hit)
        # Verify: WeasyPrint not called again (only S3 get_object)
        pass

    @patch('apps.fintech.services.boto3_client')
    def test_statement_pdf_s3_cache_invalidation(self, mock_boto3, unified_bill):
        """Cache is invalidated when bill.updated_at > statement_generated_at."""
        # First generation: statement_generated_at = now
        # Update bill.total
        # Second generation: updated_at > generated_at, cache invalidated
        # Verify: PDF regenerated with new total
        pass

    def test_statement_pdf_cache_expiry_not_applied(self, unified_bill):
        """S3 cache is permanent (not expiring) for immutable historical bills."""
        # Note: Bill PDFs are immutable once bill status='paid'
        # Cache should never expire (S3 TTL = never)
        # Verify: statement_s3_key set once, never cleared
        pass
```

---

## Implementation Details

### 1. HTML Template for Bill Statements

**File:** `apps/fintech/templates/fintech/bill_statement.html`

The template renders a professional, itemized bill statement suitable for PDF export via WeasyPrint.

**Key Elements:**

```html
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Bill Statement - {{ bill.bill_month|date:"F Y" }}</title>
    <style>
        /* CSS for WeasyPrint-compatible PDF rendering */
        body {
            font-family: Arial, sans-serif;
            margin: 40px;
            color: #333;
        }
        .header {
            text-align: center;
            margin-bottom: 30px;
            border-bottom: 2px solid #000;
            padding-bottom: 20px;
        }
        .section {
            margin: 20px 0;
        }
        .item-row {
            display: flex;
            justify-content: space-between;
            padding: 8px 0;
            border-bottom: 1px solid #ddd;
        }
        .total-row {
            display: flex;
            justify-content: space-between;
            padding: 12px 0;
            font-weight: bold;
            font-size: 16px;
            border-top: 2px solid #000;
            border-bottom: 2px solid #000;
        }
        .negative {
            color: #c41e3a;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>{{ bill.resident.community.name }}</h1>
        <p>Resident: {{ bill.resident.user.get_full_name }}</p>
        <p>Apartment: {{ bill.resident.apartment_number }}</p>
        <p>Bill Month: {{ bill.bill_month|date:"F Y" }}</p>
    </div>

    <div class="section">
        <h2>Charges</h2>
        <div class="item-row">
            <span>Rent Amount</span>
            <span>₹{{ bill.rent_amount|floatformat:2 }}</span>
        </div>
        <div class="item-row">
            <span>Maintenance Charges</span>
            <span>₹{{ bill.maintenance_amount|floatformat:2 }}</span>
        </div>
        <div class="item-row">
            <span>Marketplace Dues</span>
            <span>₹{{ bill.marketplace_amount|floatformat:2 }}</span>
        </div>
        <div class="item-row">
            <span>Convenience Fee (Flat)</span>
            <span>₹{{ bill.convenience_fee|floatformat:2 }}</span>
        </div>
        <div class="item-row">
            <span>GST on Fee (18%)</span>
            <span>₹{{ bill.gst_on_fee|floatformat:2 }}</span>
        </div>
    </div>

    <div class="section">
        <div class="total-row">
            <span>Total Amount Due</span>
            <span>₹{{ bill.total|floatformat:2 }}</span>
        </div>
    </div>

    <div class="section">
        <h3>Payment Status</h3>
        <p>Status: <strong>{{ bill.get_status_display }}</strong></p>
        {% if bill.paid_at %}
            <p>Paid On: {{ bill.paid_at|date:"d M Y, H:i" }}</p>
        {% endif %}
    </div>

    <div class="section">
        <p style="font-size: 12px; color: #666;">
            Generated on: {{ now|date:"d M Y, H:i:s" }}<br>
            For queries, contact: support@nammaNeighbor.com
        </p>
    </div>
</body>
</html>
```

**Design Rationale:**
- CSS is inline and WeasyPrint-compatible (no external stylesheets)
- Uses Django template tags for dynamic data (bill amounts, resident info, dates)
- Decimal amounts rendered with `|floatformat:2` for ₹ currency display
- No JavaScript (WeasyPrint doesn't support it)
- Print-friendly layout (page breaks managed by WeasyPrint)

### 2. PDF Generation Service

**File:** `apps/fintech/services.py` — Add or extend with:

```python
def generate_bill_pdf(bill) -> bytes:
    """
    Generate PDF bytes for a bill statement using WeasyPrint template.
    
    Args:
        bill (UnifiedBill): The bill to render
    
    Returns:
        bytes: PDF file content
    
    Raises:
        WeasyPrintError: If template rendering or PDF generation fails
    """
    # Implement:
    # 1. Load and render Django template with bill context
    # 2. Convert HTML to PDF using WeasyPrint
    # 3. Return PDF bytes
    # 4. On error, log and raise
    pass

def cache_bill_pdf_to_s3(bill, pdf_bytes) -> str:
    """
    Upload PDF to S3 and update bill.statement_s3_key.
    
    Args:
        bill (UnifiedBill): The bill object
        pdf_bytes (bytes): PDF content
    
    Returns:
        str: S3 key (e.g., 'bills/2026/04/123456.pdf')
    
    Raises:
        S3Exception: If upload fails
    """
    # Implement:
    # 1. Generate S3 key: bills/{year}/{month}/{resident_id}.pdf
    # 2. Upload pdf_bytes to S3 with content-type='application/pdf'
    # 3. Update bill.statement_s3_key = s3_key
    # 4. Update bill.statement_generated_at = now
    # 5. Save bill
    # 6. Return s3_key
    pass

def get_bill_pdf_from_s3_or_generate(bill) -> bytes:
    """
    Fetch PDF from S3 if cached and valid; otherwise generate and cache.
    
    Logic:
    1. If bill.statement_s3_key exists AND bill.updated_at < bill.statement_generated_at:
       - Fetch from S3, return bytes
    2. Else:
       - Generate PDF from template
       - Cache to S3
       - Return bytes
    
    Args:
        bill (UnifiedBill): The bill to render
    
    Returns:
        bytes: PDF file content
    """
    # Implement as per logic above
    pass
```

**Design Rationale:**
- Separation of concerns: generation, caching, and retrieval are distinct functions
- S3 key pattern `bills/{year}/{month}/{resident_id}.pdf` is simple and queryable
- Cache invalidation is based on bill.updated_at > statement_generated_at (simple timestamp comparison)
- No TTL on S3 objects—bills are immutable once paid, PDFs are permanent

### 3. PDF Download Endpoint

**File:** `apps/fintech/views.py` — Extend ResidentBillViewSet:

```python
class ResidentBillViewSet(viewsets.ModelViewSet):
    """Resident bill viewing and payment endpoints."""
    # ... existing methods ...

    @action(
        detail=False,
        methods=['GET'],
        url_path='(?P<bill_month>\\d{4}-\\d{2}-\\d{2})/statement.pdf',
        permission_classes=[IsResidentOfCommunity]
    )
    def statement_pdf(self, request, bill_month=None):
        """
        Download bill statement as PDF.
        
        Endpoint: GET /api/v1/fintech/bills/{bill_month}/statement.pdf
        
        Returns:
            - HttpResponse with PDF file attachment
            - Content-Type: application/pdf
            - Content-Disposition: attachment; filename="bill_YYYY_MM.pdf"
        
        Raises:
            - Http404: If bill not found
            - Http403: If resident doesn't own bill
        """
        # Implement:
        # 1. Parse bill_month, get bill for resident
        # 2. Call get_bill_pdf_from_s3_or_generate(bill)
        # 3. Return HttpResponse with PDF bytes, correct headers
        pass
```

**Implementation Steps:**

1. **Query bill:** Fetch UnifiedBill by resident and bill_month
2. **Permission check:** Verify resident owns the bill (existing permission class handles this)
3. **Generate or fetch PDF:** Call `get_bill_pdf_from_s3_or_generate(bill)`
4. **Return response:** Create HttpResponse with:
   - Content-Type: application/pdf
   - Content-Disposition: attachment; filename="bill_2026_04.pdf"
   - Content: PDF bytes

**Error Handling:**
- Bill not found → 404
- Permission denied → 403 (handled by permission class)
- PDF generation error → 500 with error message logged
- S3 error → 500, attempt to regenerate from template

### 4. Database Field Additions

**File:** `apps/fintech/models.py` — UnifiedBill model extensions (section-01):

These fields enable PDF caching and cache invalidation:

```python
class UnifiedBill(TimestampedModel):
    # ... existing fields ...
    
    # PDF caching
    statement_s3_key: CharField(500, blank=True)
    statement_generated_at: DateTimeField(null=True)
```

**Field Rationale:**
- `statement_s3_key`: Stores S3 object key (e.g., `bills/2026/04/123456.pdf`)
- `statement_generated_at`: Timestamp of last PDF generation; compared to `updated_at` for cache validity
- Both are nullable to handle pre-generation state
- CharField(500) is sufficient for S3 key (typical keys are ~50 chars)

---

## Implementation Sequence

1. **Create HTML template** (`bill_statement.html`)
   - Implement itemized bill layout
   - Test locally with sample data

2. **Add service functions** (`services.py`)
   - `generate_bill_pdf()` — template → PDF via WeasyPrint
   - `cache_bill_pdf_to_s3()` — upload PDF to S3, update bill model
   - `get_bill_pdf_from_s3_or_generate()` — orchestrator with caching logic

3. **Extend models** (if not in section-01)
   - Add `statement_s3_key` and `statement_generated_at` fields to UnifiedBill

4. **Add endpoint** (`views.py`)
   - `ResidentBillViewSet.statement_pdf()` action
   - Permission checks, error handling
   - Return PDF response with correct headers

5. **Write integration tests**
   - Test PDF download, content validation
   - Test S3 caching behavior
   - Test cache invalidation
   - Test permission checks

6. **Performance testing**
   - Benchmark WeasyPrint generation time (target <5s)
   - Validate S3 cache hit performance (<100ms)
   - Monitor PDF size (target <500KB per bill)

---

## Dependencies & Integration

**Depends On:**
- section-01-models-migrations: UnifiedBill model with statement_s3_key, statement_generated_at fields
- section-02-resident-endpoints: ResidentBillViewSet base class exists

**Used By:**
- section-09-testing: PDF endpoint and caching tests

**External Libraries:**
- `weasyprint` — PDF generation from HTML
- `boto3` — S3 upload/download
- `django-storages` — S3 storage backend (if configured)

**Django Installed Apps (assumed existing):**
- `django.contrib.templates`
- Celery (for potential async PDF generation, future enhancement)

---

## Configuration Assumptions

**settings.py** should include:

```python
# S3 Configuration (assumed from existing codebase)
AWS_STORAGE_BUCKET_NAME = 'namma-neighbour-fintech-pdfs'  # Or similar
AWS_S3_REGION_NAME = 'ap-south-1'  # India region

# WeasyPrint Configuration
WEASYPRINT_TIMEOUT = 10  # seconds, for large/complex PDFs

# PDF Caching
PDF_CACHE_EXPIRY = None  # Permanent (no TTL)
```

---

## Testing Strategy

### Unit Tests (services.py functions)
- Test template rendering with sample bill
- Test PDF generation (valid PDF bytes returned)
- Test S3 key generation (correct pattern)
- Test cache invalidation logic (timestamp comparison)

### Integration Tests (endpoint + caching)
- Happy path: download PDF, verify content
- Cache hit: second download fetches from S3
- Cache miss: updated bill regenerates PDF
- Permission: non-owner cannot access
- Error handling: missing bill returns 404

### Performance Tests
- PDF generation time < 5s for typical bill
- S3 cache hit < 100ms
- PDF file size < 500KB
- S3 upload time < 2s

### End-to-End Tests
- Resident flow: bill generated → download statement → verify content
- Concurrent downloads: multiple residents downloading different bills (no contention)

---

## Success Criteria

1. Bill PDF downloads successfully with correct itemization
2. First download generates PDF and caches to S3 (S3 key stored on bill)
3. Second download fetches from S3 cache (no PDF regeneration)
4. Bill update invalidates cache and regenerates PDF
5. Non-owner cannot download other residents' statements
6. PDF generation completes within 5 seconds
7. S3 cache hit returns within 100ms
8. HTML template displays all line items: rent, maintenance, marketplace, fee, GST, total
9. All tests pass with >90% code coverage