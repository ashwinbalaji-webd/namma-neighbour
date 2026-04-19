# Research: Logistics Feature Implementation

## Part A: Codebase Analysis

### Project Structure & Architecture

The NammaNeighbor project follows a **multi-app Django architecture** with clear separation of concerns:

**Directory Structure:**
- `apps/` contains all feature apps (users, communities, vendors, catalogue, orders, payments, reviews, notifications, **logistics**)
- `apps/core/` provides shared infrastructure (base models, permissions, storage backends, SMS backends)
- `config/` holds Django settings (environment-specific: base, dev, prod, test)
- Settings follow **12-factor principles** with environment variables for credentials

**Key Convention:** Each app follows this structure:
```
apps/<appname>/
├── models.py       # Database models
├── views.py        # DRF ViewSets
├── serializers.py  # DRF Serializers
├── urls.py         # Route definitions
├── services/       # Business logic
├── tasks.py        # Celery tasks
├── tests/          # Pytest-based tests
└── admin.py        # Django Admin
```

### Django Model Patterns

**Base Model:**
- **`TimestampedModel`** (from `apps/core/models.py`): Abstract base with:
  - `created_at`: immutable timestamp (`auto_now_add=True`)
  - `updated_at`: auto-updates on save (`auto_now=True`)
- Every logistics model (Parcel, DeliveryManifest, ScanEvent) should inherit from `TimestampedModel`

**State Machines:**
- Use `FSMField` (django-fsm) with `protected=True` to prevent direct assignment
- Define transitions with `@transition` decorator
- Example from orders spec:
  ```python
  status = FSMField(default=OrderStatus.PLACED, protected=True)
  
  @transition(field=status, source=OrderStatus.PLACED, target=OrderStatus.PAYMENT_PENDING)
  def await_payment(self):
      # Business logic here
  ```
- **Critical:** Transaction safety - django-fsm prevents invalid state transitions at the database level

**Foreign Keys & Uniqueness:**
- Use string paths for cross-app references: `ForeignKey('communities.Community', ...)`
- Avoids circular imports
- Multi-field uniqueness via `unique_together` constraint
- Add explicit indexes for common query patterns: `indexes = [models.Index(...)]`

**Enums:**
- Use `TextChoices` for readable choice fields
- Example: `ParcelStatus(models.TextChoices)` with LABEL_GENERATED, PICKED_UP, etc.

### API Design Conventions

**Endpoint Structure:**
- All endpoints under `/api/v1/`
- JWT Bearer token authentication (Authorization header)
- Pagination: `PageNumberPagination` with default `PAGE_SIZE=20`
- Error responses: Normalized format with `error` (snake_case code) and `detail` fields

**Permission Model:**
- Four role-based permission classes reading from JWT `roles` claim:
  - `IsResidentOfCommunity()` — resident role
  - `IsVendorOfCommunity()` — vendor role  
  - `IsCommunityAdmin()` — community_admin role
  - `IsPlatformAdmin()` — platform_admin role
- JWT includes `community_id` claim (scoped per active community at token issuance)
- Roles are community-scoped and safe to use without additional lookups

**Delivery Partner Role (New):**
- New role: `delivery_partner`
- Registered by platform admin
- Limited access: `POST /api/v1/parcels/scan/`, manifest endpoints only

### S3 File Storage

**Configuration:**
- Two storage subclasses in `apps/core/storage.py`:
  - `DocumentStorage()` - location prefix: "documents"
  - `MediaStorage()` - location prefix: "media"
- S3 bucket configured with:
  - `default_acl = "private"` — all files private by default
  - `file_overwrite = False` — prevents accidental overwrites
  - `querystring_expire = 3600` — presigned URLs valid for 1 hour
  - Region: `ap-south-1` (India)

**Credentials:**
- Dev: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` from `.env`
- Prod: IAM role attached to container (boto3 reads automatically)

**For Logistics:**
- Proof of Delivery (POD) photos → `MediaStorage()`
- QR code PDFs / labels → `DocumentStorage()`
- Path format: `{location}/{app}/{parcel_id}/{timestamp}.{ext}`

### Celery Task Pattern

**Configuration:**
- Broker & Result Backend: Redis
- Queues: default, sms, kyc, payments, notifications
- Task routing: Tasks mapped to specific queues by app
- Beat schedule: Periodic tasks via cron

**Task Definition:**
```python
@shared_task(queue='notifications')
def send_fcm_notification(user_id: int, title: str, body: str, data: dict) -> None:
    # Implementation
    pass
