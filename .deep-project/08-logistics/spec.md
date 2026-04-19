# Spec: 08-logistics

## Purpose
Post-MVP. QR code-based parcel tracking, delivery manifest system for consolidated gate entry, proof of delivery, and real-time parcel state machine with push notifications on each scan.

## Dependencies
- **05-ordering-payments** — Order model (parcel is linked to an order)
- **01-foundation** — S3 (POD photos), Celery, push notifications
- **06-mobile-app** — Delivery partner scan UI (new screens added to existing app)

## Key Packages

```
qrcode[pil]==7.4.2   # QR generation with Pillow
Pillow==10.x          # Image rendering for labels
reportlab or weasyprint  # PDF label generation
react-native-vision-camera + vision-camera-code-scanner  # QR scanning (mobile)
```

## Deliverables

### 1. Models

```python
# apps/logistics/models.py

class DeliveryManifest(TimestampedModel):
    community = models.ForeignKey('communities.Community', on_delete=models.CASCADE)
    delivery_date = models.DateField()
    manifest_code = models.CharField(max_length=30, unique=True)  # "MF-20260401-SUNRISE"
    status = models.CharField(
        choices=[
            ('draft', 'Draft'),
            ('dispatched', 'Dispatched'),
            ('at_gate', 'At Community Gate'),
            ('completed', 'Delivery Complete'),
        ],
        max_length=20, default='draft'
    )
    delivery_partner = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    gate_scan_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

class ParcelStatus(models.TextChoices):
    LABEL_GENERATED = 'label_generated', 'Label Generated'
    PICKED_UP = 'picked_up', 'Picked Up from Seller'
    IN_TRANSIT = 'in_transit', 'In Transit'
    AT_COMMUNITY_HUB = 'at_hub', 'At Community Hub'
    OUT_FOR_DELIVERY = 'out_for_delivery', 'Out for Delivery'
    DELIVERED = 'delivered', 'Delivered'
    ATTEMPTED = 'attempted', 'Delivery Attempted'
    HELD_AT_GATE = 'held_at_gate', 'Held at Gate (48h pickup)'

class Parcel(TimestampedModel):
    manifest = models.ForeignKey(DeliveryManifest, on_delete=models.CASCADE,
                                   related_name='parcels')
    order = models.OneToOneField('orders.Order', on_delete=models.CASCADE)
    qr_code = models.CharField(max_length=50, unique=True)   # "NN-20260401-0034"
    status = FSMField(default=ParcelStatus.LABEL_GENERATED, protected=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    pod_photo_s3_key = models.CharField(max_length=500, blank=True)  # Proof of Delivery

class ScanEvent(TimestampedModel):
    parcel = models.ForeignKey(Parcel, on_delete=models.CASCADE, related_name='scan_events')
    scanned_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    previous_status = models.CharField(max_length=30)
    new_status = models.CharField(max_length=30)
    location = models.CharField(max_length=100, blank=True)  # "Community Gate", "Tower A Lobby"
    scan_sequence = models.PositiveSmallIntegerField()  # anti-replay
```

### 2. QR Code Generation

```python
# apps/logistics/services/qr.py
import qrcode
import json
from qrcode.constants import ERROR_CORRECT_H

def generate_parcel_qr(parcel: Parcel) -> bytes:
    """
    Payload: minimal — no PII on printed label.
    Resolve full details server-side on scan.
    """
    payload = json.dumps({
        "o": parcel.qr_code,          # order display ID (short)
        "t": parcel.order.buyer.building.name if parcel.order.buyer.building else "",
        "f": parcel.order.buyer.flat_number,
        "s": parcel.scan_events.count() + 1,  # scan_sequence (anti-replay)
    }, separators=(',', ':'))           # compact JSON

    qr = qrcode.QRCode(
        version=2,
        error_correction=ERROR_CORRECT_H,  # 30% damage tolerance for printed labels
        box_size=10,
        border=4,
    )
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    return buffer.getvalue()
```

### 3. Parcel Label PDF

```
GET /api/v1/orders/{order_id}/label.pdf
Permission: IsOrderVendor | IsDeliveryPartner
```

Generates a printable A6 label (10.5cm × 14.8cm) containing:
- QR code (large, centered)
- Tower / Flat number (large font, visible at 2m)
- Vendor name (for seller dispatch)
- NammaNeighbor logo
- Order ID

