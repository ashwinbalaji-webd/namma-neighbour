Now I have all the context files. Let me extract the relevant content for section-05-notifications from both the claude-plan.md and claude-plan-tdd.md files.

From the index.md, section-05-notifications has these dependencies:
- Depends on: section-01-models-fsm, section-04-scan-core
- Blocks: section-07-mobile-screens, section-08-integration-tests

Let me now generate the section content:

---

# Section 05: Notifications

## Overview

This section implements the notification service for the logistics system. Delivery partners trigger parcel scans via the API, and residents receive real-time push notifications when their parcels reach key milestones (community gate, delivery, failed attempts). The notification service uses Firebase Cloud Messaging (FCM) with Celery async tasks and implements smart batching to reduce notification fatigue while maintaining urgency on critical events.

**Scope:**
- Celery async task definitions for notifications and media uploads
- FCM integration for push notifications
- Smart batching logic for AT_COMMUNITY_HUB notifications
- POD photo upload with retry and backoff
- Task integration with scan endpoint

**Depends on:** section-01-models-fsm, section-04-scan-core

**Blocks:** section-07-mobile-screens (offline queue in mobile requires understanding notification flow), section-08-integration-tests (integration tests verify end-to-end notification delivery)

---

## Database Models & State

No new database models are created in this section. This section uses existing models from section-01:

- **Parcel:** Status field (FSM-managed), parcel_id, community
- **ScanEvent:** scan_sequence, created_at, is_auto_transition
- **Order:** buyer (FK to User), status field

The notification service reads from these models to determine:
1. Parcel status after scan
2. Buyer (resident) of the parcel
3. Scan history (for timeline)
4. Community context (for multi-tenant filtering)

---

## Architecture & Design

### Notification Flow

```
1. Delivery Partner scans parcel
   ↓
2. Scan endpoint processes transition (section-04)
   ↓
3. Scan endpoint enqueues notification task (asynchronous)
   → Does NOT block scan response
   ↓
4. Celery worker picks up notification task
   ↓
5. Determine parcel status (DELIVERED, AT_COMMUNITY_HUB, ATTEMPTED)
   ↓
6. Decide: batch or individual?
   - AT_COMMUNITY_HUB: batch if >1 parcel arrived same hour
   - DELIVERED: individual (always)
   - ATTEMPTED: individual
   ↓
7. Fetch buyer's device tokens from user profile
   ↓
8. Build FCM payload
   - title: "Parcel Update"
   - message: "Your parcel is at the gate / has been delivered / etc."
   - data: parcel_id, status (client fetches full details)
   ↓
9. Send via FCM
   ↓
10. Log delivery success/failure
```

### Batching Logic (AT_COMMUNITY_HUB)

When a parcel arrives at the community gate, we batch notifications if multiple parcels for the same resident arrived within 1 hour:

```
Query: ScanEvent where:
  - parcel.order.buyer = current_buyer
  - new_status = AT_COMMUNITY_HUB
  - created_at >= now() - 1 hour
  - parcel != current_parcel

If count > 0:
  Send: "You have 3 parcels at the gate"
  Include: [parcel_id_1, parcel_id_2, parcel_id_3]
Else:
  Send: "Your parcel is at the gate"
  Include: [parcel_id]
```

### POD Photo Upload

POD photos are uploaded asynchronously after a DELIVERED scan. The scan endpoint enqueues the photo upload task separately so S3 failures don't block the scan response:

```
1. Scan endpoint stores parcel.pod_photo_s3_key = None initially
   ↓
2. Enqueues upload task with parcel_id + photo_base64
   ↓
3. Celery task executes:
   - Decode base64 → PNG/JPEG bytes
   - Upload to S3: media/logistics/parcels/{parcel_id}/pod_{timestamp}.jpg
   - Update parcel.pod_photo_s3_key
   - Update ScanEvent.pod_photo_s3_key
   ↓
4. On S3 failure:
   - Log warning
   - Retry with exponential backoff (Celery retry)
   - Max 5 retries
   - After max retries: log error (no user alert in backend; mobile handles local retry)
```

---

## File Structure

**Backend Files to Create/Modify:**

