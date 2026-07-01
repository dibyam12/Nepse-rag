# NEPSE AI RAG — Complete Codebase Understanding

> **Purpose**: This document gives any AI model (or developer) a complete understanding of the project architecture, data flow, file locations, and current capabilities — so they can start working immediately without re-exploring the codebase.

---

## 1. What Is This Project?

NEPSE AI is a **Retrieval-Augmented Generation (RAG) chatbot** for the Nepal Stock Exchange (NEPSE). It answers questions about Nepali listed stocks (like NABIL, NICA, NHPC) by:

1. Fetching **live OHLCV + technical indicators** from a Neon PostgreSQL database
2. Querying a **knowledge graph** (JSON) for sector/peer relationships
3. Searching **web news** via DuckDuckGo, NewsAPI, and direct site scraping
4. Retrieving **domain knowledge** from embedded documents via ChromaDB vector search
5. Synthesizing everything through an **LLM** (Groq → Google AI → OpenRouter → Ollama fallback chain)
6. Streaming the response **token-by-token** via SSE to a React frontend

The UI shows: PriceCards, SignalsTables, News sections, collapsible `<thinking>` reasoning blocks, source citations, and disclaimer badges.

---

## 2. Tech Stack

| Layer | Technology |
|-------|-----------|
| **Backend Framework** | Django 4.2+ with Django REST Framework |
| **ASGI Server** | Daphne (required for async SSE streaming) |
| **Database (price data)** | Neon PostgreSQL (read-only, cloud) |
| **Database (app data)** | SQLite (local: users, conversations, messages, stock metadata) |
| **Vector Store** | ChromaDB + LlamaIndex + HuggingFace `all-MiniLM-L6-v2` embeddings |
| **Knowledge Graph** | JSON file (`indexes/graph_store.json`) — sector → stock → peers |
| **LLM Providers** | Groq (llama-3.1-8b), Google AI (gemini-2.5-flash), OpenRouter (llama-3.2-3b:free), Ollama (llama3.2:3b local) |
| **Agent Orchestration** | LangGraph (StateGraph with conditional routing) |
| **Web Search** | DuckDuckGo (`ddgs` package), NewsAPI, direct HTML scraping |
| **Frontend** | React 18 + Vite + Zustand (state) + Axios + Lucide icons |
| **Styling** | Vanilla CSS with CSS custom properties (dark/light theme) |
| **Caching** | Django database cache (1-hour TTL for LLM responses, news) |

---

## 3. Project Structure

