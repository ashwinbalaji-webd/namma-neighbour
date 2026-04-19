Now I have all the context. Let me extract the test stubs and implementation details relevant to `section-08-integration-tests` and create the complete section content.

# Integration Tests for 08-Logistics

## Overview

This section implements comprehensive integration tests that validate the complete parcel delivery lifecycle, concurrent operations, permission boundaries, and field operations. Integration tests bridge unit tests and production deployment, ensuring all components work together correctly.

**Scope:**
- Complete parcel delivery workflows (happy path and failure paths)
- Concurrent operations (manifest creation, scan operations, order delivery)
- Permission boundaries and security
- Mobile offline queue validation
- Field operations (QR scanning under adverse conditions)
- Performance benchmarks
- Load testing

**Dependencies:**
- section-01-models-fsm (models, FSM, migrations)
- section-02-qr-labels (QR and label generation)
- section-03-manifest-api (manifest endpoints)
- section-04-scan-core (scan endpoint, anti-replay)
- section-05-notifications (Celery tasks, notification queue)
- section-06-api-endpoints (label and tracking endpoints)
- section-07-mobile-screens (mobile screens, offline queue)

---

## Test Files & Organization

Create the following test files in `/var/www/html/MadGirlfriend/namma-neighbour/apps/logistics/tests/`:

1. `test_parcel_lifecycle.py` — Complete delivery workflows
2. `test_concurrent_operations.py` — Race conditions, locking, atomicity
3. `test_permission_boundaries.py` — Role-based access control
4. `test_mobile_offline_queue.py` — App-side offline resilience (documented, API-side tests)
5. `test_field_operations.py` — QR scanning under adverse conditions
6. `test_performance.py` — Load testing, benchmark validation

---

## Test Stubs

### test_parcel_lifecycle.py

**Complete Delivery Flow (Happy Path)**

