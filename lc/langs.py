"""LeetCode language registry.

``slug`` is what the judge API expects; everything else is for laying out the
local solution file.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Language:
    slug: str
    name: str
    ext: str
    comment: str
    #: Rich/pygments lexer name for syntax highlighting.
    lexer: str


LANGUAGES: tuple[Language, ...] = (
    Language("python3", "Python3", ".py", "#", "python"),
    Language("python", "Python", ".py", "#", "python"),
    Language("javascript", "JavaScript", ".js", "//", "javascript"),
    Language("typescript", "TypeScript", ".ts", "//", "typescript"),
    Language("golang", "Go", ".go", "//", "go"),
    Language("cpp", "C++", ".cpp", "//", "cpp"),
    Language("c", "C", ".c", "//", "c"),
    Language("java", "Java", ".java", "//", "java"),
    Language("csharp", "C#", ".cs", "//", "csharp"),
    Language("rust", "Rust", ".rs", "//", "rust"),
    Language("kotlin", "Kotlin", ".kt", "//", "kotlin"),
    Language("swift", "Swift", ".swift", "//", "swift"),
    Language("ruby", "Ruby", ".rb", "#", "ruby"),
    Language("scala", "Scala", ".scala", "//", "scala"),
    Language("php", "PHP", ".php", "//", "php"),
    Language("dart", "Dart", ".dart", "//", "dart"),
    Language("elixir", "Elixir", ".ex", "#", "elixir"),
    Language("erlang", "Erlang", ".erl", "%", "erlang"),
    Language("racket", "Racket", ".rkt", ";", "scheme"),
    Language("bash", "Bash", ".sh", "#", "bash"),
    Language("mysql", "MySQL", ".sql", "--", "sql"),
    Language("mssql", "MS SQL Server", ".sql", "--", "sql"),
    Language("oraclesql", "Oracle SQL", ".sql", "--", "sql"),
    Language("postgresql", "PostgreSQL", ".sql", "--", "sql"),
    Language("pythondata", "Pandas", ".py", "#", "python"),
)

BY_SLUG = {lang.slug: lang for lang in LANGUAGES}

# LeetCode's `codeSnippets[].lang` display names, plus common shorthands users type.
_ALIASES = {
    "py": "python3",
    "python3": "python3",
    "js": "javascript",
    "node": "javascript",
    "ts": "typescript",
    "go": "golang",
    "c++": "cpp",
    "cxx": "cpp",
    "c#": "csharp",
    "rs": "rust",
    "kt": "kotlin",
    "rb": "ruby",
    "sh": "bash",
    "sql": "mysql",
    "pandas": "pythondata",
}


def resolve(name: str) -> Language | None:
    """Map a user-supplied language name onto a registry entry."""
    if not name:
        return None
    key = name.strip().lower()
    if key in BY_SLUG:
        return BY_SLUG[key]
    if key in _ALIASES:
        return BY_SLUG[_ALIASES[key]]
    for lang in LANGUAGES:
        if lang.name.lower() == key:
            return lang
    return None


def by_extension(ext: str) -> Language | None:
    for lang in LANGUAGES:
        if lang.ext == ext:
            return lang
    return None
