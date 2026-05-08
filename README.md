# NEPSE AI Research Assistant

NEPSE AI Research Assistant is an AI-powered web assistant that answers questions about NEPSE (Nepal Stock Exchange) using Graph RAG and Agentic RAG.

> **Disclaimer**: This project is for EDUCATIONAL AND RESEARCH PURPOSES ONLY. It does not provide financial advice.

## Recent Features & Updates

### Phase 4 & 5 (Agentic RAG & UI Polish)
- **Multi-Provider LLM Fallback**: Prioritized routing (Groq → Google AI Studio → OpenRouter → Ollama) for high availability.
- **Intelligent Routing**: Queries are routed between `sql_tool`, `graph_tool`, `vector_tool`, and `news_tool` to balance token budgets.
- **LLM Metadata Tracking**: Displays the active LLM provider and real-time token usage estimations directly in the chat footer.
- **Polished Responsive UI**: Seamlessly aligned chat interface featuring auto-expanding input fields without scrollbars, and single-line symbol dropdowns.

### Phase 1 (Data Foundation)
- **On-Demand Data Architecture**: Direct integration with a production Neon DB (PostgreSQL) to fetch live OHLCV stock data on demand.
- **Dynamic Indicators**: Computes technical indicators (RSI, MACD, EMA, Bollinger Bands, ATR, OBV, VWAP, Beta) in-memory using `pandas_ta`, avoiding local data bloat.
- **Caching Layer**: Implements multi-tiered caching for OHLCV data, indicators, LLM responses, and news to optimize performance and reduce database hits.
- **Background Keep-Alive**: Prevents serverless database cold starts to ensure fast, responsive queries.
- **Dual Database Strategy**: Uses Neon DB for heavy read-only market data and local SQLite for managing application metadata, chat history, and configurations.
- **Domain Knowledge Integration**: Contains comprehensive textual documentation covering NEPSE rules, sector overviews, SEBON circulars, and indicator explanations, ready for vector RAG.

## Tech Stack
- **Backend**: Python 3.10+, Django 4.2+, Django REST Framework (DRF), Channels/Daphne
- **Databases**: SQLite (Local Metadata), Neon PostgreSQL (Remote Read-Only Market Data)
- **Data Processing**: pandas, pandas_ta
- **RAG & Agents (Upcoming)**: LlamaIndex, LangGraph, ChromaDB, Sentence Transformers
- **Frontend (Upcoming)**: Vite, React 18, Tailwind CSS, Zustand, TanStack Query

## Setup Instructions

### 1. Backend Setup
The backend uses Django, Daphne (for SSE streaming), and LlamaIndex.

```bash
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

Configure your environment variables:
Copy `backend/.env.example` to `backend/.env` and fill in your API keys (Groq, Neon DB, etc.).

Apply migrations:
```bash
python manage.py migrate
```

### 2. Frontend Setup
The frontend is a React application powered by Vite.

```bash
cd frontend
npm install
```

## Running the Application

You must run the backend and frontend simultaneously in two separate terminals.

**Terminal 1: Start the Backend (Daphne)**
*Note: Do not use `manage.py runserver`. You must use Daphne for Server-Sent Events (SSE) streaming to work.*
```bash
cd backend
venv\Scripts\activate
python -m daphne -b 127.0.0.1 -p 8000 nepse_project.asgi:application
```

**Terminal 2: Start the Frontend (Vite)**
```bash
cd frontend
npm run dev
```

## Useful Commands

### Clearing the Django Cache
If you notice the agent returning stale data or skipping live web searches, it's likely serving a cached response. The backend uses a file-based cache that survives server restarts.

To forcefully clear the cache yourself, open a terminal and run:
```bash
cd backend
venv\Scripts\activate
python manage.py shell -c "from django.core.cache import cache; cache.clear()"
```