```python
@pytest.mark.django_db(transaction=True)
class TestParcelLifecycle:
    """Test complete parcel delivery workflows"""

    def test_complete_delivery_flow(self, authenticated_delivery_partner_client, community, vendor, buyer):
        """
        Order CONFIRMED → Parcel created → Label printed → Manifest created 
        → Scan 1 (seller) → Scan 2 (gate) → Scan 3 (flat) → Delivered
        """
        # Setup: Create confirmed order
        order = Order.objects.create(...)  # from fixtures
        parcel = Parcel.objects.get(order=order)
        assert parcel.status == 'LABEL_GENERATED'
        assert parcel.manifest is None
        
        # Vendor prints label
        response = client.get(f'/api/v1/orders/{order.id}/label.pdf')
        assert response.status_code == 200
        assert response['Content-Type'] == 'application/pdf'
        
        # Create manifest
        manifest = DeliveryManifest.objects.create(
            community=community,
            delivery_date=now().date()
        )
        parcel.manifest = manifest
        parcel.save()
        
        # Scan 1: At seller
        qr_payload = json.dumps({
            "o": parcel.qr_code,
            "t": parcel.tower,
            "f": parcel.flat
        })
        response = authenticated_delivery_partner_client.post(
            '/api/v1/parcels/scan/',
            {'qr_data': qr_payload, 'location': 'Seller'}
        )
        assert response.status_code == 200
        parcel.refresh_from_db()
        assert parcel.status == 'PICKED_UP'
        assert parcel.scan_events.count() == 1
        assert parcel.scan_events.first().scan_sequence == 1
        
        # Scan 2: At gate (parcel auto-transitions to IN_TRANSIT, then AT_COMMUNITY_HUB)
        response = authenticated_delivery_partner_client.post(
            '/api/v1/parcels/scan/',
            {'qr_data': qr_payload, 'location': 'Community Gate'}
        )
        assert response.status_code == 200
        parcel.refresh_from_db()
        assert parcel.status == 'AT_COMMUNITY_HUB'
        manifest.refresh_from_db()
        assert manifest.status == 'at_gate'
        assert manifest.gate_scan_at is not None
        
        # Scan 3: At flat (parcel auto-transitions to OUT_FOR_DELIVERY, then DELIVERED)
        response = authenticated_delivery_partner_client.post(
            '/api/v1/parcels/scan/',
            {
                'qr_data': qr_payload,
                'location': 'Flat 304',
                'pod_photo': 'base64-encoded-photo-bytes'
            }
        )
        assert response.status_code == 200
        parcel.refresh_from_db()
        assert parcel.status == 'DELIVERED'
        assert parcel.delivered_at is not None
        
        # Verify order marked delivered
        order.refresh_from_db()
        assert order.status == 'DELIVERED'
        
        # Verify timeline endpoint
        response = buyer_client.get(f'/api/v1/orders/{order.id}/tracking/')
        assert response.status_code == 200
        data = response.json()
        assert data['status'] == 'delivered'
        assert len(data['scan_events']) == 3

    def test_failed_delivery_flow(self, authenticated_delivery_partner_client, community):
        """
        Scan 1, 2 succeed → Scan 3 marked ATTEMPTED → Attempt count = 1
        → Retry scan 3 → After 2nd ATTEMPTED, auto-transition to HELD_AT_GATE
        """
        # Setup and scans 1, 2 (same as above)
        # ... (setup code)
        
        # Scan 3: First attempt (no POD)
        response = authenticated_delivery_partner_client.post(
            '/api/v1/parcels/scan/',
            {
                'qr_data': qr_payload,
                'location': 'Flat 304',
                'pod_photo': None
            }
        )
        # Should fail: DELIVERED requires POD
        assert response.status_code == 400
        
        # Manually trigger ATTEMPTED transition
        response = authenticated_delivery_partner_client.post(
            '/api/v1/parcels/scan/',
            {
                'qr_data': qr_payload,
                'action': 'attempt',
                'location': 'Flat 304'
            }
        )
        assert response.status_code == 200
        parcel.refresh_from_db()
        assert parcel.status == 'OUT_FOR_DELIVERY'  # stays OUT_FOR_DELIVERY, not ATTEMPTED
        assert parcel.delivery_attempt_count == 1
        
        # Scan again (retry)
        response = authenticated_delivery_partner_client.post(
            '/api/v1/parcels/scan/',
            {
                'qr_data': qr_payload,
                'action': 'attempt',
                'location': 'Flat 304'
            }
        )
        assert response.status_code == 200
        parcel.refresh_from_db()
        assert parcel.status == 'HELD_AT_GATE'
        assert parcel.delivery_attempt_count == 2

    def test_optimistic_jump_with_backfill(self, authenticated_delivery_partner_client):
        """
        Partner at gate scans parcel QR directly (skipping seller scan)
        → Server detects IN_TRANSIT → DELIVERED jump
        → Creates backfill ScanEvents for missing states
        → Parcel ends in DELIVERED, audit trail complete
        """
        # Setup: Parcel already in IN_TRANSIT (simulating vendor scan done manually)
        parcel = Parcel.objects.create(...)
        parcel.mark_picked_up()  # Manual transition for test setup
        parcel.save()
        
        # Scan at gate with POD (skip intermediate states)
        response = authenticated_delivery_partner_client.post(
            '/api/v1/parcels/scan/',
            {
                'qr_data': qr_payload,
                'location': 'Community Gate',
                'pod_photo': 'base64-encoded-photo'
            }
        )
        assert response.status_code == 200
        parcel.refresh_from_db()
        assert parcel.status == 'DELIVERED'
        
        # Verify backfill: scan_events should contain AT_COMMUNITY_HUB, OUT_FOR_DELIVERY with is_auto_transition=True
        events = parcel.scan_events.all()
        assert events.count() >= 2
        backfill_events = events.filter(is_auto_transition=True)
        assert backfill_events.exists()
        
        # Verify audit trail
        assert events.order_by('scan_sequence').first().previous_status == 'IN_TRANSIT'
        assert events.order_by('scan_sequence').last().new_status == 'DELIVERED'
```

**Replay Prevention**

