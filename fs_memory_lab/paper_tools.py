"""Center tool profiles transcribed from Table 12 (Appendix C.4).

The paper prints parameters, required flags and as-sent descriptions, but not
the complete serialized JSON wrapper. This module supplies that wrapper.
"""

def _field(kind: str, description: str) -> dict:
    return {"type": kind, "description": description}


def _tool(name: str, description: str, fields: dict, required: list[str]) -> dict:
    return {"type": "function", "function": {"name": name, "description": description,
            "parameters": {"type": "object", "properties": fields,
                           "required": required, "additionalProperties": False}}}


TOOL_DEFINITIONS = {
    "view": _tool("view",
        "View the contents of a memory file or list the contents of a memory directory. When viewing a file, contents are shown with line numbers (the YAML frontmatter block, if present, occupies the first lines). When viewing a directory, files and subdirectories are listed as full paths with sizes, and each file line shows the file's frontmatter description, rendered as [description: ...]; the listing shows entries up to 3 path levels below the directory, and directory sizes count their full contents including deeper files not listed.",
        {"path": _field("string", "Memory path to directory or file to view (must be '/memories' or start with '/memories/'). Use '/memories' to see the root directory."),
         "start_line": _field("integer", "Starting line number (1-indexed). Only for files."),
         "end_line": _field("integer", "Ending line number (1-indexed, inclusive). -1 for end of file. Only for files.")}, ["path"]),
    "grep": _tool("grep",
        "Grep-like line search across .md files in memory. Matches a regex pattern against each line individually (does not match across lines); every line is searched, including YAML frontmatter lines. Returns matching lines with file paths and line numbers.",
        {"pattern": _field("string", "Regex pattern to match against each line. Matched per line; cannot span multiple lines."),
         "path": _field("string", "Memory path to search: a directory (all .md files under it are searched recursively) or a single .md file (must be '/memories' or start with '/memories/')."),
         "case_sensitive": _field("boolean", "Whether the search is case-sensitive."),
         "max_results": _field("integer", "Maximum number of matching lines to return.")}, ["pattern"]),
    "create": _tool("create",
        "Create a new memory file at the specified path. The file must have a .md extension; fails if the file already exists. Parent directories that do not exist are created automatically. Files should open with a YAML frontmatter block whose name is a kebab-case slug equal to the filename stem (the name without .md) and whose description is a one-line summary surfaced in directory listings.",
        {"path": _field("string", "Memory path for the new file (must end with .md) (must start with '/memories/')."),
         "file_text": _field("string", "Content to write to the new file. The first lines must be a YAML frontmatter block where name equals the filename stem (kebab-case slug). For example, creating /memories/alice-preferences.md should start with: ---\nname: alice-preferences\ndescription: Alice's taste in music and food.\n---\n\n# Music\n.... The optional metadata: key under the frontmatter accepts free-form key/value pairs.")}, ["path", "file_text"]),
    "str_replace": _tool("str_replace",
        "Replace a unique string in a memory file. The old_str must appear exactly once in the file body (occurrences inside the YAML frontmatter block are ignored for uniqueness). If no match outside frontmatter exists, falls back to searching inside frontmatter so frontmatter fields (e.g., description:) can be edited by anchoring on a unique substring.",
        {"path": _field("string", "Memory path to the file to edit (must start with '/memories/')."),
         "old_str": _field("string", "The string to find. Must occur exactly once in the file body (outside the YAML frontmatter). If absent from the body, the tool falls back to searching inside frontmatter so frontmatter fields can be edited."),
         "new_str": _field("string", "The replacement string.")}, ["path", "old_str", "new_str"]),
    "insert": _tool("insert",
        "Insert text after a specific line number in a memory file. Inserts that would land inside the file's YAML frontmatter block are rejected.",
        {"path": _field("string", "Memory path to the file to edit (must start with '/memories/')."),
         "insert_line": _field("integer", "Insert after this line number. Lines are 1-indexed; N inserts after line N and 0 inserts at the very beginning of the file. Valid range: [0, total_lines]. In a file with a YAML frontmatter block, insert_line must be at or after the closing --- fence's line number; inserts inside the frontmatter are rejected."),
         "insert_text": _field("string", "Text to insert.")}, ["path", "insert_line", "insert_text"]),
    "delete": _tool("delete",
        "Delete a memory file or directory. Directories are deleted recursively with all their contents. Cannot delete the root /memories directory.",
        {"path": _field("string", "Memory path to delete (must start with '/memories/').")}, ["path"]),
    "rename": _tool("rename",
        "Rename or move a file or directory within the memory system. Parent directories for the new path are created automatically; fails if the destination already exists. A file must keep its .md extension, and a directory cannot be renamed to a .md path. For .md files, the response also reports the file's current frontmatter name: field.",
        {"old_path": _field("string", "Current memory path (must start with '/memories/')."),
         "new_path": _field("string", "New memory path (must start with '/memories/').")}, ["old_path", "new_path"]),
    "toc": _tool("toc",
        "Show the heading structure (table of contents) of a memory file, with heading level markers and each section's line range.",
        {"path": _field("string", "Memory path to the .md file (must start with '/memories/').")}, ["path"]),
    "section_read": _tool("section_read",
        "Read a specific section of a memory file by its heading path. The section_path must start from a top-level heading and use ' > ' to traverse into nested sections. The section runs until the next heading of the same or higher level, so nested subsections are included in the returned text.",
        {"path": _field("string", "Memory path to the .md file (must start with '/memories/')."),
         "section_path": _field("string", "Section heading path using ' > ' as the delimiter (the spaces around '>' are required). Must start from a top-level heading, not a nested heading directly. Include heading level markers (e.g., '#', '##') for each segment. Example: '# Notes > ## Setup > ### Dependencies'.")}, ["path", "section_path"]),
}

MANAGEMENT_PROFILE = ("view", "create", "str_replace", "insert", "delete", "rename", "grep")
SEARCH_PROFILE = ("view", "grep", "toc", "section_read")
