from dataclasses import dataclass
from typing import Any

import mysql.connector
from mysql.connector import Error
import pandas as pd

from config import Settings, get_settings
from validator import split_sql_statements


class DatabaseError(Exception):
    pass


@dataclass(frozen=True)
class QueryResult:
    rows: list[dict[str, Any]]
    dataframe: pd.DataFrame

    @property
    def is_empty(self) -> bool:
        return self.dataframe.empty


def get_connection(settings: Settings | None = None):
    settings = settings or get_settings()
    try:
        return mysql.connector.connect(
            host=settings.mysql_host,
            port=settings.mysql_port,
            user=settings.mysql_user,
            password=settings.mysql_password,
            database=settings.mysql_database,
        )
    except Error as exc:
        raise DatabaseError("Database connection error.") from exc


def execute_select(sql: str, settings: Settings | None = None) -> QueryResult:
    connection = None
    cursor = None

    try:
        connection = get_connection(settings)
        cursor = connection.cursor(dictionary=True)
        cursor.execute(sql)
        rows = cursor.fetchall()
        dataframe = pd.DataFrame(rows)
        return QueryResult(rows=rows, dataframe=dataframe)
    except Error as exc:
        raise DatabaseError("Database query error.") from exc
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None and connection.is_connected():
            connection.close()


def execute_selects(sql: str, settings: Settings | None = None) -> QueryResult:
    statements = split_sql_statements(sql)
    if len(statements) <= 1:
        return execute_select(sql, settings)

    connection = None
    cursor = None

    try:
        connection = get_connection(settings)
        cursor = connection.cursor(dictionary=True)
        all_rows: list[dict[str, Any]] = []

        for index, statement in enumerate(statements, start=1):
            cursor.execute(statement)
            rows = cursor.fetchall()
            for row in rows:
                all_rows.append({"query_number": index, **row})

            if not rows:
                all_rows.append({"query_number": index, "message": "No matching records were found."})

        dataframe = pd.DataFrame(all_rows)
        return QueryResult(rows=all_rows, dataframe=dataframe)
    except Error as exc:
        raise DatabaseError("Database query error.") from exc
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None and connection.is_connected():
            connection.close()
