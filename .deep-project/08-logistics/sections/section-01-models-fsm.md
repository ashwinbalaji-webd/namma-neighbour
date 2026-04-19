Now I have all the context I need. Let me generate the section content for `section-01-models-fsm`. This section is foundational - it covers the database schema definitions and state machine setup.

# Section 01: Models and FSM

## Overview

This section implements the core data models for the logistics system and the parcel state machine. These models form the foundation for all downstream API endpoints, scan processing, and notification services.

The three core models are:
1. **DeliveryManifest** - Container for daily parcel delivery routes
2. **Parcel** - Individual shipment with state machine protection
3. **ScanEvent** - Immutable audit trail of status transitions

## Tests First

Before implementing, write these test stubs in `tests/test_models.py` and `tests/test_fsm.py`:

### DeliveryManifest Model Tests

```python
def test_manifest_code_generation():
    """Manifest code follows format MF-{YYYYMMDD}-{SHIFT}"""
    # Should generate unique codes like "MF-20260401-SUNRISE"
    pass

def test_manifest_code_unique_constraint():
    """Manifest codes are database-unique"""
    # Create two manifests with same code → IntegrityError
    pass

def test_manifest_duplicate_community_date():
    """Cannot create duplicate (community, delivery_date)"""
    # Create manifest for (community, date), then attempt duplicate → IntegrityError
    pass

def test_manifest_status_progression():
    """Status progression: draft → dispatched → at_gate → completed"""
    # Cannot skip statuses; backtracking raises error
    pass

def test_manifest_parcels_relationship():
    """Creating manifest creates parcels for confirmed orders"""
    # Manifest creation auto-populates associated parcels
    pass
```

### Parcel Model Tests

```python
def test_parcel_creation_from_order():
    """Parcel created when Order transitions to CONFIRMED"""
    # Requires signal handler on Order model
    pass

def test_parcel_initial_status():
    """Parcel starts in LABEL_GENERATED state"""
    # Default status = LABEL_GENERATED
    pass

def test_parcel_order_one_to_one():
    """Each parcel links 1:1 to order with PROTECT constraint"""
    # order FK is OneToOneField with on_delete=PROTECT
    pass

def test_qr_code_generation():
    """QR code assigned at parcel creation (format: NN-{YYYYMMDD}-{NNNNN})"""
    # Should auto-generate unique QR codes
    pass

def test_qr_code_immutable():
    """QR code is immutable (unique constraint)"""
    # Cannot change qr_code after creation
    pass

def test_parcel_fsm_field():
    """Status is FSMField with protected=True"""
    # Direct assignment raises error; must use FSM methods
    pass

def test_attempt_counter_initialization():
    """delivery_attempt_count initializes to 0"""
    pass

def test_attempt_counter_increment():
    """Increments on ATTEMPTED transition"""
    pass

def test_auto_hold_after_two_attempts():
    """Auto-transition to HELD_AT_GATE after attempt_count >= 2"""
    pass

def test_pod_photo_field():
    """pod_photo_s3_key is CharField, blank=True"""
    # Set only on DELIVERED scans
    pass

def test_parcel_timestamps():
    """created_at immutable, updated_at changes, delivered_at on DELIVERED"""
    pass
```

### ScanEvent Model Tests

```python
def test_scan_event_immutability():
    """ScanEvent is append-only (created_at, never updated)"""
    # Attempting update raises error
    pass

def test_sequence_counter():
    """scan_sequence stores 1, 2, 3, ... (server-side validation)"""
    # Expected sequence = parcel.scan_events.count() + 1
    pass

def test_gps_fields_precision():
    """GPS fields: latitude (9, 6), longitude (10, 6) decimal precision"""
    # gps_accuracy_m stores meters (optional)
    pass

def test_auto_transition_flag():
    """is_auto_transition marks state jumps for audit"""
    # False for normal transitions, True for optimistic jumps
    pass
```

### FSM Transition Tests

