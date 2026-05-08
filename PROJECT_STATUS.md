# NEPSE AI Research Assistant — Project Status Tracker

> **Last Updated**: 2026-05-05  
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
| 6 | Evaluation & Documentation | NOT STARTED | 0% |

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
- `services/neon_client.py` — Read-only Neon DB connection
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
- [x] NEPSE site-prioritized DuckDuckGo search (searches sharesansar, merolagani, nepsealpha, sharehubnepal, nepalipaisa, bajarkochirfar, nepalytix, moneymitra FIRST)
- [x] Article content extraction (`fetch_article()` using httpx + BeautifulSoup4)
- [x] News scrapers (`services/news_scraper.py`): ShareSansar + MeroLagani (HTML may need selector updates)
- [x] `get_news_for_symbol()` — orchestrates search + scraping, deduplicates, persists to `NewsEvent` model
- [x] Async-safe DB persistence using `sync_to_async`
- [x] Test endpoint: `GET /api/test/news/?symbol=NABIL`

### Test Results (2026-05-05)
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

### Known Issues / TODO for Phase 2
- [ ] Fix Google CSE: Create new API key + enable Custom Search API in GCP console
- [ ] Fix SerpAPI: Create new account at serpapi.com for fresh $100 credits
- [ ] Update ShareSansar/MeroLagani scraper CSS selectors if HTML structure changes
- [ ] NewsAPI free tier is limited to 500 req/month — monitor usage

### Key Files
- `services/web_search.py` — Unified search with fallback chain
- `services/news_scraper.py` — Scrapers + `get_news_for_symbol()`
- `.env` — API keys (NewsAPI working, others commented out)

---

## Phase 3: RAG System (Vector + Graph) — COMPLETE

### What Was Done
- [x] Vector RAG using LlamaIndex + ChromaDB (`services/vector_rag.py`)
  - [x] Ingests `docs/*.txt` domain knowledge files (512 token chunks reduced to 256 for token budget)
  - [x] Sentence Transformers for local CPU embeddings (`all-MiniLM-L6-v2`)
  - [x] Lazy loading on first query to prevent slow Django startup
- [x] Graph RAG for entity relationships (`services/graph_rag.py`)
  - [x] Built manually from SQLite without LLM extraction to save tokens
  - [x] Stock → Sector, Stock → Index, and Stock → Peer relationships
  - [x] Persists to `indexes/graph_store.json` (fast loading <100ms)
- [x] Query Router (`services/query_router.py`)
  - [x] Rule-based intent classification (FACTUAL, ANALYTICAL, NEWS, PRICE, COMPARISON, GENERAL)
  - [x] Regex-based stock symbol extraction from questions
- [x] Caching added for Vector and Graph responses (`services/cache_service.py`)
- [x] Test endpoints under `/api/rag/`

### Test Results (2026-05-06)
- **Graph Index**: Built successfully in 0.1s (521 stock nodes, 9 sectors, 614 edges).
- **Vector Index**: Built successfully in 33.4s (9 documents -> 67 chunks). The `sentence-transformers` model is now downloaded and cached locally.

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
- [x] LangGraph agent workflow (`services/agent.py`)
  - [x] Query routing logic (vector, sql, graph, news, full_agent)
  - [x] Agentic tools: `sql_tool`, `graph_tool`, `vector_tool`, `news_tool`
  - [x] Parallel tool execution for `full_agent`
- [x] Conversation memory and chat history (via Django models)
- [x] Streaming responses via Server-Sent Events (SSE) and `StreamingHttpResponse`
- [x] Active LLM tracking and Token usage accounting

### Key Files
- `services/llm_client.py` — Multi-provider fallback chain and SSE parsing
- `services/agent.py` — LangGraph agent orchestration
- `apps/agent/views.py` — Chat streaming endpoints

---

## Phase 5: Frontend — COMPLETE