```

**With Retries (exponential backoff):**
```python
@shared_task(bind=True, max_retries=3, queue='default')
def generate_parcel_label(self, parcel_id: int):
    try:
        # Implementation
    except Exception as exc:
        self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))
```

**For Logistics:**
- Generate QR codes / PDF labels async
- Send FCM notifications on parcel status changes (async)
- Batch create parcels for manifest (async)
- Upload POD photos to S3

### Push Notifications (FCM)

**Device Token Management:**
- `DeviceToken` model: user → token, scoped per platform (Android/iOS)
- Registration endpoint: `POST /api/v1/notifications/register/`
- Tokens registered at app startup per platform

**Notification Data Format:**
```json
{
    "type": "parcel_status_update",
    "parcel_id": "NN-20260401-0034",
    "status": "at_hub",
    "status_label": "At Community Hub"
}
```

**Sending Pattern:**
- Triggered on parcel status transition (via @transition method)
- Sent async via Celery task
- Deep linking: Notification tap opens tracking screen in app

**For Logistics:**
- Trigger notifications on: `AT_COMMUNITY_HUB`, `OUT_FOR_DELIVERY`, `DELIVERED`, `ATTEMPTED`
- Include minimal data (parcel ID, status) - client fetches full details
- Foreground: Query invalidation (TanStack React Query) + local notification

### Testing Setup

**Framework:** pytest with pytest-django plugin

**Test Settings:** Separate `config/settings/test.py`

**Conventions:**
```python
@pytest.mark.django_db
def test_something():
    # DB access; auto-wrapped in transaction
    pass

@pytest.mark.django_db(transaction=True)
def test_concurrent():
    # Tests needing row-level locks (select_for_update)
    pass
```

**Factories:** factory-boy
```python
class ParcelFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Parcel
    qr_code = factory.Sequence(lambda n: f'NN-20260401-{n:04d}')
```

**File Structure:**
```
apps/logistics/tests/
├── factories.py       # All factories
├── conftest.py        # Fixtures
├── test_models.py
├── test_views.py
├── test_services.py
└── test_tasks.py
```

**Mocking:** unittest.mock for patching external services

### Concurrency & Transactions

**Row-Level Locking:**
```python
from django.db import transaction

with transaction.atomic():
    manifest = DeliveryManifest.objects.select_for_update().get(pk=manifest_id)
    # Lock held; other transactions wait
