Now I have all the context. Let me extract the relevant content for section-02-qr-labels. Based on the manifest and the plans, I need to focus on:

1. QR code generation service
2. Label PDF generation (single and batch)
3. Tests for these services
4. Implementation details from the plan

Let me create the comprehensive section content:

---

# QR Code Generation and Label PDF Creation (section-02-qr-labels)

## Overview

This section implements the services and endpoints for generating QR codes and printable parcel labels. The QR codes enable parcel tracking throughout the delivery lifecycle, while labels provide vendors with printable A6 documents containing QR codes, parcel identification, and recipient information.

**Key Dependencies:**
- Depends on: section-01-models-fsm (Parcel model with FSM)
- Blocks: section-03-manifest-api, section-06-api-endpoints

## Architecture

### Component Responsibilities

| Component | Purpose |
|-----------|---------|
| **QR Service** (`apps/logistics/services/qr.py`) | Generate compact QR codes with ERROR_CORRECT_H |
| **Label Service** (`apps/logistics/services/labels.py`) | Create single A6 labels and multi-page batch PDFs |
| **Label Endpoints** (`apps/logistics/api/views.py`) | HTTP endpoints for label retrieval and caching |

### Tech Stack

- **QR Generation:** `qrcode[pil]` library
- **PDF Generation:** `reportlab` (chosen for superior batch performance vs. weasyprint)
- **Storage:** S3 via Django's storage backends (DocumentStorage for labels/QRs)
- **Caching:** HTTP response caching (ETags, Cache-Control)

## Database Models (from section-01)

The Parcel model includes:
- `qr_code` (CharField, unique) — immutable identifier "NN-20260401-0034"
- `status` (FSMField) — tracks state (LABEL_GENERATED → PICKED_UP → ...)
- `order` (OneToOneField to Order) — links to order details

## Detailed Implementation

### QR Code Service

**File:** `/var/www/html/MadGirlfriend/namma-neighbour/apps/logistics/services/qr.py`

**Function: `generate_parcel_qr(parcel: Parcel) -> bytes`**

Purpose: Generate a QR PNG image for embedding in labels.

Specifications:
- **Payload:** Compact JSON containing order_id, tower, flat (NO sequence)
  - Example: `{"o": "NN-20260401-0034", "t": "B", "f": "304"}`
  - JSON is minimized (no whitespace) to reduce size
- **QR Parameters:**
  - Error Correction: `ERROR_CORRECT_H` (30% damage tolerance)
  - Version: Auto-fit (typically v2-v3 for ~45 byte payload)
  - Box Size: 10 pixels per module
  - Border: 4 boxes (standard)
- **Output:** PNG bytes suitable for embedding in PDF or image display

**Implementation Pattern (stub):**
```python
def generate_parcel_qr(parcel: Parcel) -> bytes:
    """
    Generate QR code PNG for parcel.
    
    Args:
        parcel: Parcel instance
        
    Returns:
        PNG bytes
        
    Raises:
        ValueError: If parcel data invalid
    """
    # 1. Construct minimal JSON payload
    # 2. Create QRCode instance with ERROR_CORRECT_H
    # 3. Generate PIL image
    # 4. Convert to PNG bytes
    # 5. Return bytes
    pass
```

**Test Stubs (from claude-plan-tdd.md):**
- Test: Returns PNG bytes
- Test: Payload: `{"o": order_id, "t": tower, "f": flat}`
- Test: NO sequence field (server-side validation only)
- Test: ERROR_CORRECT_H used (30% damage tolerance)
- Test: Version auto-fit (typically v2-v3)
- Test: Generated QR scannable on iOS and Android
- Test: Scannable under varying lighting conditions
- Test: Scannable when printed at 3-4cm size

### Label Service

**File:** `/var/www/html/MadGirlfriend/namma-neighbour/apps/logistics/services/labels.py`

**Function: `generate_parcel_label(parcel: Parcel) -> bytes`**

Purpose: Generate a single A6 label PDF for a parcel.