```python
def test_label_generated_to_picked_up():
    """LABEL_GENERATED → PICKED_UP transition"""
    # Callable only from LABEL_GENERATED state
    pass

def test_picked_up_to_in_transit_automatic():
    """PICKED_UP → IN_TRANSIT automatic (no explicit method)"""
    # Triggers immediately after parcel created/confirmed
    pass

def test_in_transit_to_at_hub():
    """IN_TRANSIT → AT_COMMUNITY_HUB with manifest updates"""
    # Updates manifest.gate_scan_at (first call only)
    # Updates manifest.status = 'at_gate'
    # Queues notification
    pass

def test_at_hub_to_out_for_delivery_automatic():
    """AT_COMMUNITY_HUB → OUT_FOR_DELIVERY automatic"""
    # Triggered after gate scan, no explicit method
    pass

def test_out_for_delivery_to_delivered():
    """OUT_FOR_DELIVERY → DELIVERED with POD and order.mark_delivered()"""
    # Sets delivered_at = now()
    # Calls order.mark_delivered() with state guards
    # Queues notification
    pass

def test_out_for_delivery_to_attempted():
    """OUT_FOR_DELIVERY → ATTEMPTED (manual action)"""
    # Increments delivery_attempt_count
    # Queues notification
    pass

def test_attempted_to_held_at_gate():
    """ATTEMPTED → HELD_AT_GATE (separate method, triggered after 2 attempts)"""
    # Separate transition method (not inline in mark_attempted)
    # Sets held_at_gate_at = now()
    # Queues notification
    pass

def test_attempted_to_out_for_delivery():
    """ATTEMPTED → OUT_FOR_DELIVERY (retry path)"""
    # Allows retry after failed attempt
    pass

def test_invalid_transitions_rejected():
    """Invalid transitions raise TransitionNotAllowed"""
    # LABEL_GENERATED → AT_COMMUNITY_HUB raises error
    # Any backward transition raises error
    pass

def test_optimistic_jump_in_transit_to_delivered():
    """Optimistic jump IN_TRANSIT → DELIVERED (allowed in scan API)"""
    # Not by FSM directly, but by scan service
    # Creates backfill ScanEvents for missing states
    # All marked with is_auto_transition=True
    pass
```

## Implementation Details

### File Paths to Create/Modify

```
apps/logistics/models.py
apps/logistics/migrations/
  0001_initial.py (auto-generated)
```

### 1. DeliveryManifest Model

**Purpose:** Container for daily parcel delivery routes per community.

**Fields:**
- `community` (FK to Community) — scoped per community
- `delivery_date` (DateField) — immutable
- `manifest_code` (CharField, unique) — e.g., "MF-20260401-SUNRISE"
- `status` (CharField, choices: draft, dispatched, at_gate, completed)
- `delivery_partner` (FK to User, nullable)
- `gate_scan_at` (DateTimeField, nullable) — timestamp of first AT_COMMUNITY_HUB scan
- `completed_at` (DateTimeField, nullable) — finalization time
- `created_at`, `updated_at` (from TimestampedModel mixin)

**Constraints:**
- Unique: `manifest_code`
- Unique: `(community, delivery_date)` (prevents duplicate manifests per day)
- Index: `(community, delivery_date)`
- Index: `community`

**Code stub:**

```python
class DeliveryManifest(TimestampedModel):
    community = models.ForeignKey('communities.Community', on_delete=models.CASCADE)
    delivery_date = models.DateField()
    manifest_code = models.CharField(max_length=50, unique=True)
    status = models.CharField(
        max_length=20,
        choices=[
            ('draft', 'Draft'),
            ('dispatched', 'Dispatched'),
            ('at_gate', 'At Gate'),
            ('completed', 'Completed'),
        ],
        default='draft'
    )
    delivery_partner = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True)
    gate_scan_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [['community', 'delivery_date']]
        indexes = [
            models.Index(fields=['community', 'delivery_date']),
            models.Index(fields=['community']),
        ]

    def __str__(self):
        return f"{self.manifest_code} ({self.delivery_date})"
```

### 2. Parcel Model

**Purpose:** Individual shipment linked 1:1 to an order, with FSM-protected status.

**Fields:**
- `manifest` (FK to DeliveryManifest, nullable initially)
- `order` (OneToOneField to Order)
- `community` (FK to Community) — denormalized from order.buyer.community
- `qr_code` (CharField, unique) — e.g., "NN-20260401-0034"
- `status` (FSMField, default=LABEL_GENERATED, protected=True)
- `delivered_at` (DateTimeField, nullable)
- `pod_photo_s3_key` (CharField, nullable)
- `delivery_attempt_count` (PositiveSmallIntegerField, default=0)
- `held_at_gate_at` (DateTimeField, nullable) — set on HELD_AT_GATE
- `created_at`, `updated_at`

**Constraints:**
- `order` uses on_delete=models.PROTECT (audit trail protection)
- Unique: `qr_code`
- Index: `(manifest, status)` for manifest summary queries
- Index: `community` for resident queries
- Index: `order_id` (implicit from OneToOne)

**Code stub:**

