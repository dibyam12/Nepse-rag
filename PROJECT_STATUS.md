# NEPSE AI Research Assistant — Project Status Tracker

> **Last Updated**: 2026-06-04
> **Team**: 4 students (BE Computer Engineering, Final Year)
> **Purpose**: Educational & Research — NOT financial advice

---

## Project Phases Overview

| Phase | Name | Status | Progress |
|-------|------|--------|----------|
| 1 | Data Foundation & Infrastructure | COMPLETE | 100% |
| 2 | Real-Time News & Web Search Pipeline | COMPLETE | 100% |
| 3 | RAG System (Vector + Graph) | COMPLETE | 100% |
| 4 | Agentic LLM Orchestration (LangGraph) | COMPLETE | 100% |
| 5 | Frontend (React + Vite) | COMPLETE | 100% |
| 6 | Evaluation & Documentation | COMPLETE | 100% |
| 7 | Golden Prompts & Historical Comparison | COMPLETE | 100% |
| 8 | Enhanced Screener, Route-Aware Prompts & Answer UI | COMPLETE | 100% |

---

## Phase 1: Data Foundation & Infrastructure — COMPLETE

### What Was Done
- [x] Django project scaffolding (`nepse_project/`, 4 apps: `nepse_data`, `rag`, `agent`, `api`)
- [x] Database models: `Stock`, `Sector`, `NepseIndex`, `OHLCV`, `Indicator`, `NewsEvent`
- [x] Neon PostgreSQL integration (read-only for OHLCV via `services/neon_client.py`)
- [x] Local SQLite for app metadata, chat history, indicators, news
- [x] On-demand technical indicator computation (`services/indicators.py`): RSI, MACD, EMA, Bollinger Bands, ATR, OBV, VWAP, Beta
- [x] Multi-tiered caching layer (`services/cache_service.py`): OHLCV, indicators, news, LLM responses
- [x] Background Neon keep-alive to prevent cold starts
- [x] Domain knowledge documents in `docs/` (9 files: NEPSE rules, SEBON circulars, sector descriptions, indicator explanations, FAQs, glossary, etc.)
- [x] Logging (JSONL format) to `logs/nepse_rag.jsonl`
- [x] Django REST Framework + CORS configured

### Key Files
- `services/neon_client.py` — Read-only Neon DB connection (sync `execute_neon_query`)
- `services/db_service.py` — Data access layer
- `services/indicators.py` — Technical indicator computation
- `services/cache_service.py` — Caching helpers
- `apps/nepse_data/models.py` — All Django models

---

## Phase 2: Real-Time News & Web Search Pipeline — COMPLETE

### What Was Done
- [x] Web search fallback chain (`services/web_search.py`)
  - [x] NewsAPI — **PRIMARY, WORKING** (500 req/month free)
  - [x] DuckDuckGo — **FALLBACK, WORKING** (free, unlimited, uses `ddgs` package)
  - [ ] Google Custom Search — DISABLED (403 error, needs fresh API key setup)
  - [ ] SerpAPI — DISABLED (429 error, credits exhausted, needs new account)
- [x] NEPSE site-prioritized DuckDuckGo search (searches 12 top Nepali financial portals FIRST with expanded results)
- [x] **Direct Page Scraping Fallback** (`scrape_direct_pages`): Assures fresh announcements are pulled even if search engines miss them.
- [x] Article content extraction (`fetch_article()` using httpx + BeautifulSoup4)
- [x] News scrapers (`services/news_scraper.py`): ShareSansar + MeroLagani + Direct scraping
- [x] `get_news_for_symbol()` — orchestrates search + scraping, deduplicates, persists to `NewsEvent` model
- [x] **Indian source blacklist** — 12-domain filter applied after dedup to block Indian financial news sites
- [x] Async-safe DB persistence using `sync_to_async`
- [x] Query routing upgraded to send fundamental data queries ("EPS", "Profit", etc.) to the `full_agent` which hits the news scraper.

### Test Results (2026-05-08)
| Provider | Status | Notes |
|----------|--------|-------|
| NewsAPI | WORKING (2 results) | Primary provider |
| DuckDuckGo | WORKING (3-5 results) | Site-prioritized, uses `ddgs` v9.14.2 |
| Google CSE | DISABLED | 403 — needs `Custom Search API` enabled in GCP |
| SerpAPI | DISABLED | 429 — credits exhausted |