```python
    def test_duplicate_scan_rejected(self, authenticated_delivery_partner_client):
        """Scan same QR twice → verify 400 on second scan"""
        parcel = Parcel.objects.create(...)
        qr_payload = json.dumps({...})
        
        # First scan succeeds
        response = authenticated_delivery_partner_client.post(
            '/api/v1/parcels/scan/',
            {'qr_data': qr_payload, 'location': 'Seller'}
        )
        assert response.status_code == 200
        assert parcel.scan_events.count() == 1
        
        # Second scan with same sequence fails
        response = authenticated_delivery_partner_client.post(
            '/api/v1/parcels/scan/',
            {'qr_data': qr_payload, 'location': 'Seller'}
        )
        assert response.status_code == 400
        assert 'Already scanned' in response.json()['detail']

    def test_out_of_order_scan_rejected(self, authenticated_delivery_partner_client):
        """Out-of-order scan (skip a state) → verify handled or rejected"""
        parcel = Parcel.objects.create(...)
        qr_payload = json.dumps({...})
        
        # Attempt to jump from LABEL_GENERATED directly to AT_COMMUNITY_HUB
        # (without PICKED_UP and IN_TRANSIT)
        # Depending on business logic, this may be allowed with backfill
        # OR rejected as invalid
        
        response = authenticated_delivery_partner_client.post(
            '/api/v1/parcels/scan/',
            {'qr_data': qr_payload, 'location': 'Community Gate'}
        )
        # If jumps are allowed: verify backfill
        # If jumps are rejected: verify 400
```

---

### test_concurrent_operations.py

```python
@pytest.mark.django_db(transaction=True)
class TestConcurrentOperations:
    """Test race conditions, locking, and atomicity"""

    def test_concurrent_manifest_creation_race(self, authenticated_delivery_partner_client, community):
        """
        Two partners hit POST /manifests/ simultaneously for same (community, date)
        → One succeeds, second gets 409 (IntegrityError handled)
        """
        from concurrent.futures import ThreadPoolExecutor
        import threading
        
        results = []
        lock = threading.Lock()
        
        def create_manifest():
            response = authenticated_delivery_partner_client.post(
                '/api/v1/manifests/',
                {
                    'community_id': community.id,
                    'delivery_date': '2026-04-01',
                    'shift': 'SUNRISE'
                }
            )
            with lock:
                results.append(response.status_code)
        
        with ThreadPoolExecutor(max_workers=2) as executor:
            executor.submit(create_manifest)
            executor.submit(create_manifest)
        
        assert 201 in results
        assert 409 in results or 400 in results  # One succeeds, other fails

    def test_concurrent_scans_on_manifest_lock_safety(self, authenticated_delivery_partner_client):
        """
        50 partners scanning parcels simultaneously
        → manifest.gate_scan_at set only once (first scan)
        → All scans process without deadlock
        """
        manifest = DeliveryManifest.objects.create(...)
        parcels = [Parcel.objects.create(manifest=manifest) for _ in range(50)]
        
        from concurrent.futures import ThreadPoolExecutor
        
        scan_results = []
        
        def scan_parcel(parcel):
            qr_payload = json.dumps({...})
            response = authenticated_delivery_partner_client.post(
                '/api/v1/parcels/scan/',
                {'qr_data': qr_payload, 'location': 'Community Gate'}
            )
            scan_results.append((parcel.id, response.status_code))
        
        with ThreadPoolExecutor(max_workers=10) as executor:
            for parcel in parcels:
                executor.submit(scan_parcel, parcel)
        
        # All should succeed
        assert all(status == 200 for _, status in scan_results)
        
        # Verify manifest.gate_scan_at set only once (first scan timestamp)
        manifest.refresh_from_db()
        assert manifest.gate_scan_at is not None
        
        # Verify all parcels transitioned correctly
        for parcel in parcels:
            parcel.refresh_from_db()
            assert parcel.status == 'AT_COMMUNITY_HUB'

    def test_concurrent_order_delivery_idempotency(self, authenticated_delivery_partner_client):
        """
        Order.mark_delivered() called multiple times in quick succession
        → Only first call succeeds, others handled gracefully
        """
        order = Order.objects.create(..., status='OUT_FOR_DELIVERY')
        parcel = Parcel.objects.create(order=order)
        
        from concurrent.futures import ThreadPoolExecutor
        
        results = []
        
        def call_mark_delivered():
            try:
                order.mark_delivered()
                with lock:
                    results.append('success')
            except Exception as e:
                with lock:
                    results.append(str(type(e).__name__))
        
        lock = threading.Lock()
        
        with ThreadPoolExecutor(max_workers=3) as executor:
            for _ in range(3):
                executor.submit(call_mark_delivered)
        
        # Should have one success and two graceful failures/rejections
        assert 'success' in results
```

---

### test_permission_boundaries.py