```
- Critical for concurrent manifest operations
- Tests must use `@pytest.mark.django_db(transaction=True)`

**Idempotency:**
- Use unique constraint on idempotency key
- `get_or_create()` pattern for webhook handlers
- Example: scanning same QR twice should be rejected via sequence number

### Logistics-Specific Patterns (from existing specs)

**State Machine for Orders:**
- Uses django-fsm for guaranteed valid transitions
- Transitions can have multiple source states
- Exception raised on invalid attempt
- Webhook handlers check status before transitioning (idempotency)

**QR Code Model:**
- `qr_code = CharField(max_length=50, unique=True)` - Format: "NN-20260401-0034"
- Coupled to order ID for easy lookup
- Compact JSON payload (order ID, tower, flat, sequence) on printed label

**Scan Replay Prevention:**
- `scan_sequence = PositiveSmallIntegerField()` on parcel
- Each scan increments expected sequence
- Invalid sequence → reject with 400
- Anti-tampering at the database level

**Recommendations for Logistics Implementation:**

1. **Models:** All inherit `TimestampedModel`; use `FSMField` for parcel status
2. **APIs:** Follow existing permission patterns; use role-based access
3. **Storage:** POD photos → MediaStorage; QR/PDFs → DocumentStorage
4. **Async:** Celery for label generation, manifest creation, notifications
5. **Concurrency:** Row-level locking for critical manifest operations
6. **Testing:** pytest with factories; mark DB tests appropriately
7. **Notifications:** Send via Celery task on state transitions; include parcel ID only

---

## Part B: Best Practices Research

### Topic 1: QR Code Generation & Barcode Scanning

#### Error Correction Levels

**ERROR_CORRECT_H Specification:**
- Provides **up to 30% damage tolerance** — maximum resilience
- Essential for printed shipping labels subject to outdoor handling
- Alternative: Level Q (25% tolerance) acceptable but inferior
- Logos can occupy up to 30% of QR code surface with Level H

**Size & Printing Guidelines:**

| Requirement | Specification |
|------------|---------------|
| Minimum size for printed QR | 3.8cm (1.5 inches) square minimum |
| Recommended size for A6 labels | 3-4cm × 3-4cm |
| Scanning distance formula | Distance / 10 = Minimum QR width (cm) |
| At 1 meter distance | 10cm minimum width |
| At 2 meters distance | 20cm minimum width |
| Print resolution | 300 DPI minimum (professional quality) |
| Quiet zone | 4 modules minimum on all sides |
| Paper type | Matte/uncoated preferred (even ink absorption, no reflections) |
| Vector format | SVG/EPS recommended (infinite scaling without quality loss) |

**Testing Checklist:**
- Test across multiple devices (iOS, Android)
- Test at varying distances and angles
- Print test samples on actual label stock before batch production
- Verify scanning under intended environment (warehouse lighting, outdoor sun, etc.)

#### React Native Vision Camera Implementation

**Core Architecture:**
- Create CodeScanner instance and memoize to prevent Camera session rebuilds
- Google MLKit BarcodeScanner on Android (2.2MB model download)
- iOS uses VNDetectBarcodesRequest (native platform APIs)
- Achieves 30fps scanning performance

**Platform-Specific Handling:**
- **Android:** Natively supports UPC-A
- **iOS:** Handles UPC-A as EAN-13; strip leading 0 to convert back
- Custom FPS tuning for performance/accuracy trade-off

**Known Limitations:**
- Struggles with dense formats (Code 128, PDF417) in low light or motion blur
- Device orientation handling can cause crashes on Android
- Some formats have incomplete cross-platform support

**UX Enhancements:**
- On-screen scanning guide overlay
- Visual feedback on code detection
- AR overlays to help user positioning

#### Payload Design: Minimal PII

**Recommended Approach:**
- Encode only **tracking ID or order reference**, not customer details
- Format: `<MERCHANT_CODE><ORDER_ID>` (e.g., `NN-ORD-123456`)
- Keep payload < 100 bytes (minimizes QR code complexity)
- All customer data remains server-side in database
- Scan result used only to reference database record

**Example QR Payload (Compact JSON):**
```json
{
    "o": "NN-20260401-0034",  // order display ID
    "t": "B",                  // tower
    "f": "304",                // flat
    "s": 1                      // scan sequence (anti-replay)
}
```
Total: ~45 bytes → small, robust QR code

---

### Topic 2: PDF Generation & Batch Processing

#### reportlab vs weasyprint Analysis

| Criterion | reportlab | weasyprint | Recommendation |
|-----------|-----------|-----------|------------------|
| **Learning Curve** | Moderate (programmatic API) | Shallow (HTML/CSS) | weasyprint faster initial |
| **Batch Performance** | Faster for large jobs | ~94% slower (unoptimized) | **reportlab wins** |
| **Layout Precision** | Superior for label precision | Good, pagination issues | **reportlab for labels** |
| **Complex Data** | Excellent (tables, flowables) | Adequate for standards | reportlab for structured |
| **Dev Speed (simple)** | Slower initial | 90% faster for basics | weasyprint for simple |
| **Maintenance** | More code, harder modify | HTML/CSS easier maintain | weasyprint easier |

**Conclusion:** For batch label printing (15+ orders per manifest), **reportlab is superior** due to performance and layout precision.

#### Performance Optimization: Critical Finding

**WeasyPrint Pagination Problem:**
- Global pagination model causes severe performance degradation for structured documents
- **Case Study:** 600-product document: 947s → 55s (**94% speed improvement**)
- **Root cause:** Document built in memory before pagination; for large datasets, memory + processing explode

**Batch Processing Best Practices:**

1. **Incremental Writing** (Critical for scale)
   - Stream pages to disk rather than buffer in memory
   - reportlab supports streaming via incremental PDF generation
   - Dramatically reduces memory footprint

2. **Document Optimization**
   - Pre-calculate table widths/heights (avoid dynamic layout)
   - Group similar records together
   - Flatten nested structures

3. **Parallelization**
   - Generate PDFs in parallel for independent orders
   - Connection pooling for batch DB queries
   - Cache QR code/barcode images (avoid regeneration per label)

#### A6 Label Layout Specification

**Physical Dimensions:**
- Size: A6 = 14.8cm × 10.5cm (landscape or portrait)
- Print DPI: 300+ for professional quality
- Margins: 0.3cm minimum on all sides

**Label Content Layout (Portrait A6):**

```
┌──────────────────────────┐
│  [Logo]    [QR Code]     │ ← 3.5cm QR (top)
│            (3.5×3.5cm)   │
├──────────────────────────┤
│ Flat/Tower: B 304        │ ← 0.8cm font
│ Recipient: John Doe      │ ← 0.6cm font
├──────────────────────────┤
│ NammaNeighbor            │ ← Vendor info
│ Order: NN-20260401-0034  │ ← 0.5cm font
│ ┌──────────────────────┐ │
│ │ NN-20260401-0034     │ │ ← Barcode (optional)
│ └──────────────────────┘ │
└──────────────────────────┘
```

**Technical Rendering:**
- Use reportlab's `reportlab.graphics` for vector QR rendering (no interpolation artifacts)
- Set DPI scaling to 300 for print output
- Quiet zone: 0.5cm minimum around QR code

**Image Quality & Scanability:**
- Vector formats (SVG) preferred, PNG fallback at 300+ DPI
- Print quality directly impacts maximum scanning range
- Test printing at actual size before batch production
- Typical scanning distance in sorting: 15-30cm

---

### Topic 3: Parcel Tracking System Architecture

#### Event-Driven State Machine Patterns

**Recommended State Progression:**
```
LABEL_GENERATED
    ↓
