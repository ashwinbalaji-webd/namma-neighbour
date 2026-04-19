import pytest
from apps.communities.models import Community


@pytest.mark.django_db
def test_community_has_expected_fields():
    """Community has fields id, name, is_active, created_at, updated_at."""
    community = Community.objects.create(name="Test Community")
    assert hasattr(community, 'id')
    assert hasattr(community, 'name')
    assert hasattr(community, 'is_active')
    assert hasattr(community, 'created_at')
    assert hasattr(community, 'updated_at')


@pytest.mark.django_db
def test_community_can_be_created_with_name_only():
    """Create a Community with only name set, assert is_active defaults to True."""
    community = Community.objects.create(name="Test Community")
    assert community.is_active is True


@pytest.mark.django_db
def test_community_inherits_timestamps():
    """Create a Community, assert created_at and updated_at are both set and non-null."""
    community = Community.objects.create(name="Test Community")
    assert community.created_at is not None
    assert community.updated_at is not None


@pytest.mark.django_db
def test_community_str():
    """assert str(community) is sensible (returns the name or a non-empty string)."""
    community = Community.objects.create(name="Test Community")
    assert str(community) == "Test Community"
