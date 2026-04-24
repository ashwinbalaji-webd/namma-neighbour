from django.urls import path

from apps.vendors.views import (
    DocumentUploadView,
    VendorApproveView,
    VendorPublicProfileView,
    VendorRegistrationView,
    VendorRejectView,
    VendorStatusView,
    VendorSubmitView,
)

app_name = "vendors"

urlpatterns = [
    path("vendors/register/", VendorRegistrationView.as_view(), name="register"),
    path("vendors/<int:vendor_id>/documents/", DocumentUploadView.as_view(), name="documents"),
    path("vendors/<int:vendor_id>/submit/", VendorSubmitView.as_view(), name="submit"),
    path("vendors/<int:vendor_id>/status/", VendorStatusView.as_view(), name="status"),
    path("vendors/<int:vendor_id>/profile/", VendorPublicProfileView.as_view(), name="profile"),
    path("vendors/<int:vendor_id>/approve/", VendorApproveView.as_view(), name="approve"),
    path("vendors/<int:vendor_id>/reject/", VendorRejectView.as_view(), name="reject"),
]
