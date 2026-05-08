"""
Graph RAG service — manually-built knowledge graph from Django ORM.

Builds a property graph of NEPSE entity relationships:
    Stock -> BELONGS_TO_SECTOR -> Sector
    Stock -> LISTED_ON_INDEX  -> NepseIndex
    Stock -> IS_PEER_OF       -> Stock (same sector)

Public API:
    build_knowledge_graph() -> dict
    query_stock_relationships(symbol) -> dict
    query_sector_peers(symbol) -> list[dict]
    query_graph_path(from_symbol, to_symbol) -> dict
    get_graph_stats() -> dict
"""

import os
import json
import time
import logging

from django.conf import settings
from services.cache_service import get_cached_graph_rag, cache_graph_rag

logger = logging.getLogger('nepse_rag')

_graph_data = None
GRAPH_STORE_PATH = None


def _get_graph_store_path() -> str:
    """Returns path to the persisted graph store JSON."""
    global GRAPH_STORE_PATH
    if GRAPH_STORE_PATH is None:
        index_path = getattr(settings, 'INDEX_PATH', './indexes')
        os.makedirs(index_path, exist_ok=True)
        GRAPH_STORE_PATH = os.path.join(index_path, 'graph_store.json')
    return GRAPH_STORE_PATH


def build_knowledge_graph() -> dict:
    """
    Builds the knowledge graph from Django ORM models and persists
    to indexes/graph_store.json.

    Returns stats: {stock_nodes, sector_nodes, index_nodes, total_edges, path}
    """
    global _graph_data
    from apps.nepse_data.models import Stock, Sector, NepseIndex

    start = time.time()

    stocks = list(
        Stock.objects.filter(is_active=True)
        .select_related('sector', 'index').order_by('symbol')
    )
    sectors = list(Sector.objects.all().order_by('name'))
    indexes = list(NepseIndex.objects.all().order_by('name'))

    # Build node dicts
    stock_nodes = {}
    for s in stocks:
        stock_nodes[s.symbol] = {
            'type': 'Stock', 'symbol': s.symbol, 'name': s.name,
            'sector': s.sector.name if s.sector else None,
            'index': s.index.name if s.index else None,
            'market_cap': s.market_cap,
            'listing_date': str(s.listing_date) if s.listing_date else None,
        }

    sector_nodes = {}
    for sec in sectors:
        sector_nodes[sec.name] = {
            'type': 'Sector', 'name': sec.name,
            'description': (sec.description or '')[:200],
            'stock_count': Stock.objects.filter(sector=sec, is_active=True).count(),
        }

    index_nodes = {}
    for idx in indexes:
        index_nodes[idx.name] = {
            'type': 'NepseIndex', 'name': idx.name,
            'description': (idx.description or '')[:200],
        }

    # Build edges
    edges = []
    sector_stocks = {}
    for s in stocks:
        sec_name = s.sector.name if s.sector else None
        if sec_name:
            edges.append({'source': s.symbol, 'target': sec_name,
                          'relation': 'BELONGS_TO_SECTOR'})
            sector_stocks.setdefault(sec_name, []).append(s.symbol)
        if s.index:
            edges.append({'source': s.symbol, 'target': s.index.name,
                          'relation': 'LISTED_ON_INDEX'})

    # Peer edges (one per pair)
    for sec_name, symbols in sector_stocks.items():
        for i, sym_a in enumerate(symbols):
            for sym_b in symbols[i + 1:]:
                edges.append({'source': sym_a, 'target': sym_b,
                              'relation': 'IS_PEER_OF'})

    _graph_data = {
        'stock_nodes': stock_nodes, 'sector_nodes': sector_nodes,
        'index_nodes': index_nodes, 'edges': edges,
        'sector_stocks': sector_stocks,
        'built_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
    }

    store_path = _get_graph_store_path()
    with open(store_path, 'w', encoding='utf-8') as f:
        json.dump(_graph_data, f, indent=2, ensure_ascii=False)

    latency = int((time.time() - start) * 1000)
    stats = {
        'stock_nodes': len(stock_nodes), 'sector_nodes': len(sector_nodes),
        'index_nodes': len(index_nodes), 'total_edges': len(edges),
        'peer_sectors': len(sector_stocks), 'path': store_path,
        'latency_ms': latency,
    }
    logger.info(
        "Knowledge graph built: %d stocks, %d sectors, %d edges (%dms)",
        stats['stock_nodes'], stats['sector_nodes'],
        stats['total_edges'], latency,
        extra={'event': 'graph_build', **stats}
    )
    return stats


def _load_graph() -> dict:
    """Loads graph from disk (lazy singleton)."""
    global _graph_data
    if _graph_data is not None:
        return _graph_data

    store_path = _get_graph_store_path()
    if not os.path.exists(store_path):
        raise FileNotFoundError(
            f"Graph store not found at {store_path}. "
            f"Run 'python scripts/build_graph_index.py' first."
        )
    with open(store_path, 'r', encoding='utf-8') as f:
        _graph_data = json.load(f)

    logger.info("Knowledge graph loaded from %s", store_path,
                extra={'event': 'graph_load'})
    return _graph_data


