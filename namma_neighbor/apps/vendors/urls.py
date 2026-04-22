from django.urls import path

from apps.vendors.views import (
    DocumentUploadView,
    VendorRegistrationView,
    VendorStatusView,
    VendorSubmitView,
)

urlpatterns = [
    path("register/", VendorRegistrationView.as_view(), name="vendor-register"),
    path("<int:vendor_id>/documents/", DocumentUploadView.as_view(), name="vendor-documents"),
    path("<int:vendor_id>/submit/", VendorSubmitView.as_view(), name="vendor-submit"),
    path("<int:vendor_id>/status/", VendorStatusView.as_view(), name="vendor-status"),
]
