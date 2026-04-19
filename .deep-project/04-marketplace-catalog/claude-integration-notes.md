# Integration Notes: Opus Review → claude-plan.md

## Changes Integrated

### P0: `vendor_profile` related name (Issue 6.3)
**Integrating.** Verified in `03-seller-onboarding/spec.md` line 42: `related_name='vendor_profile'`. All references to `request.user.vendor` corrected to `request.user.vendor_profile`.

Note: The first Opus session claimed a `VendorCommunity` M2M join table exists. This was **incorrect** — the spec shows a direct `Vendor.community` FK. The P0 multi-community issue from that session is a false alarm and not integrated.

### P0: Cursor pagination + ordering conflict (Issue 2.2)
**Integrating.** `CursorPagination` is incompatible with client-controlled ordering. Fix: the ViewSet uses `CursorPagination` by default (for stable, default `ordering=-created_at` browse). When the client supplies an `ordering` query parameter, the ViewSet overrides `pagination_class` to `LimitOffsetPagination` for that request. This is implemented by overriding `paginator_class` as a property on the ViewSet that checks for `ordering` in `request.query_params`.

### P0: DailyInventory COALESCE for missing rows (Issue 1.6)
**Integrating.** The `is_available_today` subquery must wrap `qty_ordered` in `Coalesce(..., 0)` so products with no DailyInventory row for today are treated as having 0 orders (i.e., fully available). Without this, the subquery returns NULL which propagates to incorrect availability results. Plan updated in Section 5 and Key Invariants.

### P1: `vendor_profile` in Celery Beat task path (Issue 7.2)
**Integrating.** The Beat schedule task path must match Celery's autodiscovered module path. Since Django apps are in `apps/`, the registered task name is `apps.catalogue.tasks.expire_flash_sales`, not `catalogue.tasks.expire_flash_sales`. Plan updated in Section 3.

### P1: FSSAI gate bypassable via Django Admin (Issue 3.1)
**Integrating.** The FSSAI validation (and GSTIN validation) must also be enforced at the model level via `Product.clean()` so Django Admin cannot bypass it. Plan updated in Section 7 and Key Invariants.

### P1: GSTIN enforcement gap (Issue 1.7)
**Integrating.** If `category.requires_gstin=True`, the create endpoint must also validate that `vendor.gstin` is not blank. This is the same pattern as the FSSAI gate. Plan updated in Section 7.

### P1: Image decompression bomb protection (Issue 3.4)
**Integrating.** Plan now specifies setting `Image.MAX_IMAGE_PIXELS = 50_000_000` (roughly 7000×7000 at 1 byte/px) at the top of `utils.py` to prevent Pillow decompression bombs. Also specifies using `Image.open()` for format verification (not relying on Content-Type header). Plan updated in Section 2 and Section 8.

### P1: delivery_days ORM lookup syntax (Issue 2.1)
**Integrating.** Specify the exact PostgreSQL JSONB `@>` (contains) lookup: `delivery_days__contains=[weekday_int]` — the value must be a list `[2]`, not a bare integer `2`. Plan updated in Section 5.

### P1: `is_available_today` subquery specification (Issue 4.2)
**Integrating.** The annotation logic is clarified: annotate `today_qty_ordered` using `Coalesce(Subquery(...), 0)`. The full `is_available_today` boolean check (delivery_days, window, qty) is computed in Python in the serializer using the annotated value, rather than as a single complex SQL annotation. This is Option A from the Opus review — simpler and easier to maintain. Plan updated.

### P2: `expire_flash_sales` should also null `flash_sale_qty` (Issue 5.5 / 18)
**Integrating.** The task should null all four flash sale fields: `is_flash_sale=False`, `flash_sale_qty=None`, `flash_sale_qty_remaining=None`, `flash_sale_ends_at=None`. Plan updated in Section 3.

### P2: Migration dependency chain (Issue 5.2)
**Integrating.** Specify that `0001_initial.py` must declare `dependencies = [('communities', 'XXXX_initial'), ('vendors', 'XXXX_initial')]`. Plan updated in Section 11.

### P2: Thumbnail S3 orphan note (Issue 15 / S3 lifecycle)
**Integrating.** Clarified that image deletion orphans 3 S3 objects (original + 2 thumbnails), not 1. S3 lifecycle policy should be set on the `media/products/` prefix.

### P2: boto3 client caching for presigned URLs (Issue 4.1)
**Integrating.** The `get_presigned_url` utility should reuse a module-level boto3 client instead of creating a new one per call. Plan updated in Section 2.

### P2: `is_active=False` default (Issue 6.1)
**Integrating.** Explicitly call out that this overrides the spec's `default=True`. Plan updated in Section 1.

---

## Not Integrating

### VendorCommunity multi-community model (Session 1, P0)
**Not integrating.** The `03-seller-onboarding/spec.md` defines `Vendor.community` as a direct FK (one vendor, one community). There is no `VendorCommunity` join table. The first Opus session was operating on incorrect assumptions about the spec. `IsApprovedVendor` checks `vendor.status == VendorStatus.APPROVED` against the top-level Vendor model, which is correct per spec.

### Missing `price` and `unit` fields (Issue 1.2)
**Not integrating as plan change.** The spec model block is the canonical source for field lists. Adding these to the prose plan would duplicate the spec. The plan references the spec for exact field definitions.

### Flash sale price field (Issue 1.3)
**Not integrating.** NammaNeighbor flash sales are quantity-limited drops (e.g., "only 10kg available today"), not necessarily price-discounted. The spec never mentions a `flash_sale_price` field. The existing `price` field serves as the sale price. This is the intended design.

### WebP re-encoding of existing WebP (Issue 4.3)
**Not integrating.** The user explicitly confirmed in the interview (Q10): "Convert everything to WebP — consistent format, better compression." Re-encoding is intentional even at the cost of minor quality loss.

### Overnight availability windows (Issue 6.2)
**Not integrating.** `available_from < available_to` validation is intentional. Overnight windows are not a use case for NammaNeighbor (vendors operate on day-shift windows).

### Flash sale cancellation endpoint (Issue 6.4)
**Not integrating.** Intentional omission. Vendors/admins can let the expiry task handle cancellation, or set `ends_at` to a near-future time when activating. Adding a cancel endpoint is out of scope for this split.

### Flash sale write contention (Issue 7.1)
**Not integrating.** The spec mandates inline flash sale fields on Product. Separating them into a `FlashSale` model would deviate from the spec. The known contention risk is acceptable for MVP traffic levels.

### No search endpoint (Issue 2.5)
**Not integrating.** Text search is out of scope for this split. The `ordering` and filter capabilities are sufficient for MVP catalog browsing.

### Rate limiting on image upload (Issue 3.3)
**Not integrating.** `django-ratelimit` is in the project but configuring it for vendor endpoints is a cross-cutting concern for split 01 or a dedicated auth hardening task. Not core to this split.

### Consolidated order sheet app placement (Issue 2.4)
**Not integrating.** The stub URL in catalogue is intentional — split 05 will override the view implementation without changing the URL. This avoids a URL refactor.

### Product update race conditions (Issue 5.4)
**Not integrating.** The flash sale stock decrement race is handled by split 05. Vendor product edits are low-frequency and don't need optimistic locking for MVP.

### `description` field omission (Issue 1.5)
**Not integrating.** Minor gap; the spec is the authoritative field list. `description` is included in `ProductDetailSerializer` implicitly.
