
import re
import sqlite3
from io import BytesIO
from pathlib import Path
from urllib.request import Request, urlopen

import pandas as pd
import sqlglot
from sqlglot import exp


# =========================================================
# CONFIGURATION
# =========================================================

DB_NAME = "queryiq_online.db"
TABLE_NAME = "sales"

MAX_ROWS = 100
QUERY_TIMEOUT_SECONDS = 10

CSV_URL = (
    "https://raw.githubusercontent.com/"
    "curran/data/gh-pages/superstoreSales/"
    "superstoreSales.csv"
)


# =========================================================
# DOWNLOAD ONLINE DATA
# =========================================================

def download_sales_data():
    """Download the online Superstore CSV and load it into pandas."""

    request = Request(
        CSV_URL,
        headers={
            "User-Agent": "Mozilla/5.0 QueryIQ/1.0"
        },
    )

    try:
        with urlopen(request, timeout=30) as response:
            content = response.read()

        if not content:
            raise RuntimeError("The downloaded CSV file is empty.")

        # Try multiple encodings to handle special characters.
        df = None
        encoding_used = None

        for encoding in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                df = pd.read_csv(
                    BytesIO(content),
                    encoding=encoding,
                    low_memory=False,
                )
                encoding_used = encoding
                break
            except UnicodeDecodeError:
                continue

        if df is None or df.empty:
            raise RuntimeError(
                "Could not read the CSV or the dataset is empty."
            )

        print(f"CSV downloaded successfully using {encoding_used}.")

        return df

    except Exception as exc:
        raise RuntimeError(
            f"Could not download/read the online CSV. "
            f"Check the URL and internet connection. Details: {exc}"
        ) from exc


# =========================================================
# CLEAN AND STANDARDIZE DATA
# =========================================================

def clean_sales_data(df):
    """Standardize column names and validate required columns."""

    df = df.copy()

    # Convert column names to lowercase snake_case.
    df.columns = [
        re.sub(
            r"_+",
            "_",
            re.sub(
                r"[^a-zA-Z0-9]+",
                "_",
                str(column).strip().lower(),
            ),
        ).strip("_")
        for column in df.columns
    ]

    # Support common alternative column names.
    aliases = {
        "order_id": [
            "order_id",
            "orderid",
        ],
        "order_date": [
            "order_date",
            "date",
        ],
        "customer_id": [
            "customer_id",
            "customerid",
        ],
        "customer_name": [
            "customer_name",
            "customer",
            "customername",
        ],
        "product_id": [
            "product_id",
            "productid",
        ],
        "product_name": [
            "product_name",
            "product",
            "productname",
        ],
        "sales": [
            "sales",
            "revenue",
            "amount",
        ],
        "profit": [
            "profit",
            "net_profit",
        ],
        "quantity": [
            "quantity",
            "qty",
        ],
        "discount": [
            "discount",
        ],
        "region": [
            "region",
        ],
        "category": [
            "category",
        ],
        "sub_category": [
            "sub_category",
            "subcategory",
        ],
        "segment": [
            "segment",
        ],
        "city": [
            "city",
        ],
        "state": [
            "state",
        ],
    }

    rename_map = {}

    for standard_name, alternatives in aliases.items():
        for column in df.columns:
            if column in alternatives:
                rename_map[column] = standard_name
                break

    df = df.rename(columns=rename_map)

    required_columns = [
        "order_id",
        "customer_name",
        "product_name",
        "sales",
        "profit",
    ]

    missing_columns = [
        column
        for column in required_columns
        if column not in df.columns
    ]

    if missing_columns:
        raise ValueError(
            f"The downloaded CSV does not contain the required "
            f"columns: {missing_columns}. "
            f"Available columns: {list(df.columns)}"
        )

    # Convert numeric columns safely.
    numeric_columns = [
        "sales",
        "profit",
        "quantity",
        "discount",
    ]

    for column in numeric_columns:
        if column in df.columns:
            df[column] = pd.to_numeric(
                df[column],
                errors="coerce",
            )

    # Remove rows without essential values.
    df = df.dropna(
        subset=[
            "order_id",
            "customer_name",
            "product_name",
            "sales",
            "profit",
        ]
    )

    if df.empty:
        raise ValueError(
            "No valid records remained after cleaning the dataset."
        )

    # Store date fields in a consistent readable format.
    for column in ["order_date", "ship_date"]:
        if column in df.columns:
            df[column] = pd.to_datetime(
                df[column],
                errors="coerce",
            ).dt.strftime("%Y-%m-%d")

    # Replace pandas missing values with SQLite-friendly values.
    df = df.astype(object).where(pd.notna(df), None)

    return df


