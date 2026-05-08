"""
User Conversation & Message models.

Conversation: Groups messages together. Linked to User (authenticated)
              or session_key (anonymous/incognito).
Message:      Individual chat message with optional AI metadata
              (signals, citations, tools_used, route, provider).
"""
from django.conf import settings
from django.db import models


class Conversation(models.Model):
    """A chat conversation (session) between user and AI assistant."""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='conversations',
        help_text='Null for anonymous/incognito sessions',
    )
    session_key = models.CharField(
        max_length=40, blank=True, db_index=True,
        help_text='Django session key for anonymous users',
    )
    title = models.CharField(max_length=200, default='New Chat')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        indexes = [
            models.Index(fields=['user', '-updated_at']),
        ]

    def __str__(self):
        owner = self.user.username if self.user else f'anon:{self.session_key[:8]}'
        return f'{owner} — {self.title}'


class Message(models.Model):
    """A single message in a conversation."""
    ROLE_CHOICES = [
        ('user', 'User'),
        ('assistant', 'Assistant'),
    ]

    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE,
        related_name='messages',
    )
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    content = models.TextField()

    # AI metadata (only for assistant messages)
    signals = models.JSONField(null=True, blank=True)
    citations = models.JSONField(null=True, blank=True)
    tools_used = models.JSONField(null=True, blank=True)
    route_used = models.CharField(max_length=50, blank=True)
    llm_provider = models.CharField(max_length=50, blank=True)
    latency_ms = models.IntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f'{self.role}: {self.content[:60]}'
