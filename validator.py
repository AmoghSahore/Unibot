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
GROUP_BY_VALIDATION_ERROR = "Grouped queries must include every GROUP BY dimension in the SELECT clause."
AGGREGATE_VALIDATION_ERROR = "Potentially inflated aggregate detected. Use DISTINCT counts or safe grouped subqueries for joined tables."
UNKNOWN_SCHEMA_ERROR = "I can't answer that because the generated query refers to information not available in the current database."
SEMANTIC_TABLE_SELECTION_ERROR = (
    "Faculty-by-department questions should use the courses table directly without unnecessary student or enrollment joins."
)
COURSE_LOOKUP_TABLE_SELECTION_ERROR = (
    "Simple course or faculty listings should use the courses table directly without unnecessary joins."
)
DERIVED_ALIAS_ERROR = "A subquery alias references a column that is not selected by that subquery."

ALLOWED_SCHEMA = {
    "students": {"roll_no", "name", "department", "cgpa", "attendance", "semester"},
    "courses": {"course_id", "course_name", "faculty", "credits", "department"},
    "enrollments": {"enrollment_id", "roll_no", "course_id", "grade"},
}

SQL_KEYWORDS = {
    "select",
    "from",
    "where",
    "join",
    "left",
    "right",
    "inner",
    "outer",
    "on",
    "as",
    "and",
    "or",
    "not",
    "in",
    "is",
    "null",
    "case",
    "when",
    "then",
    "else",
    "end",
    "group",
    "by",
    "having",
    "order",
    "asc",
    "desc",
    "limit",
    "distinct",
    "between",
    "like",
    "true",
    "false",
}

SQL_FUNCTIONS = {
    "avg",
    "count",
    "sum",
    "min",
    "max",
    "round",
    "coalesce",
    "ifnull",
}

UNSUPPORTED_CONCEPTS = (
    (r"\b(hostel|hostels|dormitory|dormitories)\b", "hostel-related information"),
    (r"\b(classroom|classrooms|class room|class rooms)\b", "classroom-related information"),
    (r"\b(bus|buses|transport|route|routes)\b", "transport-related information"),
    (r"\b(scholarship|scholarships)\b", "scholarship-related information"),
    (r"\b(library|libraries|book|books|borrowed|borrowing)\b", "library or book-borrowing information"),
    (r"\b(fee|fees|payment|payments|paid|due)\b", "fee or payment information"),
    (r"\b(address|addresses|city|cities|bangalore|live|lives|living|reside|resides|residence)\b", "address or residence information"),
    (r"\b(placement|placements|salary|salaries|company|companies)\b", "placement, salary, or company information"),
    (r"\b(parent|parents|phone|mobile|email|contact)\b", "family or contact information"),
)


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


def detect_out_of_scope(question: str) -> tuple[bool, str]:
    normalized = re.sub(r"\s+", " ", question.lower()).strip()
    for pattern, concept in UNSUPPORTED_CONCEPTS:
        if re.search(pattern, normalized):
            return True, f"The database does not contain {concept}."
    return False, ""


def is_faculty_department_question(question: str) -> bool:
    normalized = re.sub(r"\s+", " ", question.lower()).strip()
    mentions_faculty = re.search(r"\b(faculty|faculties|teacher|teachers|professor|professors)\b", normalized) is not None
    mentions_department = re.search(
        r"\b(department|departments|cse|ece|mechanical|civil|electrical)\b",
        normalized,
    ) is not None
    asks_students = re.search(r"\b(student|students|taught by|enrolled|attendance|cgpa|grade|roll)\b", normalized) is not None
    return mentions_faculty and mentions_department and not asks_students


def is_simple_course_lookup_question(question: str) -> bool:
    normalized = re.sub(r"\s+", " ", question.lower()).strip()
    mentions_courses = re.search(r"\b(course|courses|subject|subjects)\b", normalized) is not None
    mentions_faculty = re.search(
        r"\b(faculty|faculties|teacher|teachers|professor|professors|taught|teach|teaches)\b",
        normalized,
    ) is not None
    needs_student_data = re.search(
        r"\b(student|students|enrolled|enrollment|enrollments|grade|grades|cgpa|attendance|semester|roll_no|roll number|participation)\b",
        normalized,
    ) is not None
    return mentions_courses and mentions_faculty and not needs_student_data


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


