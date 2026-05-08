"""Phase 4 live end-to-end test — calls the actual LLM."""
import os
import sys
import asyncio
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'nepse_project.settings')

import django
django.setup()

from services.agent import run_agent

async def main():
    print("=" * 60)
    print("PHASE 4 LIVE END-TO-END TEST")
    print("=" * 60)

    # Test 1: Full agent route (needs LLM + all tools)
    print("\n-- Test E2E-1: Full Agent (NABIL) --")
    try:
        result = await run_agent("Why did NABIL fall today?", "NABIL")
        print(f"  Route:    {result.get('route_used')}")
        print(f"  Tools:    {result.get('tools_called')}")
        print(f"  Provider: {result.get('llm_provider_used')}")
        print(f"  Latency:  {result.get('latency_ms')}ms")
        print(f"  Signals:  {json.dumps(result.get('signals', {}), indent=2)}")
        print(f"  Cites:    {len(result.get('citations', []))} citations")
        answer = result.get('answer', '')
        has_disclaimer = 'DISCLAIMER' in answer
        print(f"  Disclaimer: {'PASS' if has_disclaimer else 'FAIL'}")
        # Show first 300 chars of answer
        print(f"  Answer:   {answer[:300]}...")
        print(f"  RESULT:   {'PASS' if has_disclaimer and result.get('route_used') else 'FAIL'}")
    except Exception as e:
        print(f"  FAIL: {e}")

    # Test 2: Vector-only route (educational question)
    print("\n-- Test E2E-2: Vector Only --")
    try:
        result = await run_agent("What is RSI in stock trading?")
        print(f"  Route:    {result.get('route_used')}")
        print(f"  Tools:    {result.get('tools_called')}")
        print(f"  Provider: {result.get('llm_provider_used')}")
        print(f"  Latency:  {result.get('latency_ms')}ms")
        has_disclaimer = 'DISCLAIMER' in result.get('answer', '')
        print(f"  Disclaimer: {'PASS' if has_disclaimer else 'FAIL'}")
        print(f"  Answer:   {result.get('answer', '')[:300]}...")
        print(f"  RESULT:   {'PASS' if result.get('route_used') == 'vector_only' else 'FAIL'}")
    except Exception as e:
        print(f"  FAIL: {e}")

    # Test 3: SQL+Graph route
    print("\n-- Test E2E-3: SQL+Graph (NABIL indicators) --")
    try:
        result = await run_agent("Show NABIL price and RSI", "NABIL")
        print(f"  Route:    {result.get('route_used')}")
        print(f"  Tools:    {result.get('tools_called')}")
        print(f"  Provider: {result.get('llm_provider_used')}")
        print(f"  Latency:  {result.get('latency_ms')}ms")
        print(f"  Signals:  {json.dumps(result.get('signals', {}), indent=2)}")
        has_disclaimer = 'DISCLAIMER' in result.get('answer', '')
        print(f"  Disclaimer: {'PASS' if has_disclaimer else 'FAIL'}")
        print(f"  RESULT:   {'PASS' if result.get('route_used') == 'sql_graph' else 'FAIL'}")
    except Exception as e:
        print(f"  FAIL: {e}")

    # Test 4: Cache hit test (repeat test 2)
    print("\n-- Test E2E-4: Cache Hit --")
    try:
        result = await run_agent("What is RSI in stock trading?")
        cache_hit = result.get('debug', {}).get('cache_hit', False)
        print(f"  Cache hit: {'PASS' if cache_hit else 'FAIL (expected cache hit)'}")
        print(f"  Latency:  {result.get('latency_ms')}ms")
    except Exception as e:
        print(f"  FAIL: {e}")

    print("\n" + "=" * 60)
    print("LIVE TESTS COMPLETE")
    print("=" * 60)

asyncio.run(main())
