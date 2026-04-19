Perfect! Now I have all the information I need. Let me generate the section content for section-04-query-errors.

# Section 04: Query Errors — TanStack Query Setup, Error Boundaries, Offline Handling

## Overview

This section establishes the query client infrastructure, global error handling, and offline resilience patterns for the Seller Web Portal. It forms the foundation for all subsequent sections that fetch data or perform mutations (sections 5–13).

**Dependencies:** Requires section-02 (auth system with cookie management) and section-01 (project initialization).

**Blocks:** Sections 06–09 (seller features), 11–13 (admin features).

---

## Tests First (TDD)

### QueryClient Setup Tests

Create test files at `/var/www/html/MadGirlfriend/namma-neighbour/seller-web/__tests__/hooks/useQueryClient.test.ts` and `/var/www/html/MadGirlfriend/namma-neighbour/seller-web/__tests__/setup.test.ts`.

**Test outline:**
- QueryClient is instantiated as a singleton on the client (using `useMemo` in context provider)
- Server Components can create per-request QueryClient instances without cross-contamination
- Default configuration applies: `staleTime: 30000ms`, `retry: 1`, `refetchOnWindowFocus: true`
- Query key convention matches documented patterns: `['listings']`, `['listings', id]`, `['orders', 'today']`, etc.

**Key assertion:**
```typescript
// Client-side singleton test
it('creates QueryClient once and reuses across renders', () => {
  // Verify same instance returned on multiple hook calls
});

// Server-side per-request test
it('server components create separate QueryClient per request', () => {
  // Verify cache() function isolation
});
```

### Error Boundary Tests

Create `/var/www/html/MadGirlfriend/namma-neighbour/seller-web/__tests__/error-boundary.test.tsx`.

**Test outline:**
- Error boundary catches rendering errors and displays fallback UI
- "Try again" button calls `reset()` and re-renders the component
- Generic error message is shown (not stack trace in production)

**Key assertion:**
```typescript
it('displays error message and provides reset button', () => {
  // Throw error in child component
  // Assert error message visible
  // Click reset button
  // Assert component re-renders without error
});
```

### Optimistic Update Tests

Create `/var/www/html/MadGirlfriend/namma-neighbour/seller-web/__tests__/hooks/useOptimisticToggle.test.tsx`.

**Test outline:**
- Toggle mutation displays optimistic state immediately (before server response)
- If mutation succeeds, query is invalidated and actual state syncs
- If mutation fails, optimistic state reverts and error toast shows

**Key assertion:**
```typescript
it('reverts optimistic state on mutation error', () => {
  // Click toggle (state flips immediately)
  // Mock API error
  // Assert state reverts to previous value
  // Assert error toast displayed
});
```

### FSSAI Polling Tests

Create `/var/www/html/MadGirlfriend/namma-neighbour/seller-web/__tests__/hooks/useFssaiPolling.test.tsx`.

**Test outline:**
- `useFssaiPolling` hook starts polling at 10-second intervals when status is `pending`
- Polling stops when status becomes `verified` or `rejected`
- Polling pauses when tab is hidden (`refetchIntervalInBackground: false`)
- Polling resumes when tab regains focus

**Key assertion:**
```typescript
it('stops polling when status changes to verified', () => {
  // Start polling (status = pending)
  // Assert refetch called at intervals
  // Update status to verified
  // Assert no further refetch calls
});

it('pauses polling when tab hidden', () => {
  // Start polling
  // Trigger visibility hidden event
  // Assert refetch not called during hidden period
});
```

### Offline Queue Tests

Create `/var/www/html/MadGirlfriend/namma-neighbour/seller-web/__tests__/hooks/useOfflineQueue.test.tsx`.

**Test outline:**
- When mutation fails with network error (no response), offline queue stores it
- If `navigator.onLine === false`, banner shows "Connection lost. Changes may not save..."
- For critical mutations, modal shows with "Retry when online" option
- On `online` event, all queued mutations retry automatically
- After 5 minutes offline, queue expires and "Could not save" message appears

**Key assertion:**
```typescript
it('queues mutation when offline and retries on reconnect', () => {
  // Simulate offline (navigator.onLine = false)
  // Trigger mutation (fails with network error)
  // Assert queue stores mutation data
  // Trigger online event
  // Assert mutation retried automatically
});

it('expires queue after 5 minutes offline', async () => {
  // Simulate offline
  // Store mutation in queue
  // Fast-forward time by 5 minutes
  // Assert queue cleared
  // Assert "could not save" message shown
});
```

### API Error Toast Tests

Create `/var/www/html/MadGirlfriend/namma-neighbour/seller-web/__tests__/hooks/useMutationErrorHandler.test.tsx`.

