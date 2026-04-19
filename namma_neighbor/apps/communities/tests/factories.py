import factory
from apps.communities.models import Community


class CommunityFactory(factory.django.DjangoModelFactory):
    name = factory.Sequence(lambda n: f"Community {n}")
    is_active = True

    class Meta:
        model = Community