Specifications:
- **Page Size:** A6 (10.5cm × 14.8cm)
- **Layout:**
  - Top: QR code (3.5cm × 3.5cm)
  - Middle: Tower/Flat/Recipient name (readable text)
  - Bottom: Order ID (human-readable barcode or plain text)
  - Margins: 0.3cm on all sides
- **Fonts:** Helvetica (standard reportlab)
- **Output:** PDF bytes

**Implementation Pattern (stub):**
```python
def generate_parcel_label(parcel: Parcel) -> bytes:
    """
    Generate single A6 PDF label for parcel.
    
    Args:
        parcel: Parcel instance
        
    Returns:
        PDF bytes
        
    Raises:
        ValueError: If parcel data invalid
    """
    # 1. Get QR code PNG from generate_parcel_qr()
    # 2. Create reportlab canvas (A6 size)
    # 3. Draw margins and layout sections
    # 4. Embed QR image
    # 5. Draw tower/flat/recipient text
    # 6. Draw order ID
    # 7. Return PDF bytes
    pass
```

**Function: `generate_vendor_labels_batch(vendor: User, date: date) -> bytes`**

Purpose: Generate multi-page PDF with one label per order for a vendor's daily orders.

Specifications:
- **Input:** Vendor user, delivery date
- **Output:** Multi-page PDF with one A6 label per order
- **Performance Requirement:** 15 orders generated in <10 seconds
- **Optimization Strategy:**
  - Cache QR PNG images in memory during batch generation
  - Stream pages to buffer (avoid buffering all pages in memory)
  - Parallel QR generation (if multiple workers available)

**Implementation Pattern (stub):**
```python
def generate_vendor_labels_batch(vendor: User, date: date) -> bytes:
    """
    Generate multi-page PDF with labels for vendor's orders.
    
    Args:
        vendor: User instance (vendor role)
        date: Delivery date
        
    Returns:
        PDF bytes (may be large)
        
    Raises:
        ValueError: If no orders found
    """
    # 1. Fetch all confirmed orders for vendor + date
    # 2. Initialize PDF writer
    # 3. For each order:
    #    a. Fetch corresponding parcel
    #    b. Call generate_parcel_label()
    #    c. Append to PDF
    # 4. Return final PDF bytes
    # Note: Use streaming/incremental writing for large batches
    pass
```

**Test Stubs:**
- Test: `generate_parcel_label()` returns PDF bytes (A6 size)
- Test: Layout correct: QR (top), tower/flat (middle), order ID (bottom)
- Test: Fonts readable at print size
- Test: Margins: 0.3cm on all sides
- Test: `generate_vendor_labels_batch()` returns multi-page PDF
- Test: One label per order
- Test: Performance: 15 orders < 10s (measured)
- Test: Incremental writing (not buffered in memory)
- Test: QR code embedded in label (not external image)
- Test: QR size: 3.5cm × 3.5cm

## API Endpoints

### GET /api/v1/orders/{order_id}/label.pdf

**Purpose:** Retrieve or generate a single label for an order.

**Permission:** `IsOrderVendor | IsDeliveryPartner`

**Behavior:**
1. Lookup order and associated parcel
2. Check parcel status:
   - If status >= PICKED_UP: return 410 Gone (label frozen)
   - If status == LABEL_GENERATED: generate label (or fetch from cache)
3. Return PDF with proper headers

**Response:**
- 200: PDF binary with `Content-Type: application/pdf` and `inline` disposition
- 410: Label frozen (parcel already picked up)
- 403: Unauthorized
- 404: Order or parcel not found

**Caching Strategy:**
- Cache generated PDF until parcel status >= PICKED_UP
- Use HTTP ETags or cache key based on (order_id, parcel_status)
- Return 410 once parcel status changes to PICKED_UP or beyond

**Implementation Stub (in views):**
```python
class OrderLabelPDFView(APIView):
    permission_classes = [IsOrderVendor | IsDeliveryPartner]
    
    def get(self, request, order_id):
        """
        Retrieve single label PDF.
        
        Returns:
            Response with PDF binary or 410 if frozen
        """
        # 1. Lookup order and parcel
        # 2. Check parcel status
        # 3. If >= PICKED_UP, return 410
        # 4. Generate or fetch from cache
        # 5. Return with proper headers
        pass
```