**Test outline:**
- Mutation error triggers `toast.error(message)` via Sonner
- Error message from API response body is used when available
- Generic fallback message if no response body

**Key assertion:**
```typescript
it('shows API error message in toast', () => {
  // Mock API returning validation error
  // Assert toast displays error message from response
});
```

---

## Implementation Details

### File Structure

```
seller-web/
├── lib/
│   ├── queryClient.ts               # QueryClient factory function
│   ├── reactQuery.ts                # TanStack Query configuration constants
│   └── errorMessages.ts             # Error message mapping utilities
├── components/
│   ├── QueryClientProvider.tsx      # Client-side singleton provider
│   ├── ErrorBoundary.tsx            # Global error boundary wrapper
│   └── OfflineIndicator.tsx         # Offline warning banner
├── hooks/
│   ├── useOptimisticToggle.ts       # Optimistic update pattern
│   ├── useFssaiPolling.ts           # FSSAI status polling with auto-stop
│   └── useOfflineQueue.ts           # Offline mutation queueing
├── app/
│   ├── layout.tsx                   # Root layout with providers
│   └── (seller|admin)/
│       └── error.tsx                # Error boundary fallback
└── __tests__/
    ├── hooks/useQueryClient.test.ts
    ├── error-boundary.test.tsx
    └── [other test files as listed above]
```

### 1. QueryClient Lifecycle

#### Server-Side (Per-Request)

Create `lib/queryClient.ts`:

```typescript
import { QueryClient } from '@tanstack/react-query';

export const createQueryClient = () => new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,           // 30 seconds
      retry: 1,                    // Retry once on network error
      refetchOnWindowFocus: true,  // Refresh on tab focus
    },
    mutations: {
      retry: 1,
    },
  },
});

// For server components: use React's cache() to ensure per-request isolation
import { cache } from 'react';

export const getQueryClient = cache(() => createQueryClient());
```

#### Client-Side (Singleton with Strict Mode Safety)

Create `components/QueryClientProvider.tsx`:

```typescript
'use client';

import React, { useMemo } from 'react';
import { QueryClientProvider as TanStackQueryClientProvider } from '@tanstack/react-query';
import { createQueryClient } from '@/lib/queryClient';

export function QueryClientProvider({ children }: { children: React.ReactNode }) {
  const [queryClient] = React.useState(() => createQueryClient());
  
  return (
    <TanStackQueryClientProvider client={queryClient}>
      {children}
    </TanStackQueryClientProvider>
  );
}
```

### 2. Query Key Conventions

Define in `lib/reactQuery.ts`:

```typescript
export const queryKeys = {
  listings: () => ['listings'] as const,
  listing: (id: string) => ['listings', id] as const,
  orders: () => ['orders'] as const,
  ordersByTab: (tab: 'today' | 'upcoming' | 'past') => ['orders', tab] as const,
  payouts: () => ['payouts'] as const,
  fssaiStatus: (vendorId: string) => ['fssai-status', vendorId] as const,
  admin: {
    dashboard: () => ['admin', 'dashboard'] as const,
    vendors: {
      pending: () => ['admin', 'vendors', 'pending'] as const,
      active: () => ['admin', 'vendors', 'active'] as const,
      detail: (id: string) => ['admin', 'vendors', id] as const,
    },
    residents: () => ['admin', 'residents'] as const,
    settings: () => ['admin', 'settings'] as const,
  },
} as const;
```

### 3. Error Boundary

Create `components/ErrorBoundary.tsx` (class component):

```typescript
'use client';

import React from 'react';
import { Button } from '@/components/ui/button';

export class ErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { hasError: boolean; error?: Error }
> {
  constructor(props: { children: React.ReactNode }) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error };
  }

  reset = () => {
    this.setState({ hasError: false, error: undefined });
  };

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex flex-col items-center justify-center min-h-screen">
          <h1 className="text-2xl font-bold mb-4">Something went wrong</h1>
          <Button onClick={this.reset}>Try again</Button>
        </div>
      );
    }

    return this.props.children;
  }
}
```

Alternatively, use Next.js error.tsx at layout level:

Create `app/(seller)/error.tsx`:

```typescript
'use client';

import { Button } from '@/components/ui/button';

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="flex flex-col items-center justify-center min-h-screen">
      <h1 className="text-2xl font-bold mb-4">Something went wrong</h1>
      <p className="mb-4 text-gray-600">{error.message}</p>
      <Button onClick={() => reset()}>Try again</Button>
    </div>
  );
}
```

### 4. Optimistic Updates Hook

Create `hooks/useOptimisticToggle.ts`:

