"""
ASGI config for nepse_project.
Django Channels entrypoint.
"""
import os
from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'nepse_project.settings')

application = ProtocolTypeRouter({
    'http': get_asgi_application(),
    # WebSocket/SSE routes will be added in later phases
})