PICKED_UP (first scan at seller)
    ↓
IN_TRANSIT
    ↓
AT_COMMUNITY_HUB (scan at gate)
    ↓
OUT_FOR_DELIVERY
    ↓
DELIVERED (final scan with POD photo)

Alternative paths:
    ↓ (anytime)
ATTEMPTED (delivery attempt without photo)
    ↓
HELD_AT_GATE (48h pickup window)
```

**Key Architectural Principles:**
- Events are **immutable** and timestamped
- State machine is the **source of truth** (not a side effect)
- Each event captured in `ScanEvent` with: parcel, status, location, sequence, scanned_by user
- Enable **event sourcing** for complete audit trail (compliance, troubleshooting)
- Notifications triggered by **state transitions**, not separate events

#### django-fsm Best Practices

**Core Implementation Pattern:**
```python
class ParcelStatus(models.TextChoices):
    LABEL_GENERATED = 'label_generated'
    PICKED_UP = 'picked_up'
    # ... other states

class Parcel(TimestampedModel):
    status = FSMField(default=ParcelStatus.LABEL_GENERATED, protected=True)
    
    @transition(
        field=status,
        source=ParcelStatus.LABEL_GENERATED,
        target=ParcelStatus.PICKED_UP
    )
    def mark_picked_up(self):
        # Business logic
        pass
```

**Best Practices:**
1. **protected=True** prevents direct assignment (enforces transition rules)
2. **Transition methods contain business logic** (updating timestamps, sending notifications)
3. **Atomic transactions** wrap transitions (data integrity)
4. **Audit tracking** via `@fsm_log_by` and `@fsm_log_description` decorators
5. **Conditions on transitions** for complex logic
   ```python
   @transition(
       field=status,
       source='in_transit',
       target='at_hub',
       conditions=[check_manifest_exists]
   )
   def arrive_at_hub(self):
       pass
   ```

**Common Pitfalls to Avoid:**
- Don't bypass FSM via direct status assignment
- Don't call multiple @transition methods in one flow
- Always wrap in @transaction.atomic
- Log external IDs (scan device, GPS coords) for troubleshooting

#### Scan Event Logging & Anti-Replay Prevention

**Problem: Distributed Scan Devices**
- Multiple delivery partners with scanning devices
- Network latency/offline scenarios
- Malicious replay attacks

**Idempotency Key Strategy:**
1. Device generates key: `<PARCEL_ID>-<DEVICE_ID>-<TIMESTAMP_MS>`
2. Device sends: scan_data + idempotency_key
3. Server stores processed keys in Redis (TTL: 24 hours)
4. Duplicate key → return cached response (don't reprocess)
5. Client can't detect if response is from cache or fresh processing (identical)

**Sequence Number Anti-Replay:**
- Each parcel has `scan_sequence` counter
- Client sends `scan_sequence = current + 1`
- Server validates: `client_sequence == server_sequence + 1`
- Invalid sequence → reject with 400 "Already scanned"

**Audit Trail Requirements:**

| Requirement | Implementation |
|-------------|-----------------|
| Immutable storage | Append-only logs (no updates/deletes) |
| Cryptographic chaining | Hash each entry with previous entry's hash |
| Verification | `hash(entry_n) = fn(data_n, hash(entry_{n-1}))` |
| Tampering detection | Immediate (hash chain breaks) |
| Standardized format | JSON with consistent field names |
| Centralized logging | Aggregate from all scanning devices |
| Compliance | Enable proof-of-delivery reconstruction |

**ScanEvent Model Structure:**
```python
class ScanEvent(TimestampedModel):
    parcel = ForeignKey(Parcel, on_delete=models.CASCADE)
    scanned_by = ForeignKey(User, on_delete=models.SET_NULL)
    previous_status = CharField(max_length=30)
    new_status = CharField(max_length=30)
    location = CharField(max_length=100)       # "Community Gate", "Tower A"
    scan_sequence = PositiveSmallIntegerField() # 1, 2, 3 (anti-replay)
    pod_photo_s3_key = CharField(blank=True)   # For delivery scans
    device_id = CharField(max_length=50)       # For tracing
    gps_coords = CharField(blank=True)         # Optional: GPS at scan
