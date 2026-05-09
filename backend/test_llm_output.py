"""
Quick test: Simulate the full pipeline for a single-symbol query
and print what the LLM would generate.
"""
import os, sys, asyncio, django

# Fix windows encoding issues
sys.stdout.reconfigure(encoding='utf-8')

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nepse_project.settings")
django.setup()

from services.query_router import classify_query
from services.agent import sql_tool, graph_tool, news_tool
from services.llm_client import build_rag_prompt, call_llm

async def test_query(question, symbol=None):
    print(f"\n{'='*60}")
    print(f"QUERY: {question}")
    print(f"{'='*60}")
    
    # Route
    decision = classify_query(question, symbol)
    print(f"Route: {decision.route}")
    print(f"Tools: {decision.tools_needed}")
    print(f"Symbols: {decision.symbols}")
    
    sym = decision.symbols[0] if decision.symbols else symbol
    tool_outputs = []
    
    # SQL
    if "sql_tool" in decision.tools_needed and sym:
        sql_text, sql_cites, sql_signals = await sql_tool(sym)
        if sql_text:
            tool_outputs.append(sql_text)
            print(f"\n--- SQL output ({len(sql_text)} chars) ---")
            print(sql_text[:300])
    
    # Graph
    if "graph_tool" in decision.tools_needed and sym:
        graph_text, graph_cites = await graph_tool(question, sym)
        if graph_text:
            tool_outputs.append(graph_text)
            print(f"\n--- Graph output ({len(graph_text)} chars) ---")
            print(graph_text[:200])
    
    # Build prompt
    prompt = build_rag_prompt(question, tool_outputs)
    print(f"\n--- RAG Prompt (last 500 chars) ---")
    print(prompt[-500:])
    
    # Call LLM
    print(f"\n--- LLM Response ---")
    answer, provider, tokens = await call_llm(prompt, max_tokens=400)
    print(answer)
    print(f"\n[Provider: {provider}, Length: {len(answer)} chars, Tokens: {tokens}]")

if __name__ == "__main__":
    asyncio.run(test_query("tell me about nabil and latest news about it?"))
