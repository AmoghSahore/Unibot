# Text-to-SQL University Chatbot

## Overview

This project is a Streamlit chatbot for querying a local MySQL university database using natural language. A user asks a question in English, Groq converts it to a SQL `SELECT` query, the app validates and executes the query, and the assistant returns a plain-English answer.

## Architecture

```text
User
-> Streamlit
-> Groq (English -> SQL)
-> SQL Validation
-> MySQL
-> Groq or local formatter (Results -> English)
-> User
```

## Features

- Natural language querying over a university management database.
- Groq-powered English-to-SQL generation.
- MySQL query execution with pandas result handling.
- Natural-language answers shown by default.
- Developer Mode for generated SQL, raw results, status, and CSV downloads.
- Session and persistent chat history via `chat_history.json`.
- Audit logging via `audit_log.jsonl`.
- Local LLM response cache via `llm_cache.json` to reduce repeated Groq calls during testing.
- Bounded retry/backoff for Groq rate limits and transient failures.
- SQL validation that only allows `SELECT` statements.
- Sidebar with database schema, suggested questions, security notes, and privacy notes.

## Project Structure

```text
.
├── app.py
├── db.py
├── llm.py
├── validator.py
├── prompts.py
├── config.py
├── requirements.txt
├── README.md
├── .env.example
└── sql/
    └── schema.sql
```

## Setup

1. Create and activate a virtual environment:

```bash
python -m venv .venv
.venv\Scripts\activate
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Create a `.env` file from `.env.example` and fill in your values:

```env
GROQ_API_KEY=your_groq_api_key
GROQ_MODEL=llama-3.1-8b-instant
USE_LLM_FOR_RESULT_SUMMARY=True
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=your_mysql_password
MYSQL_DATABASE=university_db
```

4. Create and seed the MySQL database:

```bash
mysql -u root -p < sql/schema.sql
```

5. Run the app:

```bash
streamlit run app.py
```

## Example Questions

- Which students have attendance below 75%?
- What is the average CGPA of CSE students?
- Which courses are taught by Dr. Sharma?
- Show the top 5 students by CGPA.
- Which department has the highest average attendance?
- Why do you think scores are low in some subjects?

## Developer Mode

Developer Mode is available in the sidebar and is off by default. When it is off, users only see the conversational answer. When it is on, each assistant response also shows generated SQL, raw query results, status, and CSV download controls.

## Rate Limit Controls

- `llm_cache.json` caches Groq responses by model name, task type, and prompt hash.
- Repeating the same question avoids repeated Groq calls when the generated prompts are identical.
- Groq calls retry with 5, 10, and 20 second backoff for 429, 500, and 503 style failures.
- Set `USE_LLM_FOR_RESULT_SUMMARY=False` to use Groq only for SQL generation and format query results locally.

## Security Considerations

- Only `SELECT` queries are executed.
- Generated SQL is validated before it is sent to MySQL.
- Unsafe requests such as `DELETE`, `DROP`, `UPDATE`, `INSERT`, `ALTER`, `CREATE`, and `TRUNCATE` are blocked.
- Actual database records are not sent to the LLM during SQL generation; only schema metadata is included.
- Current version may send query results to Groq for natural-language summarization when `USE_LLM_FOR_RESULT_SUMMARY=True`.
- A stricter privacy mode is available by setting `USE_LLM_FOR_RESULT_SUMMARY=False`.
- `llm_cache.json` never stores API keys, passwords, or `.env` values.
- `audit_log.jsonl` stores query attempts with timestamp, question, generated SQL, status, and error message.
- In production systems, add authentication, authorization, audit retention policy, and role-based access control.

## User Context Injection

User context injection is documented as future work and is not implemented in this project. In production systems, authenticated metadata such as student roll number, faculty ID, department, and role can be injected into prompts to support questions such as "What is my CGPA?"

This must be paired with application-layer authorization. The LLM should not decide what a user is allowed to access.

## Future Improvements

- JWT authentication.
- User context injection.
- Role-based access control.
- Conversation memory beyond local JSON files.
- Docker deployment.
- OpenAI provider implementation behind the existing `LLMProvider` interface.
