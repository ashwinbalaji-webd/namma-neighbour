import re

from django.db import transaction
from django.db.models import F
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics
from rest_framework.exceptions import PermissionDenied
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsCommunityAdmin, IsResidentOfCommunity, IsVendorOwner
from apps.users.models import UserRole
from apps.vendors.models import FSSAIStatus, Vendor, VendorCommunity, VendorCommunityStatus
from apps.vendors.serializers import (
    DocumentUploadSerializer,
    PendingVendorSerializer,
    VendorPublicProfileSerializer,
    VendorRegistrationSerializer,
    VendorStatusSerializer,
)
from apps.vendors.services.storage import upload_vendor_document
from apps.vendors.tasks import create_razorpay_linked_account, verify_fssai

_FSSAI_NUMBER_RE = re.compile(r"^\d{14}$")


class VendorRegistrationView(APIView):
    """
    Creates a Vendor profile (or retrieves existing one) and a new VendorCommunity
    membership for the given community_slug.

    Returns:
        201: {vendor_id, vendor_community_id, status, required_documents}
        400: validation error
        401: not authenticated
        404: community not found
        409: VendorCommunity already exists for (vendor, community)
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = VendorRegistrationSerializer(
            data=request.data, context={"request": request}
        )
        if not serializer.is_valid():
            errors = serializer.errors
            if "community_slug" in errors:
                return Response({"detail": str(errors["community_slug"][0])}, status=404)
            return Response(errors, status=400)
        try:
            result = serializer.save()
        except Exception as exc:
            detail = getattr(exc, "detail", {})
            if isinstance(detail, dict) and "community" in detail:
                return Response({"detail": str(detail["community"][0])}, status=409)
            raise
        return Response(result, status=201)


class DocumentUploadView(APIView):
    """
    Accepts multipart/form-data with fields: document_type (str), file (File).
    Validates file via 3-layer check (size → extension → magic bytes), uploads
    to S3, stores the key on the Vendor record.

    If document_type='fssai_cert' and vendor.fssai_number is a valid 14-digit string,
    enqueues verify_fssai.delay(vendor.pk) and sets fssai_status='pending'.

    Returns:
        200: {document_type, s3_key, missing_fssai_number: bool}
        400: validation error (file or document_type invalid)
        401: not authenticated
        403: not the vendor owner
        404: vendor not found
    """
    permission_classes = [IsAuthenticated, IsVendorOwner]

    def post(self, request, vendor_id):
        vendor = get_object_or_404(Vendor, pk=vendor_id)
        self.check_object_permissions(request, vendor)

        serializer = DocumentUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        document_type = serializer.validated_data["document_type"]
        file = serializer.validated_data["file"]

        s3_key = upload_vendor_document(vendor, document_type, file)

        missing_fssai_number = False
        if document_type == "fssai_cert":
            if _FSSAI_NUMBER_RE.match(vendor.fssai_number or ""):
                vendor.fssai_status = FSSAIStatus.PENDING
                vendor.save(update_fields=["fssai_status"])
                verify_fssai.delay(vendor.pk)
            else:
                missing_fssai_number = True

        return Response({
            "document_type": document_type,
            "s3_key": s3_key,
            "missing_fssai_number": missing_fssai_number,
        })


class VendorSubmitView(APIView):
    """
    Submits a vendor's application to a community for admin review.
    Validates that all required documents are uploaded and FSSAI status
    is not 'failed'.

    Request body: {"community_slug": "prestige-oasis"}

    Returns:
        200: {status: 'pending_review'}
        400: missing documents, fssai_status=failed
        401: not authenticated
        403: not the vendor owner
        404: vendor not found, community not found, or VendorCommunity not found
    """
    permission_classes = [IsAuthenticated, IsVendorOwner]

    def post(self, request, vendor_id):
        vendor = get_object_or_404(Vendor, pk=vendor_id)
        self.check_object_permissions(request, vendor)

        community_slug = request.data.get("community_slug", "")
        from apps.communities.models import Community
        community = get_object_or_404(Community, slug=community_slug)
        vc = get_object_or_404(VendorCommunity, vendor=vendor, community=community)

        missing = []
        if not vendor.govt_id_s3_key:
            missing.append("govt_id")
        if not vendor.bank_proof_s3_key:
            missing.append("bank_proof")
        if vendor.is_food_seller and not vendor.fssai_cert_s3_key:
            missing.append("fssai_cert")

        if missing:
            return Response(
                {"detail": f"Missing required documents: {', '.join(missing)}"},
                status=400,
            )

        if vendor.fssai_status == FSSAIStatus.FAILED:
            return Response(
                {"detail": "FSSAI verification failed — please update your FSSAI "
                           "certificate and license number before submitting"},
                status=400,
            )

        VendorCommunity.objects.filter(pk=vc.pk).update(
            status=VendorCommunityStatus.PENDING_REVIEW
        )
        # TODO: enqueue admin notification task (split 05)
        return Response({"status": VendorCommunityStatus.PENDING_REVIEW})


class VendorStatusView(APIView):
    """
    Returns the vendor's current application state: FSSAI status, any missing
    documents, and per-community approval statuses.

    Returns:
        200: VendorStatusSerializer response
        401: not authenticated
        403: not the vendor owner
        404: vendor not found
    """
    permission_classes = [IsAuthenticated, IsVendorOwner]

    def get(self, request, vendor_id):
        vendor = get_object_or_404(Vendor, pk=vendor_id)
        self.check_object_permissions(request, vendor)
        serializer = VendorStatusSerializer(vendor)
        return Response(serializer.data)


# ─── Admin Workflow Views ──────────────────────────────────────────────────────

class _AdminPagination(PageNumberPagination):
    page_size = 10


class CommunityPendingVendorsView(generics.ListAPIView):
    """
    Returns a paginated list of VendorCommunity records with status=pending_review
    for a given community. Used by community admins to review vendor applications.

    Each entry includes presigned S3 document URLs (TTL=3600s) and an fssai_warning
    flag. Presigned URL generation is CPU-bound (HMAC, no network) and safe for
    synchronous request handling at page_size=10.

    Pagination: page_size=10 (PageNumberPagination).

    Returns:
        200: paginated list of PendingVendorSerializer responses
        403: not a community admin
        404: community not found
    """
    serializer_class = PendingVendorSerializer
    permission_classes = [IsAuthenticated, IsCommunityAdmin]
    pagination_class = _AdminPagination

    def get_queryset(self):
        from apps.communities.models import Community
        slug = self.kwargs["slug"]
        community = get_object_or_404(Community, slug=slug)
        if not UserRole.objects.filter(
            user=self.request.user, role="community_admin", community=community
        ).exists():
            raise PermissionDenied()
        return VendorCommunity.objects.filter(
            community=community, status=VendorCommunityStatus.PENDING_REVIEW
        ).select_related("vendor").order_by("created_at")


class VendorApproveView(APIView):
    """
    Approves a vendor's application for a specific community.

    Business logic:
    1. Resolve community_slug → Community; 404 if not found.
    2. Cross-check: verify request.user is admin of the resolved community (not just any community).
       Return 403 if the community_slug resolves to a community the user does not admin.
    3. Retrieve VendorCommunity for (vendor, community) where status=pending_review. 404 otherwise.
    4. FSSAI guard: if vendor.fssai_status == 'failed' and override_fssai_warning != True, return 400.
    5. Atomic update:
       a. VendorCommunity.status → approved; set approved_by=request.user, approved_at=now()
       b. community.vendor_count incremented atomically (F() expression)
       c. UserRole.objects.get_or_create(user=vendor.user, role='vendor', community=community)
       d. If vendor.razorpay_onboarding_step == '': enqueue create_razorpay_linked_account.delay(vendor.pk)

    Returns:
        200: {status: 'approved'}
        400: FSSAI guard triggered (fssai_status='failed', no override)
        403: not admin of this community
        404: community not found, or VendorCommunity not in pending_review
    """
    permission_classes = [IsAuthenticated, IsCommunityAdmin]

    def post(self, request, vendor_id):
        from apps.communities.models import Community
        community_slug = request.data.get("community_slug", "")
        community = get_object_or_404(Community, slug=community_slug)

        if not UserRole.objects.filter(
            user=request.user, role="community_admin", community=community
        ).exists():
            raise PermissionDenied()

        vendor = get_object_or_404(Vendor, pk=vendor_id)
        vc = get_object_or_404(
            VendorCommunity,
            vendor=vendor,
            community=community,
            status=VendorCommunityStatus.PENDING_REVIEW,
        )

        override_fssai = request.data.get("override_fssai_warning", False)
        if vendor.fssai_status == FSSAIStatus.FAILED and not override_fssai:
            return Response(
                {"detail": "FSSAI verification failed. Set override_fssai_warning=true to proceed."},
                status=400,
            )

        with transaction.atomic():
            VendorCommunity.objects.filter(pk=vc.pk).update(
                status=VendorCommunityStatus.APPROVED,
                approved_by_id=request.user.pk,
                approved_at=timezone.now(),
            )
            Community.objects.filter(pk=community.pk).update(vendor_count=F("vendor_count") + 1)
            UserRole.objects.get_or_create(
                user=vendor.user, role="vendor", community=community
            )
            vendor.refresh_from_db(fields=["razorpay_onboarding_step"])
            if vendor.razorpay_onboarding_step == "":
                transaction.on_commit(lambda: create_razorpay_linked_account.delay(vendor.pk))

        # TODO: enqueue SMS notification to vendor (split 05)
        return Response({"status": VendorCommunityStatus.APPROVED})


class VendorRejectView(APIView):
    """
    Rejects a vendor's application for a specific community.

    Business logic:
    1. Resolve community_slug → Community; 404 if not found.
    2. Cross-check: verify request.user is admin of the resolved community. 403 if not.
    3. Retrieve VendorCommunity for (vendor, community). Records in pending_review OR
       approved can be rejected. 404 if the record does not exist.
    4. Capture previous_status = vc.status before updating.
    5. Atomic update: status → rejected; rejection_reason = reason.
    6. If previous_status == 'approved': decrement community.vendor_count atomically.
       (vendor_count represents current active/approved vendors, not lifetime count.)

    The vendor can update their documents and re-submit after rejection. The same
    VendorCommunity record is reused; VendorSubmitView resets status to pending_review.

    Returns:
        200: {status: 'rejected'}
        403: not admin of this community
        404: community not found, or VendorCommunity not found
    """
    permission_classes = [IsAuthenticated, IsCommunityAdmin]

    def post(self, request, vendor_id):
        from apps.communities.models import Community
        community_slug = request.data.get("community_slug", "")
        community = get_object_or_404(Community, slug=community_slug)

        if not UserRole.objects.filter(
            user=request.user, role="community_admin", community=community
        ).exists():
            raise PermissionDenied()

        vendor = get_object_or_404(Vendor, pk=vendor_id)
        vc = get_object_or_404(VendorCommunity, vendor=vendor, community=community)

        previous_status = vc.status
        reason = request.data.get("reason", "")

        with transaction.atomic():
            VendorCommunity.objects.filter(pk=vc.pk).update(
                status=VendorCommunityStatus.REJECTED,
                rejection_reason=reason,
            )
            if previous_status == VendorCommunityStatus.APPROVED:
                Community.objects.filter(pk=community.pk).update(
                    vendor_count=F("vendor_count") - 1
                )

        # TODO: enqueue SMS notification to vendor with rejection_reason (split 05)
        return Response({"status": VendorCommunityStatus.REJECTED})


class VendorPublicProfileView(APIView):
    """
    Returns a vendor's public-facing profile for residents to view.

    Exposes only display-safe fields: vendor_id, display_name, bio,
    average_rating, is_new_seller. No KYB, bank, S3 key, FSSAI license
    number, or Razorpay data is included.

    Returns:
        200: VendorPublicProfileSerializer response
        403: not a resident of this community
        404: vendor not found
    """
    permission_classes = [IsAuthenticated, IsResidentOfCommunity]

    def get(self, request, vendor_id):
        vendor = get_object_or_404(Vendor, pk=vendor_id)
        serializer = VendorPublicProfileSerializer(vendor)
        return Response(serializer.data)
