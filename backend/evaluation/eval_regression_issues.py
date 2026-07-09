"""
Regression test suite for:
- Issue 7: Context-blocking check and Narrowed triggers.
- Issue 8: Multi-stock prompt formatting instruction alignment and signals array format structure assertion.
"""
import os
import sys
import asyncio
from pathlib import Path

# Django setup
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nepse_project.settings")

import django
django.setup()

from services.query_router import classify_query, extract_symbols
from services.llm_client import build_rag_prompt
from services.db_service import get_stocks_by_price_filter
from apps.agent.views import _enrich_signals_with_sector

def test_context_blocking():
    print("\n--- TEST 1: Stale Context Symbol Blocking (Issue 7) ---")
    
    # 1. Ask about a specific symbol (e.g. NABIL). It should set a symbol context.
    # If the subsequent query is sector/list/market level, block it.
    dec1 = classify_query("what are hydropower stocks under 200?")
    print(f"Query: 'what are hydropower stocks under 200?'")
    print(f"  block_context_symbol: {dec1.block_context_symbol} (Expected: True)")
    assert dec1.block_context_symbol, "Should block context symbol for generic sector screeners"

    # 2. Narrowed pronoun/follow-up indicators check:
    # If the subsequent query is a relative comparison or pronoun-based follow-up, do NOT block it.
    dec2 = classify_query("how does its price compare to the sector?")
    print(f"Query: 'how does its price compare to the sector?'")
    print(f"  block_context_symbol: {dec2.block_context_symbol} (Expected: False)")
    assert not dec2.block_context_symbol, "Should preserve context symbol for pronoun/its sector comparisons"

    dec3 = classify_query("what are its peers?")
    print(f"Query: 'what are its peers?'")
    print(f"  block_context_symbol: {dec3.block_context_symbol} (Expected: False)")
    assert not dec3.block_context_symbol, "Should preserve context symbol for its peers follow-ups"

def test_multi_stock_prompt_instructions():
    print("\n--- TEST 2: Multi-Stock prompt formatting instructions (Issue 8) ---")
    
    # Verify build_rag_prompt instructions for different routes include the multi-stock formatting rules
    for route in ['vector_only', 'full_agent', 'compare', 'sql_graph', 'screener']:
        prompt = build_rag_prompt("give me a list of stocks", ["dummy data"], route=route)
        has_table_rule = "Always format multi-stock results as a markdown table" in prompt
        has_no_bullets_rule = "Never use bullet lists or bold-per-line" in prompt
        
        print(f"  Route: {route:12} | Contains table rule: {has_table_rule} | Contains no-bullets rule: {has_no_bullets_rule}")
        assert has_table_rule, f"Missing table rule for route: {route}"
        assert has_no_bullets_rule, f"Missing no-bullets rule for route: {route}"

def test_multi_stock_signals_structure():
    print("\n--- TEST 3: Multi-Stock Signals Array Structure (Issue 8) ---")
    
    # Get multi-stock signals using the db_service
    # By calling sector='Commercial Banks'
    stocks_str, stocks_list = get_stocks_by_price_filter(sector='Commercial Banks', rank_by_signals=True, limit=5)
    
    # We enrich it using _enrich_signals_with_sector (exactly like views.py)
    enriched = _enrich_signals_with_sector(stocks_list)
    
    print(f"  Retrieved {len(enriched)} commercial banks.")
    assert len(enriched) > 1, "Should return multiple banks"
    assert isinstance(enriched, list), "Enriched signals payload must be a list"
    
    for i, stock in enumerate(enriched):
        print(f"  Stock {i+1}: {stock.get('symbol')} | Close: {stock.get('close')} | RSI: {stock.get('rsi')} | MACD: {stock.get('macd')} | MFI: {stock.get('mfi')} | Sector: {stock.get('sector')}")
        assert 'symbol' in stock, "Missing 'symbol' key"
        assert 'close' in stock, "Missing 'close' key"
        assert 'rsi' in stock, "Missing 'rsi' key"
        assert 'macd' in stock, "Missing 'macd' key"
        assert 'mfi' in stock, "Missing 'mfi' key"
        assert 'sector' in stock, "Missing 'sector' key"
        assert stock['sector'] == 'Commercial Banks', f"Invalid sector mapping: {stock['sector']}"

