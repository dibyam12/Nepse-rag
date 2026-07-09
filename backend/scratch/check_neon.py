import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'nepse_project.settings')
django.setup()

from services.neon_client import execute_neon_query
from apps.nepse_data.models import Stock

# 1. Neon DB check
symbols = ['NABIL', 'NICA', 'EBL', 'LBBL', 'CFCL']
res = execute_neon_query("SELECT symbol, MAX(date) as max_date, COUNT(*) as cnt FROM stocks_stockdata WHERE symbol IN ('NABIL', 'NICA', 'EBL', 'LBBL', 'CFCL') GROUP BY symbol")
print("Neon DB rows:", res)

# 2. SQLite stock count and fields check
for sym in symbols:
    try:
        s = Stock.objects.get(symbol=sym)
        print(f"SQLite Stock: {sym} | Name: {s.name} | Sector: {s.sector.name if s.sector else 'None'}")
    except Stock.DoesNotExist:
        print(f"SQLite Stock: {sym} does not exist!")
