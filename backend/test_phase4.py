"""Phase 4 verification tests."""
import os
import sys

# Fix encoding for Windows
if sys.platform == 'win32':
    os.environ['PYTHONIOENCODING'] = 'utf-8'

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'nepse_project.settings')

import django
django.setup()

print("=" * 60)
print("PHASE 4 VERIFICATION TESTS")
print("=" * 60)

# -- Test 1: Query Router --
print("\n-- Test 1: Query Router --")
from services.query_router import (
    classify_query, extract_symbols,
    ROUTE_FULL_AGENT, ROUTE_VECTOR_ONLY, ROUTE_SQL_GRAPH, ROUTE_COMPARE,
)

tests = [
    ("Why did NABIL fall today?", "NABIL", ROUTE_FULL_AGENT),
    ("What is RSI?", None, ROUTE_VECTOR_ONLY),
    ("Show NABIL indicators", "NABIL", ROUTE_SQL_GRAPH),
    ("Compare NABIL and EBL", None, ROUTE_COMPARE),
    ("Latest news on NABIL", "NABIL", ROUTE_FULL_AGENT),
    ("What are the NEPSE trading rules?", None, ROUTE_VECTOR_ONLY),
    ("NABIL price and volume", "NABIL", ROUTE_SQL_GRAPH),
    ("Is NABIL better than EBL?", None, ROUTE_COMPARE),
]

all_passed = True
for question, symbol, expected in tests:
    result = classify_query(question, symbol)
    passed = result.route == expected
    icon = "PASS" if passed else "FAIL"
    print(f"  {icon} | '{question}' -> {result.route} (expected {expected})")
    if not passed:
        all_passed = False

print(f"\n  Router tests: {'ALL PASSED' if all_passed else 'SOME FAILED'}")

# -- Test 2: Symbol Extraction --
print("\n-- Test 2: Symbol Extraction --")
sym_tests = [
    ("Why did NABIL fall?", ["NABIL"]),
    ("Compare NABIL and EBL", ["NABIL", "EBL"]),
    ("What is RSI?", []),
    ("Show me MACD for NICA", ["NICA"]),
]
for question, expected in sym_tests:
    result = extract_symbols(question)
    passed = result == expected
    icon = "PASS" if passed else "FAIL"
    print(f"  {icon} | '{question}' -> {result} (expected {expected})")

# -- Test 3: build_rag_prompt --
print("\n-- Test 3: build_rag_prompt --")
from services.llm_client import build_rag_prompt

prompt = build_rag_prompt("What is NABIL?", ["Tool output 1", "Tool output 2"])
has_context = "<context>" in prompt
has_question = "QUESTION: What is NABIL?" in prompt
print(f"  {'PASS' if has_context else 'FAIL'} | Has context block: {has_context}")
print(f"  {'PASS' if has_question else 'FAIL'} | Has question: {has_question}")
print(f"  INFO | Prompt length: {len(prompt)} chars, ~{int(len(prompt.split()) / 0.75)} tokens")

prompt_empty = build_rag_prompt("What is NEPSE?", [])
has_q = "QUESTION" in prompt_empty
print(f"  {'PASS' if has_q else 'FAIL'} | Empty outputs handled: {has_q}")

# -- Test 4: LLM Provider Config --
print("\n-- Test 4: LLM Provider Config --")
from services.llm_client import PROVIDERS
from decouple import config

for p in PROVIDERS:
    name = p["name"]
    has_key_env = p.get("api_key_env")
    if has_key_env:
        key_val = config(has_key_env, default="")
        key_status = "SET" if key_val else "EMPTY"
    else:
        key_status = "NOT NEEDED"
    print(f"  {name}: model={p['model']}, key={key_status}")

# -- Test 5: Agent Graph Construction --
print("\n-- Test 5: Agent Graph Construction --")
try:
    from services.agent import agent_graph
    print(f"  PASS | Agent graph compiled successfully")
    print(f"  INFO | Graph type: {type(agent_graph).__name__}")
except Exception as e:
    print(f"  FAIL | Agent graph error: {e}")

# -- Test 6: Tool imports --
print("\n-- Test 6: Tool Imports --")
try:
    from services.agent import sql_tool, graph_tool, vector_tool, news_tool, run_agent
    print(f"  PASS | All tools imported: sql_tool, graph_tool, vector_tool, news_tool")
    print(f"  PASS | run_agent imported")
except Exception as e:
    print(f"  FAIL | Import error: {e}")

# -- Test 7: API URL resolution --
print("\n-- Test 7: API URL Resolution --")
try:
    from django.urls import reverse, resolve
    url = reverse('query')
    print(f"  PASS | /api/query/ resolves to: {url}")
    match = resolve('/api/query/')
    print(f"  PASS | View: {match.func.cls.__name__}")
except Exception as e:
    print(f"  FAIL | URL resolution error: {e}")

print("\n" + "=" * 60)
print("BASIC TESTS COMPLETE")
print("=" * 60)
print("\nTo test LLM calls, fill in API keys in .env and run:")
print("  python manage.py shell")
print("  >>> from services.agent import run_agent")
print("  >>> import asyncio")
print("  >>> result = asyncio.run(run_agent('Show NABIL signals', 'NABIL'))")
print("  >>> print(result['answer'])")