```
nepse_rag/
├── backend/                         # Django project root (CWD for all backend commands)
│   ├── manage.py
│   ├── .env                         # API keys (GROQ_API_KEY, GOOGLE_AI_API_KEY, etc.)
│   ├── requirements.txt
│   ├── db.sqlite3                   # Local SQLite (users, conversations, stock metadata)
│   ├── nepse_project/               # Django settings & ASGI config
│   │   ├── settings.py
│   │   ├── asgi.py
│   │   └── urls.py
│   ├── apps/
│   │   ├── nepse_data/              # Models: Stock, OHLCV, Indicator, NewsEvent
│   │   ├── agent/                   # API views: QueryView, StreamQueryView
│   │   │   ├── views.py             # POST /api/query/ and GET /api/query/stream/
│   │   │   └── urls.py
│   │   ├── accounts/                # Auth: login, register, conversations, messages
│   │   ├── api/                     # URL routing hub
│   │   └── rag/                     # Legacy Phase 3 RAG app
│   ├── services/                    # ⭐ CORE BUSINESS LOGIC ⭐
│   │   ├── agent.py                 # LangGraph agent: run_agent(), sql_tool, graph_tool, news_tool, vector_tool
│   │   ├── query_router.py          # Intent classification: 4 routes + symbol extraction + merged symbol map
│   │   ├── llm_client.py            # LLM fallback chain: call_llm(), stream_llm(), build_rag_prompt()
│   │   ├── db_service.py            # Neon DB access: get_latest_ohlcv(), get_latest_indicators()
│   │   ├── neon_client.py           # Raw Neon PostgreSQL query executor
│   │   ├── indicators.py            # Technical indicator computation (pandas_ta)
│   │   ├── news_scraper.py          # News pipeline: ShareSansar, MeroLagani, NepseAlpha scraping + DDG + NewsAPI
│   │   ├── web_search.py            # DDG search, NewsAPI search, fetch_article() for URL text extraction
│   │   ├── vector_rag.py            # ChromaDB vector search over domain docs + cross-encoder reranking
│   │   ├── graph_rag.py             # JSON knowledge graph: sector/peer lookups
│   │   ├── cache_service.py         # Django DB cache helpers
│   │   └── groundedness.py          # ⭐ Post-generation groundedness safety check (entailment based)
│   ├── evaluation/                  # ⭐ EVALUATION SUITE ⭐
│   │   ├── __init__.py
│   │   ├── test_questions.json      # 30 golden test cases
│   │   ├── eval_runner.py           # RAGAS metrics runner (Gemini LLM judge)
│   │   ├── eval_news.py             # Direct news fetch & format validator
│   │   ├── eval_retrieval.py        # Vector retrieval diversity validator
│   │   ├── eval_negative.py         # Off-topic deflection validator
│   │   └── results/                 # JSON outputs for completed evaluation runs
│   ├── docs/                        # 18 domain knowledge .txt files (embedded into ChromaDB)
│   ├── indexes/                     # graph_store.json + ChromaDB persistent data
│   ├── chroma_db/                   # ChromaDB storage directory
│   ├── logs/                        # JSONL application logs
│   ├── venv/                        # Python virtual environment
│   └── test_phase4.py               # Verification tests (query routing, prompt building, etc.)
│
├── frontend/                        # React + Vite app
│   ├── package.json
│   ├── vite.config.js               # Proxy: /api → http://localhost:8000
│   ├── src/
│   │   ├── main.jsx                 # App entry point
│   │   ├── App.jsx                  # Root component
│   │   ├── style.css                # Main stylesheet (18KB, CSS custom properties)
│   │   ├── index.css                # Secondary styles
│   │   ├── api/client.js            # Axios instance with auth interceptors
│   │   ├── store/
│   │   │   ├── chatStore.js         # ⭐ Zustand store: messages, SSE handling, auth, conversations
│   │   │   └── themeStore.js        # Dark/light theme toggle
│   │   ├── hooks/
│   │   │   ├── useSSE.js            # Standalone SSE hook (alternative to chatStore's built-in SSE)
│   │   │   └── useQuery.js          # Query helper hook
│   │   └── components/
│   │       ├── ChatWindow.jsx       # Main chat UI container
│   │       ├── MessageBubble.jsx    # ⭐ Message renderer: thinking blocks, PriceCards, SignalsTables, News
│   │       ├── PriceCard.jsx        # Stock price card (symbol, close, change%, volume, ranges)
│   │       ├── SignalsTable.jsx     # Technical indicators table (RSI, MACD, EMA, BB)
│   │       ├── NewsSection.jsx      # News article list with dot-style layout
│   │       ├── CitationList.jsx     # Source citation chips
│   │       ├── LoadingIndicator.jsx # Bouncing dots "Thinking..." animation
│   │       ├── SymbolDropdown.jsx   # Stock symbol selector dropdown
│   │       ├── AuthModal.jsx        # Login/Register modal
│   │       └── QueryHistory.jsx     # Conversation sidebar
│
├── PROJECT_STATUS.md                # Development progress, phases, change log
├── UNDERSTAND_PROJECT.md            # Earlier project overview
└── README.md                        # Setup instructions
```

---

## 4. Data Flow — How a Query Works

### SSE Streaming Flow (primary path)

```
User types "Compare NICA and NCCB" in React UI
        │
        ▼
[chatStore.sendMessage()]
  → Creates EventSource to GET /api/query/stream/?question=...&symbol=...
        │
        ▼
[StreamQueryView._async_stream()] in views.py
  1. Check cache → if hit, replay tokens from cached answer
  2. extract_symbols(question) → ['NICA', 'NCCB']
  3. classify_query(question) → RouteDecision(route='compare', symbols=['NICA','NCCB'])
  4. Yield SSE: {"type": "route", "data": "compare"}
  5. Yield SSE: {"type": "tools", "data": ["sql_tool", "graph_tool", "news_tool"]}
        │
        ▼
  6. For each symbol, run tools:
     ┌──────────────────────────────────┐
     │ sql_tool(sym)                    │ → Neon DB: OHLCV + indicators + 52W range
     │   └─ MERGED_SYMBOLS_MAP check   │   (NCCB → KBL transparently)
     │   └─ _fetch_price_from_web()    │   (if data > 3 days old)
     │ graph_tool(question, sym)        │ → graph_store.json: sector, peers
     │ news_tool(sym)                   │ → news_scraper pipeline (concurrent)
     │ vector_tool(question)            │ → ChromaDB: domain knowledge chunks
     └──────────────────────────────────┘
  7. Yield SSE: {"type": "signals", "data": [{NICA signals}, {NCCB signals}]}
        │
        ▼
  8. build_rag_prompt(question, tool_outputs)
     → Wraps outputs in XML: <sql_data>, <graph_data>, <news_data>, <vector_data>
     → Adds QUESTION + INSTRUCTIONS
     → Budget: 3000 tokens (iterative truncation)
        │
        ▼
  9. stream_llm(prompt)
     → Tries Groq → Google AI → OpenRouter → Ollama
     → Each token yielded as SSE: {"type": "token", "content": "Based"}
        │
        ▼
  10. Yield SSE: {"type": "citations", "data": [...]}
  11. Yield SSE: {"type": "provider", "data": "groq", "tokens": 674}
  12. Yield SSE: {"type": "done", "latency_ms": 27100}
  13. Cache response + Save to DB (conversation history)
```