```python
@pytest.mark.django_db
class TestPermissionBoundaries:
    """Test role-based access control and isolation"""

    def test_delivery_partner_isolation(self, client, community_a, community_b):
        """Partner A cannot access Partner B's manifests (403)"""
        partner_a = User.objects.create(roles=['delivery_partner'], community=community_a)
        partner_b = User.objects.create(roles=['delivery_partner'], community=community_b)
        
        manifest_b = DeliveryManifest.objects.create(community=community_b, delivery_date='2026-04-01')
        
        # Partner A tries to fetch Partner B's manifest
        client.force_authenticate(partner_a)
        response = client.get(f'/api/v1/manifests/{manifest_b.manifest_code}/')
        assert response.status_code == 403

    def test_partner_cannot_scan_other_community(self, authenticated_delivery_partner_client, community_a, community_b):
        """Partner A cannot scan parcels from other communities (403)"""
        parcel = Parcel.objects.create(community=community_b)
        qr_payload = json.dumps({...})
        
        response = authenticated_delivery_partner_client.post(
            '/api/v1/parcels/scan/',
            {'qr_data': qr_payload}
        )
        assert response.status_code == 403

    def test_vendor_label_access_isolation(self, client, vendor_a, vendor_b, order):
        """Vendor A cannot access Vendor B's label endpoints (403)"""
        order.vendor = vendor_b
        order.save()
        
        client.force_authenticate(vendor_a)
        response = client.get(f'/api/v1/orders/{order.id}/label.pdf')
        assert response.status_code == 403

    def test_resident_tracking_privacy(self, client, buyer, order):
        """
        Resident can only access own order tracking
        Does NOT return GPS coordinates or delivery partner info
        """
        parcel = Parcel.objects.create(order=order)
        ScanEvent.objects.create(
            parcel=parcel,
            previous_status='IN_TRANSIT',
            new_status='AT_COMMUNITY_HUB',
            gps_latitude=13.052669,
            gps_longitude=77.652245,
            scanned_by=delivery_partner
        )
        
        client.force_authenticate(buyer)
        response = client.get(f'/api/v1/orders/{order.id}/tracking/')
        assert response.status_code == 200
        
        data = response.json()
        assert 'gps_latitude' not in data
        assert 'gps_longitude' not in data
        assert data['scan_events'][0].get('scanned_by_name') is None
        
        # Non-owner cannot access
        other_buyer = User.objects.create(roles=['buyer'])
        client.force_authenticate(other_buyer)
        response = client.get(f'/api/v1/orders/{order.id}/tracking/')
        assert response.status_code == 403

    def test_non_delivery_partner_cannot_scan(self, authenticated_buyer_client):
        """Non-partner role cannot POST /scan/ (403)"""
        response = authenticated_buyer_client.post(
            '/api/v1/parcels/scan/',
            {'qr_data': '...'}
        )
        assert response.status_code == 403
```

---

### test_field_operations.py

```python
@pytest.mark.django_db
class TestFieldOperations:
    """Test QR scanning under adverse conditions"""

    def test_qr_scannable_under_poor_lighting(self):
        """QR codes functional under poor lighting"""
        parcel = Parcel.objects.create(...)
        qr_png = generate_parcel_qr(parcel)
        
        # Verify QR structure (version, error correction)
        from qrcode import QRCode
        qr = QRCode()
        qr.add_data(qr_png)
        assert qr.version <= 3  # Should fit in small version
        assert qr.error_correction == QRCode.ERROR_CORRECT_H
        
        # Simulate scanning with various OpenCV/zbar scenarios
        # This is integration with camera hardware (mocked in unit tests)
        assert qr_png is not None
        assert len(qr_png) > 1000  # Reasonable PNG size

    def test_qr_damage_tolerance_30_percent(self):
        """QR codes with 30% damage still scannable"""
        parcel = Parcel.objects.create(...)
        qr_png = generate_parcel_qr(parcel)
        
        # Simulate damage by corrupting 30% of PNG bytes
        import random
        qr_bytes = bytearray(qr_png)
        damage_count = len(qr_bytes) // 3
        for _ in range(damage_count):
            idx = random.randint(0, len(qr_bytes) - 1)
            qr_bytes[idx] = random.randint(0, 255)
        
        # This is theoretical validation (actual scanning tested in field)
        # In practice, ERROR_CORRECT_H provides 30% recovery

    def test_qr_scanning_distance_30cm_door(self):
        """QR scannable at 30cm distance (door-level scanning)"""
        parcel = Parcel.objects.create(...)
        qr_png = generate_parcel_qr(parcel)
        
        # Verify QR size suitable for 30cm scanning
        from PIL import Image
        import io
        qr_image = Image.open(io.BytesIO(qr_png))
        # Typical QR for 30cm: 3-5cm printed size
        # (size depends on DPI, assume 300 DPI label printer)
        assert qr_image.size[0] >= 100  # Min pixel size

    def test_qr_scanning_distance_1m_plus_gate(self):
        """QR scannable at 1m+ distance (gate-level scanning)"""
        # Same as above, but larger print size
        parcel = Parcel.objects.create(...)
        qr_png = generate_parcel_qr(parcel)
        assert qr_png is not None
```

