"""
Vector RAG service using LlamaIndex VectorStoreIndex + ChromaDB.

Ingests domain knowledge from docs/*.txt files into a persistent
ChromaDB vector store. Uses sentence-transformers/all-MiniLM-L6-v2
for embeddings (CPU-only, ~80MB model).

Public API:
    initialize_vector_index(force_rebuild=False) -> VectorStoreIndex
    query_vector_rag(question, top_k=3) -> list[dict]
    get_vector_index_stats() -> dict
"""

import os
import time
import logging

import chromadb
from django.conf import settings

from llama_index.core import (
    VectorStoreIndex,
    SimpleDirectoryReader,
    StorageContext,
    Settings as LlamaSettings,
)
from llama_index.core.node_parser import SentenceSplitter
from llama_index.vector_stores.chroma import ChromaVectorStore
from llama_index.embeddings.huggingface import HuggingFaceEmbedding

from services.cache_service import get_cached_vector_rag, cache_vector_rag

logger = logging.getLogger('nepse_rag')

# ── Module-level singleton ────────────────────────────────────
_index = None
_embed_model = None

COLLECTION_NAME = "nepse_docs"


def _get_embed_model():
    """
    Returns the HuggingFace embedding model singleton.
    Loads model on first call (~80MB download on first run).
    Explicitly uses CPU to respect 8GB RAM / no GPU constraint.
    """
    global _embed_model
    if _embed_model is None:
        logger.info("Loading embedding model: %s (device=%s)",
                     settings.EMBEDDING_MODEL, settings.EMBEDDING_DEVICE)
        start = time.time()
        _embed_model = HuggingFaceEmbedding(
            model_name=settings.EMBEDDING_MODEL,
            device=settings.EMBEDDING_DEVICE,
        )
        latency = int((time.time() - start) * 1000)
        logger.info("Embedding model loaded in %dms", latency,
                     extra={'event': 'embed_model_load', 'latency_ms': latency})
    return _embed_model


def _get_chroma_collection():
    """
    Returns the ChromaDB persistent collection for domain docs.
    Creates the collection if it doesn't exist.
    """
    db_path = getattr(settings, 'CHROMA_DB_PATH', './chroma_db')
    os.makedirs(db_path, exist_ok=True)
    client = chromadb.PersistentClient(path=db_path)
    return client.get_or_create_collection(COLLECTION_NAME)


def initialize_vector_index(force_rebuild: bool = False) -> VectorStoreIndex:
    """
    Initializes (or rebuilds) the vector index from docs/*.txt.

    Steps:
    1. Configure LlamaIndex to use local HuggingFace embeddings (no LLM)
    2. Connect to persistent ChromaDB collection
    3. If force_rebuild or collection is empty:
       a. Load all docs/*.txt via SimpleDirectoryReader
       b. Chunk with SentenceSplitter (512 tokens, 50 overlap)
       c. Build VectorStoreIndex (embeds + stores in ChromaDB)
    4. Else: load existing index from ChromaDB

    Args:
        force_rebuild: If True, re-indexes all documents even if
                       ChromaDB already has data.

    Returns:
        VectorStoreIndex ready for querying.
    """
    global _index

    # Configure LlamaIndex global settings
    embed_model = _get_embed_model()
    LlamaSettings.embed_model = embed_model
    # Disable LLM — Phase 3 is retrieval-only
    LlamaSettings.llm = None

    # Connect to ChromaDB
    chroma_collection = _get_chroma_collection()
    vector_store = ChromaVectorStore(chroma_collection=chroma_collection)

    existing_count = chroma_collection.count()
    should_rebuild = force_rebuild or existing_count == 0

    if should_rebuild:
        logger.info("Building vector index from docs/ (force=%s, existing=%d)",
                     force_rebuild, existing_count)
        start = time.time()

        # Load documents
        docs_path = getattr(settings, 'DOCS_PATH', './docs')
        if not os.path.isdir(docs_path):
            raise FileNotFoundError(
                f"Docs directory not found: {docs_path}. "
                f"Create docs/*.txt files before building the index."
            )

        documents = SimpleDirectoryReader(
            input_dir=docs_path,
            required_exts=[".txt"],
            recursive=False,
        ).load_data()

        if not documents:
            raise ValueError(f"No .txt files found in {docs_path}")

        # Configure chunking
        splitter = SentenceSplitter(
            chunk_size=getattr(settings, 'VECTOR_CHUNK_SIZE', 512),
            chunk_overlap=getattr(settings, 'VECTOR_CHUNK_OVERLAP', 50),
        )

        # Build index (embeds all chunks → stores in ChromaDB)
        storage_context = StorageContext.from_defaults(
            vector_store=vector_store
        )
        _index = VectorStoreIndex.from_documents(
            documents,
            storage_context=storage_context,
            transformations=[splitter],
            show_progress=True,
        )

        latency = int((time.time() - start) * 1000)
        new_count = chroma_collection.count()
        logger.info(
            "Vector index built: %d docs → %d chunks (%dms)",
            len(documents), new_count, latency,
            extra={
                'event': 'vector_index_build',
                'doc_count': len(documents),
                'chunk_count': new_count,
                'latency_ms': latency,
            }
        )
    else:
        logger.info("Loading existing vector index (%d chunks)", existing_count)
        _index = VectorStoreIndex.from_vector_store(
            vector_store=vector_store,
        )

    return _index


