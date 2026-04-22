import io
from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import InMemoryUploadedFile
from rest_framework.test import APIRequestFactory

from apps.communities.tests.factories import CommunityFactory
from apps.vendors.models import FSSAIStatus, VendorCommunity, VendorCommunityStatus
from apps.vendors.serializers import (
    DocumentUploadSerializer,
    PendingVendorSerializer,
    VendorPublicProfileSerializer,
    VendorRegistrationSerializer,
    VendorStatusSerializer,
)
from apps.vendors.tests.factories import VendorCommunityFactory, VendorFactory


def make_file(name, content, size=None):
    data = io.BytesIO(content)
    file_size = size if size is not None else len(content)
    return InMemoryUploadedFile(
        file=data, field_name="file", name=name,
        content_type="application/octet-stream", size=file_size, charset=None,
    )


def make_request(user):
    factory = APIRequestFactory()
    request = factory.post("/")
    request.user = user
    return request


# --- VendorRegistrationSerializer ---

@pytest.mark.django_db
def test_registration_creates_vendor_and_community(vendor_user):
    community = CommunityFactory()
    data = {
        "display_name": "Priya Sweets",
        "logistics_tier": "tier_b",
        "community_slug": community.slug,
    }
    s = VendorRegistrationSerializer(data=data, context={"request": make_request(vendor_user)})
    assert s.is_valid(), s.errors
    result = s.save()
    assert result["vendor_id"] is not None
    assert result["vendor_community_id"] is not None
    assert VendorCommunity.objects.filter(pk=result["vendor_community_id"]).exists()


@pytest.mark.django_db
def test_registration_sets_food_seller_on_category_hint(vendor_user):
    community = CommunityFactory()
    data = {
        "display_name": "Priya Sweets",
        "logistics_tier": "tier_b",
        "community_slug": community.slug,
        "category_hint": "food",
    }
    s = VendorRegistrationSerializer(data=data, context={"request": make_request(vendor_user)})
    assert s.is_valid(), s.errors
    result = s.save()
    from apps.vendors.models import Vendor
    vendor = Vendor.objects.get(pk=result["vendor_id"])
    assert vendor.is_food_seller is True


@pytest.mark.django_db
def test_registration_required_docs_include_fssai_for_food(vendor_user):
    community = CommunityFactory()
    data = {
        "display_name": "Priya Sweets",
        "logistics_tier": "tier_b",
        "community_slug": community.slug,
        "category_hint": "food",
    }
    s = VendorRegistrationSerializer(data=data, context={"request": make_request(vendor_user)})
    assert s.is_valid(), s.errors
    result = s.save()
    assert "fssai_cert" in result["required_documents"]


@pytest.mark.django_db
def test_registration_required_docs_no_fssai_for_non_food(vendor_user):
    community = CommunityFactory()
    data = {
        "display_name": "Priya Sweets",
        "logistics_tier": "tier_b",
        "community_slug": community.slug,
    }
    s = VendorRegistrationSerializer(data=data, context={"request": make_request(vendor_user)})
    assert s.is_valid(), s.errors
    result = s.save()
    assert "fssai_cert" not in result["required_documents"]


@pytest.mark.django_db
def test_registration_duplicate_community_raises_conflict(vendor_user):
    from rest_framework.exceptions import ValidationError as DRFValidationError
    community = CommunityFactory()
    vendor = VendorFactory(user=vendor_user)
    VendorCommunityFactory(vendor=vendor, community=community)
    data = {
        "display_name": "Priya Sweets",
        "logistics_tier": "tier_b",
        "community_slug": community.slug,
    }
    s = VendorRegistrationSerializer(data=data, context={"request": make_request(vendor_user)})
    assert s.is_valid(), s.errors
    with pytest.raises(DRFValidationError) as exc_info:
        s.save()
    assert exc_info.value.detail.get("community") or exc_info.value.get_codes() is not None


@pytest.mark.django_db
def test_registration_invalid_community_slug_fails_validation(vendor_user):
    data = {
        "display_name": "Priya Sweets",
        "logistics_tier": "tier_b",
        "community_slug": "nonexistent-slug",
    }
    s = VendorRegistrationSerializer(data=data, context={"request": make_request(vendor_user)})
    assert not s.is_valid()


@pytest.mark.django_db
def test_registration_reuses_existing_vendor(vendor_user):
    community1 = CommunityFactory()
    community2 = CommunityFactory()
    data1 = {
        "display_name": "Priya Sweets",
        "logistics_tier": "tier_b",
        "community_slug": community1.slug,
    }
    s1 = VendorRegistrationSerializer(data=data1, context={"request": make_request(vendor_user)})
    assert s1.is_valid(), s1.errors
    result1 = s1.save()

    data2 = {
        "display_name": "Priya Sweets Updated",
        "logistics_tier": "tier_b",
        "community_slug": community2.slug,
    }
    s2 = VendorRegistrationSerializer(data=data2, context={"request": make_request(vendor_user)})
    assert s2.is_valid(), s2.errors
    result2 = s2.save()
    assert result1["vendor_id"] == result2["vendor_id"]


