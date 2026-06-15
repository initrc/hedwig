# AGENTS.md

## Ravel Conventions

Before creating or modifying any tasks or design docs, read `ravel/docs/ravel-conventions.md` and follow those conventions strictly.

### Creating Tasks

When the user says "create tasks", "add a task", "create a Ravel task", or similar:

1. Read `ravel/docs/ravel-conventions.md` to confirm the current format.
2. Find the next task ID, create the file, and write the frontmatter and body per the conventions doc.
3. Do NOT use the TaskCreate tool for Ravel tasks — write the task file directly.

## Language & Comments

Write code and comments in clear, plain English.

- **Name things so the name carries the meaning.** A good name removes the need for a comment. If a name needs a comment to explain what it really is, fix the name instead.
- **Keep comments succinct.** Say each thing once. Explain *why*, not *what the code already says*. Don't pad with filler or restate a field's meaning in two places.
- **Avoid jargon and look-it-up words.** Prefer "the sample emails" over "the corpus", "the language model" over a bare "the model". If a term needs a glossary, it's the wrong term.
- **Match how much comment a thing deserves.** Two lines of code rarely need six lines of comment. If the comment is longer than the code and mostly apologizing for it, the code or the name is the problem.
