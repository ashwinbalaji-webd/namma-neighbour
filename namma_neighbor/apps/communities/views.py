from rest_framework.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import F
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from apps.communities.models import Building, Community, Flat, ResidentProfile, _generate_invite_code, infer_floor
from apps.communities.serializers import (
    BuildingSerializer,
    CommunityDetailSerializer,
    CommunityRegistrationSerializer,
    CommunitySettingsSerializer,
    JoinCommunitySerializer,
    ResidentApprovalSerializer,
    ResidentProfileSerializer,
)
from apps.core.permissions import IsCommunityAdmin
from apps.users.models import UserRole
from apps.users.serializers import CustomTokenObtainPairSerializer


def get_community_or_403(slug, request):
    community = get_object_or_404(Community, slug=slug)
    if not request.auth or request.auth.payload.get('community_id') != community.pk:
        raise PermissionDenied
    return community


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


class JoinCommunityView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = JoinCommunitySerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)

        community = serializer.validated_data['community']
        building = serializer.validated_data['building']
        flat_number = serializer.validated_data['flat_number']
        user_type = serializer.validated_data['user_type']

        with transaction.atomic():
            flat, created = Flat.objects.get_or_create(building=building, flat_number=flat_number)
            if created:
                flat.floor = infer_floor(flat_number)
                flat.save(update_fields=['floor'])
            profile = ResidentProfile.objects.create(
                user=request.user,
                community=community,
                flat=flat,
                user_type=user_type,
                status=ResidentProfile.Status.PENDING,
            )
            Community.objects.filter(pk=community.pk).update(resident_count=F('resident_count') + 1)
            UserRole.objects.get_or_create(user=request.user, role='resident', community=community)
            request.user.active_community = community
            request.user.save()

        refresh = CustomTokenObtainPairSerializer.get_token(request.user)
        tokens = {
            'access': str(refresh.access_token),
            'refresh': str(refresh),
        }
        return Response(
            {**ResidentProfileSerializer(profile).data, 'tokens': tokens},
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


class ResidentListView(APIView):
    permission_classes = [IsAuthenticated, IsCommunityAdmin]

    def get(self, request, slug):
        community = get_community_or_403(slug, request)
        qs = ResidentProfile.objects.filter(community=community).select_related('flat', 'user').order_by('id')
        status_filter = request.query_params.get('status')
        if status_filter in ('PENDING', 'APPROVED', 'REJECTED'):
            qs = qs.filter(status=status_filter)
        paginator = PageNumberPagination()
        paginator.page_size = 20
        page = paginator.paginate_queryset(qs, request)
        serializer = ResidentProfileSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class ResidentApproveView(APIView):
    permission_classes = [IsAuthenticated, IsCommunityAdmin]

    def post(self, request, slug, pk):
        community = get_community_or_403(slug, request)
        try:
            profile = ResidentProfile.objects.get(pk=pk, community=community)
        except ResidentProfile.DoesNotExist:
            raise NotFound
        profile.status = ResidentProfile.Status.APPROVED
        profile.save(update_fields=['status'])
        return Response(ResidentApprovalSerializer(profile).data)


class ResidentRejectView(APIView):
    permission_classes = [IsAuthenticated, IsCommunityAdmin]

    def post(self, request, slug, pk):
        community = get_community_or_403(slug, request)
        try:
            profile = ResidentProfile.objects.get(pk=pk, community=community)
        except ResidentProfile.DoesNotExist:
            raise NotFound
        profile.status = ResidentProfile.Status.REJECTED
        profile.save(update_fields=['status'])
        return Response(ResidentApprovalSerializer(profile).data)


class CommunitySettingsView(APIView):
    permission_classes = [IsAuthenticated, IsCommunityAdmin]

    def patch(self, request, slug):
        community = get_community_or_403(slug, request)

        serializer = CommunitySettingsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        buildings = serializer.validated_data.pop('buildings', None)
        if buildings:
            Building.objects.bulk_create(
                [Building(community=community, name=n) for n in buildings],
                ignore_conflicts=True,
            )

        update_fields = []
        for field in ('commission_pct', 'is_active'):
            if field in serializer.validated_data:
                setattr(community, field, serializer.validated_data[field])
                update_fields.append(field)

        if update_fields:
            community.save(update_fields=update_fields)

        building_names = list(
            Building.objects.filter(community=community).values_list('name', flat=True)
        )
        return Response({
            'slug': community.slug,
            'commission_pct': community.commission_pct,
            'is_active': community.is_active,
            'buildings': building_names,
        })


class InviteRegenerateView(APIView):
    permission_classes = [IsAuthenticated, IsCommunityAdmin]

    def post(self, request, slug):
        community = get_community_or_403(slug, request)

        new_code = _generate_invite_code()
        while Community.objects.filter(invite_code=new_code).exists():
            new_code = _generate_invite_code()

        Community.objects.filter(pk=community.pk).update(invite_code=new_code)
        return Response({'invite_code': new_code})
