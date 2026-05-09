# NEPSE AI Research Assistant

NEPSE AI Research Assistant is an AI-powered web assistant that answers questions about NEPSE (Nepal Stock Exchange) using Graph RAG and Agentic RAG.

> **Disclaimer**: This project is for EDUCATIONAL AND RESEARCH PURPOSES ONLY. It does not provide financial advice.

---

## Recent Features & Updates

### Phase 5 — UI Polish (2026-05-08)
- **PriceCard component** — shows close price, % change, day range, 52W range, VWAP in a structured card
- **Indicator Grid (SignalsTable)** — color-coded RSI/MACD/EMA/Bollinger status badges
- **NewsSection** — styled empty state with direct links to ShareSansar and MeroLagani when no news found
- **CitationList** — pill-shaped source chips with type icons (DB / Graph / Doc / Web)

### Phase 4 — Agentic RAG (2026-05-08)
- **Multi-Provider LLM Fallback**: Groq → Google AI Studio → OpenRouter → Ollama (Priority 1–4)
- **Ollama Local Fallback**: Uses `llama3.2:3b` via OpenAI-compatible endpoint — no API key, offline resilient
- **52-Week Range**: Fetched from Neon DB via `run_in_executor` to avoid psycopg2 async crash
- **Stale Data Detection**: Falls back to web search when Neon DB data is > 3 days old
- **LLM Metadata Tracking**: Displays active LLM provider + real-time token usage in chat footer
- **Intelligent Routing**: Queries routed between `sql_tool`, `graph_tool`, `vector_tool`, `news_tool`

### Phase 2 — News Pipeline (2026-05-05)
- **Indian Source Blacklist**: Filters 12 Indian financial news domains to avoid cross-contamination (e.g. Indian NHPC results polluting NEPSE NHPC queries)
- **On-Demand Architecture**: Direct Neon DB integration for live OHLCV data
- **Dynamic Indicators**: RSI, MACD, EMA, Bollinger Bands, ATR, OBV, VWAP, Beta computed in-memory via `pandas_ta`
- **Caching Layer**: Multi-tiered cache for OHLCV, indicators, LLM responses, and news
- **Background Keep-Alive**: Prevents Neon DB cold starts

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.10+, Django 4.2+, DRF, Channels, Daphne |
| Databases | SQLite (local metadata), Neon PostgreSQL (read-only market data) |
| Data Processing | pandas, pandas_ta |
| RAG | LlamaIndex, ChromaDB, Sentence Transformers (`all-MiniLM-L6-v2`) |
| Agent | LangGraph |
| LLMs (cloud) | Groq (Llama 3.3 70B), Google Gemini, OpenRouter |
| LLM (local) | Ollama `llama3.2:3b` (CPU, OpenAI-compatible endpoint) |
| Frontend | Vite, React 18, Tailwind CSS, Zustand |

---

## Setup Instructions

### Prerequisites
- Python 3.10+
- Node.js 18+
- [Ollama](https://ollama.com/download) installed on your system (for local LLM fallback)

### 1. Ollama Setup (Local LLM Fallback)
Ollama is an OS-level application — it is **not** a pip package.

```bash
# Download and install from https://ollama.com/download, then:
ollama pull llama3.2:3b
ollama serve   # keep this terminal running
```

### 2. Backend Setup

```bash
cd backend
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate      # Linux/macOS
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and configure your keys:

```env
NEON_DATABASE_URL=postgresql://...
NEWSAPI_KEY=your_newsapi_key
GROQ_API_KEY=your_groq_key
GOOGLE_AI_API_KEY=your_gemini_key
OPENROUTER_API_KEY=your_openrouter_key
# Optional: add HF_TOKEN to suppress HuggingFace rate-limit warnings
```

Apply migrations:

```bash
python manage.py migrate
```

Build the RAG indexes (one-time):

```bash
python scripts/build_graph_index.py
python scripts/build_vector_index.py
```

### 3. Frontend Setup

```bash
cd frontend
npm install
```

---

## Running the Application

Run backend and frontend in **two separate terminals**.

**Terminal 1 — Backend (Daphne)**

> ⚠️ Do NOT use `manage.py runserver` — Daphne is required for SSE streaming.

```bash
cd backend
venv\Scripts\activate
python -m daphne -b 127.0.0.1 -p 8000 nepse_project.asgi:application
```

**Terminal 2 — Frontend (Vite)**

```bash
cd frontend
npm run dev
```

Open [http://localhost:5173](http://localhost:5173) in your browser.

---

## LLM Fallback Chain

| Priority | Provider | Model | Approx Speed | Free Limit |
|----------|----------|-------|-------------|-----------|
| 1 | Groq | Llama 3.3 70B | 1–2s | 30 req/min |
| 2 | Google AI | Gemini | 2–3s | Free tier |
| 3 | OpenRouter | Various | 2–4s | Free tier |
| 4 | Ollama (local) | llama3.2:3b | 20–30s (CPU) | Unlimited |

---

## Useful Commands

### Clear Django Cache
If the agent returns stale data or skips live web searches, it is serving a cached response.
The backend uses a file-based cache that survives server restarts.

```bash
cd backend
venv\Scripts\activate
python manage.py shell -c "from django.core.cache import cache; cache.clear()"
```

### Rebuild Vector Index (after updating docs/)

```bash
python scripts/build_vector_index.py
```

### Rebuild Graph Index (after updating stock/sector data)

```bash
python scripts/build_graph_index.py
```

---

## Architecture Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| LLMs | API LLMs + Ollama fallback | No GPU available; RAG pipeline compensates for domain knowledge gap |
| Vector Store | ChromaDB | Zero-config embedded DB, free, native LlamaIndex support, sufficient for 67-chunk corpus |
| ASGI Server | Daphne | Required for async SSE streaming; WSGI servers (Gunicorn) are synchronous |
| Ollama | llama3.2:3b | OpenAI-compatible endpoint, no API key, offline resilience |
| Neon DB | Read-only | Remote production DB — all writes go through the data provider, not the app |