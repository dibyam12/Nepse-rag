"""
Agent URL configuration.
"""
from django.urls import path
from .views import QueryView, StreamQueryView

urlpatterns = [
    path('query/', QueryView.as_view(), name='query'),
    path('query/stream/', StreamQueryView.as_view(), name='query_stream'),
]
