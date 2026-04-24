from django.urls import path

from apps.communities.views import (
    BuildingListView,
    CommunityDetailView,
    CommunityRegisterView,
    CommunitySettingsView,
    InviteRegenerateView,
    JoinCommunityView,
    ResidentApproveView,
    ResidentListView,
    ResidentRejectView,
)
from apps.vendors.views import CommunityPendingVendorsView

app_name = "communities"

urlpatterns = [
    path("register/", CommunityRegisterView.as_view(), name="register"),
    path("join/", JoinCommunityView.as_view(), name="join"),
    # Must be before <slug:slug>/ to avoid the greedy slug pattern shadowing this URL
    path("<slug:slug>/vendors/pending/", CommunityPendingVendorsView.as_view(), name="pending-vendors"),
    path("<slug:slug>/", CommunityDetailView.as_view(), name="detail"),
    path("<slug:slug>/buildings/", BuildingListView.as_view(), name="buildings"),
    path("<slug:slug>/residents/", ResidentListView.as_view(), name="resident-list"),
    path("<slug:slug>/residents/<int:pk>/approve/", ResidentApproveView.as_view(), name="resident-approve"),
    path("<slug:slug>/residents/<int:pk>/reject/", ResidentRejectView.as_view(), name="resident-reject"),
    path("<slug:slug>/settings/", CommunitySettingsView.as_view(), name="settings"),
    path("<slug:slug>/invite/regenerate/", InviteRegenerateView.as_view(), name="invite-regenerate"),
]
