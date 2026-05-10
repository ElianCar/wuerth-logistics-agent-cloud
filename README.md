# Agentic AI Chat with your Data Prototype

This project starts with a local TPC-H database and a simple CLI backend that asks a local Ollama model to generate PostgreSQL SQL.

DuckDB is used to generate the local TPC-H sample data. PostgreSQL is used as the target database for the first backend prototype.

## First CLI prototype with local Ollama LLM

This assumes the local PostgreSQL database `agentic_ai` already exists and contains the TPC-H tables. The database setup commands are documented in `database/README.md`.

Install Python dependencies:

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

Install Ollama:

```bash
brew install ollama
```

Start Ollama:

```bash
ollama serve
```

Pull a small model:

```bash
ollama pull llama3.2:3b
```

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

The LLM only generates SQL. The backend validates that the SQL is a single `SELECT` statement against the allowed TPC-H tables. PostgreSQL then validates the query with `EXPLAIN`. Only after validation and `EXPLAIN` pass is the SQL executed.

This is intentionally not LangGraph yet. It is a simple first prototype for understanding the question-to-SQL loop before adding agent orchestration.

## Run Streamlit frontend

This reuses the same backend modules as the CLI. PostgreSQL should already be running with the TPC-H data loaded, and Ollama should have the configured local model available.

Install dependencies:

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

Start Ollama:

```bash
ollama serve
```

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

The Streamlit frontend shows the user question, deterministic answer summary, result table, generated SQL, used tables, validation status, and simple feedback buttons. Feedback is stored locally in `logs/feedback.csv`.

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

The Docker setup runs Streamlit and PostgreSQL in Docker Compose. Ollama still runs on the host machine. The Dockerized app connects to Ollama through `http://host.docker.internal:11434`.

Make sure TPC-H CSV exports exist:

```bash
source .venv/bin/activate
python database/export_tpch_to_csv.py
```

Start Ollama on the host machine:

```bash
ollama serve
```

Pull the local model if it is not already available:

```bash
ollama pull llama3.2:3b
```

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
