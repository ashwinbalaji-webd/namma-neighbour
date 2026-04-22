import io
import re
from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import InMemoryUploadedFile
from rest_framework.test import APIClient

from apps.communities.tests.factories import CommunityFactory
from apps.vendors.models import FSSAIStatus, VendorCommunity, VendorCommunityStatus
from apps.vendors.tests.factories import VendorCommunityFactory, VendorFactory


def make_pdf():
    content = b"%PDF-1.4 " + b"x" * 200
    return InMemoryUploadedFile(
        io.BytesIO(content), "file", "cert.pdf",
        "application/pdf", len(content), None,
    )


def make_jpeg():
    content = b"\xff\xd8\xff\xe0" + b"x" * 200
    return InMemoryUploadedFile(
        io.BytesIO(content), "file", "photo.jpg",
        "image/jpeg", len(content), None,
    )


@pytest.fixture
def auth_client(vendor_user):
    client = APIClient()
    client.force_authenticate(user=vendor_user)
    return client


@pytest.fixture
def community():
    return CommunityFactory()


# ─── POST /api/v1/vendors/register/ ───

REGISTER_URL = "/api/v1/vendors/register/"


@pytest.mark.django_db
def test_register_creates_vendor_and_community(auth_client, vendor_user, community):
    resp = auth_client.post(REGISTER_URL, {
        "display_name": "Priya Sweets",
        "logistics_tier": "tier_b",
        "community_slug": community.slug,
    }, format="json")
    assert resp.status_code == 201
    data = resp.json()
    assert "vendor_id" in data
    assert "vendor_community_id" in data
    assert data["status"] == "pending_review"
    assert "required_documents" in data


@pytest.mark.django_db
def test_register_sets_food_seller(auth_client, vendor_user, community):
    from apps.vendors.models import Vendor
    auth_client.post(REGISTER_URL, {
        "display_name": "Biryani House",
        "logistics_tier": "tier_b",
        "community_slug": community.slug,
        "category_hint": "food",
    }, format="json")
    vendor = Vendor.objects.get(user=vendor_user)
    assert vendor.is_food_seller is True


@pytest.mark.django_db
def test_register_required_docs_include_fssai_for_food(auth_client, vendor_user, community):
    resp = auth_client.post(REGISTER_URL, {
        "display_name": "Biryani House",
        "logistics_tier": "tier_b",
        "community_slug": community.slug,
        "category_hint": "food",
    }, format="json")
    assert "fssai_cert" in resp.json()["required_documents"]


@pytest.mark.django_db
def test_register_required_docs_no_fssai_for_non_food(auth_client, vendor_user, community):
    resp = auth_client.post(REGISTER_URL, {
        "display_name": "Craft Store",
        "logistics_tier": "tier_b",
        "community_slug": community.slug,
    }, format="json")
    assert "fssai_cert" not in resp.json()["required_documents"]


@pytest.mark.django_db
def test_register_returns_409_on_duplicate_community(auth_client, vendor_user, community):
    data = {"display_name": "Shop", "logistics_tier": "tier_b", "community_slug": community.slug}
    auth_client.post(REGISTER_URL, data, format="json")
    resp = auth_client.post(REGISTER_URL, data, format="json")
    assert resp.status_code == 409


@pytest.mark.django_db
def test_register_returns_404_for_unknown_slug(auth_client):
    resp = auth_client.post(REGISTER_URL, {
        "display_name": "Shop", "logistics_tier": "tier_b",
        "community_slug": "no-such-slug",
    }, format="json")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_register_returns_401_unauthenticated():
    client = APIClient()
    resp = client.post(REGISTER_URL, {"display_name": "x", "logistics_tier": "tier_b",
                                      "community_slug": "x"}, format="json")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_register_reuses_existing_vendor(auth_client, vendor_user):
    from apps.vendors.models import Vendor
    c1 = CommunityFactory()
    c2 = CommunityFactory()
    auth_client.post(REGISTER_URL, {"display_name": "A", "logistics_tier": "tier_b",
                                    "community_slug": c1.slug}, format="json")
    auth_client.post(REGISTER_URL, {"display_name": "B", "logistics_tier": "tier_b",
                                    "community_slug": c2.slug}, format="json")
    assert Vendor.objects.filter(user=vendor_user).count() == 1


