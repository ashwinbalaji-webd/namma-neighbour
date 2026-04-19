from django.db import models


class Community(models.Model):
    name = models.CharField(max_length=255)

    class Meta:
        db_table = 'communities_community'
