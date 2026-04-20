import os

os.environ.setdefault('AWS_STORAGE_BUCKET_NAME', 'test-bucket')

from .base import *

DEBUG = True
ALLOWED_HOSTS = ['*', 'testserver']

SMS_BACKEND = 'apps.core.sms.backends.console.ConsoleSMSBackend'

DATABASES = {
    'default': env.db('DATABASE_URL', default='sqlite:///test.db')
}

# Use dummy cache for tests to avoid Redis dependency
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.dummy.DummyCache',
    }
}