### Multi-Symbol Test (DuckDuckGo)
| Symbol | Results | Sources |
|--------|---------|---------|
| NABIL | 3 | nepsealpha, merolagani, sharesansar |
| NICA | 3 | nepsealpha, merolagani, sharehubnepal |
| SBL | 3 | nepsealpha, merolagani, sharesansar |
| HIDCL | 3 | merolagani, sharesansar, sharehubnepal |
| NLIC | 3 | merolagani, nepsealpha, sharesansar |
| NHPC | 3 | nepsealpha, merolagani, sharesansar (Indian sources now filtered) |

### Known Issues / TODO for Phase 2
- [ ] Fix Google CSE: Create new API key + enable Custom Search API in GCP console
- [ ] Fix SerpAPI: Create new account at serpapi.com for fresh $100 credits
- [ ] Update ShareSansar/MeroLagani scraper CSS selectors if HTML structure changes
- [ ] NewsAPI free tier is limited to 500 req/month — monitor usage

### Key Files
- `services/web_search.py` — Unified search with fallback chain
- `services/news_scraper.py` — Scrapers + `get_news_for_symbol()` + Indian source blacklist
- `.env` — API keys (NewsAPI working, others commented out)

---

## Phase 3: RAG System (Vector + Graph) — COMPLETE

### What Was Done
- [x] Vector RAG using LlamaIndex + ChromaDB (`services/vector_rag.py`)
  - [x] Ingests `docs/*.txt` domain knowledge files (512 token chunks reduced to 256 for token budget)
  - [x] Sentence Transformers for local CPU embeddings (`all-MiniLM-L6-v2`)
  - [x] Lazy loading + module-level singleton — model loads once per Daphne process (~9s cold start, then cached for lifetime of process)
- [x] Graph RAG for entity relationships (`services/graph_rag.py`)
  - [x] Built manually from SQLite without LLM extraction to save tokens
  - [x] Stock → Sector, Stock → Index, and Stock → Peer relationships
  - [x] Persists to `indexes/graph_store.json` (fast loading <100ms)
- [x] Query Router (`services/query_router.py`)
  - [x] Rule-based intent classification (FACTUAL, ANALYTICAL, NEWS, PRICE, COMPARISON, GENERAL)
  - [x] Regex-based stock symbol extraction from questions
- [x] Caching added for Vector and Graph responses (`services/cache_service.py`)
- [x] Test endpoints under `/api/rag/`

### Test Results (2026-05-08)
- **Graph Index**: Built successfully in 0.1s (521 stock nodes, 9 sectors, 614 edges)
- **Vector Index**: Built successfully in 33.4s (9 documents → 67 chunks); subsequent queries: <1s (warm cache)

### Key Files
- `services/vector_rag.py` — LlamaIndex + ChromaDB integration
- `services/graph_rag.py` — Django ORM-based graph relationships
- `services/query_router.py` — Rule-based intent routing
- `apps/rag/views.py` — RAG test endpoints
- `scripts/build_vector_index.py` — Vector index generator
- `scripts/build_graph_index.py` — Graph index generator

---

## Phase 4: Agentic LLM Orchestration — COMPLETE

### What Was Done
- [x] LLM fallback chain (`services/llm_client.py`): Groq → Google AI → OpenRouter → Ollama
  - [x] Ollama at `http://localhost:11434/v1/chat/completions` with model `llama3.2:3b`
  - [x] Priority 4 — activates only when all cloud providers fail
- [x] LangGraph agent workflow (`services/agent.py`)
  - [x] Query routing logic (vector, sql, graph, news, full_agent)
  - [x] Agentic tools: `sql_tool`, `graph_tool`, `vector_tool`, `news_tool`
  - [x] Parallel tool execution for `full_agent` route
  - [x] `_fetch_52w_range()` uses `loop.run_in_executor` wrapping sync `execute_neon_query` (async crash fix)
  - [x] Stale data detection — falls back to web search when Neon DB data > 3 days old
  - [x] Web price fallback uses `_current_month_year()` for temporally fresh queries
- [x] Conversation memory and chat history (via Django models)
- [x] Streaming responses via SSE (`StreamingHttpResponse`) — "Task destroyed" warning fixed
- [x] Active LLM tracking and token usage accounting

### Bug Fixes Applied (2026-05-08)
| Bug | Fix |
|-----|-----|
| `_fetch_52w_range` psycopg2 async crash | `loop.run_in_executor(None, lambda: execute_neon_query(...))` |
| Indian NHPC articles in news results | `INDIAN_SOURCES_BLACKLIST` 12-domain filter in `news_scraper.py` |
| "Task was destroyed but pending" SSE warning | `loop.shutdown_asyncgens()` + `GeneratorExit` handler in `views.py` |

