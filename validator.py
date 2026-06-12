import re
from dataclasses import dataclass


BLOCKED_KEYWORDS = {
    "insert",
    "update",
    "delete",
    "drop",
    "alter",
    "create",
    "truncate",
    "replace",
    "merge",
    "grant",
    "revoke",
    "call",
    "execute",
    "load",
    "outfile",
    "dumpfile",
}

MAX_SELECT_STATEMENTS = 5


@dataclass(frozen=True)
class ValidationResult:
    is_valid: bool
    sql: str
    message: str = ""


def clean_sql(raw_sql: str) -> str:
    sql = (raw_sql or "").strip()
    sql = re.sub(r"^```(?:sql|mysql)?", "", sql, flags=re.IGNORECASE).strip()
    sql = re.sub(r"```$", "", sql).strip()
    return sql


def split_sql_statements(raw_sql: str) -> list[str]:
    sql = clean_sql(raw_sql)
    sql = sql.strip().rstrip(";").strip()
    if not sql:
        return []

    statements = []
    current = []
    depth = 0
    in_single_quote = False
    in_double_quote = False

    for char in sql:
        if char == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
        elif char == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
        elif not in_single_quote and not in_double_quote:
            if char == "(":
                depth += 1
            elif char == ")" and depth > 0:
                depth -= 1

        if char == ";" and depth == 0 and not in_single_quote and not in_double_quote:
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
        else:
            current.append(char)

    tail = "".join(current).strip()
    if tail:
        statements.append(tail)

    if len(statements) != 1:
        return statements

    sql = statements[0]
    lines = sql.splitlines()
    statements = []
    current_lines = []
    depth = 0

    for line in lines:
        stripped = line.strip()
        starts_top_level_select = depth == 0 and re.match(r"^select\b", stripped, flags=re.IGNORECASE)
        if starts_top_level_select and current_lines:
            statements.append("\n".join(current_lines).strip())
            current_lines = []

        current_lines.append(line)

        in_single_quote = False
        in_double_quote = False
        for char in line:
            if char == "'" and not in_double_quote:
                in_single_quote = not in_single_quote
            elif char == '"' and not in_single_quote:
                in_double_quote = not in_double_quote
            elif not in_single_quote and not in_double_quote:
                if char == "(":
                    depth += 1
                elif char == ")" and depth > 0:
                    depth -= 1

    if current_lines:
        statements.append("\n".join(current_lines).strip())

    return [statement for statement in statements if statement]


def validate_sql(raw_sql: str) -> ValidationResult:
    sql = clean_sql(raw_sql)
    statements = split_sql_statements(sql)

    if not sql:
        return ValidationResult(False, sql, "I couldn't generate a valid SQL query.")

    if not statements:
        return ValidationResult(False, sql, "I couldn't generate a valid SQL query.")

    if len(statements) > MAX_SELECT_STATEMENTS:
        return ValidationResult(False, sql, f"I can run at most {MAX_SELECT_STATEMENTS} SELECT queries at once.")

    validated_statements = []
    for statement in statements:
        normalized = re.sub(r"\s+", " ", statement).strip().rstrip(";").strip()

        if not re.match(r"^select\b", normalized, flags=re.IGNORECASE):
            return ValidationResult(False, sql, "Unsafe query detected. Only SELECT statements are allowed.")

        lowered = normalized.lower()
        for keyword in BLOCKED_KEYWORDS:
            if re.search(rf"\b{re.escape(keyword)}\b", lowered):
                return ValidationResult(False, sql, "Unsafe query detected. Only SELECT statements are allowed.")

        validated_statements.append(normalized)

    return ValidationResult(True, ";\n".join(validated_statements))