# ─── POST /api/v1/vendors/{vendor_id}/documents/ ───

def doc_url(vendor_id):
    return f"/api/v1/vendors/{vendor_id}/documents/"


@pytest.mark.django_db
def test_documents_returns_403_for_wrong_user(vendor_user, community):
    vendor = VendorFactory(user=vendor_user)
    other_client = APIClient()
    from apps.users.tests.factories import UserFactory
    other_client.force_authenticate(user=UserFactory())
    resp = other_client.post(doc_url(vendor.pk), {"document_type": "govt_id", "file": make_pdf()},
                             format="multipart")
    assert resp.status_code == 403


@pytest.mark.django_db
def test_documents_rejects_large_file(auth_client, vendor_user):
    vendor = VendorFactory(user=vendor_user)
    big = InMemoryUploadedFile(io.BytesIO(b"x" * 100), "file", "big.pdf",
                               "application/pdf", 5 * 1024 * 1024 + 1, None)
    resp = auth_client.post(doc_url(vendor.pk), {"document_type": "govt_id", "file": big},
                            format="multipart")
    assert resp.status_code == 400


@pytest.mark.django_db
def test_documents_rejects_invalid_extension(auth_client, vendor_user):
    vendor = VendorFactory(user=vendor_user)
    bad = InMemoryUploadedFile(io.BytesIO(b"x" * 100), "file", "virus.exe",
                               "application/octet-stream", 100, None)
    resp = auth_client.post(doc_url(vendor.pk), {"document_type": "govt_id", "file": bad},
                            format="multipart")
    assert resp.status_code == 400


@pytest.mark.django_db
def test_documents_rejects_invalid_document_type(auth_client, vendor_user):
    vendor = VendorFactory(user=vendor_user)
    resp = auth_client.post(doc_url(vendor.pk),
                            {"document_type": "passport", "file": make_pdf()},
                            format="multipart")
    assert resp.status_code == 400


@pytest.mark.django_db
@patch("apps.vendors.views.upload_vendor_document")
def test_documents_accepts_pdf_updates_field(mock_upload, auth_client, vendor_user):
    vendor = VendorFactory(user=vendor_user)
    mock_upload.return_value = "documents/vendors/1/govt_id/abc.pdf"
    resp = auth_client.post(doc_url(vendor.pk),
                            {"document_type": "govt_id", "file": make_pdf()},
                            format="multipart")
    assert resp.status_code == 200
    assert resp.json()["document_type"] == "govt_id"


@pytest.mark.django_db
@patch("apps.vendors.views.upload_vendor_document")
@patch("apps.vendors.views.verify_fssai")
def test_documents_fssai_cert_with_number_triggers_task(mock_task, mock_upload, auth_client, vendor_user):
    vendor = VendorFactory(user=vendor_user, fssai_number="12345678901234")
    mock_upload.return_value = "documents/vendors/1/fssai_cert/abc.pdf"
    auth_client.post(doc_url(vendor.pk),
                     {"document_type": "fssai_cert", "file": make_pdf()},
                     format="multipart")
    mock_task.delay.assert_called_once_with(vendor.pk)


@pytest.mark.django_db
@patch("apps.vendors.views.upload_vendor_document")
@patch("apps.vendors.views.verify_fssai")
def test_documents_fssai_cert_without_number_warns(mock_task, mock_upload, auth_client, vendor_user):
    vendor = VendorFactory(user=vendor_user, fssai_number="")
    mock_upload.return_value = "documents/vendors/1/fssai_cert/abc.pdf"
    resp = auth_client.post(doc_url(vendor.pk),
                            {"document_type": "fssai_cert", "file": make_pdf()},
                            format="multipart")
    mock_task.delay.assert_not_called()
    assert resp.json().get("missing_fssai_number") is True


