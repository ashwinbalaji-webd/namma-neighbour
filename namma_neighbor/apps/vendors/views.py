import re

from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsVendorOwner
from apps.vendors.models import FSSAIStatus, Vendor, VendorCommunity, VendorCommunityStatus
from apps.vendors.serializers import (
    DocumentUploadSerializer,
    VendorRegistrationSerializer,
    VendorStatusSerializer,
)
from apps.vendors.services.storage import upload_vendor_document
from apps.vendors.tasks import verify_fssai

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