# =========================================================
# DATABASE CONNECTION
# =========================================================

def get_connection(read_only=False):
    """Create a connection to the SQLite database."""

    db_path = Path(DB_NAME).resolve()

    if read_only:
        if not db_path.exists():
            raise FileNotFoundError(
                f"Database not found: {db_path}. "
                "Run create_database() first."
            )

        connection = sqlite3.connect(
            db_path.as_uri() + "?mode=ro",
            uri=True,
            timeout=5,
        )
    else:
        connection = sqlite3.connect(
            str(db_path),
            timeout=5,
        )

    return connection


# =========================================================
# CREATE DATABASE
# =========================================================

def create_database(force_reload=False):
    """
    Create the SQLite database from the online dataset.

    Set force_reload=True to download the dataset again.
    """

    db_path = Path(DB_NAME)

    if db_path.exists() and not force_reload:
        try:
            with get_connection(read_only=True) as connection:
                table = connection.execute(
                    """
                    SELECT name
                    FROM sqlite_master
                    WHERE type = 'table' AND name = ?
                    """,
                    (TABLE_NAME,),
                ).fetchone()

                if table:
                    count = connection.execute(
                        f'SELECT COUNT(*) FROM "{TABLE_NAME}"'
                    ).fetchone()[0]

                    if count > 0:
                        print(
                            f"Database already exists with {count} rows."
                        )
                        return
        except sqlite3.Error:
            pass

    print("Downloading online sales dataset...")

    raw_df = download_sales_data()
    df = clean_sales_data(raw_df)

    with get_connection(read_only=False) as connection:
        df.to_sql(
            TABLE_NAME,
            connection,
            if_exists="replace",
            index=False,
        )

        # Create indexes to improve common lookup performance.
        existing_columns = set(df.columns)

        for column in [
            "customer_name",
            "product_name",
            "region",
            "order_id",
        ]:
            if column in existing_columns:
                connection.execute(
                    f'CREATE INDEX IF NOT EXISTS '
                    f'"idx_{column}" ON "{TABLE_NAME}" ("{column}")'
                )

        connection.commit()

    print("Database created successfully!")
    print(f"Database file: {db_path.resolve()}")
    print(f"Table name: {TABLE_NAME}")
    print(f"Total rows: {len(df)}")
    print(f"Columns: {list(df.columns)}")


# =========================================================
# GET DATABASE SCHEMA
# =========================================================

def get_schema():
    """Return the database schema as readable text."""

    if not Path(DB_NAME).exists():
        create_database()

    with get_connection(read_only=True) as connection:
        tables = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        ).fetchall()

        schema_parts = []

        for (table_name,) in tables:
            columns = connection.execute(
                f'PRAGMA table_info("{table_name}")'
            ).fetchall()

            schema_parts.append(f"Table: {table_name}")

            for column in columns:
                column_name = column[1]
                column_type = column[2] or "TEXT"

                schema_parts.append(
                    f"  - {column_name}: {column_type}"
                )

            schema_parts.append("")

        return "\n".join(schema_parts)


# =========================================================
# VALIDATE SQL
# =========================================================

