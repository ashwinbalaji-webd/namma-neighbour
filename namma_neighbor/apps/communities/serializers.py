import re

from django.db import IntegrityError, transaction
from rest_framework import serializers
from rest_framework.exceptions import NotFound

from apps.communities.models import Building, Community, Flat, ResidentProfile, generate_unique_slug


class CommunityRegistrationSerializer(serializers.ModelSerializer):
    buildings = serializers.ListField(
        child=serializers.CharField(max_length=50),
        write_only=True,
    )

    class Meta:
        model = Community
        fields = ['name', 'city', 'pincode', 'address', 'buildings', 'slug', 'invite_code', 'is_active']
        read_only_fields = ['slug', 'invite_code', 'is_active']

    def validate_pincode(self, value):
        if not re.match(r'^[0-9]{6}$', value):
            raise serializers.ValidationError("Pincode must be exactly 6 numeric digits.")
        return value

    def validate_buildings(self, value):
        stripped = [name.strip() for name in value]
        if not stripped:
            raise serializers.ValidationError("At least one building name is required.")
        if len({n.lower() for n in stripped}) != len(stripped):
            raise serializers.ValidationError("Building names must be unique within the list.")
        return stripped

    def create(self, validated_data):
        buildings = validated_data.pop('buildings')
        admin_user = self.context['request'].user
        for _ in range(5):
            slug = generate_unique_slug(validated_data['name'], validated_data.get('city', ''))
            try:
                with transaction.atomic():
                    community = Community.objects.create(
                        admin_user=admin_user,
                        slug=slug,
                        **validated_data,
                    )
                    Building.objects.bulk_create([
                        Building(community=community, name=name) for name in buildings
                    ])
                return community
            except IntegrityError:
                continue
        raise serializers.ValidationError("Could not generate a unique community slug after several attempts.")


class CommunityDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = Community
        fields = ['name', 'city', 'slug', 'is_active']


class BuildingSerializer(serializers.ModelSerializer):
    class Meta:
        model = Building
        fields = ['id', 'name']


class FlatSerializer(serializers.ModelSerializer):
    class Meta:
        model = Flat
        fields = ['id', 'flat_number', 'floor', 'building_id']


class JoinCommunitySerializer(serializers.Serializer):
    invite_code = serializers.CharField()
    building_id = serializers.IntegerField()
    flat_number = serializers.CharField(max_length=20)
    user_type = serializers.ChoiceField(choices=ResidentProfile.UserType.choices)

    def validate(self, attrs):
        invite_code = attrs['invite_code'].strip().upper()
        attrs['invite_code'] = invite_code

        try:
            community = Community.objects.get(invite_code=invite_code)
        except Community.DoesNotExist:
            raise NotFound("No community found with this invite code.")

        if not community.is_active:
            raise serializers.ValidationError("This community is no longer active.")

        try:
            building = Building.objects.get(id=attrs['building_id'], community=community)
        except Building.DoesNotExist:
            raise serializers.ValidationError({"building_id": "Building does not belong to this community."})

        request_user = self.context['request'].user
        if ResidentProfile.objects.filter(user=request_user).exists():
            raise serializers.ValidationError("You are already a member of a community.")

        attrs['community'] = community
        attrs['building'] = building
        return attrs


class ResidentProfileSerializer(serializers.ModelSerializer):
    flat = FlatSerializer(read_only=True)
    joined_at = serializers.DateTimeField(source='created_at', read_only=True)

    class Meta:
        model = ResidentProfile
        fields = ['id', 'user_type', 'status', 'flat', 'joined_at']
        read_only_fields = ['id', 'status', 'joined_at']


class ResidentApprovalSerializer(serializers.ModelSerializer):
    """No write fields — action is implicit from the URL. Used for output only."""

    flat = FlatSerializer(read_only=True)
    joined_at = serializers.DateTimeField(source='created_at', read_only=True)

    class Meta:
        model = ResidentProfile
        fields = ['id', 'user_type', 'status', 'flat', 'joined_at']
        read_only_fields = ['id', 'user_type', 'status', 'joined_at']
