from django.apps import AppConfig


class AgentConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.agent'
    verbose_name = 'Agent'

    def ready(self):
        try:
            from services.query_router import get_known_symbols
            get_known_symbols()
        except Exception as e:
            import logging
            logging.getLogger('nepse_rag').warning(f"Failed to preload symbols: {e}")