### Bug Fixes Applied (2026-05-09)
| Bug | Fix |
|-----|-----|
| Search API returning static profile pages | Modified DDG queries to use `after:2026-01-01` to force recent news articles |
| Overly aggressive path-depth filter blocking valid articles | Replaced heuristic with explicit case-insensitive `skip_patterns` matched to actual stock symbols |
| Symbol Context Lost on follow-up queries | Frontend (`chatStore.js`): extracted `lastSymbol` from `signals.price_cards`. Backend (`views.py`): injected `(regarding {symbol_hint})` and re-classified query. |
| Left sidebar totally hidden on desktop | Fixed `QueryHistory.jsx` CSS to use `-ml-72` for smooth collapse and removed `md:hidden` from `ChatWindow.jsx` toggle button |

### Key Files
- `services/llm_client.py` — Multi-provider fallback chain and SSE parsing
- `services/agent.py` — LangGraph agent orchestration (patched)
- `apps/agent/views.py` — Chat streaming endpoints (patched)

---

## Phase 5: Frontend — COMPLETE

### What Was Done
- [x] Vite + React 18 setup with Tailwind CSS
- [x] State management with Zustand (`useChatStore`, `useThemeStore`)
- [x] Responsive Chat UI with streaming messages and markdown rendering
- [x] Intelligent auto-detected symbol chip (replaces footer dropdown) for stateless queries
- [x] Dynamic LLM tracking display in chat footer (Provider + Token usage)
- [x] `PriceCard` — close price, % change, day range, 52W range, VWAP
- [x] `SignalsTable` (Indicator Grid) — RSI/MACD/EMA/BB status badges with color coding
- [x] `NewsFeed` — auto-expanding list of headlines with source attribution and date
- [x] `CitationList` — pill-shaped source chips with icons (DB / Graph / Doc / Web)
- [x] Light/Dark mode toggling
- [x] User Authentication UI (Login/Register)

### Key Files
- `frontend/src/components/ChatWindow.jsx` — Main chat UI (now uses context-aware symbol chip)
- `frontend/src/store/chatStore.js` — Streaming, state management, and conversational symbol persistence
- `frontend/src/components/SignalsTable.jsx` — Indicator grid
- `frontend/src/components/NewsSection.jsx` — News list with empty state
- `frontend/src/components/CitationList.jsx` — Source citation pills

---

## Phase 6: Evaluation & Documentation — COMPLETE

### What Was Done
- [x] **RAGAS Evaluation Suite (`evaluation/eval_runner.py`)**: Expanded with 3 new custom metrics: `historical_accuracy` (validates price/date comparisons), `historical_tool_routing` (verifies `historical_tool` is invoked for temporal intent), and `no_advice_compliance` (validates no forbidden buy/sell warnings in answers).
- [x] **Historical Pipeline Evaluator (`evaluation/eval_historical.py`)**: Tests historical DB lookup, date ranges, delta changes, and `historical_tool` output formats.
- [x] **Follow-up Flow Evaluator (`evaluation/eval_followup.py`)**: Validates turn-based conversational symbol resolution, non-repetition, advice compliance, and empty history clearings.
- [x] **Groundedness Checker (`services/groundedness.py`)**: Sentence claim extraction & NLI model grading.
- [x] **Negative Prompt Rejection (`evaluation/eval_negative.py`)**: Blocks off-topic queries.
- [x] **News Integrity Check (`evaluation/eval_news.py`)**: Validates news fetches and checks for Indian symbol leaks.
- [x] **Vector Diversity Test (`evaluation/eval_retrieval.py`)**: Tests ChromaDB search and cross-encoder reranking.
- [x] **DISCLAIMER integration**: Automatically appended on every response to prevent unauthorized financial advice.

---

## Phase 7: Golden Prompts & Historical Comparison — COMPLETE

### What Was Done
- [x] **Golden Prompt System (`services/golden_prompts.json`)**: Configured 7 gold templates matching common user query structures (e.g. single stock, compare two, should I buy, latest news, indicator details).
- [x] **Fuzzy + Regex Matcher (`services/golden_matcher.py`)**: Custom matching engine with LRU caching. Runs a two-pass matching algorithm (all regex first, then highest-ratio fuzzy search) to prevent false positives.
- [x] **Response Formatting Guard**: Intercepts matched queries at the view layer and injects `<ideal_structure>` templates into the LLM system prompts to guarantee perfect formatting.
- [x] **Historical Comparison Integration**: Added temporal intent classification (detects "N years ago", "since YYYY", "price history") upgrading the route to `full_agent` or `compare` to ensure `historical_tool` executes.
- [x] **Golden Quality Evaluator (`evaluation/eval_golden.py`)**: Automates unit testing for pattern matching and response structure compliance.

