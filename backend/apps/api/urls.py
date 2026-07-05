"""
API URL configuration.
Central router for all API endpoints.
"""
from django.urls import path, include
from . import views

urlpatterns = [
    # Main query endpoints (agent)
    path('', include('apps.agent.urls')),

    # Data endpoints
    path('symbols/', views.SymbolsListView.as_view(), name='symbols'),
    path('stock/<str:symbol>/', views.StockDetailView.as_view(), name='stock_detail'),
    path('sectors/', views.SectorsListView.as_view(), name='sectors'),
    path('health/', views.HealthCheckView.as_view(), name='health'),


    # RAG test endpoints
    path('rag/', include('apps.rag.urls')),

    # Phase 2 test endpoints
    path('test/news/', views.test_news, name='test_news'),
]
