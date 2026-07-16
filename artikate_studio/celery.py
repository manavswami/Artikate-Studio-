import os

from celery import Celery


os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "artikate_studio.settings",
)


app = Celery("artikate_studio")


# This loads all Django settings beginning with CELERY_.
app.config_from_object(
    "django.conf:settings",
    namespace="CELERY",
)


# Discover tasks.py inside installed Django applications.
app.autodiscover_tasks()