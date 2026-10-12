
import os
import re

from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage

load_dotenv(override=True)

MODEL_NAME = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")


def get_llm():
    """Create the Groq chat model."""
    api_key = os.getenv("GROQ_API_KEY")

    if not api_key:
        raise ValueError(
            "GROQ_API_KEY is missing. Check your .env file."
        )

    return ChatGroq(
        model=MODEL_NAME,
        api_key=api_key,
        temperature=0
    )


def ask_model(prompt, system_prompt=None):
    """Send a prompt to Groq and return the text response."""
    llm = get_llm()

    messages = []

    if system_prompt:
        messages.append(SystemMessage(content=system_prompt))

    messages.append(HumanMessage(content=prompt))

    response = llm.invoke(messages)
    content = response.content

    if isinstance(content, str):
        return content.strip()

    # Handle models that return content as a list of blocks.
    if isinstance(content, list):
        text_parts = []

        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text_parts.append(item.get("text", ""))

        return "\n".join(text_parts).strip()

    return str(content).strip()


def clean_sql(response):
    """Remove Markdown fences and extract the SQL query."""
    if not response:
        raise ValueError("The AI returned an empty response.")

    sql = response.strip()

    # Remove ```sql ... ``` formatting.
    sql = re.sub(
        r"^\s*```(?:sql)?\s*",
        "",
        sql,
        flags=re.IGNORECASE
    )
    sql = re.sub(r"\s*```\s*$", "", sql)

    # Remove a leading SQL: label.
    sql = re.sub(r"^\s*SQL\s*:\s*", "", sql, flags=re.IGNORECASE)

    sql = sql.strip()

    if sql.upper().startswith("SCHEMA_ERROR:"):
        raise ValueError(sql)

    if not re.match(r"^(SELECT|WITH)\b", sql, flags=re.IGNORECASE):
        raise ValueError(
            "The AI did not return a valid SELECT query. "
            f"Response received: {sql[:300]}"
        )

    return sql


def generate_sql(prompt, schema):
    """Generate a read-only SQLite query using the supplied schema."""
    if not prompt or not prompt.strip():
        raise ValueError("Please enter a question for SQL generation.")

    if not schema:
        raise ValueError(
            "Database schema is empty. Initialize the database first."
        )

    system_prompt = f"""
You are QueryIQ, an expert SQLite SQL generator.

Use ONLY the tables and columns listed in this database schema.

DATABASE SCHEMA:
{schema}

RULES:
1. Generate SQLite-compatible SQL.
2. Use the exact table and column names from the schema.
3. Never invent a column, table, relationship, or value.
4. Generate one read-only SELECT query.
5. A WITH clause is allowed only when it leads to a SELECT.
6. Never generate INSERT, UPDATE, DELETE, DROP, ALTER, CREATE,
   REPLACE, ATTACH, DETACH, or other data-changing statements.
7. For totals, use SUM() where appropriate.
8. For averages, use AVG() where appropriate.
9. For counts, use COUNT() where appropriate.
10. For top-N requests, use ORDER BY and LIMIT.
11. Use GROUP BY when aggregating by categories.
12. Use clear aliases such as total_sales or total_profit.
13. Use valid SQLite date functions only when date columns exist.
14. Do not use MySQL, PostgreSQL, or SQL Server-specific syntax.
15. Return SQL only, without Markdown fences or explanations.
16. If a requested column or table is missing from the schema,
    return SCHEMA_ERROR: followed by a short explanation.
"""

    response = ask_model(
        prompt=(
            "Generate a SQLite query for this request:\n"
            f"{prompt.strip()}"
        ),
        system_prompt=system_prompt
    )

    return clean_sql(response)


def repair_sql(query, error_message, schema):
    """Attempt to correct a failed SQL query."""
    system_prompt = f"""
You are an expert SQLite SQL debugger.

DATABASE SCHEMA:
{schema}

Rules:
- Fix the SQL using only the supplied schema.
- Return exactly one read-only SELECT query.
- Do not invent columns or tables.
- Do not use non-SQLite syntax.
- Do not change data or database structure.
- Return SQL only, without Markdown fences or explanations.
- If the requested operation cannot be performed with this schema,
  return SCHEMA_ERROR: followed by a short explanation.
"""

    prompt = f"""
The following SQLite query failed.

QUERY:
{query}

ERROR:
{error_message}

Correct the query so it runs against the provided schema.
"""

    response = ask_model(prompt, system_prompt)
    return clean_sql(response)


def answer_sql_question(question, schema):
    """Explain how to approach a SQL question in beginner-friendly terms."""
    system_prompt = f"""
You are QueryIQ, a friendly SQL tutor.

Database schema:
{schema}

Explain SQL concepts in simple English.
Use the actual database schema when giving examples.
If you provide a query, it must be read-only SQLite SQL.
Do not invent tables or columns.
"""

    return ask_model(question, system_prompt)


def explain_results(query, result_dataframe, schema):
    """Explain query results in plain English."""
    if result_dataframe is None:
        raise ValueError("No query result was provided.")

    if result_dataframe.empty:
        return (
            "The query ran successfully, but it returned no rows. "
            "Check your filters or the values present in the database."
        )

    preview = result_dataframe.head(10).to_string(index=False)

    system_prompt = f"""
You are QueryIQ, a data analyst.

Use the database schema and query results provided below.
Explain the findings in simple English.
Only make claims supported by the displayed results.
Do not invent numbers or facts.
Mention that the displayed result is a preview if it contains only
a subset of the complete result.
"""

    prompt = f"""
DATABASE SCHEMA:
{schema}

SQL QUERY:
{query}

RESULT ROW COUNT:
{len(result_dataframe)}

RESULT COLUMNS:
{list(result_dataframe.columns)}

RESULT PREVIEW:
{preview}

Explain what these results show.
"""

    return ask_model(prompt, system_prompt)
