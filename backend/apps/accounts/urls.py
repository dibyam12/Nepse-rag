"""
Accounts URL configuration.
"""
from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    path('register/', views.RegisterView.as_view(), name='register'),
    path('login/', views.LoginView.as_view(), name='login'),
    path('logout/', views.LogoutView.as_view(), name='logout'),
    path('profile/', views.ProfileView.as_view(), name='profile'),
    path('conversations/', views.ConversationListView.as_view(), name='conversations'),
    path('conversations/<int:pk>/', views.ConversationDetailView.as_view(), name='conversation_detail'),
]
