diff --git a/namma_neighbor/apps/communities/urls.py b/namma_neighbor/apps/communities/urls.py
index 4bfa2a29..df556751 100644
--- a/namma_neighbor/apps/communities/urls.py
+++ b/namma_neighbor/apps/communities/urls.py
@@ -11,12 +11,14 @@ from apps.communities.views import (
     ResidentListView,
     ResidentRejectView,
 )
+from apps.vendors.views import CommunityPendingVendorsView
 
 app_name = "communities"
 
 urlpatterns = [
     path("register/", CommunityRegisterView.as_view(), name="register"),
     path("join/", JoinCommunityView.as_view(), name="join"),
+    path("<slug:slug>/vendors/pending/", CommunityPendingVendorsView.as_view(), name="community-pending-vendors"),
     path("<slug:slug>/", CommunityDetailView.as_view(), name="detail"),
     path("<slug:slug>/buildings/", BuildingListView.as_view(), name="buildings"),
     path("<slug:slug>/residents/", ResidentListView.as_view(), name="resident-list"),
diff --git a/namma_neighbor/apps/vendors/tasks.py b/namma_neighbor/apps/vendors/tasks.py
index 274a5080..b54df799 100644
--- a/namma_neighbor/apps/vendors/tasks.py
+++ b/namma_neighbor/apps/vendors/tasks.py
@@ -13,3 +13,8 @@ def recheck_fssai_expiry() -> None:
 @shared_task
 def verify_fssai(vendor_pk: int) -> None:
     logger.warning("verify_fssai: not yet implemented (vendor_pk=%s)", vendor_pk)
+
+
+@shared_task
+def create_razorpay_linked_account(vendor_pk: int) -> None:
+    logger.warning("create_razorpay_linked_account: not yet implemented (vendor_pk=%s)", vendor_pk)
diff --git a/namma_neighbor/apps/vendors/tests/test_views.py b/namma_neighbor/apps/vendors/tests/test_views.py
index 3e4d1cd9..ee3a6929 100644
--- a/namma_neighbor/apps/vendors/tests/test_views.py
+++ b/namma_neighbor/apps/vendors/tests/test_views.py
@@ -327,3 +327,387 @@ def test_status_returns_403_for_wrong_user(vendor_user):
     other.force_authenticate(user=UserFactory())
     resp = other.get(status_url(vendor.pk))
     assert resp.status_code == 403
+
+
+# ─── Admin Workflow Fixtures ───────────────────────────────────────────────────
+
+class MockToken:
+    def __init__(self, *roles):
+        self.payload = {"roles": list(roles)}
+
+
+@pytest.fixture
+def admin_user(db):
+    from apps.users.tests.factories import UserFactory
+    return UserFactory()
+
+
+@pytest.fixture
+def admin_community(admin_user):
+    from apps.users.models import UserRole
+    community = CommunityFactory()
+    UserRole.objects.create(user=admin_user, role="community_admin", community=community)
+    return community
+
+
+@pytest.fixture
+def admin_client(admin_user):
+    client = APIClient()
+    client.force_authenticate(user=admin_user, token=MockToken("community_admin"))
+    return client
+
+
+@pytest.fixture
+def resident_user(db):
+    from apps.users.tests.factories import UserFactory
+    return UserFactory()
+
+
+@pytest.fixture
+def resident_client(resident_user):
+    client = APIClient()
+    client.force_authenticate(user=resident_user, token=MockToken("resident"))
+    return client
+
+
+def pending_url(slug):
+    return f"/api/v1/communities/{slug}/vendors/pending/"
+
+
+def approve_url(vendor_id):
+    return f"/api/v1/vendors/{vendor_id}/approve/"
+
+
+def reject_url(vendor_id):
+    return f"/api/v1/vendors/{vendor_id}/reject/"
+
+
+def profile_url(vendor_id):
+    return f"/api/v1/vendors/{vendor_id}/profile/"
+
+
+# ─── GET /api/v1/communities/{slug}/vendors/pending/ ──────────────────────────
+
+@pytest.mark.django_db
+def test_pending_returns_only_pending_review_in_community(admin_client, admin_community, admin_user):
+    vc1 = VendorCommunityFactory(community=admin_community, status=VendorCommunityStatus.PENDING_REVIEW)
+    vc2 = VendorCommunityFactory(community=admin_community, status=VendorCommunityStatus.PENDING_REVIEW)
+    VendorCommunityFactory(community=admin_community, status=VendorCommunityStatus.APPROVED)
+    resp = admin_client.get(pending_url(admin_community.slug))
+    assert resp.status_code == 200
+    assert resp.json()["count"] == 2
+
+
+@pytest.mark.django_db
+def test_pending_excludes_other_community_vendors(admin_client, admin_community):
+    VendorCommunityFactory(community=admin_community, status=VendorCommunityStatus.PENDING_REVIEW)
+    other_community = CommunityFactory()
+    other_vc = VendorCommunityFactory(community=other_community, status=VendorCommunityStatus.PENDING_REVIEW)
+    resp = admin_client.get(pending_url(admin_community.slug))
+    assert resp.status_code == 200
+    vendor_ids = [r["vendor_id"] for r in resp.json()["results"]]
+    assert other_vc.vendor.pk not in vendor_ids
+
+
+@pytest.mark.django_db
+@patch("apps.vendors.serializers.generate_document_presigned_url")
+def test_pending_includes_presigned_urls_for_non_empty_keys(mock_presign, admin_client, admin_community):
+    mock_presign.return_value = "https://s3.example.com/signed"
+    vendor = VendorFactory(govt_id_s3_key="documents/vendors/1/govt_id.pdf", bank_proof_s3_key="")
+    VendorCommunityFactory(vendor=vendor, community=admin_community, status=VendorCommunityStatus.PENDING_REVIEW)
+    resp = admin_client.get(pending_url(admin_community.slug))
+    assert resp.status_code == 200
+    result = resp.json()["results"][0]
+    assert result["document_urls"].get("govt_id") == "https://s3.example.com/signed"
+    assert "bank_proof" not in result["document_urls"]
+
+
+@pytest.mark.django_db
+def test_pending_fssai_warning_true_when_failed(admin_client, admin_community):
+    vendor = VendorFactory(fssai_status=FSSAIStatus.FAILED)
+    VendorCommunityFactory(vendor=vendor, community=admin_community, status=VendorCommunityStatus.PENDING_REVIEW)
+    resp = admin_client.get(pending_url(admin_community.slug))
+    assert resp.status_code == 200
+    assert resp.json()["results"][0]["fssai_warning"] is True
+
+
+@pytest.mark.django_db
+def test_pending_fssai_warning_false_when_verified(admin_client, admin_community):
+    vendor = VendorFactory(fssai_status=FSSAIStatus.VERIFIED)
+    VendorCommunityFactory(vendor=vendor, community=admin_community, status=VendorCommunityStatus.PENDING_REVIEW)
+    resp = admin_client.get(pending_url(admin_community.slug))
+    assert resp.status_code == 200
+    assert resp.json()["results"][0]["fssai_warning"] is False
+
+
+@pytest.mark.django_db
+def test_pending_paginated_page_size_10(admin_client, admin_community):
+    for _ in range(11):
+        VendorCommunityFactory(community=admin_community, status=VendorCommunityStatus.PENDING_REVIEW)
+    resp = admin_client.get(pending_url(admin_community.slug))
+    assert resp.status_code == 200
+    data = resp.json()
+    assert data["count"] == 11
+    assert len(data["results"]) == 10
+    assert data["next"] is not None
+
+
+@pytest.mark.django_db
+def test_pending_returns_403_for_non_admin(resident_client, admin_community):
+    resp = resident_client.get(pending_url(admin_community.slug))
+    assert resp.status_code == 403
+
+
+# ─── POST /api/v1/vendors/{vendor_id}/approve/ ────────────────────────────────
+
+@pytest.mark.django_db
+@patch("apps.vendors.views.create_razorpay_linked_account")
+def test_approve_transitions_status_to_approved(mock_task, admin_client, admin_community):
+    vc = VendorCommunityFactory(community=admin_community, status=VendorCommunityStatus.PENDING_REVIEW)
+    resp = admin_client.post(approve_url(vc.vendor.pk), {
+        "community_slug": admin_community.slug,
+        "override_fssai_warning": False,
+    }, format="json")
+    assert resp.status_code == 200
+    vc.refresh_from_db()
+    assert vc.status == VendorCommunityStatus.APPROVED
+
+
+@pytest.mark.django_db
+@patch("apps.vendors.views.create_razorpay_linked_account")
+def test_approve_sets_approved_by_and_approved_at(mock_task, admin_client, admin_community, admin_user):
+    vc = VendorCommunityFactory(community=admin_community, status=VendorCommunityStatus.PENDING_REVIEW)
+    admin_client.post(approve_url(vc.vendor.pk), {
+        "community_slug": admin_community.slug,
+        "override_fssai_warning": False,
+    }, format="json")
+    vc.refresh_from_db()
+    assert vc.approved_by == admin_user
+    assert vc.approved_at is not None
+
+
+@pytest.mark.django_db
+@patch("apps.vendors.views.create_razorpay_linked_account")
+def test_approve_increments_vendor_count(mock_task, admin_client, admin_community):
+    initial = admin_community.vendor_count
+    vc = VendorCommunityFactory(community=admin_community, status=VendorCommunityStatus.PENDING_REVIEW)
+    admin_client.post(approve_url(vc.vendor.pk), {
+        "community_slug": admin_community.slug,
+        "override_fssai_warning": False,
+    }, format="json")
+    admin_community.refresh_from_db()
+    assert admin_community.vendor_count == initial + 1
+
+
+@pytest.mark.django_db
+@patch("apps.vendors.views.create_razorpay_linked_account")
+def test_approve_creates_vendor_user_role(mock_task, admin_client, admin_community):
+    from apps.users.models import UserRole
+    vc = VendorCommunityFactory(community=admin_community, status=VendorCommunityStatus.PENDING_REVIEW)
+    admin_client.post(approve_url(vc.vendor.pk), {
+        "community_slug": admin_community.slug,
+        "override_fssai_warning": False,
+    }, format="json")
+    assert UserRole.objects.filter(
+        user=vc.vendor.user, role="vendor", community=admin_community
+    ).exists()
+
+
+@pytest.mark.django_db
+@patch("apps.vendors.views.create_razorpay_linked_account")
+def test_approve_vendor_role_not_duplicated(mock_task, admin_client, admin_community):
+    from apps.users.models import UserRole
+    vc = VendorCommunityFactory(community=admin_community, status=VendorCommunityStatus.PENDING_REVIEW)
+    payload = {"community_slug": admin_community.slug, "override_fssai_warning": False}
+    admin_client.post(approve_url(vc.vendor.pk), payload, format="json")
+    VendorCommunity.objects.filter(pk=vc.pk).update(status=VendorCommunityStatus.PENDING_REVIEW)
+    admin_client.post(approve_url(vc.vendor.pk), payload, format="json")
+    assert UserRole.objects.filter(
+        user=vc.vendor.user, role="vendor", community=admin_community
+    ).count() == 1
+
+
+@pytest.mark.django_db
+@patch("apps.vendors.views.create_razorpay_linked_account")
+def test_approve_enqueues_razorpay_task_on_first_approval(mock_task, admin_client, admin_community):
+    vendor = VendorFactory(razorpay_onboarding_step="")
+    VendorCommunityFactory(vendor=vendor, community=admin_community, status=VendorCommunityStatus.PENDING_REVIEW)
+    admin_client.post(approve_url(vendor.pk), {
+        "community_slug": admin_community.slug,
+        "override_fssai_warning": False,
+    }, format="json")
+    mock_task.delay.assert_called_once_with(vendor.pk)
+
+
+@pytest.mark.django_db
+@patch("apps.vendors.views.create_razorpay_linked_account")
+def test_approve_skips_razorpay_task_when_already_onboarded(mock_task, admin_client, admin_community):
+    vendor = VendorFactory(razorpay_onboarding_step="submitted")
+    VendorCommunityFactory(vendor=vendor, community=admin_community, status=VendorCommunityStatus.PENDING_REVIEW)
+    admin_client.post(approve_url(vendor.pk), {
+        "community_slug": admin_community.slug,
+        "override_fssai_warning": False,
+    }, format="json")
+    mock_task.delay.assert_not_called()
+
+
+@pytest.mark.django_db
+@patch("apps.vendors.views.create_razorpay_linked_account")
+def test_approve_returns_400_fssai_failed_no_override(mock_task, admin_client, admin_community):
+    vendor = VendorFactory(fssai_status=FSSAIStatus.FAILED)
+    VendorCommunityFactory(vendor=vendor, community=admin_community, status=VendorCommunityStatus.PENDING_REVIEW)
+    resp = admin_client.post(approve_url(vendor.pk), {
+        "community_slug": admin_community.slug,
+        "override_fssai_warning": False,
+    }, format="json")
+    assert resp.status_code == 400
+
+
+@pytest.mark.django_db
+@patch("apps.vendors.views.create_razorpay_linked_account")
+def test_approve_proceeds_fssai_failed_with_override(mock_task, admin_client, admin_community):
+    vendor = VendorFactory(fssai_status=FSSAIStatus.FAILED)
+    VendorCommunityFactory(vendor=vendor, community=admin_community, status=VendorCommunityStatus.PENDING_REVIEW)
+    resp = admin_client.post(approve_url(vendor.pk), {
+        "community_slug": admin_community.slug,
+        "override_fssai_warning": True,
+    }, format="json")
+    assert resp.status_code == 200
+    vc = VendorCommunity.objects.get(vendor=vendor, community=admin_community)
+    assert vc.status == VendorCommunityStatus.APPROVED
+
+
+@pytest.mark.django_db
+@patch("apps.vendors.views.create_razorpay_linked_account")
+def test_approve_returns_403_for_other_community(mock_task, admin_client, admin_community):
+    other = CommunityFactory()
+    vc = VendorCommunityFactory(community=other, status=VendorCommunityStatus.PENDING_REVIEW)
+    resp = admin_client.post(approve_url(vc.vendor.pk), {
+        "community_slug": other.slug,
+        "override_fssai_warning": False,
+    }, format="json")
+    assert resp.status_code == 403
+
+
+@pytest.mark.django_db
+@patch("apps.vendors.views.create_razorpay_linked_account")
+def test_approve_returns_404_when_not_pending(mock_task, admin_client, admin_community):
+    vc = VendorCommunityFactory(community=admin_community, status=VendorCommunityStatus.APPROVED)
+    resp = admin_client.post(approve_url(vc.vendor.pk), {
+        "community_slug": admin_community.slug,
+        "override_fssai_warning": False,
+    }, format="json")
+    assert resp.status_code == 404
+
+
+# ─── POST /api/v1/vendors/{vendor_id}/reject/ ─────────────────────────────────
+
+@pytest.mark.django_db
+def test_reject_transitions_status_to_rejected(admin_client, admin_community):
+    vc = VendorCommunityFactory(community=admin_community, status=VendorCommunityStatus.PENDING_REVIEW)
+    resp = admin_client.post(reject_url(vc.vendor.pk), {
+        "community_slug": admin_community.slug,
+        "reason": "FSSAI expired",
+    }, format="json")
+    assert resp.status_code == 200
+    vc.refresh_from_db()
+    assert vc.status == VendorCommunityStatus.REJECTED
+
+
+@pytest.mark.django_db
+def test_reject_stores_rejection_reason(admin_client, admin_community):
+    vc = VendorCommunityFactory(community=admin_community, status=VendorCommunityStatus.PENDING_REVIEW)
+    admin_client.post(reject_url(vc.vendor.pk), {
+        "community_slug": admin_community.slug,
+        "reason": "FSSAI expired",
+    }, format="json")
+    vc.refresh_from_db()
+    assert vc.rejection_reason == "FSSAI expired"
+
+
+@pytest.mark.django_db
+@patch("apps.vendors.views.create_razorpay_linked_account")
+def test_reject_decrements_vendor_count_when_was_approved(mock_task, admin_client, admin_community):
+    vc = VendorCommunityFactory(community=admin_community, status=VendorCommunityStatus.APPROVED)
+    from apps.communities.models import Community
+    Community.objects.filter(pk=admin_community.pk).update(vendor_count=1)
+    admin_client.post(reject_url(vc.vendor.pk), {
+        "community_slug": admin_community.slug,
+        "reason": "expired",
+    }, format="json")
+    admin_community.refresh_from_db()
+    assert admin_community.vendor_count == 0
+
+
+@pytest.mark.django_db
+def test_reject_does_not_decrement_count_when_pending(admin_client, admin_community):
+    from apps.communities.models import Community
+    Community.objects.filter(pk=admin_community.pk).update(vendor_count=5)
+    vc = VendorCommunityFactory(community=admin_community, status=VendorCommunityStatus.PENDING_REVIEW)
+    admin_client.post(reject_url(vc.vendor.pk), {
+        "community_slug": admin_community.slug,
+        "reason": "docs missing",
+    }, format="json")
+    admin_community.refresh_from_db()
+    assert admin_community.vendor_count == 5
+
+
+@pytest.mark.django_db
+def test_reject_returns_403_for_other_community(admin_client, admin_community):
+    other = CommunityFactory()
+    vc = VendorCommunityFactory(community=other, status=VendorCommunityStatus.PENDING_REVIEW)
+    resp = admin_client.post(reject_url(vc.vendor.pk), {
+        "community_slug": other.slug,
+        "reason": "nope",
+    }, format="json")
+    assert resp.status_code == 403
+
+
+@pytest.mark.django_db
+def test_reject_vendor_can_resubmit(admin_client, admin_community, vendor_user):
+    vendor = VendorFactory(user=vendor_user, govt_id_s3_key="k1", bank_proof_s3_key="k2")
+    vc = VendorCommunityFactory(vendor=vendor, community=admin_community, status=VendorCommunityStatus.PENDING_REVIEW)
+    admin_client.post(reject_url(vendor.pk), {
+        "community_slug": admin_community.slug,
+        "reason": "docs expired",
+    }, format="json")
+    vendor_client = APIClient()
+    vendor_client.force_authenticate(user=vendor_user)
+    resp = vendor_client.post(submit_url(vendor.pk), {"community_slug": admin_community.slug}, format="json")
+    assert resp.status_code == 200
+    vc.refresh_from_db()
+    assert vc.status == VendorCommunityStatus.PENDING_REVIEW
+
+
+# ─── GET /api/v1/vendors/{vendor_id}/profile/ ─────────────────────────────────
+
+@pytest.mark.django_db
+def test_profile_returns_display_safe_fields(resident_client):
+    vendor = VendorFactory()
+    resp = resident_client.get(profile_url(vendor.pk))
+    assert resp.status_code == 200
+    data = resp.json()
+    assert set(data.keys()) == {"vendor_id", "display_name", "bio", "average_rating", "is_new_seller"}
+
+
+@pytest.mark.django_db
+def test_profile_does_not_expose_sensitive_fields(resident_client):
+    vendor = VendorFactory(
+        govt_id_s3_key="sec", bank_proof_s3_key="sec",
+        fssai_cert_s3_key="sec", gst_cert_s3_key="sec",
+    )
+    resp = resident_client.get(profile_url(vendor.pk))
+    data = resp.json()
+    sensitive = {"fssai_number", "razorpay_account_id", "govt_id_s3_key",
+                 "bank_proof_s3_key", "fssai_cert_s3_key", "gst_cert_s3_key", "bank_account_verified"}
+    assert not sensitive.intersection(data.keys())
+
+
+@pytest.mark.django_db
+def test_profile_returns_403_for_non_resident():
+    from apps.users.tests.factories import UserFactory
+    no_role_client = APIClient()
+    no_role_client.force_authenticate(user=UserFactory(), token=MockToken())
+    vendor = VendorFactory()
+    resp = no_role_client.get(profile_url(vendor.pk))
+    assert resp.status_code == 403
diff --git a/namma_neighbor/apps/vendors/urls.py b/namma_neighbor/apps/vendors/urls.py
index bd0655a6..8ab943d8 100644
--- a/namma_neighbor/apps/vendors/urls.py
+++ b/namma_neighbor/apps/vendors/urls.py
@@ -2,7 +2,10 @@ from django.urls import path
 
 from apps.vendors.views import (
     DocumentUploadView,
+    VendorApproveView,
+    VendorPublicProfileView,
     VendorRegistrationView,
+    VendorRejectView,
     VendorStatusView,
     VendorSubmitView,
 )
@@ -12,4 +15,7 @@ urlpatterns = [
     path("<int:vendor_id>/documents/", DocumentUploadView.as_view(), name="vendor-documents"),
     path("<int:vendor_id>/submit/", VendorSubmitView.as_view(), name="vendor-submit"),
     path("<int:vendor_id>/status/", VendorStatusView.as_view(), name="vendor-status"),
+    path("<int:vendor_id>/approve/", VendorApproveView.as_view(), name="vendor-approve"),
+    path("<int:vendor_id>/reject/", VendorRejectView.as_view(), name="vendor-reject"),
+    path("<int:vendor_id>/profile/", VendorPublicProfileView.as_view(), name="vendor-profile"),
 ]
diff --git a/namma_neighbor/apps/vendors/views.py b/namma_neighbor/apps/vendors/views.py
index 7dd6b8ad..6c4f50c7 100644
--- a/namma_neighbor/apps/vendors/views.py
+++ b/namma_neighbor/apps/vendors/views.py
@@ -1,20 +1,29 @@
 import re
 
+from django.db import transaction
+from django.db.models import F
 from django.http import Http404
 from django.shortcuts import get_object_or_404
+from django.utils import timezone
+from rest_framework import generics
+from rest_framework.exceptions import PermissionDenied
+from rest_framework.pagination import PageNumberPagination
 from rest_framework.permissions import IsAuthenticated
 from rest_framework.response import Response
 from rest_framework.views import APIView
 
-from apps.core.permissions import IsVendorOwner
+from apps.core.permissions import IsCommunityAdmin, IsResidentOfCommunity, IsVendorOwner
+from apps.users.models import UserRole
 from apps.vendors.models import FSSAIStatus, Vendor, VendorCommunity, VendorCommunityStatus
 from apps.vendors.serializers import (
     DocumentUploadSerializer,
+    PendingVendorSerializer,
+    VendorPublicProfileSerializer,
     VendorRegistrationSerializer,
     VendorStatusSerializer,
 )
 from apps.vendors.services.storage import upload_vendor_document
-from apps.vendors.tasks import verify_fssai
+from apps.vendors.tasks import create_razorpay_linked_account, verify_fssai
 
 _FSSAI_NUMBER_RE = re.compile(r"^\d{14}$")
 
@@ -170,3 +179,184 @@ class VendorStatusView(APIView):
         self.check_object_permissions(request, vendor)
         serializer = VendorStatusSerializer(vendor)
         return Response(serializer.data)
+
+
+# ─── Admin Workflow Views ──────────────────────────────────────────────────────
+
+class _AdminPagination(PageNumberPagination):
+    page_size = 10
+
+
+class CommunityPendingVendorsView(generics.ListAPIView):
+    """
+    Returns a paginated list of VendorCommunity records with status=pending_review
+    for a given community. Used by community admins to review vendor applications.
+
+    Each entry includes presigned S3 document URLs (TTL=3600s) and an fssai_warning
+    flag. Presigned URL generation is CPU-bound (HMAC, no network) and safe for
+    synchronous request handling at page_size=10.
+
+    Pagination: page_size=10 (PageNumberPagination).
+
+    Returns:
+        200: paginated list of PendingVendorSerializer responses
+        403: not a community admin
+        404: community not found
+    """
+    serializer_class = PendingVendorSerializer
+    permission_classes = [IsAuthenticated, IsCommunityAdmin]
+    pagination_class = _AdminPagination
+
+    def get_queryset(self):
+        from apps.communities.models import Community
+        slug = self.kwargs["slug"]
+        community = get_object_or_404(Community, slug=slug)
+        if not UserRole.objects.filter(
+            user=self.request.user, role="community_admin", community=community
+        ).exists():
+            raise PermissionDenied()
+        return VendorCommunity.objects.filter(
+            community=community, status=VendorCommunityStatus.PENDING_REVIEW
+        ).select_related("vendor").order_by("created_at")
+
+
+class VendorApproveView(APIView):
+    """
+    Approves a vendor's application for a specific community.
+
+    Business logic:
+    1. Resolve community_slug → Community; 404 if not found.
+    2. Cross-check: verify request.user is admin of the resolved community (not just any community).
+       Return 403 if the community_slug resolves to a community the user does not admin.
+    3. Retrieve VendorCommunity for (vendor, community) where status=pending_review. 404 otherwise.
+    4. FSSAI guard: if vendor.fssai_status == 'failed' and override_fssai_warning != True, return 400.
+    5. Atomic update:
+       a. VendorCommunity.status → approved; set approved_by=request.user, approved_at=now()
+       b. community.vendor_count incremented atomically (F() expression)
+       c. UserRole.objects.get_or_create(user=vendor.user, role='vendor', community=community)
+       d. If vendor.razorpay_onboarding_step == '': enqueue create_razorpay_linked_account.delay(vendor.pk)
+
+    Returns:
+        200: {status: 'approved'}
+        400: FSSAI guard triggered (fssai_status='failed', no override)
+        403: not admin of this community
+        404: community not found, or VendorCommunity not in pending_review
+    """
+    permission_classes = [IsAuthenticated, IsCommunityAdmin]
+
+    def post(self, request, vendor_id):
+        from apps.communities.models import Community
+        community_slug = request.data.get("community_slug", "")
+        community = get_object_or_404(Community, slug=community_slug)
+
+        if not UserRole.objects.filter(
+            user=request.user, role="community_admin", community=community
+        ).exists():
+            raise PermissionDenied()
+
+        vendor = get_object_or_404(Vendor, pk=vendor_id)
+        vc = get_object_or_404(
+            VendorCommunity,
+            vendor=vendor,
+            community=community,
+            status=VendorCommunityStatus.PENDING_REVIEW,
+        )
+
+        override_fssai = request.data.get("override_fssai_warning", False)
+        if vendor.fssai_status == FSSAIStatus.FAILED and not override_fssai:
+            return Response(
+                {"detail": "FSSAI verification failed. Set override_fssai_warning=true to proceed."},
+                status=400,
+            )
+
+        with transaction.atomic():
+            VendorCommunity.objects.filter(pk=vc.pk).update(
+                status=VendorCommunityStatus.APPROVED,
+                approved_by_id=request.user.pk,
+                approved_at=timezone.now(),
+            )
+            Community.objects.filter(pk=community.pk).update(vendor_count=F("vendor_count") + 1)
+            UserRole.objects.get_or_create(
+                user=vendor.user, role="vendor", community=community
+            )
+            vendor.refresh_from_db(fields=["razorpay_onboarding_step"])
+            if vendor.razorpay_onboarding_step == "":
+                create_razorpay_linked_account.delay(vendor.pk)
+
+        # TODO: enqueue SMS notification to vendor (split 05)
+        return Response({"status": VendorCommunityStatus.APPROVED})
+
+
+class VendorRejectView(APIView):
+    """
+    Rejects a vendor's application for a specific community.
+
+    Business logic:
+    1. Resolve community_slug → Community; 404 if not found.
+    2. Cross-check: verify request.user is admin of the resolved community. 403 if not.
+    3. Retrieve VendorCommunity for (vendor, community). Records in pending_review OR
+       approved can be rejected. 404 if the record does not exist.
+    4. Capture previous_status = vc.status before updating.
+    5. Atomic update: status → rejected; rejection_reason = reason.
+    6. If previous_status == 'approved': decrement community.vendor_count atomically.
+       (vendor_count represents current active/approved vendors, not lifetime count.)
+
+    The vendor can update their documents and re-submit after rejection. The same
+    VendorCommunity record is reused; VendorSubmitView resets status to pending_review.
+
+    Returns:
+        200: {status: 'rejected'}
+        403: not admin of this community
+        404: community not found, or VendorCommunity not found
+    """
+    permission_classes = [IsAuthenticated, IsCommunityAdmin]
+
+    def post(self, request, vendor_id):
+        from apps.communities.models import Community
+        community_slug = request.data.get("community_slug", "")
+        community = get_object_or_404(Community, slug=community_slug)
+
+        if not UserRole.objects.filter(
+            user=request.user, role="community_admin", community=community
+        ).exists():
+            raise PermissionDenied()
+
+        vendor = get_object_or_404(Vendor, pk=vendor_id)
+        vc = get_object_or_404(VendorCommunity, vendor=vendor, community=community)
+
+        previous_status = vc.status
+        reason = request.data.get("reason", "")
+
+        with transaction.atomic():
+            VendorCommunity.objects.filter(pk=vc.pk).update(
+                status=VendorCommunityStatus.REJECTED,
+                rejection_reason=reason,
+            )
+            if previous_status == VendorCommunityStatus.APPROVED:
+                Community.objects.filter(pk=community.pk).update(
+                    vendor_count=F("vendor_count") - 1
+                )
+
+        # TODO: enqueue SMS notification to vendor with rejection_reason (split 05)
+        return Response({"status": VendorCommunityStatus.REJECTED})
+
+
+class VendorPublicProfileView(APIView):
+    """
+    Returns a vendor's public-facing profile for residents to view.
+
+    Exposes only display-safe fields: vendor_id, display_name, bio,
+    average_rating, is_new_seller. No KYB, bank, S3 key, FSSAI license
+    number, or Razorpay data is included.
+
+    Returns:
+        200: VendorPublicProfileSerializer response
+        403: not a resident of this community
+        404: vendor not found
+    """
+    permission_classes = [IsAuthenticated, IsResidentOfCommunity]
+
+    def get(self, request, vendor_id):
+        vendor = get_object_or_404(Vendor, pk=vendor_id)
+        serializer = VendorPublicProfileSerializer(vendor)
+        return Response(serializer.data)
