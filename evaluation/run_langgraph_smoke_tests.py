from pathlib import Path
import csv
import os
import sys
import tempfile


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agent.langgraph_sql_agent import SQLAgentConfig, run_sql_agent
from src.agent.logging_utils import log_query_attempt
from src.agent.sql_validator import validate_generated_sql


def fake_schema_loader() -> str:
    return """PostgreSQL schema:
Table: orders
  - o_orderkey: integer
  - o_totalprice: numeric

Semantic layer:
order_volume:
  sql: COUNT(*) FROM orders
"""


def build_fake_sql_generator():
    calls: list[tuple[str, str]] = []

    def fake_sql_generator(prompt: str, model: str, ollama_host: str, node_name: str) -> str:
        calls.append((model, prompt))
        if model == "llama3.2:3b":
            return "DROP TABLE orders"
        return "SELECT COUNT(*) AS order_count FROM orders"

    return fake_sql_generator, calls


def fake_sql_executor(sql: str, user_question: str) -> dict:
    if not sql.lower().startswith("select"):
        raise RuntimeError("executor received non-read-only SQL")
    return {
        "columns": ["order_count"],
        "rows": [(42,)],
        "row_count": 1,
        "executed_sql": sql,
        "limit_applied": False,
    }


def read_csv_rows(path: Path) -> list[dict]:
    with path.open("r", newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def main() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        os.environ["LOG_DIR"] = temp_dir
        fake_sql_generator, calls = build_fake_sql_generator()
        config = SQLAgentConfig(
            primary_model="llama3.2:3b",
            fallback_model="qwen2.5-coder:7b",
            max_primary_attempts=2,
            ollama_host="http://localhost:11434",
        )

        state = run_sql_agent(
            "How many orders are there?",
            config=config,
            schema_loader=fake_schema_loader,
            sql_generator=fake_sql_generator,
            sql_executor=fake_sql_executor,
            attempt_logger=log_query_attempt,
        )

        assert state["execution_success"] is True
        assert state["fallback_used"] is True
        assert state["selected_model"] == "qwen2.5-coder:7b"
        assert state["total_attempts"] == 3
        assert [model for model, _prompt in calls] == [
            "llama3.2:3b",
            "llama3.2:3b",
            "qwen2.5-coder:7b",
        ]

        readonly_validation = validate_generated_sql(
            state["generated_sql"],
            fake_schema_loader(),
        )
        assert readonly_validation.is_valid is True

        destructive_validation = validate_generated_sql(
            "DELETE FROM orders",
            fake_schema_loader(),
        )
        assert destructive_validation.is_valid is False

        query_log_path = Path(temp_dir) / "query_log.csv"
        rows = read_csv_rows(query_log_path)
        assert len(rows) == 3
        assert rows[0]["selected_model"] == "llama3.2:3b"
        assert rows[1]["attempt_number"] == "2"
        assert rows[2]["selected_model"] == "qwen2.5-coder:7b"
        assert rows[2]["execution_success"] == "true"

        correction_calls: list[tuple[str, str]] = []

        def correction_sql_generator(
            prompt: str,
            model: str,
            ollama_host: str,
            node_name: str,
        ) -> str:
            correction_calls.append((model, prompt))
            return "SELECT AVG(o_totalprice) AS average_order_value FROM orders"

        corrected_state = run_sql_agent(
            "How many orders are there?",
            config=config,
            previous_failed_sql="SELECT COUNT(*) AS order_count FROM orders",
            previous_final_answer="The answer is 42.",
            previous_sql_error="User said the previous answer did not match their intent.",
            user_correction="No, I meant average order value, not order count.",
            schema_loader=fake_schema_loader,
            sql_generator=correction_sql_generator,
            sql_executor=fake_sql_executor,
            attempt_logger=log_query_attempt,
        )

        assert corrected_state["execution_success"] is True
        assert corrected_state["fallback_used"] is False
        assert correction_calls
        correction_prompt = correction_calls[0][1]
        assert "No, I meant average order value, not order count." in correction_prompt
        assert "SELECT COUNT(*) AS order_count FROM orders" in correction_prompt
        assert "The answer is 42." in correction_prompt

    print("LangGraph smoke tests passed.")


if __name__ == "__main__":
    main()
