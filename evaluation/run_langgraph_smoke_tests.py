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
from src.llm.model_adapter import GeminiConfigurationError, gemini_api_key_is_placeholder, get_llm


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
        if model == "gemini-2.5-flash-lite":
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
    os.environ["DATA_SCENARIO"] = "demo"
    os.environ["LLM_PROVIDER"] = "gemini"
    os.environ["GEMINI_API_KEY"] = "key"
    os.environ["GEMINI_PRIMARY_MODEL"] = "gemini-2.5-flash-lite"
    os.environ["GEMINI_BACKUP_MODEL"] = "gemini-2.5-flash"
    os.environ.pop("MAX_PRIMARY_ATTEMPTS", None)

    assert SQLAgentConfig.from_provider("gemini").max_primary_attempts == 2

    assert gemini_api_key_is_placeholder() is True
    try:
        get_llm("gemini-2.5-flash-lite")
    except GeminiConfigurationError as error:
        assert "placeholder value 'key'" in str(error)
    else:
        raise AssertionError("Placeholder Gemini API key should stop model initialization.")

    with tempfile.TemporaryDirectory() as temp_dir:
        os.environ["LOG_DIR"] = temp_dir
        fake_sql_generator, calls = build_fake_sql_generator()
        config = SQLAgentConfig(
            primary_model="gemini-2.5-flash-lite",
            fallback_model="gemini-2.5-flash",
            max_primary_attempts=1,
            llm_provider="gemini",
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
        assert state["selected_model"] == "gemini-2.5-flash"
        assert state["total_attempts"] == 2
        assert [model for model, _prompt in calls] == [
            "gemini-2.5-flash-lite",
            "gemini-2.5-flash",
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

        same_model_config = SQLAgentConfig(
            primary_model="gemini-3.1-flash-lite-preview",
            fallback_model="gemini-3.1-flash-lite-preview",
            max_primary_attempts=1,
            llm_provider="gemini",
            ollama_host="http://localhost:11434",
        )
        same_model_calls: list[tuple[str, str]] = []

        def failing_same_model_generator(
            prompt: str,
            model: str,
            ollama_host: str,
            node_name: str,
        ) -> str:
            same_model_calls.append((model, prompt))
            return "DROP TABLE orders"

        same_model_state = run_sql_agent(
            "How many orders are there?",
            config=same_model_config,
            schema_loader=fake_schema_loader,
            sql_generator=failing_same_model_generator,
            sql_executor=fake_sql_executor,
            attempt_logger=log_query_attempt,
        )

        assert same_model_state["execution_success"] is False
        assert same_model_state["fallback_used"] is False
        assert same_model_state["selected_model"] == "gemini-3.1-flash-lite-preview"
        assert same_model_state["total_attempts"] == 1
        assert [model for model, _prompt in same_model_calls] == [
            "gemini-3.1-flash-lite-preview",
        ]

        query_log_path = Path(temp_dir) / "query_log.csv"
        rows = read_csv_rows(query_log_path)
        assert len(rows) == 5
        assert rows[0]["primary_model"] == "gemini-2.5-flash-lite"
        assert rows[0]["backup_model"] == "gemini-2.5-flash"
        assert rows[0]["model_used"] == "gemini-2.5-flash-lite"
        assert rows[0]["success"] == "false"
        assert rows[1]["model_used"] == "gemini-2.5-flash"
        assert rows[1]["execution_success"] == "true"
        assert rows[2]["run_id"] == state["run_id"]
        assert rows[2]["question"] == "How many orders are there?"
        assert rows[2]["final_sql"] == state["final_sql"]
        assert rows[2]["validation_success"] == "true"
        assert rows[2]["execution_success"] == "true"
        assert rows[2]["answer_preview"]
        assert rows[3]["primary_model"] == "gemini-3.1-flash-lite-preview"
        assert rows[3]["backup_model"] == "gemini-3.1-flash-lite-preview"
        assert rows[3]["model_used"] == "gemini-3.1-flash-lite-preview"
        assert rows[3]["success"] == "false"
        assert rows[4]["run_id"] == same_model_state["run_id"]
        assert rows[4]["execution_success"] == "false"

        rows_before_silent_run = len(rows)
        silent_state = run_sql_agent(
            "How many orders are there?",
            config=config,
            run_context="golden_test",
            use_approved_memory=False,
            enable_memory_candidate_generation=False,
            log_to_query_log=False,
            schema_loader=fake_schema_loader,
            sql_generator=lambda _prompt, _model, _host, _node: "SELECT COUNT(*) AS order_count FROM orders",
            sql_executor=fake_sql_executor,
        )

        assert silent_state["execution_success"] is True
        assert silent_state["run_context"] == "golden_test"
        assert silent_state["use_approved_memory"] is False
        assert silent_state["enable_memory_candidate_generation"] is False
        assert len(read_csv_rows(query_log_path)) == rows_before_silent_run

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