def _find_top_level_phrase(sql: str, phrase: str, start: int = 0) -> int:
    lowered = sql.lower()
    phrase = phrase.lower()
    depth = 0
    in_single_quote = False
    in_double_quote = False
    index = start

    while index <= len(sql) - len(phrase):
        char = sql[index]
        if char == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
        elif char == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
        elif not in_single_quote and not in_double_quote:
            if char == "(":
                depth += 1
            elif char == ")" and depth > 0:
                depth -= 1
            elif depth == 0 and lowered.startswith(phrase, index):
                return index
        index += 1

    return -1


def _split_top_level_csv(text: str) -> list[str]:
    parts = []
    current = []
    depth = 0
    in_single_quote = False
    in_double_quote = False

    for char in text:
        if char == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
        elif char == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
        elif not in_single_quote and not in_double_quote:
            if char == "(":
                depth += 1
            elif char == ")" and depth > 0:
                depth -= 1

        if char == "," and depth == 0 and not in_single_quote and not in_double_quote:
            part = "".join(current).strip()
            if part:
                parts.append(part)
            current = []
        else:
            current.append(char)

    tail = "".join(current).strip()
    if tail:
        parts.append(tail)
    return parts


def _normalize_expression(expression: str) -> str:
    normalized = expression.strip().strip("`")
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.lower()


def _select_terms(select_clause: str) -> tuple[set[str], set[str]]:
    expressions = set()
    aliases = set()

    for item in _split_top_level_csv(select_clause):
        normalized = _normalize_expression(item)
        expressions.add(normalized)

        alias_match = re.match(r"(.+?)\s+as\s+([a-zA-Z_][\w]*)$", item.strip(), flags=re.IGNORECASE)
        if alias_match:
            expressions.add(_normalize_expression(alias_match.group(1)))
            aliases.add(_normalize_expression(alias_match.group(2)))

    return expressions, aliases


def _validate_grouped_select(statement: str) -> str:
    group_index = _find_top_level_phrase(statement, " group by ")
    if group_index == -1:
        return ""

    from_index = _find_top_level_phrase(statement, " from ")
    if from_index == -1 or from_index <= len("select "):
        return ""

    group_end_candidates = [
        index
        for phrase in (" having ", " order by ", " limit ", " union ")
        if (index := _find_top_level_phrase(statement, phrase, group_index + len(" group by "))) != -1
    ]
    group_end = min(group_end_candidates) if group_end_candidates else len(statement)

    select_clause = statement[len("select") : from_index]
    group_clause = statement[group_index + len(" group by ") : group_end]
    selected_expressions, selected_aliases = _select_terms(select_clause)

    for group_expression in _split_top_level_csv(group_clause):
        normalized_group = _normalize_expression(re.sub(r"\s+(asc|desc)$", "", group_expression, flags=re.IGNORECASE))
        if normalized_group.isdigit():
            continue
        if normalized_group not in selected_expressions and normalized_group not in selected_aliases:
            return GROUP_BY_VALIDATION_ERROR

    return ""


def _validate_safe_aggregates(statement: str) -> str:
    lowered = statement.lower()

    risky_patterns = (
        r"\bcount\s*\(\s*(?:s|students)\.roll_no\s*\)",
        r"\bcount\s*\(\s*(?:c|courses)\.course_id\s*\)",
    )
    for pattern in risky_patterns:
        if re.search(pattern, lowered):
            return AGGREGATE_VALIDATION_ERROR

    if re.search(r"\bsum\s*\(\s*(?:c|courses)\.credits\s*\)", lowered) and " join " in lowered:
        return AGGREGATE_VALIDATION_ERROR

    return ""


def _strip_sql_literals(sql: str) -> str:
    without_single = re.sub(r"'(?:''|[^'])*'", " ", sql)
    return re.sub(r'"(?:""|[^"])*"', " ", without_single)


def _normalize_identifier(identifier: str) -> str:
    return identifier.strip().strip("`").lower()


def _matching_parenthesis(sql: str, opening_index: int) -> int:
    depth = 0
    in_single_quote = False
    in_double_quote = False

    for index in range(opening_index, len(sql)):
        char = sql[index]
        if char == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
        elif char == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
        elif not in_single_quote and not in_double_quote:
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    return index
    return -1


