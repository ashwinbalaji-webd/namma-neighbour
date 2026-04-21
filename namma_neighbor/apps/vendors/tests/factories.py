import factory

from apps.communities.tests.factories import CommunityFactory
from apps.users.tests.factories import UserFactory
from apps.vendors.models import FSSAIStatus, LogisticsTier, Vendor, VendorCommunity, VendorCommunityStatus


class VendorFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Vendor

    user = factory.SubFactory(UserFactory)
    display_name = factory.Faker("company")
    logistics_tier = LogisticsTier.TIER_B
    is_food_seller = False
    fssai_status = FSSAIStatus.NOT_APPLICABLE
    razorpay_onboarding_step = ""


class VendorCommunityFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = VendorCommunity

    vendor = factory.SubFactory(VendorFactory)
    community = factory.SubFactory(CommunityFactory)
    status = VendorCommunityStatus.PENDING_REVIEW
    delist_threshold = 2
    missed_window_count = 0