### Frontend SSE Consumption

```
EventSource.onmessage → switch(data.type):
  'route'     → store routeUsed (shows chip: "Compare")
  'tools'     → store toolsUsed (shows chips: "SQL", "Graph", "News")
  'signals'   → store signals (renders PriceCard + SignalsTable)
  'token'     → appendToken() to message content (live streaming text)
  'citations' → store citations (renders CitationList + NewsSection)
  'provider'  → store llmProvider, tokenUsage
  'done'      → finalizeMessage() → isStreaming=false
```

---

## 5. Query Routing System

File: `services/query_router.py`

| Route | Trigger | Tools |
|-------|---------|-------|
| `compare` | ≥2 symbols OR compare/vs/better keywords | sql_tool, graph_tool, news_tool |
| `full_agent` | why/news/today/fundamental/forecast keywords | sql_tool, graph_tool, news_tool, vector_tool |
| `sql_graph` | rsi/macd/price/volume/indicator keywords | sql_tool, graph_tool |
| `vector_only` | Educational/definitional (no symbols) | vector_tool |

**Keyword matching** uses `\b` word-boundary regex (via `_has_keyword()`) to prevent false positives like "eps" in "nepse".

**Symbol extraction** (`extract_symbols()`):
- Regex finds 2-10 char alphanumeric words
- Checks against DB known symbols + MERGED_SYMBOLS_MAP
- Excludes common English words, indicator abbreviations, institution names (RSI, MACD, NEPSE, etc.)

**Merged symbols**: `MERGED_SYMBOLS_MAP` maps historical tickers to active ones:
```python
NCCB → KBL, MEGA → NIMB, NIB → NIMB, BOKL → GBIME, CBL → LSL, LBL → LSL
```

---

## 6. Key Service Details

### agent.py — AgentState & Tools

```python
class AgentState(TypedDict):
    question: str
    symbol: str          # Primary active symbol
    symbols: list        # All symbols being queried
    route: str
    sql_output: str      # Formatted text from sql_tool
    graph_output: str    # Formatted text from graph_tool
    vector_output: str   # Formatted text from vector_tool
    news_output: str     # Formatted text from news_tool
    citations: list      # [{type, symbol, date, url, ...}]
    tools_called: list   # ["sql_tool", "graph_tool", ...]
    final_answer: str    # LLM response text
    llm_provider: str
    tokens_used: int
    latency_ms: int
    signals: list|dict   # Price/indicator data for PriceCard/SignalsTable
```

**sql_tool(symbol)** → Returns `(text_summary, citations, signals_dict)`:
- Fetches OHLCV from Neon via `get_latest_ohlcv()`
- Fetches indicators via `get_latest_indicators()`
- Fetches 52-week range via `_fetch_52w_range()`
- If data > 3 days old, tries `_fetch_price_from_web()`
- Builds signals dict with: close, high, low, volume, RSI, MACD, EMA_20, EMA_50, BB_upper/middle/lower, VWAP, pct_change, week52_high/low
- Merged symbols: queries active entity (KBL) but labels as "KBL (formerly NCCB)"

**news_tool(symbol)** → Returns `(text_summary, citations)`:
- Calls `get_news_for_symbol()` in news_scraper.py
- 12-second timeout
- Returns headlines + sources as text for LLM context
- Citations include headline, url, source, published_at, summary

### news_scraper.py — Current News Pipeline

The pipeline runs **6 concurrent fetches**:
1. `scrape_sharesansar(symbol)` — HTML scrape of ShareSansar news endpoint
2. `scrape_merolagani(symbol)` — AJAX/JSON endpoint for announcements
3. `scrape_nepsealpha(symbol)` — HTML scrape of NepseAlpha company news
4. `ddg_search(query_a)` — DuckDuckGo site-restricted search (batch 1)
5. `ddg_search(query_b)` — DuckDuckGo site-restricted search (batch 2)
6. `newsapi_search(query)` — NewsAPI.org supplemental search

