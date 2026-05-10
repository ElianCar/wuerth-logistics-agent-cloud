from app.answer_formatter import format_result_table
from app.llm_client import generate_sql
from app.prompt_builder import build_sql_generation_prompt
from app.query_executor import execute_sql, run_explain
from app.schema import get_schema_text
from app.semantic_layer import get_semantic_layer_text
from app.sql_validator import validate_sql


def process_question(question: str, schema_text: str, semantic_layer_text: str) -> None:
    prompt = build_sql_generation_prompt(
        question=question,
        schema_text=schema_text,
        semantic_layer_text=semantic_layer_text,
    )

    try:
        raw_sql = generate_sql(prompt)
    except RuntimeError as error:
        print()
        print(f"LLM error: {error}")
        return

    validation = validate_sql(raw_sql)

    print()
    print("Generated SQL:")
    print(validation.sql)
    print()
    print(f"Validation passed: {validation.is_valid}")
    print(f"Validation message: {validation.message}")

    if not validation.is_valid:
        print("Query failed: SQL did not pass local validation.")
        return

    try:
        run_explain(validation.sql)
    except RuntimeError as error:
        print()
        print(f"Query failed during PostgreSQL EXPLAIN: {error}")
        return

    try:
        columns, rows = execute_sql(validation.sql)
    except RuntimeError as error:
        print()
        print(f"Query failed during execution: {error}")
        return

    print()
    print("Result:")
    print(format_result_table(columns, rows))


def main() -> None:
    print("Agentic AI Chat with your Data - first CLI prototype")
    print("Type a question about the TPC-H PostgreSQL database. Type 'exit' or 'quit' to stop.")
    print()

    try:
        schema_text = get_schema_text()
        semantic_layer_text = get_semantic_layer_text()
    except Exception as error:
        print(f"Startup failed: {error}")
        return

    while True:
        try:
            question = input("Question> ").strip()
        except EOFError:
            print()
            print("Goodbye.")
            break

        if question.lower() in {"exit", "quit"}:
            print("Goodbye.")
            break

        if not question:
            continue

        process_question(question, schema_text, semantic_layer_text)
        print()


if __name__ == "__main__":
    main()