# ─── POST /api/v1/vendors/{vendor_id}/submit/ ───

def submit_url(vendor_id):
    return f"/api/v1/vendors/{vendor_id}/submit/"


@pytest.mark.django_db
def test_submit_returns_400_missing_govt_id(auth_client, vendor_user):
    vendor = VendorFactory(user=vendor_user, govt_id_s3_key="",
                           bank_proof_s3_key="some_key")
    vc = VendorCommunityFactory(vendor=vendor)
    resp = auth_client.post(submit_url(vendor.pk),
                            {"community_slug": vc.community.slug}, format="json")
    assert resp.status_code == 400


@pytest.mark.django_db
def test_submit_returns_400_missing_bank_proof(auth_client, vendor_user):
    vendor = VendorFactory(user=vendor_user, govt_id_s3_key="some_key",
                           bank_proof_s3_key="")
    vc = VendorCommunityFactory(vendor=vendor)
    resp = auth_client.post(submit_url(vendor.pk),
                            {"community_slug": vc.community.slug}, format="json")
    assert resp.status_code == 400


@pytest.mark.django_db
def test_submit_returns_400_fssai_failed(auth_client, vendor_user):
    vendor = VendorFactory(user=vendor_user, govt_id_s3_key="k1",
                           bank_proof_s3_key="k2", fssai_status=FSSAIStatus.FAILED)
    vc = VendorCommunityFactory(vendor=vendor)
    resp = auth_client.post(submit_url(vendor.pk),
                            {"community_slug": vc.community.slug}, format="json")
    assert resp.status_code == 400


@pytest.mark.django_db
def test_submit_returns_400_food_seller_missing_fssai_cert(auth_client, vendor_user):
    vendor = VendorFactory(user=vendor_user, is_food_seller=True,
                           govt_id_s3_key="k1", bank_proof_s3_key="k2",
                           fssai_cert_s3_key="")
    vc = VendorCommunityFactory(vendor=vendor)
    resp = auth_client.post(submit_url(vendor.pk),
                            {"community_slug": vc.community.slug}, format="json")
    assert resp.status_code == 400


@pytest.mark.django_db
def test_submit_succeeds_sets_pending_review(auth_client, vendor_user):
    vendor = VendorFactory(user=vendor_user, govt_id_s3_key="k1", bank_proof_s3_key="k2")
    vc = VendorCommunityFactory(vendor=vendor)
    resp = auth_client.post(submit_url(vendor.pk),
                            {"community_slug": vc.community.slug}, format="json")
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending_review"


@pytest.mark.django_db
def test_submit_returns_403_for_wrong_user(vendor_user):
    vendor = VendorFactory(user=vendor_user, govt_id_s3_key="k1", bank_proof_s3_key="k2")
    vc = VendorCommunityFactory(vendor=vendor)
    from apps.users.tests.factories import UserFactory
    other = APIClient()
    other.force_authenticate(user=UserFactory())
    resp = other.post(submit_url(vendor.pk),
                      {"community_slug": vc.community.slug}, format="json")
    assert resp.status_code == 403


# ─── GET /api/v1/vendors/{vendor_id}/status/ ───

def status_url(vendor_id):
    return f"/api/v1/vendors/{vendor_id}/status/"


@pytest.mark.django_db
def test_status_returns_fssai_status(auth_client, vendor_user):
    vendor = VendorFactory(user=vendor_user, fssai_status=FSSAIStatus.VERIFIED)
    resp = auth_client.get(status_url(vendor.pk))
    assert resp.status_code == 200
    assert resp.json()["fssai_status"] == "verified"


@pytest.mark.django_db
def test_status_missing_documents_empty_when_complete(auth_client, vendor_user):
    vendor = VendorFactory(user=vendor_user, govt_id_s3_key="k1", bank_proof_s3_key="k2")
    resp = auth_client.get(status_url(vendor.pk))
    assert resp.json()["missing_documents"] == []


