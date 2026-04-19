Now I have all the context files. Let me extract the relevant information for section-07-mobile-screens and generate the section content.

Based on the plans, section-07-mobile-screens covers:
- ManifestScanScreen (full-screen camera, scans manifest QR, parcel checklist)
- ParcelScanScreen (full-screen QR scanner, photo capture, manual fallback)
- Offline resilience (local queue, retry logic)
- Navigation integration (role-based tab switching)

Let me generate the comprehensive section content:

---

# Mobile Screens: Delivery Partner App

## Overview

This section implements the React Native delivery partner screens with offline resilience for the NammaNeighbor logistics system. These screens enable delivery partners to scan manifest and parcel QR codes, capture proof-of-delivery (POD) photos, and operate reliably in low-connectivity environments.

**Dependencies:**
- section-05-notifications (FCM push notifications)
- section-06-api-endpoints (scan endpoint, label generation, tracking)

**Deliverables:**
- `ManifestScanScreen` component
- `ParcelScanScreen` component
- Offline queue manager (SQLite/Realm-based retry logic)
- Navigation integration (role-based tab switching)
- E2E tests for scanning workflows and offline resilience

---

## Test Stubs (from claude-plan-tdd.md)

### ManifestScanScreen Tests

**Test: QR scanning**
- Scans manifest QR code, parses manifest_code from payload
- Fetches manifest details from server (GET /api/v1/manifests/{manifest_code}/)
- Displays parcel checklist with flat, tower, resident name, and status

**Test: Offline handling**
- If offline, display cached manifest from previous load
- Sync status and UI when back online

**Test: Parcel action**
- Tapping "Scan Parcel" button opens ParcelScanScreen
- On return from ParcelScanScreen, checklist automatically updates
- Parcel marked as delivered if scan succeeded

### ParcelScanScreen Tests

**Test: QR scanning**
- Scans parcel QR code, parses order_id, tower, flat from JSON payload
- Displays parcel info: tower, flat, resident name (fetched from server)
- QR payload structure: `{"o": "NN-20260401-0034", "t": "B", "f": "304"}` (NO sequence)

**Test: Scan failure handling**
- 1st scan attempt fails → show retry prompt
- 2nd scan attempt fails → show manual entry input
- Manual entry: flat number + order ID input fields
- Manual entry still requires POD photo (fallback = flat input + photo)

**Test: Photo capture**
- Tapping "Mark Delivered" button opens camera
- Captures POD photo, compresses to reasonable size (1-3MB)
- Returns to ParcelScanScreen after capture

**Test: Offline queue (CRITICAL)**
- Scan status (JSON) sent to server immediately
- Parcel marked DELIVERED locally (optimistic update)
- Photo queued in SQLite with metadata + base64 chunks
- Queue retries every 10s with exponential backoff (1s, 2s, 4s, 8s, ..., max 60s)
- Max retries: 5 (then user alert)

**Test: Conflict resolution**
- If server rejects scan (e.g., 400), app shows error
- App syncs manifest state from server to reconcile divergence
- User can retry or skip parcel

### Navigation & UX Tests

**Test: Role switching**
- User with 'delivery_partner' role sees "Switch to Delivery Mode" toggle option
- Activating toggle swaps entire tab bar to [Manifests, Scan, History, Profile]
- Deactivating returns to resident/vendor tabs
- Resident user does NOT see this option

**Test: Permission handling**
- If user denies camera permission, show helpful error message
- App handles camera errors gracefully (hardware unavailable, etc.)

---

## Implementation Details

### Architecture

**Tech Stack:**
- `react-native-vision-camera` — Full-screen QR scanner
- `react-native-camera` or `react-native-image-picker` — POD photo capture
- `realm` or `@react-native-async-storage/async-storage` — Local queue storage
- `axios` — HTTP client with retry logic
- `react-native-netinfo` — Offline detection

**Navigation Structure:**
```
RootNavigator
├── AuthStack
├── ResidentTabs
│   ├── HomeTab
│   ├── OrdersTab
│   └── ProfileTab
├── VendorTabs
│   ├── DashboardTab
│   ├── OrdersTab
│   └── ProfileTab
└── DeliveryTabs (conditional, if delivery_partner role)
    ├── ManifestsTab
    ├── ScanTab (ParcelScanScreen)
    ├── HistoryTab
    └── ProfileTab
```

**Conditional Navigation Logic:**
- Parse JWT token for `roles` array
- If `roles.includes('delivery_partner')`, show "Delivery Mode" toggle in settings
- When toggled ON, swap navigator context to DeliveryTabs
- When toggled OFF, restore previous role navigator

### ManifestScanScreen Component

