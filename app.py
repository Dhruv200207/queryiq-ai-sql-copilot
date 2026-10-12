
import streamlit as st
import pandas as pd
import sqlglot
from sqlglot import exp
from datetime import datetime

from database import (
    create_database,
    get_schema,
    get_overview,
    run_query,
)

from sql_agent import (
    generate_sql,
    repair_sql,
    answer_sql_question,
    explain_results,
)


# ============================================================
# PAGE CONFIGURATION
# ============================================================

st.set_page_config(
    page_title="QueryIQ | AI SQL Copilot",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ============================================================
# CUSTOM CSS
# ============================================================

st.markdown(
    """
    <style>
        .stApp {
            background-color: #0b1120;
            color: #e5e7eb;
        }

        [data-testid="stSidebar"] {
            background-color: #111827;
        }

        .hero {
            padding: 24px;
            border-radius: 16px;
            background: linear-gradient(135deg, #172554, #312e81);
            border: 1px solid #3730a3;
            margin-bottom: 24px;
        }

        .hero h1 {
            color: white;
            margin-bottom: 8px;
        }

        .hero p {
            color: #c7d2fe;
            margin-bottom: 0;
        }

        div[data-testid="stMetric"] {
            background: #111827;
            border: 1px solid #263247;
            padding: 16px;
            border-radius: 12px;
        }

        div.stButton > button {
            border-radius: 8px;
        }

        .small-muted {
            color: #9ca3af;
            font-size: 13px;
        }
    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# SESSION STATE
# ============================================================

DEFAULTS = {
    "generated_sql": "",
    "query_result": None,
    "query_error": "",
    "query_history": [],
    "tutor_answer": "",
    "result_explanation": "",
    "last_executed_sql": "",
    "repair_message": "",
    "sql_prompt": "",
}

for key, value in DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = value


# ============================================================
# DATABASE INITIALIZATION
# ============================================================

@st.cache_resource
def initialize_database():
    return create_database()


def load_schema():
    schema = get_schema()

    if not schema:
        raise ValueError(
            "Database schema is empty. Check database.py."
        )

    return schema


try:
    with st.spinner("Initializing database..."):
        initialize_database()

    schema = load_schema()
    database_ready = True
    database_error = ""

except Exception as exc:
    database_ready = False
    database_error = str(exc)
    schema = ""


# ============================================================
# SQL VALIDATION
# ============================================================

def validate_read_only_sql(query):
    """
    Validate that the SQL contains one read-only query.
    Actual execution must also be protected by database.run_query().
    """

    if not query or not query.strip():
        raise ValueError("SQL query cannot be empty.")

    try:
        statements = sqlglot.parse(
            query.strip(),
            read="sqlite",
        )
    except Exception as exc:
        raise ValueError(
            f"Invalid SQL syntax: {exc}"
        ) from exc

    statements = [
        statement
        for statement in statements
        if statement is not None
    ]

    if len(statements) != 1:
        raise ValueError(
            "Only one SQL statement is allowed."
        )

    tree = statements[0]

    if not isinstance(tree, exp.Query):
        raise ValueError(
            "Only read-only SELECT queries are allowed."
        )

    forbidden = (
        exp.Insert,
        exp.Update,
        exp.Delete,
        exp.Drop,
        exp.Create,
        exp.Alter,
        exp.Command,
    )

    for node_type in forbidden:
        if tree.find(node_type):
            raise ValueError(
                "The query contains a prohibited SQL operation."
            )

    # Reject potentially unsafe functions and commands.
    sql_upper = query.upper()

    unsafe_keywords = [
        "ATTACH DATABASE",
        "DETACH DATABASE",
        "PRAGMA ",
        "VACUUM",
        "INTO OUTFILE",
        "LOAD_EXTENSION",
    ]

    for keyword in unsafe_keywords:
        if keyword in sql_upper:
            raise ValueError(
                f"Prohibited SQL operation: {keyword.strip()}"
            )

    return tree.sql(dialect="sqlite")


# ============================================================
# RESULT NORMALIZATION
# ============================================================

def normalize_result(result):
    """
    Support DataFrame results and common tuple/dictionary formats.
    """

    if isinstance(result, pd.DataFrame):
        return result

    if isinstance(result, tuple):
        # If a helper returns (dataframe, metadata), use the dataframe.
        for item in result:
            if isinstance(item, pd.DataFrame):
                return item

    if isinstance(result, dict):
        return pd.DataFrame(result)

    if result is None:
        return pd.DataFrame()

    try:
        return pd.DataFrame(result)
    except Exception as exc:
        raise ValueError(
            "Unexpected result returned by run_query(). "
            "Check its return format in database.py."
        ) from exc


# ============================================================
# QUERY EXECUTION
# ============================================================

def execute_sql(query, attempt_repair=True):
    """
    Validate, execute and optionally repair a failed SQL query.
    """

    st.session_state.query_error = ""
    st.session_state.repair_message = ""
    st.session_state.result_explanation = ""
    st.session_state.query_result = None

    try:
        safe_query = validate_read_only_sql(query)

        with st.spinner("Executing SQL query..."):
            raw_result = run_query(safe_query)

        dataframe = normalize_result(raw_result)

        st.session_state.query_result = dataframe
        st.session_state.last_executed_sql = safe_query

        st.session_state.query_history.insert(
            0,
            {
                "time": datetime.now().strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                "query": safe_query,
                "status": "Success",
                "rows": len(dataframe),
            },
        )

        st.session_state.query_history = (
            st.session_state.query_history[:50]
        )

        return True

    except Exception as first_error:
        error_text = str(first_error)

        # Automatically try to repair a failed AI-generated query.
        if attempt_repair and database_ready:
            try:
                with st.spinner(
                    "Query failed. AI is attempting to repair it..."
                ):
                    corrected_sql = repair_sql(
                        query,
                        error_text,
                        schema,
                    )

                corrected_sql = validate_read_only_sql(
                    corrected_sql
                )

                raw_result = run_query(corrected_sql)
                dataframe = normalize_result(raw_result)

                st.session_state.generated_sql = corrected_sql
                st.session_state.query_result = dataframe
                st.session_state.last_executed_sql = corrected_sql
                st.session_state.repair_message = (
                    "AI repaired the query successfully. "
                    "Review the corrected SQL below."
                )

                st.session_state.query_history.insert(
                    0,
                    {
                        "time": datetime.now().strftime(
                            "%Y-%m-%d %H:%M:%S"
                        ),
                        "query": corrected_sql,
                        "status": "Repaired",
                        "rows": len(dataframe),
                    },
                )

                st.session_state.query_history = (
                    st.session_state.query_history[:50]
                )

                return True

            except Exception as repair_error:
                st.session_state.query_error = (
                    f"Original error: {error_text}\n\n"
                    f"Repair attempt failed: {repair_error}"
                )

        else:
            st.session_state.query_error = error_text

        st.session_state.query_history.insert(
            0,
            {
                "time": datetime.now().strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                "query": query,
                "status": "Failed",
                "rows": 0,
            },
        )

        st.session_state.query_history = (
            st.session_state.query_history[:50]
        )

        return False


# ============================================================
# DISPLAY RESULTS AND CHARTS
# ============================================================

def display_results():
    result = st.session_state.query_result

    if result is None:
        return

    st.subheader("Query Results")

    if result.empty:
        st.info(
            "Query executed successfully, but no rows were returned."
        )
        return

    st.success(
        f"Query executed successfully — {len(result)} row(s) returned."
    )

    st.dataframe(
        result,
        use_container_width=True,
        hide_index=True,
    )

    csv_data = result.to_csv(index=False).encode("utf-8")

    st.download_button(
        label="Download Results as CSV",
        data=csv_data,
        file_name="queryiq_results.csv",
        mime="text/csv",
        key="download_query_results",
    )

    numeric_columns = result.select_dtypes(
        include="number"
    ).columns.tolist()

    if numeric_columns:
        st.subheader("Visualize Results")

        chart_col1, chart_col2 = st.columns(2)

        with chart_col1:
            selected_y = st.selectbox(
                "Numeric column",
                numeric_columns,
                key="chart_y_column",
            )

        with chart_col2:
            category_columns = [
                column
                for column in result.columns
                if column != selected_y
            ]

            selected_x = st.selectbox(
                "Group or category column",
                category_columns,
                key="chart_x_column",
            ) if category_columns else None

        if selected_x:
            try:
                chart_data = result[
                    [selected_x, selected_y]
                ].copy()

                chart_data[selected_y] = pd.to_numeric(
                    chart_data[selected_y],
                    errors="coerce",
                )

                chart_data = chart_data.dropna(
                    subset=[selected_y]
                )

                if not chart_data.empty:
                    chart_data = chart_data.set_index(
                        selected_x
                    )
                    st.bar_chart(chart_data[selected_y])

            except Exception as exc:
                st.warning(
                    f"Unable to create chart: {exc}"
                )


# ============================================================
# SIDEBAR NAVIGATION
# ============================================================

with st.sidebar:
    st.markdown("# 🤖 QueryIQ")
    st.caption("AI-Powered SQL Copilot")

    st.divider()

    page = st.radio(
        "Navigation",
        [
            "Overview",
            "AI SQL Generator",
            "AI SQL Tutor",
            "Query History",
            "Database Schema",
        ],
        key="navigation_page",
    )

    st.divider()

    if database_ready:
        st.success("Database connected")
    else:
        st.error("Database unavailable")

    st.caption("Powered by Groq + SQLite")


# ============================================================
# HEADER
# ============================================================

st.markdown(
    """
    <div class="hero">
        <h1>🤖 QueryIQ — AI SQL Copilot</h1>
        <p>
            Generate SQL using natural language, execute queries,
            understand results, and learn SQL step by step.
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)

if not database_ready:
    st.error(
        "Database initialization failed. "
        "Check the error below and fix database.py."
    )
    st.code(database_error)

    st.info(
        "The AI SQL Generator, query execution and schema viewer "
        "require a working database."
    )


# ============================================================
# PAGE 1: OVERVIEW
# ============================================================

if page == "Overview":
    st.header("Dashboard Overview")

    if not database_ready:
        st.warning(
            "Connect the database to display overview statistics."
        )

    else:
        try:
            overview = get_overview()

            if isinstance(overview, dict):
                overview_values = overview

            elif isinstance(overview, pd.DataFrame):
                overview_values = (
                    overview.iloc[0].to_dict()
                    if not overview.empty
                    else {}
                )

            else:
                overview_values = {}

            if overview_values:
                metric_items = list(overview_values.items())

                for start in range(0, len(metric_items), 4):
                    group = metric_items[start:start + 4]
                    columns = st.columns(len(group))

                    for column, (label, value) in zip(
                        columns, group
                    ):
                        with column:
                            if isinstance(value, (int, float)):
                                st.metric(
                                    str(label).replace("_", " ").title(),
                                    f"{value:,.2f}"
                                    if isinstance(value, float)
                                    else f"{value:,}",
                                )
                            else:
                                st.metric(
                                    str(label).replace("_", " ").title(),
                                    str(value),
                                )
            else:
                st.info(
                    "No overview metrics returned. "
                    "You can still generate and execute SQL."
                )

        except Exception as exc:
            st.warning(
                f"Could not load overview statistics: {exc}"
            )

    st.divider()

    st.subheader("Try these questions")

    overview_questions = [
        "Show the first 10 rows from the sales table.",
        "Show total sales.",
        "Show total profit.",
        "Show total sales by region.",
        "Find the top 5 products by sales.",
    ]

    for question in overview_questions:
        if st.button(
            question,
            key=f"overview_{question}",
            use_container_width=True,
            disabled=not database_ready,
        ):
            st.session_state.sql_prompt = question
            st.session_state.navigation_page = (
                "AI SQL Generator"
            )
            st.rerun()


# ============================================================
# PAGE 2: AI SQL GENERATOR
# ============================================================

elif page == "AI SQL Generator":
    st.header("⚡ AI SQL Generator")

    st.write(
        "Describe what you want to find in plain English. "
        "QueryIQ will generate SQLite SQL using your database schema."
    )

    suggestions = [
        "Show the first 10 rows from the sales table.",
        "Show total sales by region.",
        "Find the top 5 products by total sales.",
        "Show total profit by product category.",
        "Find customers with total sales greater than 1000.",
        "Show the number of orders in each region.",
        "Find products with negative total profit.",
    ]

    st.subheader("Example questions")

    suggestion_columns = st.columns(2)

    for index, question in enumerate(suggestions):
        with suggestion_columns[index % 2]:
            if st.button(
                question,
                key=f"generator_suggestion_{index}",
                use_container_width=True,
                disabled=not database_ready,
            ):
                st.session_state.sql_prompt = question

    with st.form("sql_generator_form"):
        user_prompt = st.text_area(
            "What do you want to know?",
            value=st.session_state.sql_prompt,
            placeholder=(
                "Example: Show the top 5 products by total sales."
            ),
            height=120,
        )

        generate_clicked = st.form_submit_button(
            "✨ Generate SQL",
            use_container_width=True,
            disabled=not database_ready,
        )

    if generate_clicked:
        if not user_prompt.strip():
            st.warning("Please enter a question.")

        else:
            try:
                with st.spinner("Generating SQL with AI..."):
                    generated = generate_sql(
                        user_prompt,
                        schema,
                    )

                # Validate before displaying it as a usable query.
                generated = validate_read_only_sql(generated)

                st.session_state.generated_sql = generated
                st.session_state.sql_prompt = user_prompt
                st.session_state.query_error = ""
                st.session_state.repair_message = ""

            except Exception as exc:
                st.session_state.query_error = (
                    f"SQL generation failed: {exc}"
                )

    if st.session_state.generated_sql:
        st.divider()
        st.subheader("Generated SQL")

        st.caption(
            "Review or edit the SQL before executing it."
        )

        with st.form("execute_sql_form"):
            edited_sql = st.text_area(
                "SQL Editor",
                value=st.session_state.generated_sql,
                height=220,
            )

            execute_clicked = st.form_submit_button(
                "▶ Execute SQL",
                use_container_width=True,
                disabled=not database_ready,
            )

        if execute_clicked:
            st.session_state.generated_sql = edited_sql

            execute_sql(
                edited_sql,
                attempt_repair=False,
            )

    if st.session_state.repair_message:
        st.success(st.session_state.repair_message)

        st.info(
            "The corrected query is now in the SQL editor. "
            "Review it before executing again."
        )

    if st.session_state.query_error:
        st.error(st.session_state.query_error)

        if st.button(
            "🛠️ Try AI SQL Repair",
            disabled=not database_ready
            or not st.session_state.generated_sql,
        ):
            try:
                fixed_sql = repair_sql(
                    st.session_state.generated_sql,
                    st.session_state.query_error,
                    schema,
                )

                fixed_sql = validate_read_only_sql(fixed_sql)

                st.session_state.generated_sql = fixed_sql
                st.session_state.query_error = ""
                st.session_state.repair_message = (
                    "A corrected query was generated. "
                    "Review it before executing."
                )

                st.rerun()

            except Exception as exc:
                st.error(f"Repair failed: {exc}")

    if st.session_state.query_result is not None:
        display_results()


# ============================================================
# PAGE 3: AI SQL TUTOR
# ============================================================

elif page == "AI SQL Tutor":
    st.header("🎓 AI SQL Tutor")

    st.write(
        "Ask questions about SQL syntax, joins, aggregation, "
        "filtering, or the tables in your database."
    )

    tutor_examples = [
        "Explain the difference between WHERE and HAVING.",
        "Explain GROUP BY with a simple example.",
        "What is the difference between INNER JOIN and LEFT JOIN?",
        "Explain COUNT, SUM and AVG.",
        "Explain the SQL query step by step.",
    ]

    st.subheader("Suggested topics")

    for index, question in enumerate(tutor_examples):
        if st.button(
            question,
            key=f"tutor_suggestion_{index}",
            use_container_width=True,
        ):
            st.session_state.tutor_question = question

    with st.form("tutor_form"):
        tutor_question = st.text_area(
            "Ask your SQL question",
            value=st.session_state.get(
                "tutor_question", ""
            ),
            placeholder=(
                "Example: Explain GROUP BY using my sales table."
            ),
            height=100,
        )

        tutor_submit = st.form_submit_button(
            "Ask AI Tutor",
            use_container_width=True,
        )

    if tutor_submit:
        if not tutor_question.strip():
            st.warning("Please enter a question.")

        else:
            try:
                with st.spinner("Preparing your explanation..."):
                    answer = answer_sql_question(
                        tutor_question,
                        schema if database_ready else (
                            "Database is currently unavailable."
                        ),
                    )

                st.session_state.tutor_answer = answer

            except Exception as exc:
                st.error(f"Tutor error: {exc}")

    if st.session_state.tutor_answer:
        st.subheader("Explanation")
        st.markdown(st.session_state.tutor_answer)


# ============================================================
# PAGE 4: QUERY HISTORY
# ============================================================

elif page == "Query History":
    st.header("🕘 Query History")

    history = st.session_state.query_history

    if not history:
        st.info(
            "No query history yet. Generate and execute a query first."
        )

    else:
        history_df = pd.DataFrame(history)

        st.dataframe(
            history_df,
            use_container_width=True,
            hide_index=True,
        )

        st.download_button(
            "Download Query History",
            data=history_df.to_csv(index=False).encode("utf-8"),
            file_name="queryiq_history.csv",
            mime="text/csv",
        )

        st.subheader("Inspect a previous query")

        selected_index = st.selectbox(
            "Select query",
            options=list(range(len(history))),
            format_func=lambda i: (
                f"{history[i]['time']} — "
                f"{history[i]['status']} — "
                f"{history[i]['query'][:65]}"
            ),
        )

        selected_item = history[selected_index]

        st.code(
            selected_item["query"],
            language="sql",
        )

        if st.button("Load into SQL Generator"):
            st.session_state.generated_sql = (
                selected_item["query"]
            )
            st.session_state.navigation_page = (
                "AI SQL Generator"
            )
            st.rerun()

        if st.button("Clear Query History"):
            st.session_state.query_history = []
            st.rerun()


# ============================================================
# PAGE 5: DATABASE SCHEMA
# ============================================================

elif page == "Database Schema":
    st.header("🗄️ Database Schema")

    if not database_ready:
        st.error(database_error)

    else:
        st.subheader("Available tables and columns")

        st.code(
            schema,
            language="text",
        )

        st.caption(
            "AI-generated queries must use only the tables "
            "and columns listed above."
        )

        if st.button("Refresh Schema"):
            try:
                schema = load_schema()
                st.success("Schema refreshed.")
                st.rerun()

            except Exception as exc:
                st.error(f"Schema refresh failed: {exc}")


# ============================================================
# FOOTER
# ============================================================

st.divider()

st.markdown(
    """
    <p class="small-muted">
        QueryIQ · AI SQL Copilot · SQLite + Groq + Streamlit
    </p>
    """,
    unsafe_allow_html=True,
)
