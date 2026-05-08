"""
RAG app URL configuration.
"""
from django.urls import path
from . import views

app_name = 'rag'

urlpatterns = [
    path('vector/query/', views.vector_query, name='vector_query'),
    path('graph/query/', views.graph_query, name='graph_query'),
    path('route/', views.route_test, name='route_test'),
    path('status/', views.rag_status, name='rag_status'),
]