```typescript
'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

interface UseOptimisticToggleOptions {
  mutationFn: (newValue: boolean) => Promise<void>;
  currentValue: boolean;
  onSuccess?: () => void;
  invalidateKey: string[];
}

export function useOptimisticToggle({
  mutationFn,
  currentValue,
  onSuccess,
  invalidateKey,
}: UseOptimisticToggleOptions) {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: invalidateKey });
      onSuccess?.();
    },
    onError: (error: Error) => {
      toast.error(error.message || 'Failed to update');
    },
  });
}
```

Usage in component:
```typescript
const toggleMutation = useOptimisticToggle({
  mutationFn: (isActive) => updateProductActive(productId, isActive),
  currentValue: product.is_active,
  invalidateKey: queryKeys.listings(),
});

// In JSX: display state flips immediately
const displayActive = toggleMutation.isPending ? !currentValue : product.is_active;

<Switch
  checked={displayActive}
  onCheckedChange={(checked) => toggleMutation.mutate(checked)}
/>
```

### 5. FSSAI Polling Hook

Create `hooks/useFssaiPolling.ts`:

```typescript
'use client';

import { useQuery } from '@tanstack/react-query';
import { queryKeys } from '@/lib/reactQuery';

interface FSSAIStatus {
  status: 'pending' | 'verifying' | 'verified' | 'rejected';
  reason?: string;
}

export function useFssaiPolling(vendorId: string) {
  return useQuery({
    queryKey: queryKeys.fssaiStatus(vendorId),
    queryFn: async () => {
      const response = await fetch(
        `/api/proxy/v1/vendors/${vendorId}/fssai/status/`
      );
      if (!response.ok) throw new Error('Failed to fetch FSSAI status');
      return response.json() as Promise<FSSAIStatus>;
    },
    // Auto-stop when status is finalized
    refetchInterval: (query) => {
      const data = query.state.data as FSSAIStatus | undefined;
      if (data?.status === 'verified' || data?.status === 'rejected') {
        return false; // Stop polling
      }
      return 10_000; // Poll every 10 seconds while pending
    },
    // Pause polling when tab hidden
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
  });
}
```

### 6. Offline Detection and Mutation Queueing

Create `hooks/useOfflineQueue.ts`:

```typescript
'use client';

import { useEffect, useState, useRef } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

interface QueuedMutation {
  id: string;
  fn: () => Promise<unknown>;
  timestamp: number;
}

const EXPIRATION_TIME_MS = 5 * 60 * 1000; // 5 minutes

export function useOfflineQueue() {
  const [isOffline, setIsOffline] = useState(false);
  const queueRef = useRef<Map<string, QueuedMutation>>(new Map());
  const queryClient = useQueryClient();

  useEffect(() => {
    const handleOnline = async () => {
      setIsOffline(false);
      // Retry all queued mutations
      for (const [, mutation] of queueRef.current) {
        try {
          await mutation.fn();
          queueRef.current.delete(mutation.id);
        } catch (error) {
          toast.error('Failed to retry mutation');
        }
      }
    };

    const handleOffline = () => {
      setIsOffline(true);
    };

    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);

    // Set initial state
    setIsOffline(!navigator.onLine);

    return () => {
      window.removeEventListener('online', handleOnline);
      window.removeEventListener('offline', handleOffline);
    };
  }, []);

  const queueMutation = (mutationFn: () => Promise<unknown>) => {
    const id = Math.random().toString(36).substr(2, 9);
    const queued: QueuedMutation = {
      id,
      fn: mutationFn,
      timestamp: Date.now(),
    };
    queueRef.current.set(id, queued);

    // Auto-expire after 5 minutes
    setTimeout(() => {
      if (queueRef.current.has(id)) {
        queueRef.current.delete(id);
        toast.error('Your changes could not be saved');
      }
    }, EXPIRATION_TIME_MS);
  };

  return { isOffline, queueMutation, queue: queueRef.current };
}
```

### 7. Offline Indicator Banner

Create `components/OfflineIndicator.tsx`:

```typescript
'use client';

import { useEffect, useState } from 'react';
import { AlertCircle } from 'lucide-react';

export function OfflineIndicator() {
  const [isOnline, setIsOnline] = useState(true);

  useEffect(() => {
    setIsOnline(navigator.onLine);
    window.addEventListener('online', () => setIsOnline(true));
    window.addEventListener('offline', () => setIsOnline(false));
  }, []);

  if (isOnline) return null;

  return (
    <div className="fixed bottom-4 left-4 right-4 md:right-auto md:w-96 bg-yellow-50 border border-yellow-200 rounded-lg p-4 flex items-start gap-3 shadow-lg">
      <AlertCircle className="w-5 h-5 text-yellow-600 mt-0.5 flex-shrink-0" />
      <div>
        <p className="font-medium text-yellow-900">Connection lost</p>
        <p className="text-sm text-yellow-700">
          Changes may not save until you're back online.
        </p>
      </div>
    </div>
  );
}
```