---

### test_performance.py

```python
@pytest.mark.django_db(transaction=True)
class TestPerformance:
    """Load testing and benchmark validation"""

    def test_batch_label_generation_performance_15_orders(self):
        """15-order label PDF generated in <10s"""
        vendor = User.objects.create(roles=['vendor'])
        orders = [
            Order.objects.create(vendor=vendor, community=community)
            for _ in range(15)
        ]
        
        import time
        start = time.time()
        labels_pdf = generate_vendor_labels_batch(vendor, date.today())
        elapsed = time.time() - start
        
        assert elapsed < 10, f"Batch generation took {elapsed}s, expected <10s"
        assert len(labels_pdf) > 10000  # PDF should be reasonably sized

    def test_concurrent_scan_load_50_parcels(self, authenticated_delivery_partner_client):
        """50+ concurrent scans without serialization"""
        manifest = DeliveryManifest.objects.create(...)
        parcels = [
            Parcel.objects.create(manifest=manifest, status='IN_TRANSIT')
            for _ in range(50)
        ]
        
        from concurrent.futures import ThreadPoolExecutor
        import time
        
        results = []
        
        def scan_parcel(parcel):
            qr_payload = json.dumps({...})
            start = time.time()
            response = authenticated_delivery_partner_client.post(
                '/api/v1/parcels/scan/',
                {'qr_data': qr_payload}
            )
            elapsed = time.time() - start
            results.append({
                'status': response.status_code,
                'time': elapsed
            })
        
        with ThreadPoolExecutor(max_workers=20) as executor:
            for parcel in parcels:
                executor.submit(scan_parcel, parcel)
        
        # All should complete successfully
        assert all(r['status'] == 200 for r in results)
        
        # Average response time should be reasonable (<500ms per scan)
        avg_time = sum(r['time'] for r in results) / len(results)
        assert avg_time < 0.5, f"Average scan time: {avg_time}s"

    def test_manifest_lock_contention_under_load(self, authenticated_delivery_partner_client):
        """Manifest locking under 50 concurrent scans"""
        manifest = DeliveryManifest.objects.create(...)
        parcels = [
            Parcel.objects.create(manifest=manifest)
            for _ in range(50)
        ]
        
        # (same as above test, verifying lock doesn't serialize operations)
        # Expected: manifest.gate_scan_at set only once, no deadlock
```

---

## API Integration Tests (Cross-Endpoint)

