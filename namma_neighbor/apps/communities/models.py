from django.db import models
from apps.core.models import TimestampedModel


class Community(TimestampedModel):
    name = models.CharField(max_length=200)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'communities_community'

    def __str__(self):
        return self.name