@pytest.mark.django_db
def test_status_missing_documents_includes_fssai_for_food_seller(auth_client, vendor_user):
    vendor = VendorFactory(user=vendor_user, is_food_seller=True, fssai_cert_s3_key="")
    resp = auth_client.get(status_url(vendor.pk))
    assert "fssai_cert" in resp.json()["missing_documents"]


@pytest.mark.django_db
def test_status_community_statuses_count(auth_client, vendor_user):
    vendor = VendorFactory(user=vendor_user)
    VendorCommunityFactory(vendor=vendor)
    VendorCommunityFactory(vendor=vendor)
    resp = auth_client.get(status_url(vendor.pk))
    assert len(resp.json()["community_statuses"]) == 2


@pytest.mark.django_db
def test_status_returns_403_for_wrong_user(vendor_user):
    vendor = VendorFactory(user=vendor_user)
    from apps.users.tests.factories import UserFactory
    other = APIClient()
    other.force_authenticate(user=UserFactory())
    resp = other.get(status_url(vendor.pk))
    assert resp.status_code == 403


# ─── Admin Workflow Fixtures ───────────────────────────────────────────────────

class MockToken:
    def __init__(self, *roles):
        self.payload = {"roles": list(roles)}


@pytest.fixture
def admin_user(db):
    from apps.users.tests.factories import UserFactory
    return UserFactory()


@pytest.fixture
def admin_community(admin_user):
    from apps.users.models import UserRole
    community = CommunityFactory()
    UserRole.objects.create(user=admin_user, role="community_admin", community=community)
    return community


@pytest.fixture
def admin_client(admin_user):
    client = APIClient()
    client.force_authenticate(user=admin_user, token=MockToken("community_admin"))
    return client


@pytest.fixture
def resident_user(db):
    from apps.users.tests.factories import UserFactory
    return UserFactory()


@pytest.fixture
def resident_client(resident_user):
    client = APIClient()
    client.force_authenticate(user=resident_user, token=MockToken("resident"))
    return client


def pending_url(slug):
    return f"/api/v1/communities/{slug}/vendors/pending/"


def approve_url(vendor_id):
    return f"/api/v1/vendors/{vendor_id}/approve/"


def reject_url(vendor_id):
    return f"/api/v1/vendors/{vendor_id}/reject/"


def profile_url(vendor_id):
    return f"/api/v1/vendors/{vendor_id}/profile/"


# ─── GET /api/v1/communities/{slug}/vendors/pending/ ──────────────────────────

@pytest.mark.django_db
def test_pending_returns_only_pending_review_in_community(admin_client, admin_community, admin_user):
    vc1 = VendorCommunityFactory(community=admin_community, status=VendorCommunityStatus.PENDING_REVIEW)
    vc2 = VendorCommunityFactory(community=admin_community, status=VendorCommunityStatus.PENDING_REVIEW)
    VendorCommunityFactory(community=admin_community, status=VendorCommunityStatus.APPROVED)
    resp = admin_client.get(pending_url(admin_community.slug))
    assert resp.status_code == 200
    assert resp.json()["count"] == 2


@pytest.mark.django_db
def test_pending_excludes_other_community_vendors(admin_client, admin_community):
    VendorCommunityFactory(community=admin_community, status=VendorCommunityStatus.PENDING_REVIEW)
    other_community = CommunityFactory()
    other_vc = VendorCommunityFactory(community=other_community, status=VendorCommunityStatus.PENDING_REVIEW)
    resp = admin_client.get(pending_url(admin_community.slug))
    assert resp.status_code == 200
    vendor_ids = [r["vendor_id"] for r in resp.json()["results"]]
    assert other_vc.vendor.pk not in vendor_ids