# --- DocumentUploadSerializer ---

def test_document_upload_rejects_file_over_5mb():
    data = {"document_type": "govt_id"}
    f = make_file("doc.pdf", b"x" * 100, size=5 * 1024 * 1024 + 1)
    s = DocumentUploadSerializer(data={**data, "file": f})
    assert not s.is_valid()


def test_document_upload_rejects_invalid_extension():
    data = {"document_type": "govt_id"}
    f = make_file("malware.exe", b"x" * 100)
    s = DocumentUploadSerializer(data={**data, "file": f})
    assert not s.is_valid()


def test_document_upload_accepts_valid_pdf():
    data = {"document_type": "govt_id"}
    content = b"%PDF-1.4 " + b"x" * 200
    f = make_file("cert.pdf", content)
    s = DocumentUploadSerializer(data={**data, "file": f})
    assert s.is_valid(), s.errors


def test_document_upload_rejects_invalid_document_type():
    content = b"%PDF-1.4 " + b"x" * 200
    f = make_file("cert.pdf", content)
    s = DocumentUploadSerializer(data={"document_type": "passport", "file": f})
    assert not s.is_valid()


# --- VendorStatusSerializer ---

@pytest.mark.django_db
def test_status_missing_documents_empty_when_all_present():
    vendor = VendorFactory(
        govt_id_s3_key="documents/vendors/1/govt_id/abc.pdf",
        bank_proof_s3_key="documents/vendors/1/bank_proof/abc.pdf",
    )
    s = VendorStatusSerializer(vendor)
    assert s.data["missing_documents"] == []


@pytest.mark.django_db
def test_status_missing_documents_includes_govt_id_when_absent():
    vendor = VendorFactory(govt_id_s3_key="", bank_proof_s3_key="some_key")
    s = VendorStatusSerializer(vendor)
    assert "govt_id" in s.data["missing_documents"]


@pytest.mark.django_db
def test_status_missing_documents_includes_fssai_cert_for_food_seller():
    vendor = VendorFactory(is_food_seller=True, fssai_cert_s3_key="")
    s = VendorStatusSerializer(vendor)
    assert "fssai_cert" in s.data["missing_documents"]


@pytest.mark.django_db
def test_status_community_statuses_reflects_memberships():
    vc = VendorCommunityFactory()
    s = VendorStatusSerializer(vc.vendor)
    statuses = s.data["community_statuses"]
    assert len(statuses) == 1
    assert statuses[0]["status"] == VendorCommunityStatus.PENDING_REVIEW


# --- PendingVendorSerializer ---

@pytest.mark.django_db
def test_pending_vendor_document_urls_for_nonempty_keys():
    vendor = VendorFactory(govt_id_s3_key="documents/vendors/1/govt_id/abc.pdf")
    vc = VendorCommunityFactory(vendor=vendor)
    with patch("apps.vendors.serializers.generate_document_presigned_url") as mock_url:
        mock_url.return_value = "https://example.com/signed"
        s = PendingVendorSerializer(vc)
        urls = s.data["document_urls"]
    assert "govt_id" in urls
    assert urls["govt_id"] == "https://example.com/signed"


@pytest.mark.django_db
def test_pending_vendor_fssai_warning_true_when_failed():
    vendor = VendorFactory(fssai_status=FSSAIStatus.FAILED)
    vc = VendorCommunityFactory(vendor=vendor)
    with patch("apps.vendors.serializers.generate_document_presigned_url", return_value="https://x.com"):
        s = PendingVendorSerializer(vc)
        assert s.data["fssai_warning"] is True


@pytest.mark.django_db
def test_pending_vendor_fssai_warning_false_when_not_failed():
    vendor = VendorFactory(fssai_status=FSSAIStatus.VERIFIED)
    vc = VendorCommunityFactory(vendor=vendor)
    with patch("apps.vendors.serializers.generate_document_presigned_url", return_value="https://x.com"):
        s = PendingVendorSerializer(vc)
        assert s.data["fssai_warning"] is False


# --- VendorPublicProfileSerializer ---

@pytest.mark.django_db
def test_public_profile_returns_safe_fields():
    vendor = VendorFactory()
    s = VendorPublicProfileSerializer(vendor)
    data = s.data
    assert set(data.keys()) == {"vendor_id", "display_name", "bio", "average_rating", "is_new_seller"}


@pytest.mark.django_db
def test_public_profile_excludes_sensitive_fields():
    vendor = VendorFactory()
    s = VendorPublicProfileSerializer(vendor)
    data = s.data
    sensitive = ["fssai_number", "razorpay_account_id", "govt_id_s3_key",
                 "bank_proof_s3_key", "fssai_cert_s3_key", "gstin"]
    for field in sensitive:
        assert field not in data