**Purpose:** Delivery partner scans manifest QR code at community gate, views checklist of parcels for delivery.

**UI Components:**
- Full-screen camera (vision-camera, QR mode)
- Status bar with manifest code, parcel count, delivered count
- Scrollable list of parcels (flat, tower, resident, status badge)
- Action buttons: "Scan Parcel", "Mark All Delivered" (if all scanned), "End Delivery"

**Data Structure:**
```typescript
interface Manifest {
  id: string;
  manifest_code: string;
  delivery_date: string;
  community_id: string;
  delivery_partner_id: string;
  status: 'draft' | 'dispatched' | 'at_gate' | 'completed';
  parcel_count: number;
  delivered_count: number;
  parcels: Parcel[];
  cached_at: number; // For offline tracking
}

interface Parcel {
  id: string;
  qr_code: string;
  order_id: string;
  flat: string;
  tower: string;
  resident_name: string;
  status: string;
}
```

**State Management:**
- Local state: `manifest`, `parcels`, `loading`, `error`, `isOnline`
- Derived: `deliveredCount`, `pendingCount`

**Flow:**
1. Component renders: check if user is delivery_partner role
2. If offline, load cached manifest from AsyncStorage/Realm
3. Display full-screen camera in QR mode
4. User scans manifest QR → parse manifest_code
5. Fetch manifest from GET /api/v1/manifests/{manifest_code}/ with error handling
6. Display parcel checklist
7. User taps "Scan Parcel" → navigate to ParcelScanScreen with parcel_id
8. On return, poll server for parcel status (every 2s, up to 5s total)
9. Update local parcel status if changed
10. Buttons:
    - "Mark All Delivered" (enabled if all parcels scanned + delivered)
      - Updates manifest.status to 'completed' locally
      - POST to server (async, background)
    - "End Delivery" → navigate back

**Offline Handling:**
- Network state detected via NetInfo
- On offline: show "Offline" banner, disable network calls, show cached data
- Queue manifest fetch when back online
- Sync interval: 30s (check for pending uploads)

**Error Handling:**
- Manifest not found (404) → "Manifest not found. Try scanning again."
- Network error → show retry button, auto-retry after 30s
- Permission denied → "Camera access required. Check app permissions."

### ParcelScanScreen Component

**Purpose:** Delivery partner scans individual parcel QR, captures POD photo, marks delivered.

**UI Flow:**
1. Full-screen camera in QR mode
2. On successful QR scan: parse JSON `{"o": order_id, "t": tower, "f": flat}`
3. Fetch parcel details from server
4. Display parcel info (tower, flat, resident name)
5. Show buttons: "Mark Delivered", "Attempt (No Answer)", "Skip"
6. On "Mark Delivered": open photo camera
7. Capture photo, compress, store locally
8. Send scan status to server immediately
9. Queue photo upload with retry

**Data Structure:**
```typescript
interface ParcelDetails {
  id: string;
  qr_code: string;
  flat: string;
  tower: string;
  resident_name: string;
  status: string;
}

interface OfflineQueueItem {
  id: string;
  parcel_id: string;
  photo_base64: string;
  photo_size: number;
  created_at: number;
  retry_count: number;
  last_error: string | null;
  status: 'pending' | 'uploading' | 'failed' | 'success';
}
```

**State Management:**
- `scannerActive` — camera is active
- `scannedParcelId` — parcel ID from QR
- `parcelDetails` — fetched from server
- `photoBase64` — captured POD photo (base64)
- `isOnline` — network status
- `qrAttempts` — count of failed QR scans (reset on success)

**QR Scan Flow (Critical Logic):**

1. **First scan attempt:**
   - Parse QR JSON
   - Lookup parcel by qr_code
   - If success: display parcel details, show action buttons
   - If failure: increment qrAttempts, show "Scan failed. Try again." (retry camera)

2. **Second scan attempt fails:**
   - Hide camera
   - Show manual entry form (flat number input + order ID input)
   - User enters flat, app verifies resident name with server (prefetch)
   - Still requires POD photo (fallback = manual + photo)

3. **Delivery Actions:**

   - **Mark Delivered:**
     - Check if photo captured (required)
     - If missing: show error "Photo required for delivery"
     - Send scan request to POST /api/v1/parcels/scan/:
       ```json
       {
         "qr_data": "{\"o\": \"NN-20260401-0034\", \"t\": \"B\", \"f\": \"304\"}",
         "location": "Flat 304",
         "pod_photo": null,  // SEPARATE UPLOAD
         "device_id": "android-uuid",
         "gps_lat": 13.052669,
         "gps_lon": 77.652245
       }
       ```
     - If success (200): mark parcel locally as DELIVERED, optimistic update
     - Queue photo upload separately (POST /api/v1/parcels/{parcel_id}/pod/ with multipart)
     - Return to ManifestScanScreen

   - **Attempt (No Answer):**
     - Send scan request with `location: "Flat {flat}"`
     - Parcel transitions to ATTEMPTED
     - Return to camera (for next parcel)

   - **Skip:**
     - No server call
     - Return to camera