@pytest.mark.django_db
@patch("apps.vendors.serializers.generate_document_presigned_url")
def test_pending_includes_presigned_urls_for_non_empty_keys(mock_presign, admin_client, admin_community):
    mock_presign.return_value = "https://s3.example.com/signed"
    vendor = VendorFactory(govt_id_s3_key="documents/vendors/1/govt_id.pdf", bank_proof_s3_key="")
    VendorCommunityFactory(vendor=vendor, community=admin_community, status=VendorCommunityStatus.PENDING_REVIEW)
    resp = admin_client.get(pending_url(admin_community.slug))
    assert resp.status_code == 200
    result = resp.json()["results"][0]
    assert result["document_urls"].get("govt_id") == "https://s3.example.com/signed"
    assert "bank_proof" not in result["document_urls"]


@pytest.mark.django_db
def test_pending_fssai_warning_true_when_failed(admin_client, admin_community):
    vendor = VendorFactory(fssai_status=FSSAIStatus.FAILED)
    VendorCommunityFactory(vendor=vendor, community=admin_community, status=VendorCommunityStatus.PENDING_REVIEW)
    resp = admin_client.get(pending_url(admin_community.slug))
    assert resp.status_code == 200
    assert resp.json()["results"][0]["fssai_warning"] is True


@pytest.mark.django_db
def test_pending_fssai_warning_false_when_verified(admin_client, admin_community):
    vendor = VendorFactory(fssai_status=FSSAIStatus.VERIFIED)
    VendorCommunityFactory(vendor=vendor, community=admin_community, status=VendorCommunityStatus.PENDING_REVIEW)
    resp = admin_client.get(pending_url(admin_community.slug))
    assert resp.status_code == 200
    assert resp.json()["results"][0]["fssai_warning"] is False


@pytest.mark.django_db
def test_pending_paginated_page_size_10(admin_client, admin_community):
    for _ in range(11):
        VendorCommunityFactory(community=admin_community, status=VendorCommunityStatus.PENDING_REVIEW)
    resp = admin_client.get(pending_url(admin_community.slug))
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 11
    assert len(data["results"]) == 10
    assert data["next"] is not None


@pytest.mark.django_db
def test_pending_returns_403_for_non_admin(resident_client, admin_community):
    resp = resident_client.get(pending_url(admin_community.slug))
    assert resp.status_code == 403


# ─── POST /api/v1/vendors/{vendor_id}/approve/ ────────────────────────────────

@pytest.mark.django_db
@patch("apps.vendors.views.transaction.on_commit", side_effect=lambda fn: fn())
@patch("apps.vendors.views.create_razorpay_linked_account")
def test_approve_transitions_status_to_approved(mock_task, mock_on_commit, admin_client, admin_community):
    vc = VendorCommunityFactory(community=admin_community, status=VendorCommunityStatus.PENDING_REVIEW)
    resp = admin_client.post(approve_url(vc.vendor.pk), {
        "community_slug": admin_community.slug,
        "override_fssai_warning": False,
    }, format="json")
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"
    vc.refresh_from_db()
    assert vc.status == VendorCommunityStatus.APPROVED


@pytest.mark.django_db
@patch("apps.vendors.views.transaction.on_commit", side_effect=lambda fn: fn())
@patch("apps.vendors.views.create_razorpay_linked_account")
def test_approve_sets_approved_by_and_approved_at(mock_task, mock_on_commit, admin_client, admin_community, admin_user):
    vc = VendorCommunityFactory(community=admin_community, status=VendorCommunityStatus.PENDING_REVIEW)
    admin_client.post(approve_url(vc.vendor.pk), {
        "community_slug": admin_community.slug,
        "override_fssai_warning": False,
    }, format="json")
    vc.refresh_from_db()
    assert vc.approved_by == admin_user
    assert vc.approved_at is not None


@pytest.mark.django_db
@patch("apps.vendors.views.transaction.on_commit", side_effect=lambda fn: fn())
@patch("apps.vendors.views.create_razorpay_linked_account")
def test_approve_increments_vendor_count(mock_task, mock_on_commit, admin_client, admin_community):
    initial = admin_community.vendor_count
    vc = VendorCommunityFactory(community=admin_community, status=VendorCommunityStatus.PENDING_REVIEW)
    admin_client.post(approve_url(vc.vendor.pk), {
        "community_slug": admin_community.slug,
        "override_fssai_warning": False,
    }, format="json")
    admin_community.refresh_from_db()
    assert admin_community.vendor_count == initial + 1


