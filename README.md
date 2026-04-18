# NEPSE AI Research Assistant

NEPSE AI Research Assistant is an AI-powered web assistant that answers questions about NEPSE (Nepal Stock Exchange) using Graph RAG and Agentic RAG.

> **Disclaimer**: This project is for EDUCATIONAL AND RESEARCH PURPOSES ONLY. It does not provide financial advice.

## Features (Phase 1)
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

1. Clone the repository:
   ```bash
   git clone https://github.com/dibyam12/Nepse-rag.git
   cd Nepse-rag
   ```

2. Create a virtual environment and install dependencies:
   ```bash
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. Configure environment variables:
   Copy `.env.example` to `.env` and fill in your keys (e.g., `NEON_DATABASE_URL`).

4. Apply migrations and load sample data:
   ```bash
   python manage.py migrate
   python manage.py load_sample_data
   ```

5. Run the development server:
   ```bash
   python manage.py runserver
   ```