**Photo Capture & Offline Queue (CRITICAL):**

**Photo Capture:**
- On "Mark Delivered", open photo camera (separate from QR camera)
- User captures photo
- Compress to JPEG, target size 1-3MB (quality ~80%)
- Encode to base64
- Store in memory temporarily

**Offline Queue Manager:**
- Store photo + metadata in SQLite/Realm:
  ```
  Table: photos
  - id (uuid)
  - parcel_id
  - photo_base64 (BLOB, chunked if >1MB)
  - photo_size
  - created_at
  - retry_count
  - last_error
  - status ('pending', 'uploading', 'failed', 'success')
  ```

**Retry Loop:**
- Run every 10s when app is active
- For each 'pending' item:
  - Check if online (NetInfo)
  - If offline: skip this cycle
  - If online:
    - Attempt upload: POST /api/v1/parcels/{parcel_id}/pod/ (multipart)
    - If 204: mark as 'success', delete from queue
    - If 4xx/5xx: increment retry_count
    - If retry_count >= 5: mark as 'failed', notify user
    - Exponential backoff: wait = min(2^retry_count, 60) seconds

- **Exponential Backoff Schedule:**
  ```
  Retry 1: 1s delay
  Retry 2: 2s delay
  Retry 3: 4s delay
  Retry 4: 8s delay
  Retry 5: 16s delay
  Retry 6+: 60s (capped)
  ```

**User Alert:**
- If all 5 retries fail:
  - Show notification: "Photo upload failed. Please retry when online."
  - Option: "Retry Now" (manual retry)
  - Option: "Try Later" (background queue continues)

**Error Handling:**
- Network error (no internet) → queue item remains pending, auto-retry
- 400/401/403 → log error, mark as 'failed', alert user
- 404 (parcel not found) → log error, mark as 'failed', alert user
- 500 (server error) → queue item remains pending, auto-retry

### Offline Resilience Implementation

**Offline Detection:**
```typescript
import NetInfo from '@react-native-async-storage/async-storage';

useEffect(() => {
  const unsubscribe = NetInfo.addEventListener(state => {
    setIsOnline(state.isConnected);
    if (state.isConnected) {
      // Trigger retry loops
      processPhotoQueue();
      syncManifestState();
    }
  });
  return unsubscribe;
}, []);
```

**Photo Queue Processing:**
```typescript
async function processPhotoQueue() {
  const queue = await realm.objects('OfflineQueueItem')
    .filtered('status = "pending" OR status = "uploading"');
  
  for (const item of queue) {
    if (item.retry_count >= 5) continue; // Skip failed items
    
    const delay = Math.min(Math.pow(2, item.retry_count), 60000);
    if (Date.now() - item.last_retry_at < delay) continue; // Skip if backoff not elapsed
    
    try {
      const formData = new FormData();
      formData.append('file', {
        uri: `data:image/jpeg;base64,${item.photo_base64}`,
        type: 'image/jpeg',
        name: `pod_${item.parcel_id}.jpg`,
      });
      
      const response = await axios.post(
        `/api/v1/parcels/${item.parcel_id}/pod/`,
        formData,
        { headers: { 'Content-Type': 'multipart/form-data' } }
      );
      
      if (response.status === 204) {
        realm.write(() => {
          item.status = 'success';
        });
      }
    } catch (error) {
      realm.write(() => {
        item.retry_count += 1;
        item.last_error = error.message;
        item.last_retry_at = Date.now();
        if (item.retry_count >= 5) {
          item.status = 'failed';
          // Notify user
        }
      });
    }
  }
}
```

**Local Parcel State:**
- Parcel marked DELIVERED optimistically (before photo upload succeeds)
- Server scan endpoint returns 200 immediately (photo upload async)
- If photo upload fails: parcel state remains DELIVERED (user retried, likely delivered)
- Audit trail shows failed attempts via is_auto_transition flag

**Sync on Reconnect:**
- When device comes online, trigger `processPhotoQueue()`
- Also fetch manifest state from server (in background, non-blocking)
- Merge with local state (server is source of truth)

### Navigation Integration

**Role Detection (JWT Token):**
```typescript
const parseJWT = (token: string) => {
  const [, payload] = token.split('.');
  return JSON.parse(atob(payload));
};

const user = useAuthContext();
const roles = parseJWT(user.token).roles || [];
const isDeliveryPartner = roles.includes('delivery_partner');
```

