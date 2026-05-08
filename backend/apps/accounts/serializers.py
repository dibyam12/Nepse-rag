"""
DRF Serializers for accounts app.

Serializers for user registration, login, profile,
conversation list/detail, and messages.
"""
from django.contrib.auth.models import User
from rest_framework import serializers
from .models import Conversation, Message


class RegisterSerializer(serializers.Serializer):
    """User registration: username + password."""
    username = serializers.CharField(
        min_length=3, max_length=30,
        help_text='3-30 characters, letters/digits/underscores',
    )
    password = serializers.CharField(
        min_length=6, max_length=128, write_only=True,
    )

    def validate_username(self, value):
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError('Username already taken.')
        return value

    def create(self, validated_data):
        user = User.objects.create_user(
            username=validated_data['username'],
            password=validated_data['password'],
        )
        return user


class LoginSerializer(serializers.Serializer):
    """User login: username + password."""
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)


class UserSerializer(serializers.ModelSerializer):
    """Public user profile."""
    class Meta:
        model = User
        fields = ['id', 'username', 'date_joined']
        read_only_fields = fields


class MessageSerializer(serializers.ModelSerializer):
    """Chat message within a conversation."""
    class Meta:
        model = Message
        fields = [
            'id', 'role', 'content', 'signals', 'citations',
            'tools_used', 'route_used', 'llm_provider',
            'latency_ms', 'created_at',
        ]
        read_only_fields = fields


class ConversationListSerializer(serializers.ModelSerializer):
    """Conversation summary for list view (no messages)."""
    message_count = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = ['id', 'title', 'created_at', 'updated_at', 'message_count']
        read_only_fields = fields

    def get_message_count(self, obj):
        return obj.messages.count()


class ConversationDetailSerializer(serializers.ModelSerializer):
    """Conversation with all messages included."""
    messages = MessageSerializer(many=True, read_only=True)

    class Meta:
        model = Conversation
        fields = ['id', 'title', 'created_at', 'updated_at', 'messages']
        read_only_fields = ['id', 'created_at', 'updated_at', 'messages']