```
apps/logistics/tasks.py
  - send_parcel_status_notification(parcel_id: int, new_status: str)
  - upload_pod_photo_to_s3(parcel_id: int, photo_base64: str)

apps/logistics/services/notifications.py
  - NotificationService class
    - build_notification_message(parcel_id: int, new_status: str) -> dict
    - determine_batching(parcel_id: int, new_status: str) -> bool
    - fetch_buyer_device_tokens(buyer_id: int) -> list[str]
    - send_fcm_notification(device_tokens: list[str], message: dict) -> dict

apps/logistics/services/media.py
  - upload_pod_photo(parcel_id: int, photo_bytes: bytes, timestamp: datetime) -> str
  - ensure_s3_bucket() -> bool

(Modified) apps/logistics/views.py or apps/logistics/services/scans.py
  - Enqueue notification tasks on scan completion
  - Pass parcel_id + new_status to task
```

---

## Tests (TDD First)

### Celery Task Tests

**Test: send_parcel_status_notification() with AT_COMMUNITY_HUB**
- Preconditions: Parcel in IN_TRANSIT status, order has buyer with device_token
- Call: send_parcel_status_notification(parcel_id=123, new_status='at_hub')
- Assertions:
  - Query ScanEvent for same buyer, same hour, AT_COMMUNITY_HUB → returns 0 other parcels
  - FCM called with message: "Your parcel is at the gate"
  - FCM payload includes parcel_id=123
  - No batching happens (only 1 parcel)

**Test: send_parcel_status_notification() with AT_COMMUNITY_HUB batching**
- Preconditions: 3 parcels for same buyer arrived at gate within 1 hour
- Call: send_parcel_status_notification(parcel_id=123, new_status='at_hub')
- Assertions:
  - Query ScanEvent for same buyer, same hour, AT_COMMUNITY_HUB → returns 2 other parcels
  - FCM called with message: "You have 3 parcels at the gate" (aggregated)
  - FCM payload includes all 3 parcel_ids
  - Single FCM call (not 3 separate)

**Test: send_parcel_status_notification() with DELIVERED**
- Preconditions: Parcel delivered, order has buyer with device_token
- Call: send_parcel_status_notification(parcel_id=123, new_status='delivered')
- Assertions:
  - FCM called with message: "Your parcel has been delivered"
  - FCM payload includes parcel_id=123
  - Not batched (DELIVERED always individual)

**Test: send_parcel_status_notification() with ATTEMPTED**
- Preconditions: Delivery attempt failed, order has buyer with device_token
- Call: send_parcel_status_notification(parcel_id=123, new_status='attempted')
- Assertions:
  - FCM called with message: "Delivery attempt failed"
  - FCM payload includes parcel_id=123
  - Not batched (ATTEMPTED always individual)

**Test: send_parcel_status_notification() - no device tokens**
- Preconditions: Buyer has no device tokens registered
- Call: send_parcel_status_notification(parcel_id=123, new_status='at_hub')
- Assertions:
  - FCM not called
  - Logged as info (not error)
  - Task completes successfully

**Test: send_parcel_status_notification() - parcel not found**
- Call: send_parcel_status_notification(parcel_id=99999, new_status='at_hub')
- Assertions:
  - Raises Parcel.DoesNotExist or logs and returns gracefully
  - Task does not crash other queued tasks

**Test: upload_pod_photo_to_s3() - success**
- Preconditions: Parcel exists, S3 bucket accessible
- Call: upload_pod_photo_to_s3(parcel_id=123, photo_base64="iVBORw0KG...")
- Assertions:
  - Decodes base64 → PNG/JPEG bytes
  - Uploads to S3 with key: media/logistics/parcels/123/pod_{timestamp}.jpg
  - Returns S3 key
  - Parcel.pod_photo_s3_key updated
  - Corresponding ScanEvent.pod_photo_s3_key updated

**Test: upload_pod_photo_to_s3() - S3 failure with retry**
- Preconditions: S3 unavailable (simulated)
- Call: upload_pod_photo_to_s3(parcel_id=123, photo_base64="...")
- Assertions:
  - First attempt raises exception
  - Celery retry triggered (exponential backoff: 1s, 2s, 4s, 8s, 16s)
  - After 5 retries: task marks as failed, logs error
  - Parcel not updated (partial failure)

**Test: upload_pod_photo_to_s3() - invalid base64**
- Call: upload_pod_photo_to_s3(parcel_id=123, photo_base64="invalid")
- Assertions:
  - Base64 decode fails
  - Logged as error (not retried)
  - Task completes with failure status

### Notification Service Tests

