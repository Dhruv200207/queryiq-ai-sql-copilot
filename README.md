# QueryIQ — AI SQL Copilot

An AI-powered SQL assistant built with Python and Streamlit that helps users generate SQL queries from natural language, execute queries, understand SQL concepts, and explore database results.

## 🚀 Live Demo

**Try QueryIQ here:** [Open Live App] :https://queryiq-ai-sql-copilot-q7fr5j4vxtj2nu5kas8okh.streamlit.app/

## 📌 Project Overview

QueryIQ is an AI-powered application designed to simplify SQL querying and database exploration. It uses a Large Language Model (LLM) to convert natural-language questions into SQL queries and help users understand query logic and results.

The application combines AI capabilities with a SQLite database to provide an interactive SQL learning and analysis experience.

## ✨ Features

- **AI SQL Generator:** Convert natural-language questions into SQL queries.
- **Query Execution:** Execute supported SQL queries against a SQLite database.
- **AI SQL Tutor:** Get explanations of SQL concepts and query logic.
- **SQL Error Assistance:** Help identify and repair SQL query errors.
- **Database Schema Explorer:** View database tables, columns, and schema information.
- **Query History:** Review previous queries.
- **Data Visualization:** Explore query results using charts where supported.
- **CSV Export:** Download query results for further analysis.
- **Interactive Dashboard:** Explore database information through a Streamlit interface.

## 🛠️ Tech Stack

- **Language:** Python
- **Frontend:** Streamlit
- **Database:** SQLite
- **AI/LLM:** Groq API
- **LLM Integration:** LangChain
- **Data Processing:** Pandas
- **SQL Parsing and Validation:** SQLGlot
- **Configuration:** Python dotenv

## 🏗️ Project Structure

```text
queryiq-ai-sql-copilot/
├── app.py
├── database.py
├── sql_agent.py
├── requirements.txt
├── .gitignore
└── README.md
```

## ⚙️ Run Locally

### 1. Clone the repository

```bash
git clone https://github.com/Dhruv200207/queryiq-ai-sql-copilot.git
cd queryiq-ai-sql-copilot
```

### 2. Create a virtual environment

```bash
python -m venv venv
```

Activate it on Windows:

```bash
venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure your API key

Create a `.env` file in the project root:

```env
GROQ_API_KEY=your_groq_api_key
GROQ_MODEL=openai/gpt-oss-20b
```

Replace the placeholder with your own Groq API key. Never commit your `.env` file or publish API keys.

### 5. Run the application

```bash
streamlit run app.py
```

The application will open in your browser.

## 🔐 Security

- Store API keys in environment variables or Streamlit Secrets.
- Never commit `.env` files or expose API keys in source code.
- Use appropriate query validation and database access controls when executing SQL.

## 🎯 Learning Outcomes

This project demonstrates practical experience with:

- Integrating LLM APIs into Python applications.
- Building interactive applications using Streamlit.
- Connecting AI workflows with relational databases.
- Generating and validating SQL queries.
- Handling query execution and database schema information.
- Managing Python dependencies and deploying an application.

## 👨‍💻 Author

**Dhruv Ajay Sharma**

GitHub: [Dhruv200207](https://github.com/Dhruv200207)

---

*Built as a hands-on project exploring Generative AI, Python, SQL, and database automation.*