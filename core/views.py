from django.shortcuts import render
from datetime import datetime
from django.http import JsonResponse

def logs(request):

    try:
        log_file = f'bot/data/logs/growthbot_{datetime.now().strftime("%Y-%m-%d")}.log'
        with open(log_file, 'r') as file:
            logs = file.read()
    except FileNotFoundError:
        logs = ''

    return JsonResponse({
        'logs': logs,
    })