**Test: build_notification_message() - AT_COMMUNITY_HUB**
- Call: NotificationService.build_notification_message(parcel_id=123, new_status='at_hub')
- Assertions:
  - Returns dict: {"title": "Parcel Update", "body": "Your parcel is at the gate"}
  - No batching info in message (service layer is pure)

**Test: build_notification_message() - DELIVERED**
- Call: NotificationService.build_notification_message(parcel_id=123, new_status='delivered')
- Assertions:
  - Returns dict: {"title": "Parcel Update", "body": "Your parcel has been delivered"}

**Test: build_notification_message() - ATTEMPTED**
- Call: NotificationService.build_notification_message(parcel_id=123, new_status='attempted')
- Assertions:
  - Returns dict: {"title": "Parcel Update", "body": "Delivery attempt failed. We'll try again."}

**Test: determine_batching() - AT_COMMUNITY_HUB with >1 parcel**
- Preconditions: 2 other parcels for same buyer, same hour, AT_COMMUNITY_HUB
- Call: NotificationService.determine_batching(parcel_id=123, new_status='at_hub')
- Assertions:
  - Returns True (should batch)
  - Queries ScanEvent(new_status='at_hub', created_at >= now() - 1h)

**Test: determine_batching() - AT_COMMUNITY_HUB with 0 other parcels**
- Preconditions: Only 1 parcel at gate in past hour
- Call: NotificationService.determine_batching(parcel_id=123, new_status='at_hub')
- Assertions:
  - Returns False (no batching, individual notification)

**Test: determine_batching() - DELIVERED always returns False**
- Call: NotificationService.determine_batching(parcel_id=123, new_status='delivered')
- Assertions:
  - Returns False (DELIVERED never batched)

**Test: fetch_buyer_device_tokens() - returns list**
- Preconditions: Buyer has 2 device tokens
- Call: NotificationService.fetch_buyer_device_tokens(buyer_id=456)
- Assertions:
  - Returns list: ["token1", "token2"]
  - Excludes revoked tokens

**Test: fetch_buyer_device_tokens() - empty list**
- Preconditions: Buyer has no device tokens
- Call: NotificationService.fetch_buyer_device_tokens(buyer_id=456)
- Assertions:
  - Returns empty list []

**Test: send_fcm_notification() - success**
- Preconditions: FCM client mock configured
- Call: NotificationService.send_fcm_notification(["token1", "token2"], {"title": "...", "body": "..."})
- Assertions:
  - FCM client called with tokens and message
  - Returns success response (dict with success_count, failure_count)

**Test: send_fcm_notification() - partial failure**
- Preconditions: FCM returns success for token1, failure for token2
- Call: NotificationService.send_fcm_notification(["token1", "token2"], {...})
- Assertions:
  - Returns dict: {"success": 1, "failure": 1, "failed_tokens": ["token2"]}
  - Failures logged for later retry

### Integration Tests

**Test: Complete flow - AT_COMMUNITY_HUB notification**
- Preconditions: Parcel IN_TRANSIT, buyer has device_token
- Steps:
  1. Call scan endpoint with parcel QR → AT_COMMUNITY_HUB transition
  2. Scan endpoint enqueues send_parcel_status_notification task
  3. Celery executes task
  4. NotificationService.determine_batching() called
  5. FCM notification sent
- Assertions:
  - Parcel status updated to AT_COMMUNITY_HUB
  - ScanEvent created with correct timestamp
  - FCM call made with correct message
  - Task completes successfully

**Test: Complete flow - DELIVERED with POD photo**
- Preconditions: Parcel OUT_FOR_DELIVERY, S3 bucket accessible
- Steps:
  1. Call scan endpoint with parcel QR + pod_photo_base64
  2. Scan endpoint transitions parcel to DELIVERED
  3. Enqueues send_parcel_status_notification task
  4. Enqueues upload_pod_photo_to_s3 task (separately)
  5. Both tasks execute
- Assertions:
  - Parcel status = DELIVERED
  - pod_photo_s3_key set on both Parcel and ScanEvent
  - FCM notification sent (DELIVERED, individual)
  - Both tasks complete successfully

---

## Implementation Details

### Celery Task Definitions (`apps/logistics/tasks.py`)

