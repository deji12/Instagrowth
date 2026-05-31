from celery import shared_task
from django.conf import settings

@shared_task
def say_hello():
    print('Hello')