Then: dedup by URL → filter Indian sources → filter non-article URLs → enrich top 2 articles with full bodies via `fetch_article()` → normalize schema → cache 1 hour → save to DB.

**Enrichment**: Extracts full text (up to 1,500 chars) concurrently from top news URLs and attaches it under the `body` field. The excerpt is prefilled into the LLM context.

### llm_client.py — Prompt Structure

System prompt enforces:
- `<thinking>` block before analysis (CoT reasoning)
- Strict grounding: never invent data
- Don't repeat PriceCard/SignalsTable numbers
- Concise Bloomberg-terminal style

RAG prompt wraps tool outputs in XML tags:
```xml
<context>
<sql_data>NICA as of 2026-04-17: Close: 366.30, RSI: 51.0...</sql_data>
<graph_data>NICA — Graph Context: Sector: Commercial Banks...</graph_data>
<news_data>Recent news for NICA: 1. 'headline' — source...</news_data>
<vector_data>From indicator_explanations.txt: ...</vector_data>
</context>

QUESTION: Compare NICA and NCCB fundamentals

INSTRUCTIONS: Using ONLY the context above, answer concisely...
```

Token budget: 3000 tokens max (iteratively truncates longest output by 20%).

### views.py — SSE Event Types

The `StreamQueryView._async_stream()` yields these SSE events in order:

| Order | Event Type | Data |
|-------|-----------|------|
| 1 | `route` | Route name string |
| 2 | `tools` | Array of tool names |
| 3 | `signals` | Single dict or array of dicts |
| 4 | `token` | Individual LLM tokens (many events) |
| 5 | `citations` | Array of citation objects |
| 6 | `provider` | Provider name + token count |
| 7 | `done` | Latency in ms |

### groundedness.py — Groundedness Checker

Built as an entailment-based safety guard.
- **Trigger**: Runs at the end of the streaming pipeline (views.py) as a best-effort, non-blocking asynchronous task.
- **Model**: Reuses the `cross-encoder/ms-marco-MiniLM-L-6-v2` singleton loaded for vector reranking.
- **Process**:
  1. Splits the LLM response into sentence-level claims (filtering out thinking tags and boilerplate disclaimers).
  2. Scores each claim against the combined retrieved context (`sql_output`, `graph_output`, `vector_output`, `news_output`).
  3. If a claim scores `< 0.3`, it is flagged.
  4. If the overall average score is `< 0.5`, it appends a disclaimer warning: `⚠️ [Note: some claims in this response could not be fully verified from available data...]` so users are alerted.

### evaluation/ — Automated Test Suite

A complete framework to ensure retrieval quality and guard against regressions:
- **`test_questions.json`**: Gold dataset containing 30 hand-crafted test questions covering stock analysis (5), news queries (5), anti-hallucination (5), definitional (3), comparison (3), negative/off-topic prompts (5), and sub-related topics (4).
- **`eval_runner.py`**: Executes the RAGAS evaluation. Uses Google AI (Gemini) as the LLM judge. Computes:
  - *Faithfulness*: Groundedness of response in context.
  - *Answer Relevancy*: How well the answer matches the question.
  - *Context Precision*: Accuracy of retrieval.
  - Also outputs basic metrics like route accuracy, tool recall, negative deflection rate, and average latency.
- **`eval_negative.py`**: Evaluates boundary and off-topic prompt rejection (Mt. Everest, crypto, etc.) to ensure the bot politely redirects off-topic chatter.
- **`eval_news.py`**: Directly invokes `news_tool` for 5 key symbols to verify article presence, ensure markdown elements are stripped, and check that Indian NHPC results are blocked.
- **`eval_retrieval.py`**: Directly calls `query_vector_rag` across 10 queries, validating source diversity and confirming that `fundamental_analysis_guide.txt` doesn't dominate.

---

## 7. Frontend Architecture

### State Management (Zustand — chatStore.js)

```javascript
{
  messages: [],           // Array of message objects
  isLoading: false,
  selectedSymbol: '',     // From URL/dropdown
  lastSymbol: null,       // Last queried symbol (for context)
  symbols: [],            // All available symbols from DB
  conversations: [],      // User's conversation history
  activeConversationId: null,
  user: null,             // Auth state
  token: null,            // Auth token
}
```