def _get_index() -> VectorStoreIndex:
    """
    Returns the vector index singleton.
    Lazy-loads on first call to avoid slow Django startup.
    """
    global _index
    if _index is None:
        _index = initialize_vector_index(force_rebuild=False)
    return _index


def query_vector_rag(question: str, top_k: int = None) -> list[dict]:
    """
    Queries the vector RAG index for relevant document chunks.

    Steps:
    1. Check cache (TTL 30 min)
    2. If miss: query ChromaDB via LlamaIndex retriever
    3. Format results, cache, return

    Args:
        question: Natural language query
        top_k: Number of chunks to retrieve (default from settings)

    Returns:
        List of dicts, each with:
        - text: chunk content (capped at 300 tokens / ~1200 chars)
        - source_file: original filename
        - score: similarity score (0-1)

    Returns empty list if index is not built or query fails.
    """
    if top_k is None:
        top_k = getattr(settings, 'VECTOR_TOP_K', 3)

    # 1. Check cache
    cached = get_cached_vector_rag(question)
    if cached is not None:
        logger.debug("vector_rag cache hit for: %s", question[:50])
        return cached

    # 2. Query index
    try:
        start = time.time()
        index = _get_index()
        retriever = index.as_retriever(similarity_top_k=top_k)
        nodes = retriever.retrieve(question)
        latency = int((time.time() - start) * 1000)
    except Exception as e:
        logger.error("vector_rag query failed: %s", e,
                     extra={'event': 'vector_rag_error'})
        return []

    # 3. Format results
    results = []
    for node in nodes:
        # Extract source filename from metadata
        metadata = node.node.metadata or {}
        source_file = metadata.get('file_name', 'unknown')

        # Cap text at ~1200 chars (~300 tokens) for tool output budget
        text = node.node.get_content()
        if len(text) > 1200:
            text = text[:1200] + "..."

        results.append({
            'text': text,
            'source_file': source_file,
            'score': round(float(node.score), 4) if node.score else 0.0,
        })

    # 4. Cache and return
    cache_vector_rag(question, results)
    logger.info(
        "vector_rag: %d chunks for '%s' (%dms)",
        len(results), question[:50], latency,
        extra={
            'event': 'vector_rag_query',
            'chunks': len(results),
            'latency_ms': latency,
        }
    )
    return results


def get_vector_index_stats() -> dict:
    """
    Returns stats about the vector index.
    Used by /api/rag/status/ endpoint.

    Returns:
        {collection_name, chunk_count, docs_path, embedding_model}
    """
    try:
        collection = _get_chroma_collection()
        count = collection.count()
    except Exception:
        count = 0

    return {
        'collection_name': COLLECTION_NAME,
        'chunk_count': count,
        'docs_path': getattr(settings, 'DOCS_PATH', './docs'),
        'embedding_model': getattr(settings, 'EMBEDDING_MODEL', 'unknown'),
        'embedding_device': getattr(settings, 'EMBEDDING_DEVICE', 'cpu'),
    }