def test_sector_data_integrity():
    """Issue 9: Verify critical sectors have sufficient stocks tagged in the DB."""
    print("\n--- TEST 4: Sector Data Integrity (Issue 9) ---")
    from apps.nepse_data.models import Stock
    from django.db.models import Count

    sector_counts = {
        item['sector__name']: item['count']
        for item in Stock.objects.values('sector__name').annotate(count=Count('id'))
        if item['sector__name'] is not None
    }

    print(f"  Sector counts: {sector_counts}")

    critical_sectors = {
        'Commercial Banks': 10,
        'Hydropower': 20,
        'Microfinance': 15,
        'Development Banks': 5,
        'Finance Companies': 5,
    }
    for sector, min_count in critical_sectors.items():
        actual = sector_counts.get(sector, 0)
        print(f"  {sector}: {actual} stocks (min required: {min_count})")
        assert actual >= min_count, f"Sector '{sector}' only has {actual} stocks, expected >= {min_count}"
    print("  PASS: All critical sectors have sufficient stocks")


def test_db_service_returns_tuple():
    """Issue 9: get_stocks_by_price_filter must ALWAYS return a (str, list) tuple."""
    print("\n--- TEST 5: db_service returns tuple always (Issue 9) ---")

    # Case 1: Valid sector
    result = get_stocks_by_price_filter(sector='Commercial Banks', limit=3)
    assert isinstance(result, tuple) and len(result) == 2, f"Expected (str, list) tuple, got: {type(result)}"
    s, lst = result
    assert isinstance(s, str), f"First element must be str, got {type(s)}"
    assert isinstance(lst, list), f"Second element must be list, got {type(lst)}"
    print(f"  Valid sector -> tuple OK. Count: {len(lst)}")

    # Case 2: Unknown sector → must return (error_str, []) not just a plain string
    result2 = get_stocks_by_price_filter(sector='FakeSectorXYZ', limit=3)
    assert isinstance(result2, tuple) and len(result2) == 2, f"Unknown sector must still return tuple, got: {type(result2)}"
    s2, lst2 = result2
    assert lst2 == [], f"Unknown sector must return empty list, got: {lst2}"
    assert 'No stocks found' in s2 or 'Error' in s2, f"Expected error string, got: {s2}"
    print(f"  Unknown sector -> tuple OK. Message: {s2[:60]}")

    print("  PASS: db_service always returns (str, list) tuple")


def test_context_blocking_order_of_operations():
    """Issue 10: classify_query must block context for generic hydro/sector/banks queries."""
    print("\n--- TEST 6: Context blocking order-of-operations (Issues 10 & 11) ---")

    # Hydro (with 'hydro' short form)
    dec_hydro = classify_query("give me list of hydro stocks to invest in")
    print(f"  'give me list of hydro stocks to invest in' -> block={dec_hydro.block_context_symbol}, route={dec_hydro.route}")
    assert dec_hydro.block_context_symbol, "hydro query must block context symbol"
    assert dec_hydro.route == 'screener', f"hydro query should be screener, got: {dec_hydro.route}"

    # Full 'hydropower'
    dec_hydrop = classify_query("list of hydropower stocks under 500")
    print(f"  'list of hydropower stocks under 500' -> block={dec_hydrop.block_context_symbol}, route={dec_hydrop.route}")
    assert dec_hydrop.block_context_symbol, "hydropower query must block context symbol"

    # 'banks' plural
    dec_banks = classify_query("which banks stocks should I buy?")
    print(f"  'which banks stocks should I buy?' -> block={dec_banks.block_context_symbol}, sector={dec_banks.sector}")
    assert dec_banks.block_context_symbol, "banks query must block context symbol"
    assert dec_banks.sector == 'Commercial Banks', f"'banks' must map to 'Commercial Banks', got: {dec_banks.sector}"

    # Pronoun follow-up must NOT block
    dec_followup = classify_query("how does its RSI compare to peers?")
    print(f"  'how does its RSI compare to peers?' -> block={dec_followup.block_context_symbol}")
    assert not dec_followup.block_context_symbol, "Pronoun follow-up must NOT block context symbol"

    print("  PASS: All routing/blocking assertions passed")


def test_screener_prompt_has_sector_fallback_rule():
    """Issue 9/10: screener route prompt must contain the sector-not-found fallback instruction."""
    print("\n--- TEST 7: Screener prompt sector-fallback rule (Issue 9) ---")
    prompt = build_rag_prompt(
        "list hydropower stocks to buy",
        ["No stocks found for sector: Hydropower"],
        route='screener'
    )
    assert "No stocks found for sector:" in prompt, "Prompt must pass through the sector-not-found signal"
    assert "sharesansar.com" in prompt, "Screener route instructions must mention sharesansar.com as fallback"
    print("  PASS: Screener route prompt includes sector fallback instruction")


