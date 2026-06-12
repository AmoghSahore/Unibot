import json
import re
from decimal import Decimal
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from config import get_settings
from db import DatabaseError, execute_selects
from llm import LLMError, LLMRateLimitError, get_llm_provider
from prompts import DATABASE_SCHEMA
from validator import clean_sql, validate_sql


CHAT_HISTORY_PATH = Path("chat_history.json")
AUDIT_LOG_PATH = Path("audit_log.jsonl")


st.set_page_config(page_title="University SQL Assistant", page_icon="🎓", layout="wide")


st.markdown(
    """
    <style>
        .stApp {
            background:
                radial-gradient(circle at top left, rgba(56, 189, 248, 0.10), transparent 32rem),
                linear-gradient(135deg, #0f172a 0%, #111827 46%, #1f2937 100%);
            color: #e5e7eb;
        }

        .block-container {
            max-width: 1050px;
            padding-top: 2.5rem;
            padding-bottom: 4rem;
        }

        [data-testid="stSidebar"] {
            background: rgba(15, 23, 42, 0.96);
            border-right: 1px solid rgba(148, 163, 184, 0.20);
        }

        [data-testid="stSidebar"] .stButton > button {
            border: 1px solid rgba(148, 163, 184, 0.28);
            border-radius: 0.55rem;
            background: rgba(30, 41, 59, 0.82);
            color: #e5e7eb;
            text-align: left;
            justify-content: flex-start;
            min-height: 2.8rem;
            white-space: normal;
        }

        [data-testid="stSidebar"] .stButton > button:hover {
            border-color: rgba(56, 189, 248, 0.70);
            background: rgba(51, 65, 85, 0.92);
            color: #ffffff;
        }

        div[data-testid="stChatMessage"] {
            border-bottom: 1px solid rgba(148, 163, 184, 0.16);
            border-radius: 0;
            padding: 1.05rem 0.2rem;
            background: transparent;
            box-shadow: none;
        }

        div[data-testid="stExpander"] {
            border: 1px solid rgba(148, 163, 184, 0.20);
            border-radius: 0.75rem;
            background: rgba(15, 23, 42, 0.45);
        }

        .app-header {
            padding: 0.4rem 0 1.4rem;
        }

        .app-header h1 {
            margin: 0;
            color: #f8fafc;
            font-size: 2.35rem;
            font-weight: 750;
            letter-spacing: 0;
        }

        .app-header p {
            margin: 0.45rem 0 0;
            color: #cbd5e1;
            font-size: 1.05rem;
        }

        .app-explainer {
            margin: 0 0 1.5rem;
            color: #94a3b8;
            font-size: 0.96rem;
        }

        .sidebar-meta {
            padding: 0.8rem 0;
            color: #cbd5e1;
            line-height: 1.65;
        }

        .status-pill {
            display: inline-block;
            margin-top: 0.35rem;
            padding: 0.16rem 0.5rem;
            border-radius: 999px;
            background: rgba(14, 165, 233, 0.16);
            color: #bae6fd;
            font-size: 0.78rem;
        }
    </style>
    """,
    unsafe_allow_html=True,
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_messages() -> list[dict[str, Any]]:
    return [
        {
            "role": "assistant",
            "answer": "Ask a question about students, courses, attendance, CGPA, departments, or enrollments.",
            "generated_sql": "",
            "query_results": [],
            "timestamp": now_iso(),
            "status": "success",
        }
    ]


def normalize_message(message: dict[str, Any]) -> dict[str, Any]:
    role = message.get("role")

    if role == "user":
        return {
            "role": "user",
            "content": str(message.get("content", "")),
            "timestamp": message.get("timestamp") or now_iso(),
        }

    return {
        "role": "assistant",
        "answer": str(message.get("answer", "")),
        "generated_sql": str(message.get("generated_sql") or message.get("sql") or ""),
        "query_results": message.get("query_results") or [],
        "timestamp": message.get("timestamp") or now_iso(),
        "status": message.get("status") or ("error" if message.get("error") else "success"),
    }


def load_chat_history() -> list[dict[str, Any]]:
    if not CHAT_HISTORY_PATH.exists():
        return default_messages()

    try:
        raw_messages = json.loads(CHAT_HISTORY_PATH.read_text(encoding="utf-8"))
        if not isinstance(raw_messages, list):
            return default_messages()
        return [normalize_message(message) for message in raw_messages if isinstance(message, dict)]
    except (OSError, json.JSONDecodeError):
        return default_messages()


def save_chat_history(messages: list[dict[str, Any]]) -> None:
    CHAT_HISTORY_PATH.write_text(
        json.dumps(messages, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )


def clear_chat_history() -> None:
    st.session_state.messages = default_messages()
    st.session_state.pending_question = ""
    if CHAT_HISTORY_PATH.exists():
        CHAT_HISTORY_PATH.unlink()


def append_audit_log(
    *,
    timestamp: str,
    question: str,
    generated_sql: str,
    status: str,
    error_message: str = "",
) -> None:
    event = {
        "timestamp": timestamp,
        "user_question": question,
        "generated_sql": generated_sql,
        "status": status,
        "error_message": error_message,
    }
    with AUDIT_LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")


def dataframe_to_prompt_text(dataframe: pd.DataFrame) -> str:
    if dataframe.empty:
        return "No matching records were found."

    limited = dataframe.head(50)
    return limited.to_string(index=False)


def dataframe_to_records(dataframe: pd.DataFrame) -> list[dict[str, Any]]:
    records = dataframe.to_dict(orient="records")
    return json.loads(json.dumps(records, ensure_ascii=False, default=str))


def records_to_dataframe(records: Any) -> pd.DataFrame:
    if isinstance(records, list):
        return pd.DataFrame(records)
    return pd.DataFrame()


def local_result_summary(question: str, dataframe: pd.DataFrame) -> str:
    if dataframe.empty:
        return "No matching records were found."

    row_count = len(dataframe)
    columns = list(dataframe.columns)

    if row_count == 1 and len(columns) == 1:
        value = dataframe.iloc[0, 0]
        return f"The answer is {value}."

    if row_count <= 5 and len(columns) <= 3:
        formatted_rows = dataframe.astype(str).apply(
            lambda row: ", ".join(f"{column}: {row[column]}" for column in columns),
            axis=1,
        )
        return "I found these matching results: " + "; ".join(formatted_rows.tolist()) + "."

    return f"I found {row_count} matching records. Turn on Developer Mode to inspect the full result table."


def clean_repetitive_answer(answer: str, max_sentences: int = 5) -> str:
    if not answer:
        return answer

    parts = re.split(r"(?<=[.!?])\s+", answer.strip())
    cleaned_parts = []
    seen = set()

    for part in parts:
        normalized = re.sub(r"\s+", " ", part.strip().lower())
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        cleaned_parts.append(part.strip())
        if len(cleaned_parts) >= max_sentences:
            break

    return " ".join(cleaned_parts).strip() or answer.strip()


def analytical_result_summary(question: str, dataframe: pd.DataFrame) -> str | None:
    if dataframe.empty:
        return "No matching records were found."

    numeric_columns = []
    for column in dataframe.columns:
        series = dataframe[column]
        has_numeric_values = series.map(lambda value: isinstance(value, (int, float, Decimal))).any()
        if pd.api.types.is_numeric_dtype(series) or has_numeric_values:
            numeric_columns.append(column)
    label_columns = [column for column in dataframe.columns if column not in numeric_columns]

    if len(dataframe) > 5 and numeric_columns and label_columns:
        label_column = label_columns[0]
        metric_column = numeric_columns[-1]
        top_rows = dataframe.head(5)
        labels = ", ".join(str(value) for value in top_rows[label_column].tolist())
        return (
            f"I found {len(dataframe)} matching rows. The leading entries by {metric_column} are {labels}. "
            "Turn on Developer Mode to inspect the full result table."
        )

    return None


def is_unsafe_request(question: str) -> bool:
    normalized = question.strip().lower()
    unsafe_patterns = [
        r"^\s*(delete|drop|update|insert|alter|truncate)\b",
        r"\b(delete|drop|update|insert|alter|truncate)\b.*\b(students|student|courses|course|enrollments|enrollment|table|database)\b",
        r"\b(remove|erase|wipe)\b.*\b(students|student|courses|course|enrollments|enrollment|records|data)\b",
    ]
    return any(re.search(pattern, normalized) for pattern in unsafe_patterns)


def is_security_validation_failure(raw_sql: str, message: str) -> bool:
    sql = clean_sql(raw_sql)
    if "unsafe" in message.lower():
        return True
    if sql and not re.match(r"^select\b", sql.strip(), flags=re.IGNORECASE):
        return True
    return False


def build_assistant_message(
    *,
    answer: str,
    generated_sql: str = "",
    dataframe: pd.DataFrame | None = None,
    status: str,
) -> dict[str, Any]:
    return {
        "role": "assistant",
        "answer": answer,
        "generated_sql": generated_sql,
        "query_results": dataframe_to_records(dataframe) if dataframe is not None else [],
        "timestamp": now_iso(),
        "status": status,
    }


def run_question(question: str) -> dict[str, Any]:
    timestamp = now_iso()
    generated_sql = ""
    status = "error"
    error_message = ""

    try:
        if is_unsafe_request(question):
            status = "security_blocked"
            error_message = "Unsafe query detected. Only SELECT queries are allowed."
            return build_assistant_message(answer=error_message, generated_sql="", status=status)

        settings = get_settings()
        llm = get_llm_provider(settings)
        raw_sql = llm.generate_sql(question)
        generated_sql = clean_sql(raw_sql)
        validation = validate_sql(raw_sql)

        if not validation.is_valid:
            if is_security_validation_failure(raw_sql, validation.message):
                status = "security_blocked"
                answer = "Unsafe query detected. Only SELECT queries are allowed."
            else:
                status = "error"
                answer = "I couldn't generate a valid SQL query for that request."
            error_message = answer
            return build_assistant_message(answer=answer, generated_sql=generated_sql, status=status)

        result = execute_selects(validation.sql)
        generated_sql = validation.sql

        if result.is_empty:
            status = "no_results"
            return build_assistant_message(
                answer="No matching records were found.",
                generated_sql=generated_sql,
                dataframe=result.dataframe,
                status=status,
            )

        analytical_answer = analytical_result_summary(question, result.dataframe)
        if analytical_answer:
            answer = analytical_answer
        elif settings.use_llm_for_result_summary:
            prompt_results = dataframe_to_prompt_text(result.dataframe)
            answer = clean_repetitive_answer(llm.summarize_results(question, validation.sql, prompt_results))
        else:
            answer = local_result_summary(question, result.dataframe)
        status = "success"

        return build_assistant_message(
            answer=answer,
            generated_sql=generated_sql,
            dataframe=result.dataframe,
            status=status,
        )
    except LLMRateLimitError as exc:
        status = "error"
        error_message = str(exc)
        return build_assistant_message(answer=error_message, generated_sql=generated_sql, status=status)
    except LLMError as exc:
        status = "error"
        error_message = str(exc) or "The AI service is temporarily unavailable. Please try again."
        return build_assistant_message(answer=error_message, generated_sql=generated_sql, status=status)
    except DatabaseError:
        status = "error"
        error_message = "Database connection or query execution failed."
        return build_assistant_message(answer=error_message, generated_sql=generated_sql, status=status)
    except Exception:
        status = "error"
        error_message = "Something went wrong while processing your request."
        return build_assistant_message(answer=error_message, generated_sql=generated_sql, status=status)
    finally:
        append_audit_log(
            timestamp=timestamp,
            question=question,
            generated_sql=generated_sql,
            status=status,
            error_message=error_message,
        )


def render_assistant_message(message: dict[str, Any], index: int, developer_mode: bool) -> None:
    with st.chat_message("assistant"):
        st.markdown("**University SQL Assistant**")
        st.write(message.get("answer", ""))

        if not developer_mode:
            return

        status = message.get("status", "success")
        st.markdown("#### Technical Details")
        st.markdown(f'<span class="status-pill">{status}</span>', unsafe_allow_html=True)

        generated_sql = str(message.get("generated_sql") or "")
        st.markdown("**Generated SQL**")
        if generated_sql:
            st.code(generated_sql, language="sql")
        elif index > 0:
            st.info("No SQL was generated because the request was blocked before execution.")

        dataframe = records_to_dataframe(message.get("query_results"))
        should_show_results = bool(generated_sql) and status in {"success", "no_results"}
        if should_show_results:
            st.markdown("**Query Results**")
            if dataframe.empty:
                st.info("No matching records were found.")
                return

            st.dataframe(dataframe, use_container_width=True)
            csv = dataframe.to_csv(index=False).encode("utf-8")
            st.download_button(
                "Download Results as CSV",
                csv,
                file_name=f"query_results_{index + 1}.csv",
                mime="text/csv",
                key=f"download_{index}",
            )


def process_question(question: str) -> None:
    user_message = {"role": "user", "content": question, "timestamp": now_iso()}
    st.session_state.messages.append(user_message)
    assistant_message = run_question(question)
    st.session_state.messages.append(assistant_message)
    save_chat_history(st.session_state.messages)


def process_question_once(question: str) -> None:
    normalized_question = question.strip()
    if not normalized_question:
        return

    current_request_key = f"{normalized_question}|{len(st.session_state.messages)}"
    if st.session_state.get("active_request_key") == current_request_key:
        return

    st.session_state.active_request_key = current_request_key
    process_question(normalized_question)
    st.session_state.active_request_key = ""


if "messages" not in st.session_state:
    st.session_state.messages = load_chat_history()

if "pending_question" not in st.session_state:
    st.session_state.pending_question = ""

if "active_request_key" not in st.session_state:
    st.session_state.active_request_key = ""


with st.sidebar:
    st.title("🎓 University SQL Assistant")

    developer_mode = st.toggle("Developer Mode", value=False)

    st.subheader("Database")
    st.markdown(
        """
        <div class="sidebar-meta">
            <strong>Name:</strong> university_db<br>
            <strong>Available Tables:</strong><br>
            students<br>
            courses<br>
            enrollments
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.divider()
    st.subheader("Example Questions")
    suggestions = [
        "Which students have attendance below 75%?",
        "What is the average CGPA of CSE students?",
        "Which courses are taught by Dr. Sharma?",
        "Show the top 5 students by CGPA.",
        "Which department has the highest average attendance?",
        "Why do you think scores are low in some subjects?",
    ]

    for index, suggestion in enumerate(suggestions):
        if st.button(suggestion, use_container_width=True, key=f"suggestion_{index}"):
            st.session_state.pending_question = suggestion
            st.rerun()

    st.divider()
    st.subheader("Security Notes")
    st.markdown(
        """
        - Only SELECT queries are allowed.
        - SQL is validated before execution.
        - The LLM generates SQL but does not directly access the database.
        - Production systems should add authentication, authorization, audit logs, and context injection.
        """
    )

    st.divider()
    st.subheader("Privacy Note")
    st.markdown(
        """
        The LLM receives the database schema and user question to generate SQL. The SQL query is executed locally against MySQL. Raw database records are hidden in normal mode and available in Developer Mode.

        Current version may send query results to Groq for natural-language summarization. A stricter privacy mode can format results locally without sending row data to the LLM.
        """
    )

    with st.expander("View Database Schema", expanded=False):
        st.code(DATABASE_SCHEMA, language="text")

    st.divider()
    if st.button("Clear Chat History", use_container_width=True):
        clear_chat_history()
        st.rerun()


st.markdown(
    """
    <div class="app-header">
        <h1>🎓 University SQL Assistant</h1>
        <p>Ask questions in plain English and get answers from a MySQL university database.</p>
    </div>
    <p class="app-explainer">
        This assistant converts natural language into safe SQL queries, executes them on the university database,
        and returns results in plain English.
    </p>
    """,
    unsafe_allow_html=True,
)

for message_index, message in enumerate(st.session_state.messages):
    if message.get("role") == "user":
        with st.chat_message("user"):
            st.markdown("**You**")
            st.write(message.get("content", ""))
    else:
        render_assistant_message(message, message_index, developer_mode)


typed_question = st.chat_input("Ask a question about the university database")
question = st.session_state.pending_question or typed_question
st.session_state.pending_question = ""

if question:
    with st.spinner("Generating SQL, querying MySQL, and preparing the answer..."):
        process_question_once(question)
    st.rerun()