```python
from celery import shared_task
from django.core.cache import cache
from apps.logistics.models import Parcel, ScanEvent
from apps.logistics.services.notifications import NotificationService
from apps.logistics.services.media import upload_pod_photo

@shared_task(bind=True, max_retries=5)
def send_parcel_status_notification(self, parcel_id: int, new_status: str):
    """
    Async task to send push notification on parcel status change.
    
    - Determines batching strategy (AT_COMMUNITY_HUB batched, DELIVERED individual)
    - Fetches buyer's device tokens
    - Sends FCM notification
    - Handles no-token case gracefully
    
    Args:
        parcel_id: ID of scanned parcel
        new_status: New FSM status (string, e.g., 'at_hub', 'delivered')
    """
    # Stub implementation - details below
    pass

@shared_task(bind=True, max_retries=5)
def upload_pod_photo_to_s3(self, parcel_id: int, photo_base64: str):
    """
    Async task to upload proof-of-delivery photo to S3.
    
    - Decodes base64 to bytes
    - Uploads to S3 with key: media/logistics/parcels/{parcel_id}/pod_{timestamp}.jpg
    - Updates Parcel.pod_photo_s3_key and ScanEvent.pod_photo_s3_key
    - Retries on failure with exponential backoff (max 5 retries)
    
    Args:
        parcel_id: ID of parcel
        photo_base64: Base64-encoded PNG/JPEG
    
    Raises:
        Parcel.DoesNotExist: if parcel not found
        Exception: on S3 upload failure (triggers retry)
    """
    # Stub implementation - details below
    pass
```

### Notification Service (`apps/logistics/services/notifications.py`)

```python
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from django.db.models import QuerySet
from apps.logistics.models import Parcel, ScanEvent
from apps.firebase import firebaseClient  # Assume from foundation

logger = logging.getLogger(__name__)

class NotificationService:
    """
    Service layer for FCM push notifications.
    
    Responsibilities:
    - Build notification message based on parcel status
    - Determine batching strategy (AT_COMMUNITY_HUB batched, others individual)
    - Fetch buyer device tokens
    - Send to FCM
    - Log results
    """
    
    @staticmethod
    def build_notification_message(parcel_id: int, new_status: str) -> Dict[str, str]:
        """
        Build FCM notification message content.
        
        Args:
            parcel_id: ID of parcel
            new_status: Status string (e.g., 'at_hub', 'delivered', 'attempted')
        
        Returns:
            Dict with keys: title, body
        """
        # Stub: return {"title": "...", "body": "..."}
        pass
    
    @staticmethod
    def determine_batching(parcel_id: int, new_status: str) -> bool:
        """
        Decide if notification should be batched with others.
        
        Logic:
        - AT_COMMUNITY_HUB: check if >1 parcel arrived for same buyer in past 1h
          - If yes, return True (batch)
          - If no, return False (individual)
        - DELIVERED: always return False (individual)
        - ATTEMPTED: always return False (individual)
        
        Args:
            parcel_id: ID of parcel
            new_status: Status string
        
        Returns:
            Boolean: True if should batch, False if individual
        """
        # Stub implementation
        pass
    
    @staticmethod
    def fetch_buyer_device_tokens(buyer_id: int) -> List[str]:
        """
        Fetch all active device tokens for a buyer (resident).
        
        Query: User.devicetoken_set where is_active=True and platform in ['ios', 'android']
        
        Args:
            buyer_id: User ID of buyer
        
        Returns:
            List of FCM device token strings (may be empty)
        """
        # Stub implementation
        pass
    
    @staticmethod
    def send_fcm_notification(device_tokens: List[str], message: Dict[str, str]) -> Dict:
        """
        Send FCM notification to device tokens.
        
        Args:
            device_tokens: List of FCM tokens
            message: Dict with title and body keys
        
        Returns:
            Dict with keys: success (int), failure (int), failed_tokens (list)
        """
        # Stub: call firebaseClient.send_multicast(tokens, message)
        pass
```

### Media Upload Service (`apps/logistics/services/media.py`)

```python
import base64
import logging
from datetime import datetime
from io import BytesIO
from django.core.files.base import ContentFile
from apps.storage import MediaStorage  # Assume from foundation
from apps.logistics.models import Parcel, ScanEvent

logger = logging.getLogger(__name__)

def upload_pod_photo(parcel_id: int, photo_base64: str, timestamp: datetime) -> str:
    """
    Upload POD photo to S3 and update parcel + scanevent records.
    
    Args:
        parcel_id: ID of parcel
        photo_base64: Base64-encoded image
        timestamp: When upload triggered
    
    Returns:
        S3 key (path) where photo stored
    
    Raises:
        Parcel.DoesNotExist: if parcel not found
        Exception: on S3 upload failure
    """
    # Stub implementation
    pass

def ensure_s3_bucket() -> bool:
    """
    Verify S3 bucket exists and is accessible.
    
    Returns:
        True if accessible, False otherwise
    """
    # Stub implementation
    pass
```

