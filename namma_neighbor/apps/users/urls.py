from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from apps.users.views import SendOTPView, VerifyOTPView, LogoutView

app_name = "users"

urlpatterns = [
    path("send-otp/", SendOTPView.as_view(), name="send-otp"),
    path("verify-otp/", VerifyOTPView.as_view(), name="verify-otp"),
    path("refresh/", TokenRefreshView.as_view(), name="token-refresh"),
    path("logout/", LogoutView.as_view(), name="logout"),
]