def _projected_column_name(select_item: str) -> str:
    item = select_item.strip()
    alias_match = re.match(r".+?\s+as\s+(`?[a-zA-Z_][\w]*`?)$", item, flags=re.IGNORECASE)
    if alias_match:
        return _normalize_identifier(alias_match.group(1))

    trailing_alias = re.match(r".+?\s+(`?[a-zA-Z_][\w]*`?)$", item, flags=re.IGNORECASE)
    if trailing_alias and ("(" in item or "." in item):
        return _normalize_identifier(trailing_alias.group(1))

    column_match = re.match(r"(?:`?[a-zA-Z_][\w]*`?\s*\.\s*)?`?([a-zA-Z_][\w]*)`?$", item)
    if column_match:
        return _normalize_identifier(column_match.group(1))
    if item == "*" or item.endswith(".*"):
        return "*"
    return ""


def _extract_derived_alias_columns(statement: str) -> dict[str, set[str]]:
    sql = _strip_sql_literals(statement)
    derived_columns: dict[str, set[str]] = {}

    for match in re.finditer(r"\b(?:from|join)\s*\(", sql, flags=re.IGNORECASE):
        opening_index = sql.find("(", match.start())
        closing_index = _matching_parenthesis(sql, opening_index)
        if closing_index == -1:
            continue

        alias_match = re.match(
            r"\s*(?:as\s+)?(`?[a-zA-Z_][\w]*`?)",
            sql[closing_index + 1 :],
            flags=re.IGNORECASE,
        )
        if not alias_match:
            continue

        alias = _normalize_identifier(alias_match.group(1))
        subquery = sql[opening_index + 1 : closing_index].strip()
        if not re.match(r"^select\b", subquery, flags=re.IGNORECASE):
            continue

        from_index = _find_top_level_phrase(subquery, " from ")
        if from_index == -1:
            continue

        select_clause = subquery[len("select") : from_index]
        projected_columns = {
            column_name
            for item in _split_top_level_csv(select_clause)
            if (column_name := _projected_column_name(item))
        }
        derived_columns[alias] = projected_columns

    return derived_columns


def _extract_table_aliases(statement: str) -> tuple[dict[str, str], dict[str, set[str]], str]:
    sql = _strip_sql_literals(statement)
    table_aliases: dict[str, str] = {}
    derived_aliases = _extract_derived_alias_columns(sql)

    for match in re.finditer(
        r"\b(from|join)\s+(`?[a-zA-Z_][\w]*`?)(?:\s+(?:as\s+)?(`?[a-zA-Z_][\w]*`?))?",
        sql,
        flags=re.IGNORECASE,
    ):
        table_name = _normalize_identifier(match.group(2))
        alias = _normalize_identifier(match.group(3) or table_name)
        if table_name not in ALLOWED_SCHEMA:
            return table_aliases, derived_aliases, UNKNOWN_SCHEMA_ERROR
        table_aliases[table_name] = table_name
        table_aliases[alias] = table_name

    return table_aliases, derived_aliases, ""


def _extract_select_aliases(statement: str) -> set[str]:
    aliases = set()
    select_index = _find_top_level_phrase(f" {statement}", " select ")
    from_index = _find_top_level_phrase(statement, " from ")
    if from_index == -1:
        return aliases

    select_clause = statement[len("select") : from_index]
    for item in _split_top_level_csv(select_clause):
        alias_match = re.match(r".+?\s+as\s+(`?[a-zA-Z_][\w]*`?)$", item.strip(), flags=re.IGNORECASE)
        if alias_match:
            aliases.add(_normalize_identifier(alias_match.group(1)))
            continue

        trailing_alias = re.match(r".+?\s+(`?[a-zA-Z_][\w]*`?)$", item.strip(), flags=re.IGNORECASE)
        if trailing_alias and "(" in item:
            aliases.add(_normalize_identifier(trailing_alias.group(1)))

    return aliases