**Test Stubs:**
- Test: Generates A6 label (10.5cm × 14.8cm)
- Test: Includes QR code (3.5cm), tower/flat, order ID, vendor name
- Test: QR payload does NOT include sequence
- Test: Generated PDF cached until parcel status >= PICKED_UP
- Test: Subsequent requests return cached version
- Test: Once parcel status >= PICKED_UP, return 410 Gone
- Test: Permissions enforced (IsOrderVendor, IsDeliveryPartner)
- Test: Other roles return 403

### GET /api/v1/vendors/orders/labels.pdf?date=2026-04-01

**Purpose:** Retrieve batch PDF of all labels for a vendor's daily orders.

**Permission:** `IsVendor`

**Query Parameters:**
- `date` (required): Delivery date (YYYY-MM-DD format)

**Behavior:**
1. Fetch all confirmed orders for (vendor, date)
2. If >10 orders: queue Celery task (async)
   - Return 202 Accepted with task_id
   - Client polls for completion or receives webhook callback
3. If ≤10 orders: generate synchronously
   - Return 200 with PDF binary

**Response:**
- 200: PDF binary (sync generation, ≤10 orders)
- 202: Accepted (async task queued for >10 orders) with task_id
- 400: Invalid query params
- 403: Unauthorized

**Implementation Stub (in views):**
```python
class VendorLabelsBatchPDFView(APIView):
    permission_classes = [IsVendor]
    
    def get(self, request):
        """
        Retrieve batch labels PDF.
        
        Query params:
            date: YYYY-MM-DD
            
        Returns:
            Response with PDF (200 if ≤10 orders)
            or task_id (202 if >10 orders)
        """
        # 1. Parse and validate date param
        # 2. Fetch orders for vendor + date
        # 3. Check order count
        # 4. If <= 10: generate synchronously
        # 5. If > 10: queue Celery task, return 202
        pass
```

**Test Stubs:**
- Test: Fetches all vendor's orders for given date
- Test: Generates multi-page PDF (one label per order)
- Test: Performance: 15 orders in <10s
- Test: If >10 orders, queue Celery task, return 202 with task_id
- Test: If ≤10 orders, generate synchronously, return 200
- Test: Permissions enforced (IsVendor only)
- Test: Other roles return 403

## File Structure

```
apps/logistics/
├── services/
│   ├── qr.py
│   │   └── generate_parcel_qr(parcel) -> bytes
│   └── labels.py
│       ├── generate_parcel_label(parcel) -> bytes
│       └── generate_vendor_labels_batch(vendor, date) -> bytes
├── api/
│   ├── views.py
│   │   ├── OrderLabelPDFView (GET /api/v1/orders/{order_id}/label.pdf)
│   │   └── VendorLabelsBatchPDFView (GET /api/v1/vendors/orders/labels.pdf)
│   ├── serializers.py
│   │   └── Label serializers (if any custom validation)
│   └── urls.py
└── tests/
    ├── test_services_qr.py
    ├── test_services_labels.py
    └── test_api_labels.py
```

## Key Integration Points

### With section-01-models-fsm

- Parcel model provides: order_id (via qr_code), tower, flat, status
- FSMField status determines label availability (frozen after PICKED_UP)
- Order model provides: vendor info, confirmation status

### With section-03-manifest-api

- After manifest creation, parcels are ready for label generation
- Labels must be generated before PICKED_UP status

### With section-06-api-endpoints

- Label endpoints are part of the full API surface
- Batch label generation may trigger async tasks (Celery)

## Implementation Checklist

1. **Setup**
   - Install `qrcode[pil]` and `reportlab` dependencies in pyproject.toml
   - Create `/apps/logistics/services/qr.py` and `/apps/logistics/services/labels.py`