### Integration with Scan Endpoint

When the scan endpoint completes a parcel transition, it enqueues notification tasks:

```python
# In apps/logistics/views.py (ScanViewSet) or apps/logistics/services/scans.py

from apps.logistics.tasks import send_parcel_status_notification, upload_pod_photo_to_s3

def handle_parcel_scan(...) -> Response:
    """After successful FSM transition, enqueue async tasks."""
    
    # 1. Transition parcel (FSM logic from section-04)
    parcel.mark_at_hub()  # or equivalent transition
    
    # 2. Create ScanEvent
    scan_event = ScanEvent.objects.create(...)
    
    # 3. Enqueue notification (async, don't block response)
    send_parcel_status_notification.delay(parcel.id, parcel.status)
    
    # 4. If POD photo provided, enqueue upload separately
    if pod_photo_base64:
        upload_pod_photo_to_s3.delay(parcel.id, pod_photo_base64)
    
    # 5. Return scan response immediately (notification happens in background)
    return Response({...})
```

---

## Configuration & Environment

### Celery Configuration

Assume Celery is configured in the project (from foundation). In `settings.py`:

```python
# apps/logistics/tasks use these settings
CELERY_TASK_ROUTES = {
    'apps.logistics.tasks.send_parcel_status_notification': {'queue': 'notifications'},
    'apps.logistics.tasks.upload_pod_photo_to_s3': {'queue': 'media'},
}

CELERY_TASK_TIME_LIMIT = 30 * 60  # 30 min hard limit
CELERY_TASK_SOFT_TIME_LIMIT = 25 * 60  # 25 min soft limit
```

### FCM Configuration

FCM client assumes to be initialized in `apps.firebase` (from foundation):

```python
# apps/firebase.py (assumed to exist from foundation)
from firebase_admin import messaging

firebaseClient = messaging  # Simplified assumption
```

Device tokens are assumed stored in a `UserDeviceToken` model:

```python
# Assume this exists in a foundation app (e.g., apps/accounts/models.py)
class UserDeviceToken(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='device_tokens')
    token = models.CharField(max_length=500, unique=True)
    platform = models.CharField(choices=[('ios', 'iOS'), ('android', 'Android')])
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

---

## Dependencies & Integration Points

### Upstream Dependencies

1. **section-01-models-fsm:** Parcel, ScanEvent, FSM transitions
2. **section-04-scan-core:** Scan endpoint that enqueues notification tasks
3. **01-foundation (Celery):** Task queue runtime
4. **01-foundation (FCM):** Firebase Cloud Messaging credentials and client
5. **01-foundation (S3):** MediaStorage for POD photo uploads

### Downstream Dependencies

1. **section-07-mobile-screens:** Displays notifications received via FCM
2. **section-08-integration-tests:** Tests end-to-end notification delivery flow

---

## Key Design Decisions

| Decision | Rationale | Trade-offs |
|----------|-----------|-----------|
| **Async notification tasks** | Prevents slow FCM calls from blocking scan response | Added Celery complexity, eventual consistency |
| **Smart batching for AT_COMMUNITY_HUB** | Reduces notification fatigue (multiple parcels same hour batched) | Requires time-window query, may miss edge cases near hour boundary |
| **Individual notifications for DELIVERED** | Urgency (resident should know immediately parcel arrived) | More notifications to user (but acceptable for critical status) |
| **Separate POD upload task** | S3 failures don't block scan response; mobile handles local retry | Photo may lag behind status update; mobile must handle eventual consistency |
| **Max 5 retries for S3** | Balances resilience with avoiding stuck tasks | After 5 retries, photo lost (mobile can re-upload, but cumbersome) |

---

## Success Criteria

By end of implementation:
- Notification sent within 1s of scan completion (async to Celery queue)
- AT_COMMUNITY_HUB notifications batched if >1 parcel within 1h (reduces fatigue)
- DELIVERED and ATTEMPTED notifications sent individually (urgency)
- FCM failures logged but don't crash task queue
- POD photos uploaded with exponential backoff retry (max 5 attempts)
- All tasks are idempotent (can be retried safely)
- Integration tests verify end-to-end flow (scan → notification → FCM call)