# Agentic AI Chat with your Data Prototype

This project starts with a local TPC-H database and a simple CLI backend that asks an LLM to generate PostgreSQL SQL. Gemini is the default LLM provider, with Ollama still available for local runs.

DuckDB is used to generate the local TPC-H sample data. PostgreSQL is used as the target database for the first backend prototype.

## First CLI prototype

This assumes the local PostgreSQL database `agentic_ai` already exists and contains the TPC-H tables. The database setup commands are documented in `database/README.md`.

Install Python dependencies:

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

Replace the placeholder `GEMINI_API_KEY` value in `.env` with a real Gemini API key before making Gemini calls.

Run the prototype:

```bash
python main.py
```

Optional local configuration:

```bash
cp .env.example .env
```

Example questions:

```text
What is the total revenue?
What are the top 10 customers by revenue?
What is the revenue by nation?
How many orders are there by order status?
What is the monthly order volume?
```

The CLI LLM path only generates SQL. The backend validates that the SQL is a single `SELECT` statement against the allowed TPC-H tables. PostgreSQL then validates the query with `EXPLAIN`. Only after validation and `EXPLAIN` pass is the SQL executed.

## Run Streamlit frontend

This reuses the same backend modules as the CLI. PostgreSQL should already be running with the TPC-H data loaded. Gemini is used by default.

Install dependencies:

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

Replace the placeholder `GEMINI_API_KEY` value in `.env` with a real Gemini API key.

Run the Streamlit app:

```bash
streamlit run streamlit_app.py
```

Example questions:

```text
What is the total revenue?
What are the top 10 customers by revenue?
What is the revenue by nation?
How many orders are there by order status?
What is the monthly order volume?
```

The Streamlit frontend shows the user question, deterministic answer summary, result table, generated SQL, used tables, selected model, attempt count, fallback status, graph trace steps, and feedback buttons. Feedback is stored locally in `logs/feedback.csv`.

## Run LangGraph SQL agent workflow

The Streamlit frontend runs a LangGraph SQL workflow with explicit nodes for loading schema context, SQL generation, validation, execution, SQL repair, fallback model switching, and final answer generation.

The app first uses Gemini Flash Lite:

```text
LLM_PROVIDER=gemini
GEMINI_PRIMARY_MODEL=gemini-2.5-flash-lite
```

If the primary API call fails, returns invalid SQL, fails SQL validation, or fails PostgreSQL execution, the graph retries once with Gemini Flash:

```text
GEMINI_BACKUP_MODEL=gemini-2.5-flash
```

To use local Ollama instead, set `LLM_PROVIDER=ollama` and configure `OLLAMA_HOST`, `PRIMARY_MODEL`, and `FALLBACK_MODEL`.

Run the app:

```bash
streamlit run streamlit_app.py
```

Useful local environment variables:

```text
GEMINI_API_KEY=<your-gemini-api-key>
LLM_PROVIDER=gemini
GEMINI_PRIMARY_MODEL=gemini-2.5-flash-lite
GEMINI_BACKUP_MODEL=gemini-2.5-flash
LLM_TEMPERATURE=0
LLM_MAX_OUTPUT_TOKENS=1024
```

Every SQL generation attempt is logged to `logs/query_log.csv`. Streamlit feedback is logged to `logs/feedback.csv`.

The feedback controls support correction-driven reruns:

- `Good answer` and `Bad answer` save feedback only.
- `Retry with comment` sends the original question, previous SQL, previous answer, and your correction comment back through the LangGraph workflow.
- `Use fallback model` reruns the question with `FALLBACK_MODEL` immediately, optionally using your correction comment.

## Evaluation and logging

Run evaluation:

```bash
python evaluation/run_evaluation.py
```

View query logs:

```bash
cat logs/query_log.csv
```

View feedback logs:

```bash
cat logs/feedback.csv
```

`evaluation/golden_questions.yaml` contains predefined benchmark questions for the TPC-H dataset. `evaluation/run_evaluation.py` tests whether the prototype generates reasonable SQL by checking expected tables, expected SQL keywords, SQL validation, PostgreSQL `EXPLAIN`, and query execution.

`logs/query_log.csv` stores every processed question from Streamlit. `logs/feedback.csv` stores user feedback from the thumbs up/down buttons. These logs support traceability and manual validation while the prototype is still simple and local.

## Run with Docker Compose

The Docker setup runs Streamlit and PostgreSQL in Docker Compose. The app service reads `.env` through `env_file`, so replace the placeholder Gemini API key before asking questions.

Make sure TPC-H CSV exports exist:

```bash
source .venv/bin/activate
python database/export_tpch_to_csv.py
```

If you set `LLM_PROVIDER=ollama`, Ollama still runs on the host machine and the Dockerized app connects through `http://host.docker.internal:11434`.

Start Docker Compose:

```bash
docker compose up --build
```

If your Docker install only has the legacy Compose binary, use the same command with `docker-compose`:

```bash
docker-compose up --build
```

Open Streamlit:

```text
http://localhost:8501
```

Stop containers:

```bash
docker compose down
```

Reset the database completely:

```bash
docker compose down -v
```

Then start again:

```bash
docker compose up --build
```

Dockerized PostgreSQL is exposed on host port `5433`, mapped to container port `5432`. Inside Docker, the Streamlit app connects to PostgreSQL at `postgres:5432`.

Database initialization only runs when the `postgres_data` Docker volume is empty. If the CSV files in `database/exports/` change, reset the database with `docker compose down -v` before restarting so PostgreSQL reruns the initialization scripts.

Test the Dockerized PostgreSQL database from your host:

```bash
psql -h localhost -p 5433 -U postgres -d agentic_ai -c "SELECT COUNT(*) FROM lineitem;"
```

Password:

```text
postgres
```