Message object shape:
```javascript
{
  id: number,
  role: 'user' | 'assistant',
  content: string,        // Raw LLM text (may contain <thinking> tags)
  isStreaming: boolean,
  signals: object|array,  // From SSE 'signals' event
  citations: array,       // From SSE 'citations' event
  toolsUsed: array,
  routeUsed: string,
  llmProvider: string,
  tokenUsage: number,
  latencyMs: number,
  created_at: string,
}
```

### MessageBubble.jsx — Rendering Pipeline

1. `extractThinking(content)` → Splits `<thinking>...</thinking>` from clean text
2. `cleanContent(cleanText)` → Removes "no recent news" noise
3. Renders in order:
   - Tool chips row (route + tools + provider + latency)
   - Collapsible `<details>` reasoning block (with pulse animation while streaming)
   - PriceCard(s) — one per symbol in signalsList
   - Main LLM text (markdown → HTML via `mdToHtml()`)
   - SignalsTable(s) — one per symbol
   - NewsSection — filtered news citations
   - CitationList — all source chips
   - Disclaimer footer

### CSS Theming

- CSS custom properties in `style.css` (18KB)
- Dark/light mode via `data-theme` attribute
- Premium glassmorphism aesthetic
- All colors use HSL with CSS vars

---

## 8. API Endpoints

| Method | URL | Description |
|--------|-----|-------------|
| POST | `/api/query/` | Non-streaming query (fallback) |
| GET | `/api/query/stream/` | SSE streaming query (primary) |
| GET | `/api/symbols/` | List all stock symbols |
| POST | `/api/auth/login/` | Login (returns token) |
| POST | `/api/auth/register/` | Register |
| POST | `/api/auth/logout/` | Logout |
| GET | `/api/auth/conversations/` | List user conversations |
| GET | `/api/auth/conversations/:id/` | Get conversation messages |
| DELETE | `/api/auth/conversations/:id/` | Delete conversation |

---

## 9. Environment & Running

### .env Keys (in backend/.env)
```
NEON_DATABASE_URL=...       # Read-only Neon PostgreSQL
GROQ_API_KEY=...            # Priority 1 LLM
GOOGLE_AI_API_KEY=...       # Priority 2 LLM
OPENROUTER_API_KEY=...      # Priority 3 LLM
NEWSAPI_KEY=...             # News search
```

### Running the App
```bash
# Backend (from backend/ directory):
venv\Scripts\python.exe -m daphne -b 127.0.0.1 -p 8000 nepse_project.asgi:application

# Frontend (from frontend/ directory):
npm run dev    # Vite dev server on port 5173, proxies /api to :8000
```

### Running Tests
```bash
# From backend/:
venv\Scripts\python.exe test_phase4.py    # Unit tests (routing, prompt, graph, imports)
venv\Scripts\python.exe test_phase4_live.py  # E2E tests (calls actual LLM)
```

---

## 10. Known Limitations & Current Gaps

1. **OHLCV data staleness**: Neon DB data is from 2026-04-17. The web price fallback often fails to parse prices from scraped HTML.

2. **News deduplication is URL-only**: Same story from different sources isn't deduplicated by content similarity.

3. **Single-round conversation**: No multi-turn memory. Each query is independent (context symbol is the only carryover).

---

## 11. Recent Changes (2026-06-04)

- **Richer News**: Scraping full article bodies for top results using `fetch_article()` with site-specific selectors, stripping boilerplates, and passing excerpts to the LLM context.
- **Live SSE Agent Status Indicators**: Added real-time SSE progress events (e.g., "Fetching price data for NICA...") shown dynamically in the frontend message bubble with matching icons.
- **Anti-Hallucination & Prompt Engineering**: Added grounding rules, a few-shot example, response prefilling, and chain-of-verification checks in the `<thinking>` block. Tagged XML blocks with symbols.
- **Word-boundary keyword matching**: `_has_keyword()` with `\b` regex prevents false positives (e.g., "eps" in "nepse")
- **NEPSE excluded from symbols**: Added "NEPSE" to `_EXCLUDED_WORDS` so "What are the NEPSE trading rules?" routes to `vector_only` not `full_agent`
- **Merged symbols support**: NCCB→KBL, MEGA→NIMB etc. transparently queried
- **Context pollution fix**: Explicit symbols in query override stale URL param symbol
- **CoT reasoning**: `<thinking>` blocks with collapsible UI
- **XML-tagged RAG context**: `<sql_data>`, `<graph_data>`, `<news_data>`, `<vector_data>` tags with symbol attributes
- **Multi-symbol signals**: PriceCard and SignalsTable render for all queried symbols

---

*Last updated: 2026-06-04*
