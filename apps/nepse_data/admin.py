"""
Django Admin configuration for NEPSE Data models.
Only local SQLite models — no OHLCV or Indicator (those live in Neon DB).
"""
from django.contrib import admin
from .models import Sector, NepseIndex, Stock, NewsEvent


@admin.register(Sector)
class SectorAdmin(admin.ModelAdmin):
    list_display = ('name', 'description')
    search_fields = ('name',)


@admin.register(NepseIndex)
class NepseIndexAdmin(admin.ModelAdmin):
    list_display = ('name', 'description')
    search_fields = ('name',)


@admin.register(Stock)
class StockAdmin(admin.ModelAdmin):
    list_display = ('symbol', 'name', 'sector', 'index', 'market_cap', 'is_active')
    list_filter = ('is_active', 'sector', 'index')
    search_fields = ('symbol', 'name')
    list_editable = ('is_active',)


@admin.register(NewsEvent)
class NewsEventAdmin(admin.ModelAdmin):
    list_display = ('headline_short', 'symbol', 'source', 'published_date', 'sentiment_score')
    list_filter = ('source', 'published_date', 'symbol')
    search_fields = ('headline', 'summary')
    date_hierarchy = 'published_date'
    list_per_page = 30

    @admin.display(description='Headline')
    def headline_short(self, obj):
        return obj.headline[:80] + '...' if len(obj.headline) > 80 else obj.headline
