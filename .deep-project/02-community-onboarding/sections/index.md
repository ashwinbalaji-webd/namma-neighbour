<!-- PROJECT_CONFIG
runtime: python-uv
test_command: uv run pytest apps/communities/
END_PROJECT_CONFIG -->

<!-- SECTION_MANIFEST
section-01-models-migration
section-02-serializers
section-03-community-views
section-04-join-approval-views
section-05-admin-views
section-06-urls-permissions
section-07-django-admin
section-08-tests
END_MANIFEST -->

# Implementation Sections Index: 02-Community Onboarding

## Dependency Graph

| Section | Depends On | Blocks | Parallelizable |
|---------|------------|--------|----------------|
| section-01-models-migration | — | 02, 03, 04, 05, 06, 07, 08 | No |
| section-02-serializers | 01 | 03, 04, 05 | No |
| section-03-community-views | 02 | 06 | Yes |
| section-04-join-approval-views | 02 | 06 | Yes |
| section-05-admin-views | 02 | 06 | Yes |
| section-06-urls-permissions | 03, 04, 05 | 08 | No |
| section-07-django-admin | 01 | 08 | Yes (parallel with 02–05) |
| section-08-tests | 06, 07 | — | No |

## Execution Order

1. **section-01-models-migration** (foundational — all models + migration)
2. **section-02-serializers** + **section-07-django-admin** (parallel — both only need models)
3. **section-03-community-views** + **section-04-join-approval-views** + **section-05-admin-views** (parallel — all need serializers)
4. **section-06-urls-permissions** (after all views are done)
5. **section-08-tests** (final — needs complete wiring)

## Section Summaries

### section-01-models-migration
Replace the `Community` stub from split 01 with the full model. Add `Building`, `Flat`, and `ResidentProfile` models. Write the Django migration handling the schema expansion without data loss. Includes model-level validation helpers (invite_code generation, slug generation, floor inference).

### section-02-serializers
All DRF serializers: `CommunityRegistrationSerializer`, `CommunityDetailSerializer`, `BuildingSerializer`, `FlatSerializer`, `JoinCommunitySerializer`, `ResidentProfileSerializer`, `ResidentApprovalSerializer`. Serializer validation logic lives here (pincode regex, invite_code lookup, duplicate join check).

### section-03-community-views
`CommunityRegisterView`, `CommunityDetailView`, `BuildingListView`. Covers the registration flow (atomic community + buildings creation, UserRole assignment, JWT reissuance) and the public read endpoints.

### section-04-join-approval-views
`JoinCommunityView`, `ResidentListView`, `ResidentApproveView`, `ResidentRejectView`. The core resident onboarding flow: join with invite code, get-or-create Flat, create PENDING ResidentProfile, increment resident_count via F(), reissue JWT. Plus the admin approval/rejection endpoints.

### section-05-admin-views
`CommunitySettingsView` (PATCH — commission_pct, add buildings, deactivate) and `InviteRegenerateView` (POST). Both require `IsCommunityAdmin` + community_id guard.

### section-06-urls-permissions
`apps/communities/urls.py` wiring all views to their URL patterns. Include statement in `config/urls.py`. Verify `IsCommunityAdmin` cross-community guard helper (`get_community_or_403`). `AnonRateThrottle` on public endpoints.

### section-07-django-admin
Custom `ModelAdmin` for `Community` (list display, actions: deactivate, mark reviewed, regenerate invite, BuildingInline) and `ResidentProfile` (list display, approve/reject actions, filters by status/community).

### section-08-tests
Test factories (`CommunityFactory`, `BuildingFactory`, `FlatFactory`, `ResidentProfileFactory`), `conftest.py` fixtures, `test_models.py` (constraint tests), `test_views.py` (full API surface — registration, join, approval, permissions, JWT claims, counter increments, edge cases).