@pytest.mark.django_db
@patch("apps.vendors.views.transaction.on_commit", side_effect=lambda fn: fn())
@patch("apps.vendors.views.create_razorpay_linked_account")
def test_approve_creates_vendor_user_role(mock_task, mock_on_commit, admin_client, admin_community):
    from apps.users.models import UserRole
    vc = VendorCommunityFactory(community=admin_community, status=VendorCommunityStatus.PENDING_REVIEW)
    admin_client.post(approve_url(vc.vendor.pk), {
        "community_slug": admin_community.slug,
        "override_fssai_warning": False,
    }, format="json")
    assert UserRole.objects.filter(
        user=vc.vendor.user, role="vendor", community=admin_community
    ).exists()


@pytest.mark.django_db
@patch("apps.vendors.views.transaction.on_commit", side_effect=lambda fn: fn())
@patch("apps.vendors.views.create_razorpay_linked_account")
def test_approve_vendor_role_not_duplicated(mock_task, mock_on_commit, admin_client, admin_community):
    from apps.users.models import UserRole
    vc = VendorCommunityFactory(community=admin_community, status=VendorCommunityStatus.PENDING_REVIEW)
    payload = {"community_slug": admin_community.slug, "override_fssai_warning": False}
    admin_client.post(approve_url(vc.vendor.pk), payload, format="json")
    VendorCommunity.objects.filter(pk=vc.pk).update(status=VendorCommunityStatus.PENDING_REVIEW)
    admin_client.post(approve_url(vc.vendor.pk), payload, format="json")
    assert UserRole.objects.filter(
        user=vc.vendor.user, role="vendor", community=admin_community
    ).count() == 1


@pytest.mark.django_db
@patch("apps.vendors.views.transaction.on_commit", side_effect=lambda fn: fn())
@patch("apps.vendors.views.create_razorpay_linked_account")
def test_approve_enqueues_razorpay_task_on_first_approval(mock_task, mock_on_commit, admin_client, admin_community):
    vendor = VendorFactory(razorpay_onboarding_step="")
    VendorCommunityFactory(vendor=vendor, community=admin_community, status=VendorCommunityStatus.PENDING_REVIEW)
    admin_client.post(approve_url(vendor.pk), {
        "community_slug": admin_community.slug,
        "override_fssai_warning": False,
    }, format="json")
    mock_task.delay.assert_called_once_with(vendor.pk)


@pytest.mark.django_db
@patch("apps.vendors.views.transaction.on_commit", side_effect=lambda fn: fn())
@patch("apps.vendors.views.create_razorpay_linked_account")
def test_approve_skips_razorpay_task_when_already_onboarded(mock_task, mock_on_commit, admin_client, admin_community):
    vendor = VendorFactory(razorpay_onboarding_step="submitted")
    VendorCommunityFactory(vendor=vendor, community=admin_community, status=VendorCommunityStatus.PENDING_REVIEW)
    admin_client.post(approve_url(vendor.pk), {
        "community_slug": admin_community.slug,
        "override_fssai_warning": False,
    }, format="json")
    mock_task.delay.assert_not_called()


@pytest.mark.django_db
def test_approve_returns_400_fssai_failed_no_override(admin_client, admin_community):
    vendor = VendorFactory(fssai_status=FSSAIStatus.FAILED)
    VendorCommunityFactory(vendor=vendor, community=admin_community, status=VendorCommunityStatus.PENDING_REVIEW)
    resp = admin_client.post(approve_url(vendor.pk), {
        "community_slug": admin_community.slug,
        "override_fssai_warning": False,
    }, format="json")
    assert resp.status_code == 400


