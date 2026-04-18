"""
NEPSE Data Models — Local SQLite Only

Models for NEPSE stock metadata and news events.
OHLCV data lives in Neon DB (read-only, queried via services/neon_client.py).
Indicators are computed on-demand (services/indicators.py) — never stored.
"""
from django.db import models


class Sector(models.Model):
    """Stock market sector classification (e.g., Commercial Banks, Hydropower)."""
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class NepseIndex(models.Model):
    """NEPSE market index (e.g., NEPSE Index, Sensitive Index)."""
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)

    class Meta:
        verbose_name = 'NEPSE Index'
        verbose_name_plural = 'NEPSE Indexes'
        ordering = ['name']

    def __str__(self):
        return self.name


class Stock(models.Model):
    """Listed stock on NEPSE."""
    symbol = models.CharField(max_length=20, unique=True, db_index=True)
    name = models.CharField(max_length=200)
    sector = models.ForeignKey(
        Sector, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='stocks'
    )
    index = models.ForeignKey(
        NepseIndex, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='stocks'
    )
    market_cap = models.BigIntegerField(null=True, blank=True)
    listing_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['symbol']

    def __str__(self):
        return f"{self.symbol} — {self.name}"


class NewsEvent(models.Model):
    """News article or event related to a stock or the market."""
    symbol = models.ForeignKey(
        Stock, on_delete=models.CASCADE, to_field='symbol',
        null=True, blank=True,
        related_name='news_events'
    )
    headline = models.CharField(max_length=500)
    url = models.URLField(max_length=1000)
    source = models.CharField(max_length=100)
    published_date = models.DateField(null=True, blank=True)
    summary = models.TextField(blank=True)
    sentiment_score = models.DecimalField(
        max_digits=5, decimal_places=4, null=True, blank=True
    )
    fetched_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-published_date', '-fetched_at']
        indexes = [models.Index(fields=['symbol', 'published_date'])]
        verbose_name = 'News Event'

    def __str__(self):
        return f"{self.symbol_id} — {self.headline[:60]}"
