"""
API views for NEPSE AI Research Assistant.

Endpoints:
    GET  /api/symbols/          — All active stocks
    GET  /api/stock/<symbol>/   — Stock detail + latest indicators
    GET  /api/sectors/          — Sectors with stock lists
    GET  /api/health/           — Service health check
    GET  /api/test/news/        — Test news endpoint (Phase 2)
"""
import asyncio
import logging

from django.http import JsonResponse
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

logger = logging.getLogger('nepse_rag')


# ── Symbols List ──────────────────────────────────────────────

class SymbolsListView(APIView):
    """
    GET /api/symbols/
    Returns all active stocks sorted alphabetically.
    Cached 24 hours in db_service.get_all_symbols().
    """

    def get(self, request):
        from services.db_service import get_all_symbols
        symbols = get_all_symbols()
        return Response(symbols)


# ── Stock Detail ──────────────────────────────────────────────

class StockDetailView(APIView):
    """
    GET /api/stock/<symbol>/
    Returns latest OHLCV + computed indicators for a symbol.
    """

    def get(self, request, symbol):
        symbol = symbol.upper().strip()
        if not symbol:
            return Response(
                {'error': 'Symbol is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            from services.db_service import (
                get_latest_ohlcv, get_latest_indicators, get_stock_info,
            )

            # Get metadata from local SQLite
            try:
                info = get_stock_info(symbol)
            except Exception:
                info = {'symbol': symbol}

            # Get OHLCV + indicators from Neon DB (async)
            loop = asyncio.new_event_loop()
            try:
                ohlcv = loop.run_until_complete(get_latest_ohlcv(symbol))
                indicators = loop.run_until_complete(
                    get_latest_indicators(symbol)
                )
            finally:
                loop.close()

            return Response({
                'info': info,
                'ohlcv': ohlcv,
                'indicators': indicators,
            })

        except ValueError as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_404_NOT_FOUND,
            )
        except Exception as e:
            logger.error(
                'Stock detail failed for %s: %s', symbol, e,
                extra={'event': 'stock_detail_error', 'symbol': symbol},
            )
            return Response(
                {'error': f'Failed to fetch data for {symbol}.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


# ── Sectors List ──────────────────────────────────────────────

class SectorsListView(APIView):
    """
    GET /api/sectors/
    Returns all sectors with their stock symbols.
    """

    def get(self, request):
        from apps.nepse_data.models import Sector
        sectors = Sector.objects.prefetch_related('stocks').all()

        result = []
        for sector in sectors:
            stocks = sector.stocks.filter(
                is_active=True
            ).values_list('symbol', flat=True).order_by('symbol')
            result.append({
                'name': sector.name,
                'stocks': list(stocks),
            })

        return Response(result)


# ── Health Check ──────────────────────────────────────────────

class HealthCheckView(APIView):
    """
    GET /api/health/
    Returns status of all services: database, ChromaDB,
    graph index, LLM providers, and cache.
    """

    def get(self, request):
        health = {
            'status': 'ok',
            'database': 'unknown',
            'neon_db': 'unknown',
            'chroma_db': 'unknown',
            'graph_index': 'unknown',
            'llm_providers': {},
            'cache': 'unknown',
        }

        # 1. Local SQLite
        try:
            from apps.nepse_data.models import Stock
            count = Stock.objects.count()
            health['database'] = f'connected ({count} stocks)'
        except Exception as e:
            health['database'] = f'error: {e}'
            health['status'] = 'degraded'

        # 2. Neon DB
        try:
            from services.neon_client import execute_neon_query
            rows = execute_neon_query('SELECT 1')
            health['neon_db'] = 'connected'
        except Exception as e:
            health['neon_db'] = f'error: {e}'
            health['status'] = 'degraded'

        # 3. ChromaDB / Vector Index
        try:
            from services.vector_rag import get_vector_index_stats
            stats = get_vector_index_stats()
            chunk_count = stats.get('chunk_count', 0)
            health['chroma_db'] = f'loaded ({chunk_count} chunks)'
        except Exception as e:
            health['chroma_db'] = f'error: {e}'

        # 4. Graph Index
        try:
            from services.graph_rag import get_graph_stats
            stats = get_graph_stats()
            node_count = stats.get('stock_count', 0)
            health['graph_index'] = f'loaded ({node_count} nodes)'
        except Exception as e:
            health['graph_index'] = f'error: {e}'

        # 5. LLM Providers
        from services.cache_service import is_llm_provider_exhausted
        from decouple import config as decouple_config
        providers = {
            'groq': ('GROQ_API_KEY', 'groq'),
            'google_ai_studio': ('GOOGLE_AI_API_KEY', 'google_ai_studio'),
            'openrouter': ('OPENROUTER_API_KEY', 'openrouter'),
            'ollama': (None, 'ollama'),
        }
        for display_name, (env_key, cache_name) in providers.items():
            if env_key:
                key = decouple_config(env_key, default='')
                if not key:
                    health['llm_providers'][display_name] = 'no API key'
                elif is_llm_provider_exhausted(cache_name):
                    health['llm_providers'][display_name] = 'exhausted'
                else:
                    health['llm_providers'][display_name] = 'available'
            else:
                # Ollama — check if running
                health['llm_providers'][display_name] = 'available (local)'

        # 6. Cache
        try:
            from django.core.cache import cache
            cache.set('_health_check', True, timeout=10)
            if cache.get('_health_check'):
                health['cache'] = 'connected'
            else:
                health['cache'] = 'error: read-back failed'
        except Exception as e:
            health['cache'] = f'error: {e}'

        return Response(health)


# ── Test News (from Phase 2) ─────────────────────────────────

def test_news(request):
    """GET /api/test/news/?symbol=NABIL — Phase 2 test endpoint."""
    from services.news_scraper import get_news_for_symbol
    symbol = request.GET.get('symbol', 'NABIL').upper()
    loop = asyncio.new_event_loop()
    try:
        results = loop.run_until_complete(get_news_for_symbol(symbol))
    finally:
        loop.close()
    return JsonResponse({
        'symbol': symbol,
        'count': len(results),
        'results': results,
    })
