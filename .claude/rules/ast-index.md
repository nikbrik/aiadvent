# ast-index Rules

Use `ast-index` or the `ast-index` MCP tools first for structural code
navigation: files, symbols, classes, usages, callers, implementations, refs,
outlines, modules, dependencies, and project maps.

Use `rg` for raw text, regex, comments, exact string literals, or when
ast-index returns no useful hits.

Before reading a large source file, run:

```bash
ast-index outline path/to/file
```

Keep the index fresh:

```bash
export AST_INDEX_DB_PATH=/Users/nikita/code/aiadvent/.ast-index/index.db
ast-index stats
ast-index update
```

Index is local and gitignored. After pull/rebase or noticeable code changes,
run:

```bash
AST_INDEX_DB_PATH=/Users/nikita/code/aiadvent/.ast-index/index.db ast-index update
```

Run `ast-index rebuild` only for first setup or a broken index.
