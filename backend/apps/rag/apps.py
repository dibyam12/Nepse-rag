from django.apps import AppConfig
import logging

logger = logging.getLogger('nepse_rag')


class RagConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.rag'
    verbose_name = 'NEPSE RAG System'

    def ready(self):
        """
        Initialize RAG indexes when Django starts.

        - Vector index: lazy load (loads on first query to avoid
          downloading embedding model at startup)
        - Graph index: load immediately (fast, ~100ms, pure JSON)
        - Both are optional — if they fail, Django still starts
        """
        import os
        # Avoid running in management commands or migrations
        if os.environ.get('RUN_MAIN') != 'true':
            return

        try:
            from django.conf import settings
            rebuild = getattr(settings, 'GRAPH_REBUILD_ON_STARTUP', False)

            if rebuild:
                from services.graph_rag import build_knowledge_graph
                build_knowledge_graph()
                logger.info("Graph RAG rebuilt on startup")
            else:
                from services.graph_rag import _load_graph
                _load_graph()
                logger.info("Graph RAG loaded from disk")
        except FileNotFoundError:
            logger.warning(
                "Graph store not found — run "
                "'python scripts/build_graph_index.py' first"
            )
        except Exception as e:
            logger.error("Graph RAG initialization failed: %s", e)

        logger.info("Vector RAG ready (lazy loading enabled)")
