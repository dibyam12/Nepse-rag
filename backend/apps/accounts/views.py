"""
Auth & Conversation API views.

Endpoints:
    POST /api/auth/register/           — Create new user + return token
    POST /api/auth/login/              — Login + return token
    POST /api/auth/logout/             — Invalidate token
    GET  /api/auth/profile/            — Current user info
    GET  /api/auth/conversations/      — List user conversations
    POST /api/auth/conversations/      — Create new conversation
    GET  /api/auth/conversations/<id>/ — Get conversation with messages
    DELETE /api/auth/conversations/<id>/ — Delete conversation
"""
import logging

from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Conversation
from .serializers import (
    RegisterSerializer,
    LoginSerializer,
    UserSerializer,
    ConversationListSerializer,
    ConversationDetailSerializer,
)

logger = logging.getLogger('nepse_rag')


class RegisterView(APIView):
    """POST /api/auth/register/ — Create user + return token."""
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {'errors': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )
        user = serializer.save()
        token, _ = Token.objects.get_or_create(user=user)
        logger.info(
            'User registered: %s', user.username,
            extra={'event': 'user_register', 'username': user.username},
        )
        return Response({
            'token': token.key,
            'user': UserSerializer(user).data,
        }, status=status.HTTP_201_CREATED)


class LoginView(APIView):
    """POST /api/auth/login/ — Authenticate + return token."""
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {'errors': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )
        user = authenticate(
            username=serializer.validated_data['username'],
            password=serializer.validated_data['password'],
        )
        if not user:
            return Response(
                {'error': 'Invalid username or password.'},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        token, _ = Token.objects.get_or_create(user=user)
        logger.info(
            'User login: %s', user.username,
            extra={'event': 'user_login', 'username': user.username},
        )
        return Response({
            'token': token.key,
            'user': UserSerializer(user).data,
        })


class LogoutView(APIView):
    """POST /api/auth/logout/ — Delete auth token."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            request.user.auth_token.delete()
        except Exception:
            pass
        return Response({'detail': 'Logged out.'})


class ProfileView(APIView):
    """GET /api/auth/profile/ — Current user info."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(UserSerializer(request.user).data)


class ConversationListView(APIView):
    """
    GET  /api/auth/conversations/ — List user's conversations
    POST /api/auth/conversations/ — Create new conversation
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        convos = Conversation.objects.filter(user=request.user)
        serializer = ConversationListSerializer(convos, many=True)
        return Response(serializer.data)

    def post(self, request):
        title = request.data.get('title', 'New Chat')
        convo = Conversation.objects.create(user=request.user, title=title)
        serializer = ConversationListSerializer(convo)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class ConversationDetailView(APIView):
    """
    GET    /api/auth/conversations/<id>/ — Conversation + messages
    DELETE /api/auth/conversations/<id>/ — Delete conversation
    PATCH  /api/auth/conversations/<id>/ — Update title
    """
    permission_classes = [IsAuthenticated]

    def _get_conversation(self, request, pk):
        try:
            return Conversation.objects.get(pk=pk, user=request.user)
        except Conversation.DoesNotExist:
            return None

    def get(self, request, pk):
        convo = self._get_conversation(request, pk)
        if not convo:
            return Response(
                {'error': 'Conversation not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        serializer = ConversationDetailSerializer(convo)
        return Response(serializer.data)

    def patch(self, request, pk):
        convo = self._get_conversation(request, pk)
        if not convo:
            return Response(
                {'error': 'Conversation not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        title = request.data.get('title')
        if title:
            convo.title = title[:200]
            convo.save(update_fields=['title'])
        serializer = ConversationDetailSerializer(convo)
        return Response(serializer.data)

    def delete(self, request, pk):
        convo = self._get_conversation(request, pk)
        if not convo:
            return Response(
                {'error': 'Conversation not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        convo.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