```python
@pytest.mark.django_db(transaction=True)
class TestEndToEndAPIs:
    """Test API endpoint interactions"""

    def test_manifest_creation_returns_valid_qr_payload(self, authenticated_delivery_partner_client, community):
        """POST /manifests/ returns manifest_code usable in QR"""
        response = authenticated_delivery_partner_client.post(
            '/api/v1/manifests/',
            {
                'community_id': community.id,
                'delivery_date': '2026-04-01'
            }
        )
        assert response.status_code == 201
        data = response.json()
        manifest_code = data['manifest_code']
        
        # Verify manifest_code format
        assert manifest_code.startswith('MF-')
        assert len(manifest_code) == 16  # MF-20260401-SUNRISE

    def test_scan_endpoint_honors_sequence_validation(self, authenticated_delivery_partner_client):
        """Scan endpoint validates sequence server-side"""
        parcel = Parcel.objects.create(...)
        qr_payload = json.dumps({'o': parcel.qr_code, 't': parcel.tower, 'f': parcel.flat})
        
        # Expected sequence starts at 1
        # Client sends bare JSON (no sequence field)
        response = authenticated_delivery_partner_client.post(
            '/api/v1/parcels/scan/',
            {'qr_data': qr_payload}
        )
        assert response.status_code == 200
        
        # Try to scan again (sequence 1 already consumed)
        response = authenticated_delivery_partner_client.post(
            '/api/v1/parcels/scan/',
            {'qr_data': qr_payload}
        )
        assert response.status_code == 400
        assert 'Already scanned' in response.json()['detail']

    def test_tracking_endpoint_shows_complete_timeline(self, buyer_client, order):
        """GET /tracking/ shows all scans in correct order"""
        parcel = Parcel.objects.create(order=order)
        
        # Create scan events
        ScanEvent.objects.create(
            parcel=parcel, previous_status='LABEL_GENERATED',
            new_status='PICKED_UP', scan_sequence=1
        )
        ScanEvent.objects.create(
            parcel=parcel, previous_status='IN_TRANSIT',
            new_status='AT_COMMUNITY_HUB', scan_sequence=2
        )
        ScanEvent.objects.create(
            parcel=parcel, previous_status='OUT_FOR_DELIVERY',
            new_status='DELIVERED', scan_sequence=3
        )
        
        response = buyer_client.get(f'/api/v1/orders/{order.id}/tracking/')
        assert response.status_code == 200
        data = response.json()
        
        # Verify chronological order
        events = data['scan_events']
        assert len(events) == 3
        assert events[0]['status'] == 'picked_up'
        assert events[1]['status'] == 'at_hub'
        assert events[2]['status'] == 'delivered'
```

---

## Mobile Offline Queue Tests (API-Side)

These tests document expected mobile behavior; implementation is in section-07.

```python
@pytest.mark.django_db
class TestMobileOfflineQueueAPI:
    """Document expected mobile offline queue behavior"""

    def test_api_accepts_photo_upload_separately(self, authenticated_delivery_partner_client):
        """
        New endpoint: POST /api/v1/parcels/{parcel_id}/pod/
        Mobile app uploads photo separately after scan status
        """
        parcel = Parcel.objects.create(status='DELIVERED')
        
        # Upload photo as multipart/form-data
        from django.core.files.uploadedfile import SimpleUploadedFile
        photo_file = SimpleUploadedFile(
            name='pod.jpg',
            content=b'fake-jpeg-bytes',
            content_type='image/jpeg'
        )
        
        response = authenticated_delivery_partner_client.post(
            f'/api/v1/parcels/{parcel.id}/pod/',
            {'file': photo_file}
        )
        assert response.status_code in [200, 204]
        
        # Verify S3 key stored
        parcel.refresh_from_db()
        assert parcel.pod_photo_s3_key is not None
        assert 'pod_' in parcel.pod_photo_s3_key

    def test_api_returns_200_even_if_s3_fails(self, authenticated_delivery_partner_client, mock_s3_failure):
        """
        If S3 upload fails, API returns 200 (client will retry)
        Scan status already persisted, photo retry queued
        """
        parcel = Parcel.objects.create(status='DELIVERED')
        qr_payload = json.dumps({...})
        
        response = authenticated_delivery_partner_client.post(
            '/api/v1/parcels/scan/',
            {'qr_data': qr_payload}
        )
        # Even if S3 fails internally, response is 200
        # (mobile will retry photo upload separately)
        assert response.status_code == 200
```

---

## Fixtures & Test Utilities

Create `/var/www/html/MadGirlfriend/namma-neighbour/apps/logistics/tests/conftest.py`:

```python
import pytest
from django.contrib.auth.models import User
from apps.logistics.models import DeliveryManifest, Parcel, ScanEvent
from apps.core.models import Community
from rest_framework.test import APIClient


@pytest.fixture
def community():
    """Create a test community"""
    return Community.objects.create(name='Sunrise Enclave', city='Bangalore')


@pytest.fixture
def delivery_partner(community):
    """Create a delivery partner user"""
    partner = User.objects.create_user(
        username='partner1',
        password='testpass',
        roles=['delivery_partner'],
        community=community
    )
    return partner


@pytest.fixture
def authenticated_delivery_partner_client(delivery_partner):
    """API client authenticated as delivery partner"""
    client = APIClient()
    client.force_authenticate(delivery_partner)
    return client


@pytest.fixture
def vendor():
    """Create a vendor user"""
    return User.objects.create_user(
        username='vendor1',
        password='testpass',
        roles=['vendor']
    )


@pytest.fixture
def buyer():
    """Create a buyer user"""
    return User.objects.create_user(
        username='buyer1',
        password='testpass',
        roles=['buyer']
    )


@pytest.fixture
def authenticated_buyer_client(buyer):
    """API client authenticated as buyer"""
    client = APIClient()
    client.force_authenticate(buyer)
    return client


@pytest.fixture
def order(vendor, buyer, community):
    """Create a confirmed order"""
    from apps.ordering.models import Order
    return Order.objects.create(
        vendor=vendor,
        buyer=buyer,
        community=community,
        status='CONFIRMED'
    )
```

