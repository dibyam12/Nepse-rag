"""
RAG test endpoints for Phase 3 verification.

Endpoints:
    GET /api/rag/vector/query/?q=...   — Test vector retrieval
    GET /api/rag/graph/query/?symbol=... — Test graph retrieval
    GET /api/rag/route/?q=...           — Test query routing
    GET /api/rag/status/                — Index health check
"""

import logging
from datetime import datetime, timezone

from django.http import JsonResponse
from django.views.decorators.http import require_GET

from services.vector_rag import query_vector_rag, get_vector_index_stats
from services.graph_rag import (
    query_stock_relationships,
    get_graph_stats,
)
from services.query_router import classify_query

logger = logging.getLogger('nepse_rag')


@require_GET
def vector_query(request):
    """
    GET /api/rag/vector/query/?q=what+is+RSI

    Tests vector RAG retrieval. Returns matching document chunks
    with source file and similarity score.
    """
    question = request.GET.get('q', '').strip()
    if not question:
        return JsonResponse({
            'status': 'error',
            'message': 'Missing required parameter: q',
        }, status=400)

    try:
        results = query_vector_rag(question)
        return JsonResponse({
            'status': 'success',
            'question': question,
            'results': results,
            'total_results': len(results),
            'retrieved_at': datetime.now(timezone.utc).isoformat(),
        })
    except Exception as e:
        logger.error("vector_query failed: %s", e)
        return JsonResponse({
            'status': 'error',
            'message': str(e),
        }, status=500)


@require_GET
def graph_query(request):
    """
    GET /api/rag/graph/query/?symbol=NABIL

    Tests graph RAG retrieval. Returns stock relationships,
    sector, index, and peer stocks.
    """
    symbol = request.GET.get('symbol', '').strip().upper()
    if not symbol:
        return JsonResponse({
            'status': 'error',
            'message': 'Missing required parameter: symbol',
        }, status=400)

    try:
        result = query_stock_relationships(symbol)
        return JsonResponse({
            'status': 'success',
            **result,
        })
    except Exception as e:
        logger.error("graph_query failed: %s", e)
        return JsonResponse({
            'status': 'error',
            'message': str(e),
        }, status=500)


@require_GET
def route_test(request):
    """
    GET /api/rag/route/?q=analyze+NABIL+stock

    Tests query routing. Returns classified intent, extracted
    symbols, and tools needed.
    """
    question = request.GET.get('q', '').strip()
    if not question:
        return JsonResponse({
            'status': 'error',
            'message': 'Missing required parameter: q',
        }, status=400)

    try:
        decision = classify_query(question)
        return JsonResponse({
            'status': 'success',
            'question': question,
            'route': decision.route,
            'symbols': decision.symbols,
            'tools_needed': decision.tools_needed,
        })
    except Exception as e:
        logger.error("route_test failed: %s", e)
        return JsonResponse({
            'status': 'error',
            'message': str(e),
        }, status=500)


@require_GET
def rag_status(request):
    """
    GET /api/rag/status/

    Returns health check for all RAG components: vector index,
    graph index, and query router readiness.
    """
    try:
        vector_stats = get_vector_index_stats()
        graph_stats = get_graph_stats()

        return JsonResponse({
            'status': 'ok',
            'vector_rag': {
                'ready': vector_stats.get('chunk_count', 0) > 0,
                'total_chunks': vector_stats.get('chunk_count', 0),
                'embedding_model': vector_stats.get('embedding_model'),
                'embedding_device': vector_stats.get('embedding_device'),
                'docs_path': vector_stats.get('docs_path'),
            },
            'graph_rag': {
                'ready': graph_stats.get('loaded', False),
                'nodes': {
                    'stocks': graph_stats.get('stock_count', 0),
                    'sectors': graph_stats.get('sector_count', 0),
                    'indices': graph_stats.get('index_count', 0),
                },
                'relationships': graph_stats.get('edge_count', 0),
                'built_at': graph_stats.get('built_at'),
                'store_path': graph_stats.get('store_path'),
            },
            'query_router': {
                'ready': True,
                'routes_supported': [
                    'full_agent', 'compare',
                    'sql_graph', 'vector_only',
                ],
            },
        })
    except Exception as e:
        logger.error("rag_status failed: %s", e)
        return JsonResponse({
            'status': 'error',
            'message': str(e),
        }, status=500)
