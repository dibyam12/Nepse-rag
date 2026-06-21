import os
import sys
import asyncio
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'nepse_project.settings')

import django
django.setup()

from services.agent import run_agent
from django.core.cache import cache

async def test_agent():
    print("Clearing cache...")
    cache.clear()

    # Query 1: Compare NICA and NCCB fundamentals
    q1 = "Compare NICA and NCCB fundamentals"
    print(f"\nQuerying: '{q1}'")
    res1 = await run_agent(q1)
    
    print("\n--- RESULTS 1 ---")
    print(f"Route Used: {res1.get('route_used')}")
    print(f"Tools Called: {res1.get('tools_called')}")
    print(f"Signals: {json.dumps(res1.get('signals'), indent=2)}")
    print(f"Citations: {len(res1.get('citations'))} items")
    answer = res1.get('answer', '')
    print(f"Answer snippet (first 600 chars):\n{answer[:600]}")
    
    print("\n-----------------")
    
    # Query 2: "what about nabil?" with NICA as context
    q2 = "what about nabil?"
    print(f"\nQuerying: '{q2}' (context symbol: 'NICA')")
    res2 = await run_agent(q2, "NICA")
    
    print("\n--- RESULTS 2 ---")
    print(f"Route Used: {res2.get('route_used')}")
    print(f"Tools Called: {res2.get('tools_called')}")
    print(f"Signals: {json.dumps(res2.get('signals'), indent=2)}")
    print(f"Citations: {len(res2.get('citations'))} items")
    answer2 = res2.get('answer', '')
    print(f"Answer snippet (first 600 chars):\n{answer2[:600]}")

if __name__ == "__main__":
    asyncio.run(test_agent())