## Phase 8: Enhanced Screener, Route-Aware Prompts & Answer-Focused UI — COMPLETE

### What Was Done
- [x] **Composite Signal-based Stock Screener (`services/db_service.py`)**:
  - Implemented `_enrich_with_signals` to calculate a composite score from RSI (40%), MACD (30%), and EMA-20 (30%) under NEPSE market practices.
  - Returns ranked list labeled with `🟢 Buy` (composite >= 0.65), `🟡 Neutral` (composite 0.40-0.64), or `🔴 Sell/Avoid` (composite < 0.40).
  - Raised default screener limit to 15 stocks.
- [x] **Route-Aware Prompts (`services/llm_client.py`)**:
  - Added route-aware instructions in `build_rag_prompt`.
  - Allowed structured formatting (headings, lists, and formulas) on `vector_only` route for educational queries, and signal formatting on `screener`.
- [x] **Extended Retrieval for Educational Queries (`services/agent.py`)**:
  - Implemented `extended` parameter in `vector_tool` to retrieve up to 6 chunks (up from 3) and increase chunk size to 1000 characters (up from 400).
- [x] **Answer-Focused Collapsible Frontend Layout (`MessageBubble.jsx`, `ChatWindow.jsx`, `style.css`)**:
  - Added answer-focused query detection.
  - Primary text answer renders first with `.answer-highlight` styled border.
  - Secondary `PriceCard` and `SignalsTable` render inside a collapsible "Current Market Data" section.
- [x] **Expanded Knowledge Base**:
  - Expanded `docs/indicator_explanations.txt` from 10 to 25 technical indicators with detailed formulas, explanations, and NEPSE-specific edge cases.

### Architecture Decisions to Document
| Decision | Choice | Rationale |
|----------|--------|-----------|
| LLMs | API + Ollama fallback | No GPU; RAG compensates for domain knowledge gap |
| Vector DB | ChromaDB | Zero-config, free, native LlamaIndex support, sufficient for 67 chunks |
| ASGI Server | Daphne | Required for async SSE; WSGI servers are synchronous |
| Local LLM | Ollama llama3.2:3b | OpenAI-compatible, no API key, offline resilience |
| Price DB | Neon (read-only) | Production DB — app never writes market data |

---

## Environment & Configuration

### .env Keys Status
| Key | Status | Notes |
|-----|--------|-------|
| `NEON_DATABASE_URL` | CONFIGURED | Read-only Neon PostgreSQL |
| `NEWSAPI_KEY` | WORKING | Primary search provider |
| `GROQ_API_KEY` | CONFIGURED | Priority 1 LLM |
| `GOOGLE_AI_API_KEY` | CONFIGURED | Priority 2 LLM |
| `OPENROUTER_API_KEY` | CONFIGURED | Priority 3 LLM |
| `GOOGLE_CSE_API_KEY` | DISABLED | 403 error |
| `SERPAPI_KEY` | DISABLED | 429, credits exhausted |
| `HF_TOKEN` | OPTIONAL | Suppresses HuggingFace rate-limit warnings on first model load |

### Dependencies (requirements.txt)
- Django 4.2+, DRF, Channels, Daphne
- pandas, pandas_ta (indicators)
- httpx, beautifulsoup4, lxml (scraping)
- ddgs (DuckDuckGo search)
- newsapi-python, serpapi, google-api-python-client (search providers)
- python-decouple, psycopg2-binary
- python-json-logger (logging)
- langgraph, llama-index-core, llama-index-vector-stores-chroma, llama-index-embeddings-huggingface
- chromadb, sentence-transformers

> **Note**: Ollama is NOT a pip package. Install from https://ollama.com/download, then `ollama pull llama3.2:3b`.

### Project Structure
```text
nepse_rag/
├── apps/
│   ├── nepse_data/    # Models: Stock, OHLCV, Indicator, NewsEvent
│   ├── rag/           # RAG app (Phase 3)
│   ├── agent/         # Agent app (Phase 4)
│   └── api/           # REST endpoints
├── services/
│   ├── neon_client.py     # Neon DB — sync execute_neon_query (Phase 1)
│   ├── db_service.py      # Data access layer (Phase 1)
│   ├── indicators.py      # Technical indicators (Phase 1)
│   ├── cache_service.py   # Caching layer (Phase 1)
│   ├── web_search.py      # Web search fallback chain (Phase 2)
│   ├── news_scraper.py    # News scraping + Indian source blacklist (Phase 2)
│   ├── vector_rag.py      # Vector RAG — LlamaIndex + ChromaDB (Phase 3)
│   ├── graph_rag.py       # Graph RAG (Phase 3)
│   ├── query_router.py    # Rule-based intent routing (Phase 3)
│   ├── llm_client.py      # LLM fallback chain + stream handling (Phase 4)
│   └── agent.py           # LangGraph agent + fixes (Phase 4)
├── frontend/          # React + Vite application (Phase 5)
├── docs/              # Domain knowledge (9 files)
├── indexes/           # graph_store.json + ChromaDB data
├── logs/              # JSONL logs
├── nepse_project/     # Django settings
├── .env               # API keys
└── requirements.txt
```