2. **QR Service**
   - Implement `generate_parcel_qr()` with payload JSON (no sequence)
   - Test with actual QR scanner (iOS/Android)
   - Verify 30% damage tolerance under poor conditions

3. **Label Service**
   - Implement `generate_parcel_label()` with reportlab
   - Test A6 dimensions and margins
   - Implement `generate_vendor_labels_batch()` with streaming
   - Performance test: 15 orders < 10 seconds

4. **Endpoints**
   - Create `OrderLabelPDFView` with caching and 410 freezing logic
   - Create `VendorLabelsBatchPDFView` with async task queueing
   - Add URL routing in `/apps/logistics/api/urls.py`

5. **Testing**
   - Unit tests for QR generation (payload, encoding, scanability)
   - Unit tests for label generation (PDF validity, dimensions, text rendering)
   - Unit tests for batch generation (performance, streaming)
   - API tests for both endpoints (caching, permissions, async handling)

6. **Field Operations Validation**
   - Print A6 labels on actual paper
   - Test QR scanning at 30cm distance
   - Test under poor lighting and with damaged codes
   - Validate 15-order batch completes in <10s

## Success Criteria

1. QR codes generate correctly with compact JSON payload (no sequence)
2. QR codes scannable under poor lighting, with 30% damage tolerance
3. Single label endpoint returns A6 PDF, cached until PICKED_UP, then 410 Gone
4. Batch label endpoint generates 15 orders in <10 seconds
5. Batch endpoint returns 202 with task_id for >10 orders
6. Permissions enforced (IsOrderVendor, IsDeliveryPartner, IsVendor)
7. All PDF dimensions and margins correct (A6 = 10.5cm × 14.8cm, margins = 0.3cm)
8. QR embedded in PDF (not external image)

## Testing Examples

### Unit Test Structure

**File:** `/var/www/html/MadGirlfriend/namma-neighbour/apps/logistics/tests/test_services_qr.py`

```python
# Stub structure only
import pytest
from apps.logistics.services.qr import generate_parcel_qr

class TestQRGeneration:
    def test_generate_parcel_qr_returns_bytes(self, parcel_factory):
        """QR generation returns PNG bytes."""
        # Arrange: create parcel fixture
        # Act: call generate_parcel_qr()
        # Assert: result is bytes and valid PNG
        pass
    
    def test_qr_payload_structure(self, parcel_factory):
        """QR payload contains order_id, tower, flat (NO sequence)."""
        # Arrange: create parcel
        # Act: generate QR, decode payload
        # Assert: payload has o, t, f fields but no sequence
        pass
    
    def test_qr_error_correction_h(self, parcel_factory):
        """QR uses ERROR_CORRECT_H (30% damage tolerance)."""
        # Implementation will verify this internally
        pass
```

### API Test Structure

**File:** `/var/www/html/MadGirlfriend/namma-neighbour/apps/logistics/tests/test_api_labels.py`

```python
# Stub structure only
import pytest
from django.test import APIClient

class TestOrderLabelEndpoint:
    def test_get_label_returns_pdf(self, api_client, order_factory):
        """GET /api/v1/orders/{order_id}/label.pdf returns PDF."""
        # Arrange: create order with LABEL_GENERATED parcel
        # Act: GET endpoint
        # Assert: status 200, PDF binary returned
        pass
    
    def test_label_frozen_after_picked_up(self, api_client, order_factory):
        """Label returns 410 after parcel PICKED_UP."""
        # Arrange: create order, transition parcel to PICKED_UP
        # Act: GET endpoint
        # Assert: status 410 Gone
        pass
    
    def test_vendor_batch_async_for_large_orders(self, api_client, vendor_factory):
        """Batch endpoint queues async for >10 orders."""
        # Arrange: create vendor with 15 orders
        # Act: GET batch endpoint
        # Assert: status 202, task_id returned
        pass
```

---

**Note:** This section provides implementation stubs and test structures. The actual code implementation should follow TDD methodology (tests first, then minimal implementation to pass tests). All file paths are absolute and relative to the Django project root.