@pytest.mark.django_db
@patch("apps.vendors.views.transaction.on_commit", side_effect=lambda fn: fn())
@patch("apps.vendors.views.create_razorpay_linked_account")
def test_approve_proceeds_fssai_failed_with_override(mock_task, mock_on_commit, admin_client, admin_community):
    vendor = VendorFactory(fssai_status=FSSAIStatus.FAILED)
    VendorCommunityFactory(vendor=vendor, community=admin_community, status=VendorCommunityStatus.PENDING_REVIEW)
    resp = admin_client.post(approve_url(vendor.pk), {
        "community_slug": admin_community.slug,
        "override_fssai_warning": True,
    }, format="json")
    assert resp.status_code == 200
    vc = VendorCommunity.objects.get(vendor=vendor, community=admin_community)
    assert vc.status == VendorCommunityStatus.APPROVED


@pytest.mark.django_db
def test_approve_returns_403_for_other_community(admin_client, admin_community):
    other = CommunityFactory()
    vc = VendorCommunityFactory(community=other, status=VendorCommunityStatus.PENDING_REVIEW)
    resp = admin_client.post(approve_url(vc.vendor.pk), {
        "community_slug": other.slug,
        "override_fssai_warning": False,
    }, format="json")
    assert resp.status_code == 403


@pytest.mark.django_db
def test_approve_returns_403_for_non_admin(resident_client, admin_community):
    vc = VendorCommunityFactory(community=admin_community, status=VendorCommunityStatus.PENDING_REVIEW)
    resp = resident_client.post(approve_url(vc.vendor.pk), {
        "community_slug": admin_community.slug,
        "override_fssai_warning": False,
    }, format="json")
    assert resp.status_code == 403


@pytest.mark.django_db
def test_approve_returns_404_for_unknown_community(admin_client, admin_community):
    vc = VendorCommunityFactory(community=admin_community, status=VendorCommunityStatus.PENDING_REVIEW)
    resp = admin_client.post(approve_url(vc.vendor.pk), {
        "community_slug": "no-such-community",
        "override_fssai_warning": False,
    }, format="json")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_approve_returns_404_for_unknown_vendor(admin_client, admin_community):
    resp = admin_client.post(approve_url(99999), {
        "community_slug": admin_community.slug,
        "override_fssai_warning": False,
    }, format="json")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_approve_returns_404_when_not_pending(admin_client, admin_community):
    vc = VendorCommunityFactory(community=admin_community, status=VendorCommunityStatus.APPROVED)
    resp = admin_client.post(approve_url(vc.vendor.pk), {
        "community_slug": admin_community.slug,
        "override_fssai_warning": False,
    }, format="json")
    assert resp.status_code == 404


# ─── POST /api/v1/vendors/{vendor_id}/reject/ ─────────────────────────────────

@pytest.mark.django_db
def test_reject_transitions_status_to_rejected(admin_client, admin_community):
    vc = VendorCommunityFactory(community=admin_community, status=VendorCommunityStatus.PENDING_REVIEW)
    resp = admin_client.post(reject_url(vc.vendor.pk), {
        "community_slug": admin_community.slug,
        "reason": "FSSAI expired",
    }, format="json")
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"
    vc.refresh_from_db()
    assert vc.status == VendorCommunityStatus.REJECTED


@pytest.mark.django_db
def test_reject_stores_rejection_reason(admin_client, admin_community):
    vc = VendorCommunityFactory(community=admin_community, status=VendorCommunityStatus.PENDING_REVIEW)
    admin_client.post(reject_url(vc.vendor.pk), {
        "community_slug": admin_community.slug,
        "reason": "FSSAI expired",
    }, format="json")
    vc.refresh_from_db()
    assert vc.rejection_reason == "FSSAI expired"


@pytest.mark.django_db
@patch("apps.vendors.views.create_razorpay_linked_account")
def test_reject_decrements_vendor_count_when_was_approved(mock_task, admin_client, admin_community):
    vc = VendorCommunityFactory(community=admin_community, status=VendorCommunityStatus.APPROVED)
    from apps.communities.models import Community
    Community.objects.filter(pk=admin_community.pk).update(vendor_count=1)
    admin_client.post(reject_url(vc.vendor.pk), {
        "community_slug": admin_community.slug,
        "reason": "expired",
    }, format="json")
    admin_community.refresh_from_db()
    assert admin_community.vendor_count == 0