def _validate_schema_identifiers(statement: str) -> str:
    sql = _strip_sql_literals(statement)
    lowered = sql.lower()

    for pattern, _concept in UNSUPPORTED_CONCEPTS:
        if re.search(pattern, lowered):
            return UNKNOWN_SCHEMA_ERROR

    table_aliases, derived_aliases, table_error = _extract_table_aliases(sql)
    if table_error:
        return table_error

    for qualifier, column in re.findall(r"`?([a-zA-Z_][\w]*)`?\s*\.\s*`?([a-zA-Z_][\w]*)`?", sql):
        normalized_qualifier = _normalize_identifier(qualifier)
        normalized_column = _normalize_identifier(column)

        if normalized_qualifier in derived_aliases:
            projected_columns = derived_aliases[normalized_qualifier]
            if "*" not in projected_columns and normalized_column not in projected_columns:
                return DERIVED_ALIAS_ERROR
            continue

        table_name = table_aliases.get(normalized_qualifier)
        if not table_name:
            return UNKNOWN_SCHEMA_ERROR
        if normalized_column not in ALLOWED_SCHEMA[table_name]:
            return UNKNOWN_SCHEMA_ERROR

    allowed_identifiers = set(ALLOWED_SCHEMA)
    for columns in ALLOWED_SCHEMA.values():
        allowed_identifiers.update(columns)
    allowed_identifiers.update(table_aliases)
    allowed_identifiers.update(derived_aliases)
    for projected_columns in derived_aliases.values():
        allowed_identifiers.update(projected_columns)
    allowed_identifiers.update(_extract_select_aliases(sql))
    allowed_identifiers.update(SQL_KEYWORDS)
    allowed_identifiers.update(SQL_FUNCTIONS)

    without_qualified = re.sub(r"`?[a-zA-Z_][\w]*`?\s*\.\s*`?[a-zA-Z_][\w]*`?", " ", sql)
    without_alias_declarations = re.sub(
        r"\b(from|join)\s+`?[a-zA-Z_][\w]*`?(?:\s+(?:as\s+)?`?[a-zA-Z_][\w]*`?)?",
        " ",
        without_qualified,
        flags=re.IGNORECASE,
    )
    without_select_aliases = re.sub(
        r"\bas\s+`?[a-zA-Z_][\w]*`?",
        " ",
        without_alias_declarations,
        flags=re.IGNORECASE,
    )

    for token in re.findall(r"`?([a-zA-Z_][\w]*)`?", without_select_aliases):
        normalized_token = _normalize_identifier(token)
        if normalized_token in allowed_identifiers:
            continue
        if normalized_token.startswith("average_") or normalized_token.endswith("_count") or normalized_token.endswith("_stats"):
            continue
        return UNKNOWN_SCHEMA_ERROR

    return ""


def validate_semantic_sql(question: str, sql: str) -> tuple[bool, str]:
    for statement in split_sql_statements(sql):
        lowered = re.sub(r"\s+", " ", statement).lower()
        references_courses = re.search(r"\bfrom\s+courses\b|\bjoin\s+courses\b", lowered) is not None
        references_unnecessary_tables = re.search(
            r"\b(from|join)\s+(?:as\s+)?(students|enrollments)\b",
            lowered,
        ) is not None

        if is_faculty_department_question(question):
            references_faculty = re.search(r"\b(?:c|courses)\.faculty\b|\bfaculty\b", lowered) is not None
            if references_faculty and (not references_courses or references_unnecessary_tables):
                return False, SEMANTIC_TABLE_SELECTION_ERROR

        if is_simple_course_lookup_question(question):
            has_any_join = re.search(r"\bjoin\b", lowered) is not None
            if not references_courses or references_unnecessary_tables or has_any_join:
                return False, COURSE_LOOKUP_TABLE_SELECTION_ERROR

    return True, ""


def validate_sql_for_question(question: str, raw_sql: str) -> ValidationResult:
    validation = validate_sql(raw_sql)
    if not validation.is_valid:
        return validation

    semantic_valid, semantic_message = validate_semantic_sql(question, validation.sql)
    if not semantic_valid:
        return ValidationResult(False, validation.sql, semantic_message)
    return validation


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

        schema_error = _validate_schema_identifiers(normalized)
        if schema_error:
            return ValidationResult(False, sql, schema_error)

        group_error = _validate_grouped_select(normalized)
        if group_error:
            return ValidationResult(False, sql, group_error)

        aggregate_error = _validate_safe_aggregates(normalized)
        if aggregate_error:
            return ValidationResult(False, sql, aggregate_error)

        validated_statements.append(normalized)

    return ValidationResult(True, ";\n".join(validated_statements))
