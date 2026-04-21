from django.urls import path

from apps.communities.views import BuildingListView, CommunityDetailView, CommunityRegisterView

app_name = "communities"

urlpatterns = [
    path("register/", CommunityRegisterView.as_view(), name="register"),
    path("<slug:slug>/", CommunityDetailView.as_view(), name="detail"),
    path("<slug:slug>/buildings/", BuildingListView.as_view(), name="buildings"),
]