```python
from django_fsm import FSMField, transition

class Parcel(TimestampedModel):
    LABEL_GENERATED = 'label_generated'
    PICKED_UP = 'picked_up'
    IN_TRANSIT = 'in_transit'
    AT_COMMUNITY_HUB = 'at_community_hub'
    OUT_FOR_DELIVERY = 'out_for_delivery'
    DELIVERED = 'delivered'
    ATTEMPTED = 'attempted'
    HELD_AT_GATE = 'held_at_gate'

    STATUS_CHOICES = [
        (LABEL_GENERATED, 'Label Generated'),
        (PICKED_UP, 'Picked Up'),
        (IN_TRANSIT, 'In Transit'),
        (AT_COMMUNITY_HUB, 'At Community Hub'),
        (OUT_FOR_DELIVERY, 'Out for Delivery'),
        (DELIVERED, 'Delivered'),
        (ATTEMPTED, 'Delivery Attempted'),
        (HELD_AT_GATE, 'Held at Gate'),
    ]

    manifest = models.ForeignKey(DeliveryManifest, on_delete=models.CASCADE, related_name='parcels', null=True, blank=True)
    order = models.OneToOneField('orders.Order', on_delete=models.PROTECT)
    community = models.ForeignKey('communities.Community', on_delete=models.CASCADE)
    qr_code = models.CharField(max_length=50, unique=True)
    status = FSMField(default=LABEL_GENERATED, protected=True, choices=STATUS_CHOICES)
    delivered_at = models.DateTimeField(null=True, blank=True)
    pod_photo_s3_key = models.CharField(max_length=255, blank=True)
    delivery_attempt_count = models.PositiveSmallIntegerField(default=0)
    held_at_gate_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['manifest', 'status']),
            models.Index(fields=['community']),
        ]

    def __str__(self):
        return f"Parcel {self.qr_code} ({self.status})"

    @transition(field=status, source=LABEL_GENERATED, target=PICKED_UP)
    def mark_picked_up(self):
        """Transition to PICKED_UP (first scan at seller)"""
        pass

    @transition(field=status, source=IN_TRANSIT, target=AT_COMMUNITY_HUB)
    def mark_at_hub(self):
        """Transition to AT_COMMUNITY_HUB (gate scan, updates manifest)"""
        pass

    @transition(field=status, source=OUT_FOR_DELIVERY, target=DELIVERED)
    def mark_delivered(self):
        """Transition to DELIVERED (final delivery scan with POD)"""
        self.delivered_at = timezone.now()

    @transition(field=status, source=OUT_FOR_DELIVERY, target=ATTEMPTED)
    def mark_attempted(self):
        """Transition to ATTEMPTED (delivery failed, retry)"""
        self.delivery_attempt_count += 1

    @transition(field=status, source=ATTEMPTED, target=HELD_AT_GATE)
    def mark_held_at_gate(self):
        """Transition to HELD_AT_GATE (after 2 failed attempts)"""
        self.held_at_gate_at = timezone.now()

    @transition(field=status, source=ATTEMPTED, target=OUT_FOR_DELIVERY)
    def retry_delivery(self):
        """Return to OUT_FOR_DELIVERY for retry after ATTEMPTED"""
        pass
```

**Important Notes:**
- Automatic transitions (PICKED_UP → IN_TRANSIT, AT_COMMUNITY_HUB → OUT_FOR_DELIVERY) are NOT implemented as FSM methods. Instead, the scan service logic will handle these transitions directly using raw state updates in the database (or via a separate service method).
- Optimistic jumps (IN_TRANSIT → DELIVERED) are handled in the scan service, not in the FSM. The scan service creates backfill ScanEvents for audit.

### 3. ScanEvent Model

**Purpose:** Immutable audit trail of parcel status transitions.

**Fields:**
- `parcel` (FK to Parcel)
- `scanned_by` (FK to User, nullable)
- `previous_status` (CharField)
- `new_status` (CharField)
- `location` (CharField, blank=True)
- `scan_sequence` (PositiveSmallIntegerField) — 1, 2, 3, ...
- `pod_photo_s3_key` (CharField, blank=True)
- `device_id` (CharField, blank=True)
- `gps_latitude` (DecimalField(max_digits=9, decimal_places=6), nullable)
- `gps_longitude` (DecimalField(max_digits=10, decimal_places=6), nullable)
- `gps_accuracy_m` (IntegerField, nullable)
- `is_auto_transition` (BooleanField, default=False)
- `created_at` (DateTimeField, immutable)
- `updated_at` (DateTimeField, never changes)

**Constraints:**
- Immutable: no updates after creation
- Index: `(parcel, created_at)` for chronological timeline
- Index: `(scanned_by, created_at)` for delivery partner activity

**Code stub:**