Multiple labels can be batch-printed:
```
GET /api/v1/vendors/orders/labels.pdf?date=2026-04-01
```
Generates a multi-page PDF with one label per order for that day.

### 4. Delivery Manifest

```
POST /api/v1/manifests/
Permission: IsDeliveryPartner | IsCommunityAdmin
```
Creates manifest for a community + date, auto-assigns all confirmed orders for that day as parcels. Generates manifest QR code.

Manifest QR payload: `{"m": "MF-20260401-SUNRISE"}` — scanned by delivery partner at gate to register arrival.

```
GET /api/v1/manifests/{manifest_code}/
GET /api/v1/manifests/{manifest_code}/parcels/
```

### 5. QR Scan API

```
POST /api/v1/parcels/scan/
Permission: IsDeliveryPartner
```
Payload:
```json
{
  "qr_data": "{\"o\":\"NN-20260401-0034\",\"t\":\"B\",\"f\":\"304\",\"s\":1}",
  "location": "Community Gate",
  "pod_photo": null   // base64 or null (required for DELIVERED scan)
}
```

Logic:
1. Parse `qr_data`, look up Parcel by `qr_code`
2. Validate `scan_sequence` (must be current_count + 1, prevents replay attacks)
3. Determine next status from current status (state machine)
4. Record ScanEvent
5. If pod_photo present: upload to S3, store key on Parcel
6. Send FCM push to buyer with new status
7. Return: parcel status, buyer flat/tower, resident name (for verbal confirmation)

**Status transitions on scan:**
- First scan (at seller): `LABEL_GENERATED → PICKED_UP`
- Second scan (at community gate): `IN_TRANSIT → AT_COMMUNITY_HUB`
  - Also updates `DeliveryManifest.status = at_gate`, sets `gate_scan_at`
- Third scan (at flat door): `OUT_FOR_DELIVERY → DELIVERED`
  - Requires `pod_photo`
  - Also triggers order delivery confirmation (calls order.mark_delivered())

### 6. Delivery Partner Role

New role: `delivery_partner`. Delivery partners are registered by platform admin (Django Admin). They only have access to:
- `POST /api/v1/parcels/scan/`
- `GET /api/v1/manifests/{manifest_code}/`
- `GET /api/v1/manifests/{manifest_code}/parcels/`

### 7. Mobile App: Scanner Screens (added to split 06 app)

New screens added to the existing React Native app under a "Delivery" role tab:

**ManifestScanScreen:**
- Full-screen camera via `react-native-vision-camera`
- Scans manifest QR at gate → shows all parcels in that manifest
- Manifest parcel checklist (check off each flat as delivered)

**ParcelScanScreen:**
- Scans individual parcel QR
- Shows: Flat/Tower to deliver to, resident name
- "Mark Delivered" → requires photo (expo-image-picker, captures proof)
- "Attempted" button → notes field

### 8. Resident Tracking

```
GET /api/v1/orders/{order_id}/tracking/
Permission: IsOrderBuyer
```
Returns:
```json
{
  "status": "at_hub",
  "status_label": "At Community Hub",
  "scan_events": [
    {"status": "picked_up", "time": "09:15", "location": "Seller location"},
    {"status": "at_hub", "time": "10:45", "location": "Community Gate"}
  ],
  "eta": "Delivery in progress — today"
}
```

## Acceptance Criteria

1. QR code generated for each order is scannable under poor lighting / slight damage (ERROR_CORRECT_H)
2. Scan replay attack rejected: scanning same QR a second time returns 400 ("Already scanned")
3. Parcel status updates from `LABEL_GENERATED → DELIVERED` through all intermediate states in correct order
4. `AT_COMMUNITY_HUB` scan sends FCM push to buyer: "Your order has arrived at the community gate"
5. `DELIVERED` scan requires POD photo — rejected without it (400)
6. PDF label renders correctly on A6 paper with QR visible at 30cm
7. Batch label PDF for a vendor with 15 orders generates within 10s
8. Delivery partner role cannot access any other API endpoints (403)
9. `GET /api/v1/orders/{order_id}/tracking/` shows correct scan history timeline
10. Order's `mark_delivered()` is called automatically on final `DELIVERED` scan (triggering payout release)
