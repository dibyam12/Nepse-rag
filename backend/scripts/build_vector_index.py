"""
Build vector index using LlamaIndex + ChromaDB.

Reads all docs/*.txt domain knowledge files, chunks them,
embeds with sentence-transformers, and stores in ChromaDB.

Usage:
    python scripts/build_vector_index.py           # skip if exists
    python scripts/build_vector_index.py --force    # rebuild from scratch
"""

import os
import sys
import time
import argparse

# Setup Django environment
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'nepse_project.settings')

import django
django.setup()

from services.vector_rag import initialize_vector_index, get_vector_index_stats


def main():
    parser = argparse.ArgumentParser(
        description='Build the NEPSE domain knowledge vector index'
    )
    parser.add_argument(
        '--force', action='store_true',
        help='Force rebuild even if index already exists'
    )
    args = parser.parse_args()

    # Check if index already exists
    stats = get_vector_index_stats()
    if stats['chunk_count'] > 0 and not args.force:
        print(f"Vector index already exists ({stats['chunk_count']} chunks).")
        print(f"  Collection: {stats['collection_name']}")
        print(f"  Embedding model: {stats['embedding_model']}")
        print("Use --force to rebuild.")
        return

    print("=" * 60)
    print("Building NEPSE Vector Index")
    print("=" * 60)
    print(f"  Docs path: {stats['docs_path']}")
    print(f"  Embedding: {stats['embedding_model']} ({stats['embedding_device']})")
    print(f"  Force rebuild: {args.force}")
    print()

    start = time.time()
    try:
        initialize_vector_index(force_rebuild=args.force)
    except Exception as e:
        print(f"\nERROR: {e}")
        sys.exit(1)

    elapsed = time.time() - start
    new_stats = get_vector_index_stats()

    print()
    print("=" * 60)
    print("Vector Index Built Successfully!")
    print("=" * 60)
    print(f"  Chunks indexed: {new_stats['chunk_count']}")
    print(f"  Time taken: {elapsed:.1f}s")
    print(f"  Collection: {new_stats['collection_name']}")
    print()


if __name__ == '__main__':
    main()
