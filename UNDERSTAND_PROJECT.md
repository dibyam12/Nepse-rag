# NEPSE AI Research Assistant — Mid-Defense Master Q&A Study Guide

This document is a comprehensive study guide designed to prepare you for any Q&A question that could be asked during your mid-defense session tomorrow. It breaks down the system's files, the RAG evaluations, query routing, token definitions, and provides answers for both small and large questions.

---

## 1. File-by-File Codebase Directory Guide

Here is the exact purpose of every file in the backend codebase, so you can point out exactly where any logic resides if asked by the examiners.

### Core RAG & LLM Services (`backend/services/`)
1. **[agent.py](file:///d:/Home/BE/projects/nepse_rag/backend/services/agent.py)**: Orchestrates the LangGraph agent state machine. Compiles the graph, defines the nodes (`sql_node`, `news_node`, `vector_node`, `graph_node`, `synthesize_node`), and manages parallel tool executions.
2. **[llm_client.py](file:///d:/Home/BE/projects/nepse_rag/backend/services/llm_client.py)**: Houses the multi-provider LLM fallback chain. Contains the system prompts (anti-hallucination rules, verification instructions), handles token streaming, and manages connections to Groq, Gemini, OpenRouter, and Ollama.
3. **[query_router.py](file:///d:/Home/BE/projects/nepse_rag/backend/services/query_router.py)**: Deterministically routes the user query to the appropriate pipeline (`vector_only`, `sql_graph`, `full_agent`, `compare`, `chat`) using regex and database-driven stock symbol matches.
4. **[db_service.py](file:///d:/Home/BE/projects/nepse_rag/backend/services/db_service.py)**: The local data access layer. Integrates with the metadata database, triggers the technical indicator calculations, and handles caching layers.
5. **[indicators.py](file:///d:/Home/BE/projects/nepse_rag/backend/services/indicators.py)**: Computes all mathematical technical indicators (RSI, MACD, Bollinger Bands, EMAs, VWAP, Beta) in real-time using Pandas and Pandas-TA.
6. **[neon_client.py](file:///d:/Home/BE/projects/nepse_rag/backend/services/neon_client.py)**: Connects to the serverless Neon PostgreSQL cluster read-only using `psycopg2`. Contains the keep-alive background thread to prevent database hibernation.
7. **[news_scraper.py](file:///d:/Home/BE/projects/nepse_rag/backend/services/news_scraper.py)**: Scrapes Nepalese financial news outlets (ShareSansar, MeroLagani, NepseAlpha) in real-time, filters out non-Nepalese stocks (using the Indian source blacklist), and parses article titles/excerpts.
8. **[vector_rag.py](file:///d:/Home/BE/projects/nepse_rag/backend/services/vector_rag.py)**: Connects to ChromaDB using LlamaIndex. Encapsulates document loading, semantic vector searches, and metadata filtering.
9. **[graph_rag.py](file:///d:/Home/BE/projects/nepse_rag/backend/services/graph_rag.py)**: Queries the sector-peer graph database in memory using JSON-based node-edge relationships.
10. **[web_search.py](file:///d:/Home/BE/projects/nepse_rag/backend/services/web_search.py)**: Queries DuckDuckGo and NewsAPI as fallbacks for live news searches.
11. **[cache_service.py](file:///d:/Home/BE/projects/nepse_rag/backend/services/cache_service.py)**: Manages redis/file caches, keeps track of LLM token counters, and handles API rate-limiting sleep cycles.
12. **[groundedness.py](file:///d:/Home/BE/projects/nepse_rag/backend/services/groundedness.py)**: Performs post-generation groundedness checks by splitting response sentences into claims and scoring them via cross-encoder entailment against context. Appends a warning if score is below 0.5.

### Django Apps Layer (`backend/apps/`)
1. **`accounts/`**: Manages user authentication, profile serialization, registration, login/logout endpoints, and database models (`Conversation`, `Message`) to store chat logs.
2. **`agent/`**: Exposes the REST API and the Event Stream (SSE) views `/api/query/` and `/api/query/stream/`.
3. **`nepse_data/`**: Manages SQLite tables containing static stock indices, sectors, and historical news mappings.
4. **`api/`**: Exposes unified endpoints for loading company lists, sector data, and checking system health.

---

## 2. Deep Dive: Tokens, Routing, and Evaluations

### A. What are Tokens, How are they used, and Why are they required?
*   **Definition**: A **token** is the basic unit of text that an LLM reads and writes. It represents a common sequence of characters (e.g. 1 token $\approx$ 4 characters or 0.75 English words).
*   **Why they are required**:
    1.  **Rate Limits (TPM)**: LLM API providers (like Groq and Gemini) place limits on "Tokens Per Minute". If the system sends too much text at once, it gets blocked (`429 Rate Limit Exceeded`).
    2.  **Context Windows**: LLMs can only process a finite amount of text in a single request.
    3.  **Cost Control**: Commercial models charge per input/output token.
*   **How we use them here**:
    - We track token consumption in `cache_service.py` using memory-saved daily counters.
    - We enforce a **token budget (3,000 to 4,500 tokens)** during RAG prompt construction (`build_rag_prompt`). If retrieved data exceeds the budget, the system recursively truncates the longest text snippets by 20% to prevent prompt overflows.

### B. What does the Query Router do?
*   **Purpose**: It analyzes the user's input before any AI models are called. It extracts NEPSE stock symbols (e.g., matching "NABIL" or "Nabil Bank Limited" -> `NABIL`) and assigns the question to one of four retrieval routes (`vector_only`, `sql_graph`, `full_agent`, `compare`, or casual `chat`).
*   **Why a deterministic router instead of an LLM router?**
    - Using an LLM to decide the route takes **1.5 to 2 seconds** and consumes API tokens.
    - Our regex/keyword-based router determines the path in **under 1 millisecond** with **100% consistency**, ensuring zero routing latency.

### C. How are Model Responses Evaluated and how do you determine which is "Right"?
We evaluate our system across two primary dimensions:
1.  **Deterministic Route Verification & Quality Gate Scripts**:
    - **Off-Topic Deflection (`eval_negative.py`)**: Checks 18 queries (politics, weather, Everest, Tesla, Bitcoin) to verify the system rejects off-topic chats.
    - **News Integrity (`eval_news.py`)**: Validates news fetches for 5 symbols, confirming markdown stripping and ensuring Indian NHPC is blocked.
    - **Retrieval Diversity (`eval_retrieval.py`)**: Tests source file diversity across 10 queries, validating that cross-encoder reranking is active and functional.
2.  **RAGAS Quality Metrics (`eval_runner.py`)**:
    - Uses a gold dataset of 30 hand-crafted test questions (`test_questions.json`).
    - Uses Google AI (Gemini) as the LLM judge for evaluation.
    - **Faithfulness**: Evaluates whether the LLM's final answer is derived *only* from the retrieved context. (If the LLM outputs a price or number not found in the XML context block, its faithfulness score drops, signaling a hallucination).
    - **Answer Relevancy**: Checks if the response directly addresses the user's question, penalizing rambling.
    - **Context Precision**: Verifies that the retrieval tools successfully retrieved the actual information required to answer the query.
*   **How to determine which is "Right"?**
    - The ground truth is the database and scrapers.
    - We verify that the model's `<thinking>` block contains a **Chain-of-Verification (CoV)** where it lists every claim and marks it as `[VERIFIED: <source>]`. Any final response where the values match the XML data block and has zero external fabrications is determined to be a correct ("right") response.
    - RAGAS targets: Faithfulness > 0.8, Answer Relevancy > 0.7, Context Precision > 0.6.

---

## 3. Comprehensive Q&A Collection (Defence Preparation)

### Category A: Architecture & Tech Stack (Small Questions)

#### Q: Why not use a standard single-server setup? Why Daphne?
**A**: Daphne is an ASGI server. In a standard setup (like WSGI `runserver`), Server-Sent Events (SSE) stream tokens, holding the thread open and blocking other users. Daphne runs an asynchronous event loop, allowing thousands of users to stream answers concurrently.

#### Q: What is the database breakdown? Why do we have two databases?
**A**: We use **SQLite** locally for local state (user registration, login tokens, and saving chat history). We use **Neon PostgreSQL** in the cloud for massive tick/price/indicator data. Keeping them separate keeps our database operations light and protects the production database from local migration mistakes.

#### Q: How does the server connect to Neon PostgreSQL securely?
**A**: We connect read-only via a strict connection string. We use `psycopg2` directly instead of Django models. This guarantees our Django migrations (`makemigrations`) will never affect or alter the Neon DB structure.

#### Q: Why does the system calculate technical indicators in memory instead of database columns?
**A**: Indicators change with every daily close. Writing them continuously to a DB requires heavy cron-job scripts and wastes space. We fetch the raw 100-day OHLCV feed and compute EMA/RSI in-memory under **100ms** using Pandas and cache it for 15 minutes.

---

### Category B: RAG & AI Agent (Medium Questions)

#### Q: What does "Closed-Book" mode mean for your RAG model?
**A**: It means the LLM is explicitly instructed in the system prompt to ignore any pre-trained finance data and rely *only* on the text inside the `<context>` XML block. If a stat isn't in the context, it must say "Data not available".

#### Q: Explain the Graph RAG index. What relationships does it store?
**A**: It stores company-to-sector and peer relationships in a JSON property graph. It allows the system to identify banking peers (e.g. NABIL, NICA) immediately for financial comparisons without running expensive, imprecise semantic document chunk searches.

#### Q: How does the system handle a situation where the SQLite/Neon DB data is outdated?
**A**: If the last recorded price in the DB is older than 3 days (e.g. over a long holiday), `agent.py` triggers an automated web-search fallback. It queries ShareSansar or MeroLagani using DuckDuckGo, extracts the live Last Traded Price (LTP), overrides the DB close price, and displays a warning banner to the user.

#### Q: What does the Indian Source Blacklist do?
**A**: Several Indian companies share symbols with NEPSE tickers (e.g., NHPC is a major power company listed on both the Indian NSE and Nepal's NEPSE). The scraper blacklist filters out domains like `moneycontrol.com` or `economictimes.indiatimes.com` to prevent Indian stock data from polluting Nepalese company insights.

---

### Category C: Q&A / Defense Scenarios (Big Questions)

#### Q: If the user inputs "Should I buy NABIL stock?", how does the system respond?
**A**:
1. The **Query Router** identifies "buy" and "NABIL", routing it to `ROUTE_FULL_AGENT` with `symbol = NABIL`.
2. The agent runs **SQL**, **Graph**, **News**, and **Vector** tools concurrently.
3. The LLM synthesizes current price indicators, recent news sentiment, and peer reviews.
4. The system prompt forces a strict **DISCLAIMER: This is for educational purposes only. Not financial advice** at the end.

#### Q: How do you handle LLM rate limits or API outages during a live demo?
**A**: We use an automated **Fallback Chain**. If Groq fails with a `429` (rate limit) or connection timeout, the system immediately marks it as exhausted in cache and attempts the request on Gemini. If Gemini fails, it queries OpenRouter, and if all fails, it uses a local CPU-hosted Ollama model.

#### Q: How did you implement Conversational Memory in the SSE stream?
**A**: The backend retrieves the last 6 messages of the active `conversation_id` from the SQLite database. It passes them to the LLM as chat history. The system prompt contains rules that instruct the model to read these turns and avoid repeating previously stated metrics, indicators, or news headlines. Additionally, the frontend carries the `lastSymbol` as a context parameter `is_followup` to avoid repeating raw price charts in follow-up chat turns.

#### Q: Explain the Caching Architecture. What are the TTL parameters?
**A**: The caching layer uses Django's cache framework configured for switchable File-Based or Redis backends. The caching durations are optimized based on EOD (end-of-day) data profiles:
* **OHLCV Data** & **Technical Indicators**: Cached for **6 Hours** (TTLs match the system diagram) since Neon DB only records daily closing data. This reduces remote PostgreSQL server connection overheads.
* **News Results**: Cached for **30 Minutes** to capture intra-day market updates.
* **LLM Responses**: Cached for **1 Hour** matching MD5 hashes of `question` + `symbol` inputs to prevent duplicate API token consumption on identical queries.

#### Q: What is the Golden Prompt Matching System?
**A**: It is an optimization in `services/golden_matcher.py` that intercepts common user queries. Using a two-pass matching strategy (checking all explicit regular expression rules globally before falling back to sequence matcher ratios), it prevents false positive shadowing. A match triggers views to inject `<ideal_structure>` formatting guidelines into the LLM system prompts, ensuring clean, report-grade structure.

#### Q: How does the system evaluate relative price comparisons?
**A**: A temporal intent classifier detects comparative metrics (e.g. "N years ago" or "since YYYY") and routes the query to `ROUTE_FULL_AGENT` or `ROUTE_COMPARE`. The agent triggers `historical_tool` which fetches the exact close price from Neon at the historical date (with fallback to the latest DB records in case of non-trading day/data lag) and computes the exact relative change.
Our `eval_runner.py` suite includes automated checks (`historical_accuracy`, `historical_tool_routing`, and `no_advice_compliance`) alongside separate scripts (`eval_historical.py`, `eval_followup.py`, and `eval_golden.py`) to test this E2E.

#### Q: How does the composite stock screening and signal ranking work?
**A**: When the user requests a list of stocks matching a price range (e.g., "below 300") and indicates a ranking preference (e.g., "best buy", "profitable"), the Query Router directs the query to the `screener` route with `rank_by_signals=True`. In `db_service.py`, the system fetches live OHLCV data and calculates a composite signal score:
1. **RSI (40% weight)**: Oversold (<30) yields 1.0, while overbought (>70) yields 0.1.
2. **MACD (30% weight)**: Bullish crossovers and positive levels score up to 1.0.
3. **EMA-20 (30% weight)**: Price position relative to the 20-day exponential moving average measures short-term trend strength.
Stocks are sorted in descending order of their composite score and labeled with `🟢 Buy` (score >= 0.65), `🟡 Neutral` (score 0.40 - 0.64), or `🔴 Sell/Avoid` (score < 0.40).

#### Q: How do you handle educational questions where strict prose formatting is inappropriate?
**A**: Standard stock queries force the LLM to output "flowing prose with no bullet points or headers" to sound like a senior analyst. However, for educational queries (e.g., "explain RSI and MACD formulas"), this constraint is counterproductive.
We resolved this by making the prompting engine route-aware. For `vector_only` queries, the system prompt overrides the prose restriction and guides the LLM to use structured markdown (headers, numbered lists, bullet points, and formulas). Additionally, the system triggers `extended` retrieval, doubling the vector chunk limit to 1000 characters and fetching 6 passages (instead of 3) to provide a rich context base.

#### Q: How does the answer-focused collapsible frontend layout improve user experience?
**A**: For standard queries, the user wants the latest `PriceCard` and `SignalsTable` front and center. But for follow-ups (e.g., "what was its price a year ago?") or definitions (e.g., "explain RSI"), rendering a huge current price card at the top pushes the actual answers off the screen.
The frontend (`MessageBubble.jsx`) now uses an answer-focus heuristic. If the query is educational or comparative, the LLM text answer is displayed first with a vertical highlighted accent border. The current `PriceCard` and metrics are moved below into a collapsible "Current Market Data" container.


