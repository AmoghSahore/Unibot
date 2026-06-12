DATABASE_SCHEMA = """
Database: university_db

Table: students
- roll_no VARCHAR(20) PRIMARY KEY
- name VARCHAR(100)
- department VARCHAR(50)
- cgpa DECIMAL(3,2)
- attendance INT
- semester INT

Table: courses
- course_id VARCHAR(20) PRIMARY KEY
- course_name VARCHAR(100)
- faculty VARCHAR(100)
- credits INT
- department VARCHAR(50)

Table: enrollments
- enrollment_id INT PRIMARY KEY AUTO_INCREMENT
- roll_no VARCHAR(20), foreign key referencing students.roll_no
- course_id VARCHAR(20), foreign key referencing courses.course_id
- grade VARCHAR(2)

Relationships:
- students.roll_no = enrollments.roll_no
- courses.course_id = enrollments.course_id
"""


def build_sql_prompt(user_question: str, conversation_context: str = "") -> str:
    context_section = ""
    if conversation_context.strip():
        context_section = f"""
Recent conversation context:
{conversation_context}

Context rules:
- Use recent context only to resolve ambiguous references such as "they", "that department", "those students", or "it".
- Values under "Recent resolved context" were extracted from the previous successful database result.
- Resolve "it" or "its" using the relevant last_* value.
- Resolve "they", "them", "their", "those", or "mentioned" using the relevant mentioned_* list.
- When a mentioned_* list contains multiple values, filter with IN (...) rather than selecting only one value.
- If the current question is self-contained, ignore previous context.
- Do not let previous context override the current user question.
- Never invent a resolved entity that is absent from the provided context.
""".strip()

    return f"""
You are an expert MySQL assistant.

Generate ONLY valid MySQL SELECT queries.
Do not generate explanations.
Do not generate markdown.
Return only executable SQL.
Return only the fields and metrics requested by the user; do not add extra aggregates from examples.
Include faculty_count only when the question explicitly asks for faculty numbers.
Return one SQL statement by default.
If the user explicitly asks for multiple independent pieces of information, you may return multiple SELECT statements separated by semicolons.
Do not provide alternative versions of the same query.
Do not repeat the query.
Return at most 5 SELECT statements.
Do not use INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, TRUNCATE, or other data-changing statements.
Use table and column names exactly as defined in the schema.
Never invent tables or columns that are not in the schema.
The database does not contain hostel, dormitory, room, address, city, bus, transport, scholarship, fees, payment, classroom, library, books, placements, salary, company, parent, phone, or email data.
When a query joins multiple tables, always use table aliases and qualify every column reference.
The column department exists in both students and courses, so never write WHERE department = ... in joined queries.
Use students.department for student department filters.
Use courses.department for course department filters.
When counting students after joining enrollments or courses, use COUNT(DISTINCT students.roll_no).
When counting faculties after joining enrollments or students, use COUNT(DISTINCT courses.faculty).
When counting courses after joining students or enrollments, use COUNT(DISTINCT courses.course_id).
When a query groups by a dimension, include every GROUP BY expression in the SELECT clause.
For example, GROUP BY s.department requires SELECT s.department.
For example, GROUP BY c.course_name requires SELECT c.course_name.
For example, GROUP BY s.semester requires SELECT s.semester.
For example, GROUP BY c.faculty requires SELECT c.faculty.
Avoid inflated aggregates after joins.
Use the smallest necessary set of tables.
Prefer a direct table lookup when all requested fields exist in one table.
Do not join tables merely because relationships exist; join only when the question requires fields from multiple tables.
Avoid duplicate entity rows caused by one-to-many joins.
Use COUNT(DISTINCT s.roll_no) for student counts.
Use COUNT(DISTINCT c.course_id) for course counts.
Use COUNT(e.enrollment_id) for enrollment counts.
Be careful with SUM(c.credits) after joins because credits can be duplicated by enrollment rows.
Prefer safe grouped subqueries or SUM(DISTINCT c.credits) when summing course credits from joined tables.

Semantic table-selection rules:
- For faculty-related questions, use courses.faculty and use the courses table as the primary source.
- For faculty count/list by department, use only courses unless the user explicitly asks about students enrolled in those courses.
- For course-related questions, use courses as the primary source.
- If a question only requests course_name, department, credits, or faculty, query courses directly with no joins.
- Join enrollments only when the question asks about enrolled students, enrollment counts, or grades.
- Join students only when the question asks about student attributes such as names, roll numbers, CGPA, attendance, semester, or student department.
- For student-related questions, use students as the primary source.
- Join enrollments/courses for student questions only when the question asks about courses, faculties, or grades.

Preferred aliases:
- students AS s
- enrollments AS e
- courses AS c

Example:
SELECT COUNT(DISTINCT s.roll_no) AS student_count, COUNT(DISTINCT c.faculty) AS faculty_count
FROM students AS s
JOIN enrollments AS e ON s.roll_no = e.roll_no
JOIN courses AS c ON e.course_id = c.course_id
WHERE s.department = 'CSE'

Faculty count by department example:
SELECT department, COUNT(DISTINCT faculty) AS faculty_count
FROM courses
WHERE department = 'CSE'
GROUP BY department

Faculty list by department example:
SELECT DISTINCT faculty
FROM courses
WHERE department = 'CSE'

Students taught by faculty example:
SELECT DISTINCT s.roll_no, s.name, s.department
FROM courses AS c
JOIN enrollments AS e ON c.course_id = e.course_id
JOIN students AS s ON e.roll_no = s.roll_no
WHERE c.faculty = 'Dr. Sharma'

Safe department comparison example:
SELECT
student_stats.department,
student_stats.student_count,
student_stats.average_cgpa,
student_stats.average_attendance,
COALESCE(course_stats.courses_offered, 0) AS courses_offered,
COALESCE(enrollment_stats.total_enrollments, 0) AS total_enrollments,
ROUND(COALESCE(enrollment_stats.total_enrollments, 0) / student_stats.student_count, 2) AS average_enrollments_per_student
FROM (
    SELECT
    s.department,
    COUNT(DISTINCT s.roll_no) AS student_count,
    ROUND(AVG(s.cgpa), 2) AS average_cgpa,
    ROUND(AVG(s.attendance), 2) AS average_attendance
    FROM students AS s
    GROUP BY s.department
    HAVING COUNT(DISTINCT s.roll_no) >= 3
) AS student_stats
LEFT JOIN (
    SELECT
    c.department,
    COUNT(DISTINCT c.course_id) AS courses_offered
    FROM courses AS c
    GROUP BY c.department
) AS course_stats ON student_stats.department = course_stats.department
LEFT JOIN (
    SELECT
    s.department,
    COUNT(e.enrollment_id) AS total_enrollments
    FROM students AS s
    LEFT JOIN enrollments AS e ON s.roll_no = e.roll_no
    GROUP BY s.department
) AS enrollment_stats ON student_stats.department = enrollment_stats.department
ORDER BY student_stats.average_cgpa DESC, student_stats.average_attendance DESC

If a department comparison explicitly asks for distinct faculty members, extend course_stats with:
COUNT(DISTINCT c.faculty) AS faculty_count
Then select:
COALESCE(course_stats.faculty_count, 0) AS faculty_count
Do not reference course_stats.faculty directly in the outer query.

Database Schema:
{DATABASE_SCHEMA}

{context_section}

Question:
{user_question}
""".strip()