@pytest.mark.django_db
def test_reject_does_not_decrement_count_when_pending(admin_client, admin_community):
    from apps.communities.models import Community
    Community.objects.filter(pk=admin_community.pk).update(vendor_count=5)
    vc = VendorCommunityFactory(community=admin_community, status=VendorCommunityStatus.PENDING_REVIEW)
    admin_client.post(reject_url(vc.vendor.pk), {
        "community_slug": admin_community.slug,
        "reason": "docs missing",
    }, format="json")
    admin_community.refresh_from_db()
    assert admin_community.vendor_count == 5


@pytest.mark.django_db
def test_reject_returns_403_for_other_community(admin_client, admin_community):
    other = CommunityFactory()
    vc = VendorCommunityFactory(community=other, status=VendorCommunityStatus.PENDING_REVIEW)
    resp = admin_client.post(reject_url(vc.vendor.pk), {
        "community_slug": other.slug,
        "reason": "nope",
    }, format="json")
    assert resp.status_code == 403


@pytest.mark.django_db
def test_reject_returns_403_for_non_admin(resident_client, admin_community):
    vc = VendorCommunityFactory(community=admin_community, status=VendorCommunityStatus.PENDING_REVIEW)
    resp = resident_client.post(reject_url(vc.vendor.pk), {
        "community_slug": admin_community.slug,
        "reason": "nope",
    }, format="json")
    assert resp.status_code == 403


@pytest.mark.django_db
def test_reject_vendor_can_resubmit(admin_client, admin_community, vendor_user):
    vendor = VendorFactory(
        user=vendor_user,
        is_food_seller=False,
        govt_id_s3_key="k1",
        bank_proof_s3_key="k2",
    )
    vc = VendorCommunityFactory(vendor=vendor, community=admin_community, status=VendorCommunityStatus.PENDING_REVIEW)
    admin_client.post(reject_url(vendor.pk), {
        "community_slug": admin_community.slug,
        "reason": "docs expired",
    }, format="json")
    vendor_client = APIClient()
    vendor_client.force_authenticate(user=vendor_user)
    resp = vendor_client.post(submit_url(vendor.pk), {"community_slug": admin_community.slug}, format="json")
    assert resp.status_code == 200
    vc.refresh_from_db()
    assert vc.status == VendorCommunityStatus.PENDING_REVIEW


# ─── GET /api/v1/vendors/{vendor_id}/profile/ ─────────────────────────────────

@pytest.mark.django_db
def test_profile_returns_display_safe_fields(resident_client):
    vendor = VendorFactory()
    resp = resident_client.get(profile_url(vendor.pk))
    assert resp.status_code == 200
    data = resp.json()
    assert set(data.keys()) == {"vendor_id", "display_name", "bio", "average_rating", "is_new_seller"}


@pytest.mark.django_db
def test_profile_does_not_expose_sensitive_fields(resident_client):
    vendor = VendorFactory(
        govt_id_s3_key="sec", bank_proof_s3_key="sec",
        fssai_cert_s3_key="sec", gst_cert_s3_key="sec",
    )
    resp = resident_client.get(profile_url(vendor.pk))
    data = resp.json()
    sensitive = {"fssai_number", "razorpay_account_id", "govt_id_s3_key",
                 "bank_proof_s3_key", "fssai_cert_s3_key", "gst_cert_s3_key", "bank_account_verified"}
    assert not sensitive.intersection(data.keys())


@pytest.mark.django_db
def test_profile_returns_403_for_non_resident():
    from apps.users.tests.factories import UserFactory
    no_role_client = APIClient()
    no_role_client.force_authenticate(user=UserFactory(), token=MockToken())
    vendor = VendorFactory()
    resp = no_role_client.get(profile_url(vendor.pk))
    assert resp.status_code == 403
