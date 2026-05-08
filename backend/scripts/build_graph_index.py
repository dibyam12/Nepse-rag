"""
Build knowledge graph from Django ORM models.

Reads Stock, Sector, NepseIndex from local SQLite and creates
a JSON graph with entity relationships.

Usage:
    python scripts/build_graph_index.py           # always rebuilds
    python scripts/build_graph_index.py --force    # same (graph is fast)
"""

import os
import sys
import time

# Setup Django environment
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'nepse_project.settings')

import django
django.setup()

from services.graph_rag import build_knowledge_graph, get_graph_stats


def main():
    print("=" * 60)
    print("Building NEPSE Knowledge Graph")
    print("=" * 60)

    start = time.time()
    try:
        stats = build_knowledge_graph()
    except Exception as e:
        print(f"\nERROR: {e}")
        sys.exit(1)

    elapsed = time.time() - start

    print()
    print("=" * 60)
    print("Knowledge Graph Built Successfully!")
    print("=" * 60)
    print(f"  Stock nodes:  {stats['stock_nodes']}")
    print(f"  Sector nodes: {stats['sector_nodes']}")
    print(f"  Index nodes:  {stats['index_nodes']}")
    print(f"  Total edges:  {stats['total_edges']}")
    print(f"  Saved to:     {stats['path']}")
    print(f"  Time taken:   {elapsed:.1f}s")
    print()


if __name__ == '__main__':
    main()
