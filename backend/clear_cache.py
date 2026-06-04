import os
import sys

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'nepse_project.settings')

import django
django.setup()

from django.core.cache import cache

def main():
    print("Clearing Django cache...")
    cache.clear()
    print("Cache cleared successfully.")

if __name__ == "__main__":
    main()