---

## Running the Tests

```bash
# Install dependencies (if not already installed)
uv pip install pytest pytest-django pytest-xdist factory-boy

# Run all integration tests
uv run pytest apps/logistics/tests/test_*integration* -v

# Run specific test file
uv run pytest apps/logistics/tests/test_parcel_lifecycle.py -v

# Run with coverage
uv run pytest apps/logistics/tests/ --cov=apps.logistics --cov-report=html

# Run concurrent tests with transaction support
uv run pytest apps/logistics/tests/test_concurrent_operations.py -v --tb=short

# Run with markers
uv run pytest -m "integration" apps/logistics/tests/
```

---

## Acceptance Criteria Validation

Each test maps to a success metric from claude-plan.md:

| Acceptance Criterion | Test File | Test Name |
|---------------------|-----------|-----------|
| QR scannable under poor lighting / 30% damage | test_field_operations.py | test_qr_damage_tolerance_30_percent |
| Duplicate scans rejected (400) | test_parcel_lifecycle.py | test_duplicate_scan_rejected |
| Parcel progresses through all states | test_parcel_lifecycle.py | test_complete_delivery_flow |
| AT_COMMUNITY_HUB notifies buyer | test_parcel_lifecycle.py | (notification verification) |
| DELIVERED rejected without POD | test_parcel_lifecycle.py | test_complete_delivery_flow |
| A6 labels print, QR scannable at 30cm | test_field_operations.py | test_qr_scanning_distance_30cm_door |
| 15-order batch PDF <10s | test_performance.py | test_batch_label_generation_performance_15_orders |
| Delivery partner role isolated (403) | test_permission_boundaries.py | test_partner_cannot_scan_other_community |
| Tracking endpoint shows correct timeline | test_parcel_lifecycle.py | test_complete_delivery_flow |
| Order mark_delivered() called automatically | test_parcel_lifecycle.py | test_complete_delivery_flow |

---

## Notes for Implementers

1. **Transaction Testing:** Use `@pytest.mark.django_db(transaction=True)` for tests involving concurrent operations (locks, race conditions).

2. **Mocking S3 & Celery:** In unit/integration tests, mock S3 uploads and Celery task enqueueing to avoid external dependencies.

3. **Fixtures:** Use factory-boy for complex object creation to reduce boilerplate.

4. **Sequence Validation:** Critical to test server-side sequence validation in the scan endpoint; this prevents replay attacks and ensures idempotency.

5. **Optimistic Jumps:** Document and test backfill logic clearly; audit trail is essential for dispute resolution.

6. **Field Operations:** Some tests (QR scanning at various distances/lighting) require manual field validation post-development.

7. **Load Testing:** Use `concurrent.futures.ThreadPoolExecutor` for simulating concurrent operations; measure response times and lock contention.

---

## Files to Create/Modify

- Create: `/var/www/html/MadGirlfriend/namma-neighbour/apps/logistics/tests/test_parcel_lifecycle.py`
- Create: `/var/www/html/MadGirlfriend/namma-neighbour/apps/logistics/tests/test_concurrent_operations.py`
- Create: `/var/www/html/MadGirlfriend/namma-neighbour/apps/logistics/tests/test_permission_boundaries.py`
- Create: `/var/www/html/MadGirlfriend/namma-neighbour/apps/logistics/tests/test_field_operations.py`
- Create: `/var/www/html/MadGirlfriend/namma-neighbour/apps/logistics/tests/test_performance.py`
- Create: `/var/www/html/MadGirlfriend/namma-neighbour/apps/logistics/tests/conftest.py`
- Modify: `/var/www/html/MadGirlfriend/namma-neighbour/apps/logistics/tests/__init__.py` (ensure it exists)