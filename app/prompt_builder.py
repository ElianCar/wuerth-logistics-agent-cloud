def build_sql_generation_prompt(
    question: str,
    schema_text: str,
    semantic_layer_text: str,
) -> str:
    return f"""You are a PostgreSQL SQL generator.

Return only SQL.
Do not explain.
Do not include markdown code fences.
Use only the provided tables and columns.
Generate only SELECT queries.
Do not use INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, TRUNCATE, COPY, GRANT, or REVOKE.
Prefer explicit JOIN syntax.
Add LIMIT 50 unless the user asks for aggregation only or asks for a specific limit.
Use the semantic layer for business meaning.
For revenue, use SUM(l_extendedprice * (1 - l_discount)) unless otherwise stated.

Database schema:
{schema_text}

Semantic layer:
{semantic_layer_text}

User question:
{question}
"""