def build_answer_prompt(question: str, sql: str, results: str) -> str:
    return f"""
Question:
{question}

SQL Query:
{sql}

Available Schema:
{DATABASE_SCHEMA}

Database Results:
{results}

You are a helpful university database assistant.

Answer the user's question in plain English for a non-technical user.
Lead with the direct conversational answer.
Do not simply restate table rows.
Be concise but complete.
Do not invent information that is not present in the database results.
Only make claims supported by the returned SQL results and the available schema.
Do not introduce concepts that are not present in the schema or result columns.
Do not say "credits earned" unless a returned result column explicitly uses that meaning.
If discussing credits from the courses table, say "course credits offered" or "credits associated with courses".
Do not imply successful completion, teaching quality, student effort, motivation, course difficulty, or causality unless the returned columns directly support it.
Use at most 5 sentences unless the user explicitly asks for a detailed report.
Do not repeat the same sentence or idea.
Mention the most important 3 to 5 findings instead of narrating every row.
If there are many rows, summarize the pattern and say the full table is available in Developer Mode.
If the result is empty, say: No matching records were found.
Prefer careful wording such as "Based on the available data", "The database suggests", or "This indicates a pattern, not a confirmed cause" when interpreting results.

If the user asks why, asks for reasons, asks for causes, or asks you to explain why:
- Use the database results only to identify visible patterns.
- Clearly state that the database can show patterns but may not contain causal explanations.
- Do not claim causes such as teaching quality, student behavior, syllabus difficulty, or personal reasons unless those fields are directly present in the results.
- Say that the database does not contain enough information to determine the exact reason when causal evidence is not present.
- Add this line when useful: Insight: This is a pattern-based observation, not a confirmed cause.
""".strip()


def build_sql_repair_prompt(
    user_question: str,
    invalid_sql: str,
    validation_error: str,
    conversation_context: str = "",
) -> str:
    context_section = ""
    if conversation_context.strip():
        context_section = f"""
Recent conversation context:
{conversation_context}

Context rules:
- Use recent context only to resolve ambiguous references.
- Resolve singular references using the relevant last_* value.
- Resolve plural references using the relevant mentioned_* list and use IN (...) when needed.
- If the current question is self-contained, ignore previous context.
- Do not let previous context override the current user question.
- Never invent a resolved entity that is absent from the provided context.
""".strip()

    return f"""
You are an expert MySQL assistant.

The SQL below was rejected by validation:
{invalid_sql}

Validation error:
{validation_error}

Rewrite it as valid MySQL SELECT SQL.
Return only executable SQL.
Do not use markdown.
Do not explain.
Do not use INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, TRUNCATE, or other data-changing statements.
Never invent tables or columns that are not in the schema.
Use table aliases and qualify ambiguous columns.
If the query uses GROUP BY, every GROUP BY expression must appear in SELECT.
Never reference a column through a subquery alias unless that column is explicitly selected inside the subquery.
Use the smallest necessary set of tables and prefer direct table lookup when one table contains all requested fields.
Avoid one-to-many joins that duplicate course rows.
Use COUNT(DISTINCT s.roll_no) for student counts.
Use COUNT(DISTINCT c.course_id) for course counts.
Use COUNT(e.enrollment_id) for enrollment counts.
Avoid SUM(c.credits) after joins unless it is protected with DISTINCT or a safe grouped subquery.
For faculty count/list by department, use courses directly and do not join students or enrollments.
For simple course listings by faculty, use courses directly and do not join students or enrollments.
For questions about students taught by a faculty, join courses to enrollments to students.

Database Schema:
{DATABASE_SCHEMA}

{context_section}

Original question:
{user_question}
""".strip()