---

## Change Log

### 2026-07-09 — Stale Context Resolution, Multi-Stock Tables, Screener Signals, MFI Indicator, and Date Injection
- **Stale stock-symbol context blocking & auto-clear (Issue 7)**: Added `block_context_symbol` parameter to `RouteDecision` inside `query_router.py` (triggered on market/sector/list keywords). Applied a narrowed pronoun heuristic to preserve symbol context during peer and sector comparisons (e.g., *"how does its price compare to the sector?"*). Configured the backend views to emit a `clear_context_symbol` SSE event when context symbol injection is blocked, and wired the React `chatStore.js` to auto-clear the context chip on this event or on screener/compare routes.
- **Multi-Stock structured table rendering & prompt alignment (Issue 8)**: Enforced strict multi-stock markdown table instructions in prompt templates across all data routes in `llm_client.py`. Implemented a `MultiSignalsTable` React component inside `MessageBubble.jsx` to directly render tables from the `signals` array when multiple stocks are returned, replacing duplicate individual `PriceCard` and `SignalsTable` outputs. Unpacked `get_stocks_by_price_filter()` tuples in views and agent node blocks to supply raw stock dictionary lists under the `signals` payload. Broadened the list-to-table fallback parser in `mdToHtml()` to be line-based and support blank lines, commas, and parentheses.
- **Server Date/Day Injection (Issue 1)**: Configured dynamic injection of `<system_date>` (using `datetime.now()`) into the LLM system prompt on every request. Instructed the model to answer today's date directly from this tag without deflection. Verified via `eval_screener.py`.
- **MFI (Money Flow Index) Indicator (Issue 2)**: Added MFI calculation (`pandas_ta.mfi`) utilizing OHLCV inputs. Integrated it into the indicators return dictionary in `indicators.py`, the signals returned by `sql_tool` in `agent.py`, the `<sql_data>` XML prompt context, and the `SignalsTable.jsx` frontend card grid (with color-coded overbought/oversold status badges).
- **Collision-Free Screener Routing (Issue 3 & 5)**: Prevented collisions by matching screener query patterns only when no specific ticker symbols are present. Expanded intent detection to capture sector-screening queries (e.g. "top commercial banks to buy") and generic buys (e.g. "which stocks look good right now"). Mapped plurals and fallbacks to exact SQLite sector names.
- **Screener Formatting as Markdown Table (Issue 4)**: Instructed the model on the `screener` route to format multi-stock screening results exclusively as a markdown table with columns `Symbol | Price | Signal | RSI | MACD | MFI`. Built a custom regex table parser and list-to-table converter inside `mdToHtml()` in `MessageBubble.jsx` to render CSS-styled tables with zebra-striping and hover highlights.
- **Educational Indicator Deflection Fix (Issue 6)**: Added indicator acronyms (`BETA`, `MFI`, `ADX`, `CCI`, `ROC`, `CMF`, `PPO`, `SAR`, `BBW`) to `_EXCLUDED_WORDS` to prevent false positive symbol matches. Routed educational questions with no symbols straight to `vector_only`. Verified via `eval_screener.py` tests.

### 2026-07-06 — Golden Prompts, Historical RAG, and Evaluation Suite Completion
- **Caching Alignment**: Standardized the caching architecture to support both environment-switchable Redis and FileBasedCache backends. Aligned caching TTLs with the system architecture specifications: OHLCV (`6 Hours`), Indicators (`6 Hours`), News (`30 Minutes`), and LLM responses (`1 Hour`) to minimize Neon DB connection loads.
- **Golden Prompt Matching**: Added `golden_prompts.json` and a two-pass `golden_matcher.py` (regex matches checked first globally, then falling back to sequence matcher ratios to prevent false positive shadowings). Matched templates are injected into `views.py` before prompting.
- **Historical Comparison RAG**: Extended `db_service.py` to compute multi-year backtests. Implemented `historical_tool` in `agent.py` to compile relative changes and wired temporal intent detection in `query_router.py` to upgrade routed queries to agents handling comparison tasks. Added automatic latest-row fallback in `get_price_change_summary` to prevent crashes when todays data hasn't yet loaded.
- **Evaluation Completion**: Added `eval_historical.py`, `eval_followup.py`, and `eval_golden.py` checking performance across historical data, multi-turn contexts, and ideal response structures. Added `historical_accuracy`, `historical_tool_routing`, and `no_advice_compliance` metrics to `eval_runner.py`.

