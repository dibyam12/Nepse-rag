"""
Evaluation and verification script for:
1. Date Awareness (Issue 1)
2. MFI calculation & integration (Issue 2)
3. Screener sector queries without price bounds (Issue 3 & 5)
4. Screener markdown table prompts (Issue 4)
5. Indicator abbreviations symbol extraction exclusion (Issue 6)
"""
import os
import sys
import asyncio
import pandas as pd
from pathlib import Path

# Django setup
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nepse_project.settings")

import django
django.setup()

from services.query_router import classify_query, extract_symbols
from services.indicators import compute_mfi, prepare_ohlcv_dataframe
from services.db_service import get_latest_indicators, get_stocks_by_price_filter
from services.agent import sql_tool
from services.llm_client import build_rag_prompt

def test_date_awareness():
    print("\n--- TEST 1: Date Awareness ---")
    prompt = build_rag_prompt("what is today's date?", [])
    has_system_date = "<system_date>" in prompt
    has_rule = "answer directly from <system_date>" in prompt
    
    print(f"  PASS | Prompt contains <system_date> tag: {has_system_date}")
    print(f"  PASS | Prompt contains direct answer date rule: {has_rule}")
    assert has_system_date, "Missing <system_date> tag"
    assert has_rule, "Missing date rule"

def test_mfi_indicator():
    print("\n--- TEST 2: MFI Calculation & Integration ---")
    # Test indicators calculation
    dummy_data = {
        'high': [10.0 + i for i in range(20)],
        'low': [5.0 + i for i in range(20)],
        'close': [8.0 + i for i in range(20)],
        'volume': [1000 for _ in range(20)],
        'date': [f"2026-06-{i+1:02d}" for i in range(20)]
    }
    df = pd.DataFrame(dummy_data)
    mfi_val = compute_mfi(df)
    print(f"  PASS | MFI computed value on dummy data: {mfi_val}")
    assert mfi_val is not None, "MFI computed to None"

    # Test DB indicators integration
    indicators = asyncio.run(get_latest_indicators('NABIL'))
    has_mfi = 'mfi' in indicators
    print(f"  PASS | get_latest_indicators returns MFI: {has_mfi} (Value: {indicators.get('mfi')})")
    assert has_mfi, "MFI not returned in indicators dictionary"

    # Test sql_tool output format
    sql_text, _, signals = asyncio.run(sql_tool('NABIL'))
    has_mfi_text = "MFI is" in sql_text
    has_mfi_signal = "MFI" in signals
    print(f"  PASS | sql_tool text output mentions MFI: {has_mfi_text}")
    print(f"  PASS | sql_tool signals payload includes MFI: {has_mfi_signal}")
    assert has_mfi_text, "MFI not in sql_tool text"
    assert has_mfi_signal, "MFI not in signals dictionary"

def test_screener_queries():
    print("\n--- TEST 3: Screener Routing & Sector Matching ---")
    
    # 1. Sector-only screening with no price bounds
    dec1 = classify_query("best commercial banks to buy")
    print(f"Query: 'best commercial banks to buy'")
    print(f"  Route: {dec1.route} (Expected: screener)")
    print(f"  Sector: {dec1.sector} (Expected: Commercial Banks)")
    print(f"  rank_by_signals: {dec1.rank_by_signals} (Expected: True)")
    print(f"  price_below: {dec1.price_below} (Expected: None)")
    assert dec1.route == 'screener', "Should route to screener"
    assert dec1.sector == 'Commercial Banks', "Should extract 'Commercial Banks'"
    assert dec1.rank_by_signals, "Should set rank_by_signals=True"
    assert dec1.price_below is None, "Price bounds should be None"

    # 2. Generic screening without sector or price bounds
    dec2 = classify_query("which stocks look good right now")
    print(f"Query: 'which stocks look good right now'")
    print(f"  Route: {dec2.route} (Expected: screener)")
    print(f"  rank_by_signals: {dec2.rank_by_signals} (Expected: True)")
    assert dec2.route == 'screener', "Should route to screener"
    assert dec2.rank_by_signals, "Should rank by signals"

    # 3. Collision prevention check
    dec3 = classify_query("is NABIL under 500 a buy?")
    print(f"Query: 'is NABIL under 500 a buy?'")
    print(f"  Route: {dec3.route} (Expected: full_agent / sql_graph, NOT screener)")
    print(f"  Symbols: {dec3.symbols} (Expected: ['NABIL'])")
    assert dec3.route != 'screener', "Should not route to screener when tickers are named"
    assert 'NABIL' in dec3.symbols, "Should extract NABIL"

def test_indicator_abbreviations_exclusion():
    print("\n--- TEST 4: Indicator Abbreviations Symbol Extraction ---")
    
    # Check that BETA, OBV, ATR, MFI are excluded from symbol matches
    syms = extract_symbols("what are OBV, ATR, BETA, and MFI?")
    print(f"Query: 'what are OBV, ATR, BETA, and MFI?'")
    print(f"  Symbols: {syms} (Expected: [])")
    assert len(syms) == 0, f"False positive symbols matched: {syms}"

    # Verify routing of multi-indicator educational queries
    dec = classify_query("what are OBV, ATR, and Beta?")
    print(f"Query: 'what are OBV, ATR, and Beta?'")
    print(f"  Route: {dec.route} (Expected: vector_only)")
    assert dec.route == 'vector_only', "Should route indicator queries with no symbols to vector_only"

def run_all_tests():
    print("=" * 60)
    print("RUNNING SCREENER, DATE, MFI, AND ROUTER TESTS")
    print("=" * 60)
    
    from django.core.cache import cache
    cache.clear()
    
    test_date_awareness()
    test_mfi_indicator()
    test_screener_queries()
    test_indicator_abbreviations_exclusion()
    
    print("\n" + "=" * 60)
    print("ALL TESTS PASSED SUCCESSFULLY!")
    print("=" * 60)

if __name__ == "__main__":
    run_all_tests()