def query_stock_relationships(symbol: str) -> dict:
    """
    Returns full relationship context for a stock.

    Returns: {symbol, name, sector, index, peers, peer_count,
              graph_nodes_found, sector_description}
    """
    sym = symbol.upper()
    cached = get_cached_graph_rag(sym)
    if cached is not None:
        return cached

    start = time.time()
    empty = {
        'symbol': sym, 'name': None, 'sector': None,
        'index': None, 'peers': [], 'peer_count': 0,
        'graph_nodes_found': [], 'sector_description': None,
    }

    try:
        graph = _load_graph()
    except FileNotFoundError:
        return empty

    stock_info = graph.get('stock_nodes', {}).get(sym)
    if not stock_info:
        return empty

    sector_name = stock_info.get('sector')
    index_name = stock_info.get('index')
    peers = [s for s in graph.get('sector_stocks', {}).get(sector_name, [])
             if s != sym]

    sector_desc = None
    if sector_name:
        sector_desc = graph.get('sector_nodes', {}).get(
            sector_name, {}).get('description', '')

    graph_nodes_found = [sym]
    if sector_name:
        graph_nodes_found.append(sector_name)
    if index_name:
        graph_nodes_found.append(index_name)

    latency = int((time.time() - start) * 1000)
    result = {
        'symbol': sym, 'name': stock_info.get('name'),
        'sector': sector_name, 'index': index_name,
        'peers': peers[:15], 'peer_count': len(peers),
        'graph_nodes_found': graph_nodes_found,
        'sector_description': sector_desc,
    }

    cache_graph_rag(sym, result)
    logger.info("graph_rag: %s -> sector=%s, %d peers (%dms)",
                sym, sector_name, len(peers), latency,
                extra={'event': 'graph_rag_query', 'symbol': sym})
    return result


def query_sector_peers(symbol: str) -> list[dict]:
    """Returns peer stocks in the same sector with basic info."""
    try:
        graph = _load_graph()
    except FileNotFoundError:
        return []

    stock_nodes = graph.get('stock_nodes', {})
    stock_info = stock_nodes.get(symbol.upper())
    if not stock_info or not stock_info.get('sector'):
        return []

    sector_name = stock_info['sector']
    peer_symbols = graph.get('sector_stocks', {}).get(sector_name, [])
    return [
        {'symbol': p, 'name': stock_nodes.get(p, {}).get('name', ''),
         'market_cap': stock_nodes.get(p, {}).get('market_cap')}
        for p in peer_symbols if p != symbol.upper()
    ]


def query_graph_path(from_symbol: str, to_symbol: str) -> dict:
    """Finds relationship path between two stocks via shared sector/index."""
    from_sym, to_sym = from_symbol.upper(), to_symbol.upper()
    empty = {'from_symbol': from_sym, 'to_symbol': to_sym,
             'path': [], 'shared_sector': None,
             'shared_index': None, 'are_peers': False}

    try:
        graph = _load_graph()
    except FileNotFoundError:
        return empty

    stock_nodes = graph.get('stock_nodes', {})
    from_info = stock_nodes.get(from_sym, {})
    to_info = stock_nodes.get(to_sym, {})

    shared_sector = (from_info.get('sector')
                     if from_info.get('sector') == to_info.get('sector')
                     else None)
    shared_index = (from_info.get('index')
                    if from_info.get('index') == to_info.get('index')
                    else None)

    path = [from_sym]
    if shared_sector:
        path.append(f"-> [{shared_sector}] ->")
    elif shared_index:
        path.append(f"-> [{shared_index}] ->")
    else:
        path.append(f"-> [{from_info.get('sector', '?')}]"
                     f" <> [{to_info.get('sector', '?')}] ->")
    path.append(to_sym)

    return {
        'from_symbol': from_sym, 'to_symbol': to_sym,
        'path': path, 'shared_sector': shared_sector,
        'shared_index': shared_index,
        'are_peers': shared_sector is not None,
    }


def get_graph_stats() -> dict:
    """Returns graph stats for /api/rag/status/ endpoint."""
    store_path = _get_graph_store_path()
    try:
        graph = _load_graph()
        return {
            'stock_count': len(graph.get('stock_nodes', {})),
            'sector_count': len(graph.get('sector_nodes', {})),
            'index_count': len(graph.get('index_nodes', {})),
            'edge_count': len(graph.get('edges', [])),
            'built_at': graph.get('built_at'), 'store_path': store_path,
            'loaded': True,
        }
    except FileNotFoundError:
        return {
            'stock_count': 0, 'sector_count': 0,
            'index_count': 0, 'edge_count': 0,
            'built_at': None, 'store_path': store_path, 'loaded': False,
        }