def validate_sql(query):
    """
    Allow only a single read-only SQL query.

    Returns True for valid queries.
    Raises ValueError for invalid or unsafe SQL.
    """

    if not isinstance(query, str) or not query.strip():
        raise ValueError("Please enter a SQL query.")

    query = query.strip()

    try:
        statements = sqlglot.parse(
            query,
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
            "Only one SQL query can be executed at a time."
        )

    statement = statements[0]

    if not isinstance(statement, exp.Query):
        raise ValueError(
            "Only read-only SELECT queries are allowed."
        )

    # Explicitly block write or administrative operations.
    forbidden_types = (
        exp.Insert,
        exp.Update,
        exp.Delete,
        exp.Create,
        exp.Drop,
        exp.Alter,
        exp.Command,
    )

    if any(
        isinstance(node, forbidden_types)
        for node in statement.walk()
    ):
        raise ValueError(
            "This query contains a prohibited SQL operation."
        )

    # Reject SELECT INTO, which can create a table in some dialects.
    if any(
        isinstance(node, exp.Into)
        for node in statement.walk()
    ):
        raise ValueError(
            "SELECT INTO is not allowed."
        )

    return True


# =========================================================
# EXECUTE SQL QUERY
# =========================================================

def run_query(query):
    """Execute a validated SELECT query and return a DataFrame."""

    if not Path(DB_NAME).exists():
        create_database()

    validate_sql(query)

    # Remove a trailing semicolon before wrapping the query.
    clean_query = query.strip().rstrip(";").strip()

    # Cap returned rows to keep the Streamlit UI responsive.
    limited_query = (
        f"SELECT * FROM ({clean_query}) AS queryiq_result "
        f"LIMIT {MAX_ROWS}"
    )

    connection = get_connection(read_only=True)

    try:
        # Stop unexpectedly expensive queries after the time limit.
        connection.set_progress_handler(
            lambda: 1,
            QUERY_TIMEOUT_SECONDS * 10000,
        )

        result = pd.read_sql_query(
            limited_query,
            connection,
        )

        return result

    except sqlite3.OperationalError as exc:
        if "interrupted" in str(exc).lower():
            raise RuntimeError(
                f"Query exceeded the {QUERY_TIMEOUT_SECONDS}-second "
                "execution limit. Try a simpler query."
            ) from exc

        raise

    finally:
        connection.close()


# =========================================================
# OVERVIEW METRICS
# =========================================================

def get_overview():
    """Return key metrics for the Streamlit dashboard."""

    if not Path(DB_NAME).exists():
        create_database()

    with get_connection(read_only=True) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                """
            ).fetchall()
        }

        if TABLE_NAME not in tables:
            raise RuntimeError(
                f"Table '{TABLE_NAME}' does not exist."
            )

        columns = {
            row[1]
            for row in connection.execute(
                f'PRAGMA table_info("{TABLE_NAME}")'
            ).fetchall()
        }

        customers = 0
        products = 0
        revenue = 0.0

        if "customer_name" in columns:
            customers = connection.execute(
                f"""
                SELECT COUNT(DISTINCT customer_name)
                FROM "{TABLE_NAME}"
                """
            ).fetchone()[0]

        if "product_name" in columns:
            products = connection.execute(
                f"""
                SELECT COUNT(DISTINCT product_name)
                FROM "{TABLE_NAME}"
                """
            ).fetchone()[0]

        if "sales" in columns:
            revenue = connection.execute(
                f"""
                SELECT COALESCE(SUM(sales), 0)
                FROM "{TABLE_NAME}"
                """
            ).fetchone()[0]

        total_rows = connection.execute(
            f'SELECT COUNT(*) FROM "{TABLE_NAME}"'
        ).fetchone()[0]

    return {
        "customers": customers,
        "sales": total_rows,
        "revenue": float(revenue or 0),
        "products": products,
    }


# =========================================================
# TEST DATABASE
# =========================================================

if __name__ == "__main__":
    try:
        # Force a fresh download when you run this file directly.
        create_database(force_reload=True)

        print("\nDATABASE SCHEMA")
        print("-" * 40)
        print(get_schema())

        print("\nDASHBOARD OVERVIEW")
        print("-" * 40)
        print(get_overview())

        print("\nSAMPLE QUERY")
        print("-" * 40)

        sample_result = run_query(
            "SELECT * FROM sales LIMIT 5"
        )

        print(sample_result.to_string(index=False))

    except Exception as exc:
        print("\nDATABASE INITIALIZATION FAILED")
        print(str(exc))
