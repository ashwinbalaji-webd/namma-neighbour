import redis
import redis.exceptions
from django.conf import settings
from django.db import OperationalError, connection
from django.http import JsonResponse
from rest_framework import viewsets


def health_check(request):
    try:
        connection.ensure_connection()
        db_status = "ok"
    except OperationalError:
        db_status = "error"

    try:
        r = redis.Redis.from_url(settings.REDIS_URL)
        r.ping()
        redis_status = "ok"
    except (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError, ConnectionError):
        redis_status = "error"

    overall = "ok" if db_status == "ok" and redis_status == "ok" else "error"
    http_status = 200 if overall == "ok" else 503

    return JsonResponse(
        {"status": overall, "db": db_status, "redis": redis_status},
        status=http_status,
    )