**Tab Navigator (Conditional):**
```typescript
function RootNavigator() {
  const { user } = useAuthContext();
  const [deliveryMode, setDeliveryMode] = useState(false);
  
  const roles = parseJWT(user.token).roles || [];
  const isDeliveryPartner = roles.includes('delivery_partner');
  
  if (isDeliveryPartner && deliveryMode) {
    return <DeliveryTabs />;
  }
  
  return <ResidentVendorTabs />;
}

function DeliveryTabs() {
  return (
    <Tab.Navigator>
      <Tab.Screen name="Manifests" component={ManifestScanScreen} />
      <Tab.Screen name="Scan" component={ParcelScanScreen} />
      <Tab.Screen name="History" component={DeliveryHistoryScreen} />
      <Tab.Screen name="Profile" component={ProfileScreen} />
    </Tab.Navigator>
  );
}
```

**Settings Toggle:**
```typescript
function ProfileScreen() {
  const [deliveryMode, setDeliveryMode] = useDeliveryMode(); // Context
  
  return (
    <View>
      {isDeliveryPartner && (
        <Switch
          label="Delivery Mode"
          value={deliveryMode}
          onValueChange={setDeliveryMode}
        />
      )}
    </View>
  );
}
```

---

## File Paths

**Mobile App Structure:**
- `/apps/mobile/src/screens/delivery/ManifestScanScreen.tsx`
- `/apps/mobile/src/screens/delivery/ParcelScanScreen.tsx`
- `/apps/mobile/src/services/OfflineQueueManager.ts`
- `/apps/mobile/src/services/ScanService.ts`
- `/apps/mobile/src/context/DeliveryContext.tsx`
- `/apps/mobile/src/navigation/DeliveryNavigator.tsx`
- `/apps/mobile/src/utils/qrParser.ts`
- `/apps/mobile/src/utils/photoCompression.ts`

**Test Files:**
- `/apps/mobile/src/screens/delivery/__tests__/ManifestScanScreen.test.tsx`
- `/apps/mobile/src/screens/delivery/__tests__/ParcelScanScreen.test.tsx`
- `/apps/mobile/src/services/__tests__/OfflineQueueManager.test.ts`
- `/apps/mobile/src/navigation/__tests__/navigationIntegration.e2e.ts`

---

## Dependencies on Other Sections

**section-05-notifications (FCM):**
- Notification messages triggered by parcel scans (AT_COMMUNITY_HUB, DELIVERED, ATTEMPTED)
- Mobile app displays notifications as native alerts
- Parcel details fetched from notification payload (parcel_id, status)

**section-06-api-endpoints:**
- GET /api/v1/manifests/{manifest_code}/ — fetch manifest details + parcel list
- POST /api/v1/parcels/scan/ — submit scan event
- POST /api/v1/parcels/{parcel_id}/pod/ — upload POD photo (multipart)
- GET /api/v1/orders/{order_id}/label.pdf — verify label caching (not used in delivery mode, informational)

---

## Key Implementation Notes

**Offline-First Design:**
- All operations (scan status, parcel state) optimistic locally
- Server is source of truth; sync on reconnect
- Photo upload retried indefinitely (with backoff), never abandoned

**Photo Upload Separation:**
- Scan status sent immediately: POST /api/v1/parcels/scan/ (JSON, low bandwidth)
- Photo uploaded separately: POST /api/v1/parcels/{parcel_id}/pod/ (multipart)
- Decoupling allows fast scan response even if photo upload slow

**Manual Fallback:**
- QR scan fails twice → show flat + order ID input
- Still requires POD photo (manual + photo = acceptable)
- Server verifies flat matches parcel (loose coupling)

**Error Recovery:**
- Network errors → queue item remains, retries indefinitely
- Server validation errors (4xx) → mark failed, alert user
- User can manually retry via "Retry" button

---

## Testing Strategy

**Unit Tests:**
- QR parsing logic
- Photo compression (file size, format)
- Offline queue state transitions
- Retry backoff calculations

**Integration Tests:**
- Manifest fetch + parcel list display
- QR scan → parcel detail fetch → action
- Photo capture → offline queue → retry on reconnect
- Manifest state sync on reconnect

**E2E Tests:**
- Complete delivery flow (manifest → parcel → photo → success)
- Network disconnect during scan → local queue → reconnect → upload
- Manual fallback (QR fails, manual entry, photo)
- Role-based navigation switching

**Field Operations Tests:**
- QR scan under various lighting
- QR scan with damaged/smudged codes
- Photo capture on low-light conditions
- Offline operation for 30+ minutes