### What Was Done
- [x] Vite + React 18 setup with Tailwind CSS
- [x] State management with Zustand (`useChatStore`, `useThemeStore`)
- [x] Responsive Chat UI with streaming messages and markdown rendering
- [x] Intelligent Symbol Dropdown with searchable stocks
- [x] Dynamic LLM tracking display in chat footer (Provider + Token usage)
- [x] UI component replacements: `PriceCard`, Indicator Grid (`SignalsTable`), Styled Empty States (`NewsSection`), Pill Source Chips (`CitationList`)
- [x] Light/Dark mode toggling
- [x] User Authentication UI (Login/Register)

### Key Files
- `frontend/src/components/ChatWindow.jsx` — Main chat UI
- `frontend/src/store/chatStore.js` — Streaming and state management
- `frontend/src/components/SymbolDropdown.jsx` — Market symbol selector

---

## Phase 6: Evaluation & Documentation — NOT STARTED

### Planned Work
- [ ] RAG evaluation metrics (faithfulness, relevancy, answer quality)
- [ ] Agent evaluation (tool selection accuracy, multi-step reasoning)
- [ ] Performance benchmarks (latency, cache hit rates)
- [ ] Final project report and documentation
- [ ] Disclaimer on every LLM response

---

## Environment & Configuration

### .env Keys Status
| Key | Status | Notes |
|-----|--------|-------|
| `NEON_DATABASE_URL` | CONFIGURED | Read-only Neon PostgreSQL |
| `NEWSAPI_KEY` | WORKING | Primary search provider |
| `GROQ_API_KEY` | CONFIGURED | For Phase 4 LLM chain |
| `GOOGLE_AI_API_KEY` | CONFIGURED | For Phase 4 LLM chain |
| `OPENROUTER_API_KEY` | CONFIGURED | For Phase 4 LLM chain |
| `GOOGLE_CSE_API_KEY` | DISABLED | 403 error |
| `SERPAPI_KEY` | DISABLED | 429, credits exhausted |

### Dependencies (requirements.txt)
- Django 4.2+, DRF, Channels, Daphne
- pandas, pandas_ta (indicators)
- httpx, beautifulsoup4, lxml (scraping)
- ddgs (DuckDuckGo search)
- newsapi-python, serpapi, google-api-python-client (search providers)
- python-decouple, psycopg2-binary
- python-json-logger (logging)

### Project Structure
```
nepse_rag/
├── apps/
│   ├── nepse_data/    # Models: Stock, OHLCV, Indicator, NewsEvent
│   ├── rag/           # RAG app (Phase 3)
│   ├── agent/         # Agent app (Phase 4)
│   └── api/           # REST endpoints
├── services/
│   ├── neon_client.py     # Neon DB connection (Phase 1)
│   ├── db_service.py      # Data access layer (Phase 1)
│   ├── indicators.py      # Technical indicators (Phase 1)
│   ├── cache_service.py   # Caching layer (Phase 1)
│   ├── web_search.py      # Web search fallback chain (Phase 2)
│   ├── news_scraper.py    # News scraping pipeline (Phase 2)
│   ├── vector_rag.py      # Vector RAG (Phase 3)
│   ├── graph_rag.py       # Graph RAG (Phase 3)
│   ├── query_router.py    # Query routing (Phase 3)
│   ├── llm_client.py      # LLM client & stream handling (Phase 4)
│   └── agent.py           # Agent orchestration via LangGraph (Phase 4)
├── frontend/          # React + Vite application (Phase 5)
├── docs/              # Domain knowledge (9 files)
├── logs/              # JSONL logs
├── nepse_project/     # Django settings
├── .env               # API keys
└── requirements.txt
```

---

## Change Log

### 2026-05-08 — Phase 4 & 5 Complete
- Implemented LangGraph Agent Orchestration in `services/agent.py`
- Implemented `services/llm_client.py` with multi-provider fallback (Groq, Gemini, OpenRouter, Ollama)
- Created fully responsive React + Vite frontend with Tailwind CSS
- Added SSE streaming message capabilities with live typewriter effect
- Integrated dynamic LLM token usage tracking directly in the frontend chat interface
- Polished UI layout alignments and dynamic text box heights
- Replaced raw text outputs with structured UI components (`PriceCard`, `SignalsTable` grid, `NewsSection`, pill-shaped `CitationList`)

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