### 2026-06-04 — Richer News, Live Agent Status, & Anti-Hallucination Improvements
- **Richer News Body Extraction (Component 1)**: Integrated direct article body scraping using `fetch_article()` in `web_search.py` with selectors customized for Nepali financial websites (ShareSansar, MeroLagani, NepseAlpha), stripping ad/cookie boilerplate, and attaching body text (up to 1,500 chars) under a new `body` field returned by `get_news_for_symbol()`. Pre-populated excerpts (first 400 chars) into the LLM context and mapped richer text to the frontend citation summaries.
- **Live Agent Status Indicators (Component 2)**: Added real-time SSE progress events (e.g. `{"type": "status", "message": "Fetching price data for NICA..."}`) emitted before calling `sql_tool`, `graph_tool`, `news_tool`, `vector_tool`, and generating the LLM response. Added Zustand state management in `chatStore.js` and created a premium React `StatusIndicator` component with Lucide icons (Database, GitBranch, Globe, Sparkles, Search), a pulsing green dot, and smooth fade-in animations to make long-running queries feel snappy.
- **Anti-Hallucination & Prompt Engineering (Component 3)**: Added robust grounding rules, few-shot response examples, prefill hints, and chain-of-verification checks in the system prompt. Enhanced `build_rag_prompt()` to accept a query route (increasing the token budget from 3000 -> 4500 on news-heavy routes) and dynamically tag XML data blocks with their respective symbols (`<sql_data symbol="NICA">`).
- **Context Symbol Pollution Fix**: Updated `classify_query` in `query_router.py`, `route_node` in `agent.py`, and `_async_stream` in `views.py` to only inject context symbol if the query itself is devoid of tickers. This prevents stale URL params (like `NICA`) from polluting subsequent queries (like *"what about nabil?"*).
- **Merged Stocks Ticker Mapping**: Added `MERGED_SYMBOLS_MAP` in `query_router.py` mapping historically merged tickers (like `NCCB` -> `KBL`, `MEGA` -> `NIMB`). Updated `extract_symbols` to recognize them, and `sql_tool`, `graph_tool`, `news_tool` in `agent.py` to transparently route to active entity database records while displaying a clean transition name in the PriceCard.
- **Symmetric Comparison UI**: Updated `MessageBubble.jsx` to render a separate `SignalsTable` for every symbol listed in the comparison list, and updated `SignalsTable.jsx` to display the symbol name in its section title.

### 2026-05-09 — UI Polish & Response Quality Improvements
- **Frontend UI Redesign**: Fixed missing `style.css` import in `main.jsx` and completely rewrote the chat UI to use a premium, card-based design with colored tool chips, a `PriceCard` with a 3-column meta grid, an indicator `SignalsTable`, and type-colored citation chips. Also fixed contrast issues for disclaimer and token row text in light/dark mode.
- **Backend Response Quality (`services/llm_client.py`)**: Rewrote the `SYSTEM_PROMPT` to enforce structured output (summary tables, numbered lists, bold headers) and explicitly instructed the LLM not to ignore SQL tool output. Increased `max_tokens` (500 → 800) and `max_input_tokens` (2000 → 3000) to support detailed, Perplexity-style responses.
- **Agent Data Enrichment (`services/agent.py`)**: Added `symbol` and `date` to the `sql_tool` signals dictionary for the frontend. Formatted raw SQL dictionary output into explicit, human-readable sentences for better LLM comprehension.
- **News Scraper Fixes (`services/news_scraper.py` & `services/web_search.py`)**: Added `publishedAt` fallback mapping for web search results. Wrapped the DuckDuckGo `loop.run_in_executor` call with `asyncio.wait_for` (timeout 5.0s) to prevent the `news_tool` from hanging the SSE stream indefinitely when blocked.
- **Query Router Optimization (`services/query_router.py`)**: Added logic to explicitly block the `vector_tool` from firing on pure data/price intent queries (`PRICE_DATA_KEYWORDS`), preventing irrelevant definitional context from confusing the LLM.