```python
class ScanEvent(models.Model):
    parcel = models.ForeignKey(Parcel, on_delete=models.CASCADE, related_name='scan_events')
    scanned_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True)
    previous_status = models.CharField(max_length=50)
    new_status = models.CharField(max_length=50)
    location = models.CharField(max_length=255, blank=True)
    scan_sequence = models.PositiveSmallIntegerField()
    pod_photo_s3_key = models.CharField(max_length=255, blank=True)
    device_id = models.CharField(max_length=255, blank=True)
    gps_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    gps_longitude = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True)
    gps_accuracy_m = models.IntegerField(null=True, blank=True)
    is_auto_transition = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now_add=True)  # Never updates

    class Meta:
        indexes = [
            models.Index(fields=['parcel', 'created_at']),
            models.Index(fields=['scanned_by', 'created_at']),
        ]

    def __str__(self):
        return f"Scan {self.parcel.qr_code}: {self.previous_status} → {self.new_status}"

    def save(self, *args, **kwargs):
        """Enforce immutability: ScanEvent is append-only"""
        if self.pk is not None:
            raise ValueError("ScanEvent cannot be updated after creation")
        super().save(*args, **kwargs)
```

### 4. Signal Handler for Parcel Creation

When an Order transitions to CONFIRMED status, a Parcel should be auto-created.

**Code stub** (`apps/logistics/signals.py`):

```python
from django.db.models.signals import post_save
from django.dispatch import receiver
from orders.models import Order
from logistics.models import Parcel

@receiver(post_save, sender=Order)
def create_parcel_on_order_confirmed(sender, instance, created, **kwargs):
    """
    Create a Parcel when Order reaches CONFIRMED status.
    
    Parcel starts in LABEL_GENERATED state and receives manifest_id
    when assigned to a DeliveryManifest during manifest creation.
    """
    if instance.status == Order.CONFIRMED:
        # Generate QR code: NN-{YYYYMMDD}-{NNNNN}
        qr_code = generate_qr_code(instance)
        
        Parcel.objects.get_or_create(
            order=instance,
            defaults={
                'qr_code': qr_code,
                'community': instance.buyer.community,
                'status': Parcel.LABEL_GENERATED,
            }
        )

def generate_qr_code(order):
    """Generate unique QR code for order"""
    # Format: NN-{YYYYMMDD}-{NNNNN}
    # Example: NN-20260401-00123
    pass
```

**Register signal in** `apps/logistics/apps.py`:

```python
class LogisticsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.logistics'

    def ready(self):
        import apps.logistics.signals
```

## State Machine Overview

The parcel state machine follows this progression:

```
LABEL_GENERATED
    ↓ (first scan at seller)
PICKED_UP
    ↓ (automatic)
IN_TRANSIT
    ↓ (scan at gate)
AT_COMMUNITY_HUB
    ↓ (automatic)
OUT_FOR_DELIVERY
    ├─ ↓ (final scan with POD)
    │  DELIVERED ✓
    │
    └─ ↓ (delivery attempt fails)
       ATTEMPTED
       ├─ ↓ (retry)
       │  OUT_FOR_DELIVERY (loop back)
       │
       └─ → HELD_AT_GATE (after 2 attempts)
```

**Key Notes:**
- Automatic transitions (PICKED_UP → IN_TRANSIT, AT_COMMUNITY_HUB → OUT_FOR_DELIVERY) are not FSM methods. The scan service will handle these explicitly.
- Optimistic jumps (e.g., IN_TRANSIT → DELIVERED) are allowed by the scan service, not the FSM. The scan service creates backfill ScanEvents for audit trail.
- ATTEMPTED → HELD_AT_GATE is a separate method, triggered when `delivery_attempt_count >= 2` (not automatic).

## Integration Dependencies

**Upstream:**
- **05-ordering-payments:** Order model must exist with CONFIRMED status
- **Communities:** Community model must exist

**Downstream (implemented in later sections):**
- Section 02 (QR/Labels): Uses Parcel.qr_code
- Section 03 (Manifest API): Creates DeliveryManifest and assigns parcels
- Section 04 (Scan Core): Calls FSM transitions, creates ScanEvents
- Section 05 (Notifications): Reads parcel status to determine message type

## Database Indexes & Performance

The following indexes optimize common query patterns:

1. **`(community, delivery_date)`** on DeliveryManifest — for daily manifest listing
2. **`(manifest, status)`** on Parcel — for manifest summary counts
3. **`community`** on Parcel — for resident tracking queries
4. **`(parcel, created_at)`** on ScanEvent — for timeline display
5. **`(scanned_by, created_at)`** on ScanEvent — for delivery partner activity reports

## Testing Execution

Run tests with:
```bash
uv run pytest tests/test_models.py tests/test_fsm.py -v
```

Tests should start RED (failing) until implementation is complete. Use pytest-django's `@pytest.mark.django_db` for database access in tests.

## Summary

This section establishes the data model foundation:
- **DeliveryManifest:** Represents daily delivery route containers
- **Parcel:** Individual shipment with FSM-protected state
- **ScanEvent:** Immutable audit trail of transitions

All three models are fully indexed for query performance, and the Parcel state machine is guarded by django-fsm to prevent invalid transitions. Automatic transitions and optimistic jumps are handled by the scan service layer (Section 04), not by the FSM itself.