```

#### Real-Time Status Updates & Notifications

**Trigger Model:**
- **On state transition** (via @transition completion) → send notification
- **Not as separate event** (tight coupling prevents bugs)
- **Asynchronous** via Celery task (don't block HTTP response)

**Notification Content:**
```python
@transition(field=status, ...)
def mark_at_hub(self):
    # ... state change
    # Trigger notification async
    send_fcm_notification.delay(
        user_id=self.order.buyer.id,
        title="Your order has arrived",
        body=f"Order {self.qr_code} is at community gate",
        data={
            "type": "parcel_status",
            "parcel_id": self.qr_code,
            "status": self.status
        }
    )
```

**Real-Time Technology Stack:**
- **Status Push:** WebSocket (web clients) or FCM/APNs (mobile)
- **Async Queue:** Celery tasks for notification sending
- **Cache:** Redis for state caching (<100ms reads)
- **Database:** Parcel status as source of truth

**Notification Triggers:**
- `AT_COMMUNITY_HUB`: "Your order has arrived at the community gate"
- `OUT_FOR_DELIVERY`: "Your order is out for delivery — expect arrival today"
- `DELIVERED`: "Your order has been delivered. Rate your experience"
- `ATTEMPTED`: "We couldn't reach you. We'll return tomorrow — please be available"

**Intelligent Frequency:**
- Batch updates per region (don't notify every single parcel)
- Avoid notification fatigue (max 2-3 per day per customer)
- Smart timing: mid-morning/early evening (avoid overnight notifications)

**Proactive Exception Handling:**
- Delay prediction: if >2 hours late from estimated → send delay notification
- Attempt failure: after 2 failed attempts → escalate to customer service
- Long-held: after 48 hours at gate → send pickup reminder + escalation

**Delivery Accuracy Improvement:**
- ML model to predict delivery window (based on traffic, weather, history)
- Update ETA proactively (vs waiting for manual status updates)
- Learn from past patterns to reduce failed attempts

---

## Synthesis for Logistics Implementation

### Critical Success Factors

1. **QR Code Design**
   - Use ERROR_CORRECT_H (30% damage tolerance)
   - 3-4cm size on A6 label
   - Compact JSON payload (45 bytes) with parcel ID, tower, flat, sequence
   - Matte paper, 300 DPI printing

2. **PDF Label Generation**
   - Use **reportlab** (superior performance + precision)
   - Batch process with incremental writing (memory-efficient)
   - Cache QR code images
   - Target: generate 15-order manifest in <10s

3. **State Machine**
   - Use django-fsm with protected=True
   - 8-state progression: LABEL_GENERATED → PICKED_UP → IN_TRANSIT → AT_COMMUNITY_HUB → OUT_FOR_DELIVERY → DELIVERED
   - Transitions should send notifications async
   - Lock manifest operations with select_for_update()

4. **Anti-Replay Security**
   - Scan sequence counter (server-side source of truth)
   - Idempotency key in Redis (24h TTL)
   - Reject duplicate sequence numbers
   - Log all attempts (fraud detection)

5. **Real-Time Notifications**
   - Trigger on state transitions
   - Send async via Celery
   - Include parcel ID + status in FCM payload
   - Client deep-links to tracking screen

6. **Testing**
   - Factory for Parcel/Manifest creation
   - Test all state transitions (valid + invalid)
   - Test scan replay rejection
   - Test concurrent manifest operations
   - Test async notification sending

### Technology Recommendations

| Component | Technology | Rationale |
|-----------|-----------|-----------|
| QR generation | qrcode[pil] | Standard, battle-tested, minimal dependencies |
| PDF labels | reportlab | Performance + precision for batch printing |
| State machine | django-fsm | Database-level enforcement + transitions |
| Camera scanning | react-native-vision-camera | 30fps, supports Android/iOS natively |
| Async jobs | Celery + Redis | Existing setup, handles queuing + retries |
| Notifications | FCM | Existing integration, cross-platform |
| Storage | S3 | Existing infrastructure, PDFs + POD photos |
| Testing | pytest + factory-boy | Existing setup, factories for fixtures |

