import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'nepse_project.settings')
django.setup()

from services.query_router import classify_query
from services.db_service import get_stocks_by_price_filter

question = "give me the list of banks stocks that I should consider to buy"
decision = classify_query(question)
print("1. ROUTE DECISION:")
print(f"   Route: {decision.route}")
print(f"   Sector: {decision.sector}")

print("\n2. DB SCREENER RESULTS:")
stocks_str, stocks_list = get_stocks_by_price_filter(
    sector=decision.sector,
    max_price=decision.price_below,
    min_price=decision.price_above,
    limit=15,
    rank_by_signals=getattr(decision, 'rank_by_signals', False),
)

print(f"\nStocks list output (total {len(stocks_list)}):")
for s in stocks_list:
    print(f"  {s['symbol']} | Sector: {s['sector']} | Close: {s['close']}")