def test_non_nepse_detection():
    """Issue 12: Verify non-NEPSE stock detection works for static known tickers."""
    print("\n--- TEST 8: Non-NEPSE stock detection (Issue 12) ---")
    import asyncio
    from services.non_nepse_detector import identify_non_nepse_stock, extract_unknown_symbols_from_query

    query = "tell me about TSLA stock"
    unknown_syms = extract_unknown_symbols_from_query(query)
    
    assert "TSLA" in unknown_syms, f"TSLA should be extracted as unknown symbol, got: {unknown_syms}"
    
    info = asyncio.run(identify_non_nepse_stock(query, unknown_syms))
    assert info is not None, "identify_non_nepse_stock should return info for TSLA"
    assert info["ticker"] == "TSLA", f"Expected ticker TSLA, got {info.get('ticker')}"
    assert info["exchange"] == "NASDAQ", f"Expected exchange NASDAQ, got {info.get('exchange')}"
    
    print(f"  Matched non-NEPSE stock: {info['ticker']} -> {info['exchange']} ({info['company']})")
    print("  PASS: Static non-NEPSE detection working")

def test_sector_follow_up_routing():
    """Issue 13: Verify conversational sector queries route to screener."""
    print("\n--- TEST 9: Sector follow-up routing (Issue 13) ---")
    
    # "what about the development bank sector?" -> should route to screener
    dec_dev_bank = classify_query("what about the development bank sector?")
    print(f"  'what about the development bank sector?' -> block={dec_dev_bank.block_context_symbol}, route={dec_dev_bank.route}, sector={dec_dev_bank.sector}")
    assert dec_dev_bank.route == 'screener', f"Expected route 'screener', got '{dec_dev_bank.route}'"
    assert dec_dev_bank.sector == 'Development Banks', f"Expected sector 'Development Banks', got '{dec_dev_bank.sector}'"
    assert dec_dev_bank.block_context_symbol, "Expected block_context_symbol=True"
    
    # "and the finance ones?" -> should route to screener
    dec_finance = classify_query("and the finance ones?")
    print(f"  'and the finance ones?' -> block={dec_finance.block_context_symbol}, route={dec_finance.route}, sector={dec_finance.sector}")
    assert dec_finance.route == 'screener', f"Expected route 'screener', got '{dec_finance.route}'"
    assert dec_finance.sector == 'Finance Companies', f"Expected sector 'Finance Companies', got '{dec_finance.sector}'"

    print("  PASS: Sector follow-up routing working")

def test_golden_prompts_expanded():
    """Issue 14: Verify new golden prompts are loaded and matching dynamically."""
    print("\n--- TEST 10: Expanded Golden Prompts (Issue 14) ---")
    from services.golden_matcher import match_golden, list_golden_ids
    
    ids = list_golden_ids()
    print(f"  Loaded {len(ids)} golden prompts.")
    assert len(ids) >= 20, f"Expected at least 20 golden prompts, found {len(ids)}"
    
    # Test 'today_date'
    match_date = match_golden("what is today's date")
    assert match_date and match_date["id"] == "today_date", "Failed to match 'today_date'"
    
    # Test dynamic matching: "what is the price of NICA" -> stock_price_only
    match_price = match_golden("what is the price of NICA", symbols=["NICA"])
    print(f"  'what is the price of NICA' matched -> {match_price['id'] if match_price else 'None'}")
    assert match_price and match_price["id"] == "stock_price_only", "Failed to dynamically match stock_price_only"
    
    # Test dynamic matching: "list hydropower stocks" -> sector_screener
    match_sector = match_golden("list hydropower stocks", symbols=[])
    print(f"  'list hydropower stocks' matched -> {match_sector['id'] if match_sector else 'None'}")
    assert match_sector and match_sector["id"] == "sector_screener", "Failed to match sector_screener"

    print("  PASS: Golden prompts loaded and matching dynamically")

def run_regression_tests():
    print("=" * 60)
    print("RUNNING REGRESSION TESTS FOR ISSUES 7-14")
    print("=" * 60)

    test_context_blocking()
    test_multi_stock_prompt_instructions()
    test_multi_stock_signals_structure()
    test_sector_data_integrity()
    test_db_service_returns_tuple()
    test_context_blocking_order_of_operations()
    test_screener_prompt_has_sector_fallback_rule()
    test_non_nepse_detection()
    test_sector_follow_up_routing()
    test_golden_prompts_expanded()

    print("\n" + "=" * 60)
    print("ALL REGRESSION TESTS PASSED SUCCESSFULLY!")
    print("=" * 60)

if __name__ == "__main__":
    run_regression_tests()