### 8. Root Layout Integration

Modify `app/layout.tsx` to wrap providers:

```typescript
import { QueryClientProvider } from '@/components/QueryClientProvider';
import { OfflineIndicator } from '@/components/OfflineIndicator';
import { Toaster } from 'sonner';

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <QueryClientProvider>
          <ErrorBoundary>
            {children}
            <OfflineIndicator />
          </ErrorBoundary>
          <Toaster />
        </QueryClientProvider>
      </body>
    </html>
  );
}
```

### 9. API Error Handling in Mutations

Hook for standardized error handling in mutations:

Create `hooks/useMutationErrorHandler.ts`:

```typescript
'use client';

import { useMutation } from '@tanstack/react-query';
import { toast } from 'sonner';
import { useOfflineQueue } from './useOfflineQueue';

interface UseMutationErrorHandlerOptions<T> {
  mutationFn: (variables: T) => Promise<unknown>;
  onSuccess?: () => void;
  onError?: (error: Error) => void;
  queueOnOffline?: boolean;
}

export function useMutationErrorHandler<T>({
  mutationFn,
  onSuccess,
  onError,
  queueOnOffline = true,
}: UseMutationErrorHandlerOptions<T>) {
  const { isOffline, queueMutation } = useOfflineQueue();

  return useMutation({
    mutationFn,
    onSuccess: () => {
      toast.success('Changes saved');
      onSuccess?.();
    },
    onError: (error: Error) => {
      // Check if this is a network error
      if (error.message === 'Failed to fetch' || error.message.includes('network')) {
        if (isOffline && queueOnOffline) {
          queueMutation(() => mutationFn({} as T));
        } else {
          toast.error('Connection error. Please try again.');
        }
      } else {
        // API error with response body
        toast.error(error.message || 'Failed to save changes');
      }
      onError?.(error);
    },
  });
}
```

---

## Key Architectural Decisions

1. **QueryClient Isolation:** Server Components use `cache()` to ensure per-request instances, preventing data leakage between users. Client uses context + `useMemo` for React Strict Mode safety.

2. **Stale Time vs Refetch:** 30-second stale time reduces over-fetching on tab focus, while `refetchOnWindowFocus: true` ensures eventual consistency when the user returns.

3. **Optimistic Updates Pattern:** Toggle mutations display state change immediately (`variables.isActive`) before server confirms. Errors revert the display. Query invalidation on success syncs with server truth.

4. **FSSAI Polling:** Uses `refetchInterval` function that returns `false` when status is final (`verified` or `rejected`). Automatically stops polling without manual cleanup.

5. **Offline Queue:** Stores failed mutations when offline and retries on reconnect. Expires after 5 minutes to prevent stale action queues. Does not queue validation errors (API 4xx), only network failures.

6. **Error Toast Patterns:** Mutations always show `toast.error()` on failure. Network errors show generic message. API errors show response body message when available.

---

## Dependencies & Blocking

- **Depends On:**
  - section-01: Project initialization (Next.js, shadcn/ui, Jest setup)
  - section-02: Auth system (JWT cookies, BFF proxy)

- **Blocks:**
  - section-06 through section-13: All sections that fetch data or perform mutations depend on this query client foundation

- **Can Parallelize With:**
  - section-03 (middleware): Can start after section-02 completes

---

## Testing Checklist

- QueryClient singleton created once per client lifecycle
- Server-side per-request isolation verified
- Error boundary displays fallback UI and reset button works
- Optimistic toggle reverts on mutation error
- FSSAI polling stops when status finalizes
- Offline banner shows when `navigator.onLine === false`
- Mutation queued when offline; retried on reconnect
- Queue expires after 5 minutes with error message
- Error toasts display API response messages
- `refetchOnWindowFocus` recovers from transient 502 errors

---

## File Paths Summary

All files created under `/var/www/html/MadGirlfriend/namma-neighbour/seller-web/`:

- `lib/queryClient.ts` — QueryClient factory and caching
- `lib/reactQuery.ts` — Query key conventions
- `components/QueryClientProvider.tsx` — Client-side singleton provider
- `components/ErrorBoundary.tsx` — Global error boundary
- `components/OfflineIndicator.tsx` — Offline banner
- `hooks/useOptimisticToggle.ts` — Optimistic update pattern
- `hooks/useFssaiPolling.ts` — FSSAI polling with auto-stop
- `hooks/useOfflineQueue.ts` — Offline mutation queueing
- `hooks/useMutationErrorHandler.ts` — Error handling in mutations
- `app/layout.tsx` — Root provider setup
- `app/(seller)/error.tsx` — Seller error boundary
- `app/(admin)/error.tsx` — Admin error boundary (mirrored)