### 2026-05-09 — Compare Route & Multi-Symbol Fixes
- **Query Router Priority (`services/query_router.py`)**: Moved `ROUTE_COMPARE` check above `ROUTE_FULL_AGENT` — compare is more specific (≥2 symbols or explicit keywords like "compare", "vs") and should not be overridden by generic `FULL_AGENT_KEYWORDS` ("show", "news"). Added `news_tool` to the `ROUTE_COMPARE` tools list so news is fetched alongside comparisons. Blocked `vector_tool` unconditionally for COMPARE route.
- **Multi-Symbol SSE Streaming (`apps/agent/views.py`)**: Rewrote the SSE retrieval loop to iterate ALL extracted symbols (not just the first one). Both `sql_tool` and `graph_tool` now run for every symbol in the query. `news_tool` is called concurrently via `asyncio.gather()` for all symbols (not sequentially). Signals are now sent as an ARRAY for multi-symbol queries, enabling multi-card rendering.
- **News Pipeline Speed (`services/agent.py` & `services/news_scraper.py`)**: Reduced `news_tool` timeout from 20s → 12s. In `news_scraper.py`, **completely removed `_safe_fetch` full-text article fetching** — this was the #1 bottleneck (4-8s per query). ShareSansar/MeroLagani scraper results have no `snippet` field, so they always triggered the fetch. Now uses headline as fallback summary. Also made DB persist fire-and-forget via `asyncio.create_task()` so it doesn't block the response.
- **System Prompt (`services/llm_client.py`)**: Rewritten with MANDATORY rules using forceful language (Groq/Llama compliance): explicitly forbids explaining indicators ("Wrong: 'RSI is a momentum indicator...' Right: 'RSI: 51.0 — neutral'"), requires ALL SQL DATA blocks to be presented, uses "violating ANY of these is UNACCEPTABLE" phrasing.
- **Frontend Multi-Card (`MessageBubble.jsx`)**: Signals can now be an array. Renders a `PriceCard` for EACH symbol in multi-symbol queries (e.g., side-by-side NABIL and NICA cards).
- **NABIL PriceCard Missing Fix (`services/agent.py`)**: Fixed critical bug where `sql_tool` returned empty signals `{}` when web price extraction returned `raw_text` instead of a numeric close. The early return on line 235 (`return text, citations, {}`) was removed — now uses DB data with a stale note instead.
- **DDG Source Label Fix (`services/web_search.py` & `NewsSection.jsx`)**: DuckDuckGo results now extract the actual domain name from the URL (e.g., "sharesansar.com") instead of showing "DuckDuckGo" as the source. Frontend also has a fallback domain extractor.
- **News Symbol Attribution (`agent.py` & `NewsSection.jsx`)**: Added `symbol` field to news citations. NewsSection now shows "Latest News — NICA & NABIL" instead of just one symbol.
- **Vector Tool Blocking Fix (`apps/agent/views.py`)**: Changed vector_tool execution from route-based check (`if route in (ROUTE_FULL_AGENT,...)`) to `if "vector_tool" in decision.tools_needed`. This respects the router's blocking logic — previously, even when `query_router.py` stripped vector_tool from `tools_needed`, views.py would still run it because it only checked the route name.
- **Stock Name Cleanup (`load_sample_data.py`)**: Updated `get_or_create` loop to also fix `name` field when it contains "auto-created" — 58 stocks updated to proper names (e.g., "Nabil Bank Limited" instead of "NABIL (auto-created from Neon)"). This fixes PriceCard subtitle display AND news search quality.
- **News Search Quality (`services/news_scraper.py`)**: Added sanitization to skip junk stock names containing "auto-created" in search queries. Now uses full company name (e.g., "NABIL Nabil Bank Limited Nepal May 2026") for more specific results.
- **System Prompt v3 (`services/llm_client.py`)**: Added Rule 5 (never write "[context unclear]" placeholders) and Rule 6 (don't repeat PriceCard/SignalsTable numbers — provide analysis instead). Changed format to request commentary over raw data duplication.

### 2026-05-08 — Bug Fixes (Phases 2, 4)

#### services/agent.py
- Fixed `_fetch_52w_range()` psycopg2 async crash — now uses `loop.run_in_executor(None, lambda: execute_neon_query(...))`, matching the sync pattern in `db_service.py`
- Added `_current_month_year()` helper — web search queries now include current month ("May 2026") for temporally fresh results
- Added 52-week high/low to `signals` dict returned by `sql_tool`

#### services/news_scraper.py
- Added `INDIAN_SOURCES_BLACKLIST` (12 domains) and `_is_nepse_article()` filter
- Root cause: NewsAPI returned Indian NHPC articles from thehindubusinessline.com
- Filter applied after deduplication, before DB persistence

#### apps/agent/views.py
- Fixed `Task was destroyed but it is pending!` SSE warning
- Added `loop.run_until_complete(loop.shutdown_asyncgens())` in `_stream_events()` finally block
- Added `GeneratorExit` handler calling `async_gen.aclose()` on client disconnect

### 2026-05-08 — Phase 4 & 5 Complete
- Implemented LangGraph Agent Orchestration in `services/agent.py`
- Implemented `services/llm_client.py` with multi-provider fallback (Groq, Gemini, OpenRouter, Ollama)
- Ollama configured as Priority 4 with OpenAI-compatible `/v1/chat/completions` endpoint, model `llama3.2:3b`
- Created fully responsive React + Vite frontend with Tailwind CSS
- Added SSE streaming with typewriter effect
- Integrated dynamic LLM token usage tracking in chat footer
- Replaced raw text outputs with structured components: `PriceCard`, `SignalsTable`, `NewsSection`, `CitationList`
- Polished UI: auto-expanding textarea, single-line symbol dropdown, aligned header

### 2026-05-05 — Phase 2 Complete
- Implemented `services/web_search.py` with 4-provider fallback chain
- Implemented `services/news_scraper.py` with ShareSansar + MeroLagani scrapers
- Switched from deprecated `duckduckgo_search` to new `ddgs` package (v9.14.2)
- Added NEPSE site-prioritized DuckDuckGo search (8 financial sites)
- Fixed async DB persistence with `sync_to_async`
- Updated `.env` with working NewsAPI key
- Disabled Google CSE (403) and SerpAPI (429) with placeholder functions
- Added `services/cache_service.py` with TTL-based caching + LLM token tracking
- Verified pipeline: NewsAPI returns 2 articles, DuckDuckGo returns 3-5 per symbol

---

## Phase 6: Evaluation & Documentation — COMPLETE

### What Was Done
- [x] **Cross-Encoder Reranking (`services/vector_rag.py`)**: Integrated `cross-encoder/ms-marco-MiniLM-L-6-v2` to rerank top-10 bi-encoder ChromaDB retrievals, returning top-3. This prevents broad files like `fundamental_analysis_guide.txt` from dominating search results.
- [x] **Post-Generation Groundedness Checker (`services/groundedness.py`)**: Built an entailment-based checker using the cross-encoder to grade LLM answers against context. If the average groundedness score is `< 0.5`, the system appends a warning disclaimer to the streamed response.
- [x] **RAGAS Evaluation Suite (`evaluation/eval_runner.py`)**: Implemented a full test suite with 30 representative questions across 7 categories (stock analysis, news, anti-hallucination, definitional, comparison, negative prompts, and sub-related). Uses Google AI (Gemini) as the LLM judge.
- [x] **Negative Prompt Rejection Evaluator (`evaluation/eval_negative.py`)**: Automated checking of off-topic deflection (Mt Everest, Tesla, Bitcoin, politics, weather) to ensure the agent stays in character.
- [x] **News Reliability Test (`evaluation/eval_news.py`)**: Direct validation of news fetches for 5 symbols (NABIL, NICA, NHPC, SBL, UPPER) checking for articles, markdown leaks, and Indian NHPC filtering.
- [x] **Retrieval Diversity Test (`evaluation/eval_retrieval.py`)**: Tests source file diversity and checks the effectiveness of cross-encoder reranking.
- [x] **Bug Fixes**:
  - [x] Strict anti-hallucination rules (Rule 8: Forbidden financial ratios list in `llm_client.py`).
  - [x] Ambiguous symbol disambiguation (NHPC Nepal-specific filters in `news_scraper.py`).
  - [x] Clear conversation history in screener-to-query transitions to avoid history context pollution in `views.py`.
  - [x] Tighter regex-based symbol matching (expanded `_EXCLUDED_WORDS` in `query_router.py`).
  - [x] Robust markdown, HTML, and entity stripping in frontend `NewsSection.jsx`.

### Key Files
- `services/groundedness.py` — Entailment-based groundedness checker
- `evaluation/eval_runner.py` — RAGAS metric runner using Gemini judge
- `evaluation/eval_negative.py` — Off-topic query rejection tests
- `evaluation/eval_news.py` — News pipeline validator (no markdown, no Indian NHPC)
- `evaluation/eval_retrieval.py` — Vector retrieval diversity and reranking checks
- `evaluation/test_questions.json` — 30-question gold dataset