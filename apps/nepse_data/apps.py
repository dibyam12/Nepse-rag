from django.apps import AppConfig


class NepseDataConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.nepse_data'
    verbose_name = 'NEPSE Data'

    def ready(self):
        # Only start keep-alive in the main process
        # (not during migrations, tests, or management commands)
        import os
        if os.environ.get('RUN_MAIN') == 'true' or \
           os.environ.get('DAPHNE') == 'true':
            from services.neon_client import start_keepalive
            start_keepalive()
