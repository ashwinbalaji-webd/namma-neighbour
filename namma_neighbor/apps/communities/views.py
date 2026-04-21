from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from apps.communities.models import Building, Community
from apps.communities.serializers import (
    BuildingSerializer,
    CommunityDetailSerializer,
    CommunityRegistrationSerializer,
)
from apps.users.models import UserRole
from apps.users.serializers import CustomTokenObtainPairSerializer


class CommunityRegisterView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = CommunityRegistrationSerializer(
            data=request.data,
            context={'request': request},
        )
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            community = serializer.save()
            UserRole.objects.create(
                user=request.user,
                role='community_admin',
                community=community,
            )
            request.user.active_community = community
            request.user.save()
        refresh = CustomTokenObtainPairSerializer.get_token(request.user)
        tokens = {
            'access': str(refresh.access_token),
            'refresh': str(refresh),
        }
        return Response(
            {**serializer.data, 'tokens': tokens},
            status=status.HTTP_201_CREATED,
        )


class CommunityDetailView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [AnonRateThrottle]

    def get(self, request, slug):
        community = get_object_or_404(Community, slug=slug)
        serializer = CommunityDetailSerializer(community)
        return Response(serializer.data)


class BuildingListView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, slug):
        community = get_object_or_404(Community, slug=slug)
        buildings = Building.objects.filter(community=community)
        serializer = BuildingSerializer(buildings, many=True)
        return Response(serializer.data)
