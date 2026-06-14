# Ravel Conventions

## Design Docs

Design docs must be stored in:

```txt
ravel/docs/
```

Example:

```txt
ravel/docs/design-v1.md
```

Design docs describe:
- technical architecture
- implementation plans
- important technical decisions

---

## Tasks

Tasks must be stored in:

```txt
ravel/tasks/
```

Task filename format:

```txt
T0003-apply-shadcn-ui-primitives.md
```

Rules:
- Use zero-padded task IDs (`T0001`)
- Use lowercase kebab-case title in filename
- Keep filenames concise
- To pick the next task ID, find the highest-numbered task in `ravel/tasks/` and increment (e.g., if T0032 is highest, next is T0033)

---

## Task Format

Tasks must use Markdown with YAML frontmatter.

Required schema:

```yaml
id: T0003
title: Apply shadcn ui primitives
status: new
dependencies:
  - T0002
```

Rules:
- `id` must match filename
- `title` should be short and action-oriented
- `status` must be one of:
  - `new`
  - `in-progress`
  - `review`
  - `done`
- `dependencies` may be empty

Example with no dependencies:

```yaml
id: T0004
title: Add task parser
status: new
dependencies: []
```

Task body structure (all three sections are required):

```md
# Scope

- What should be implemented — a concise summary of the change.

# Acceptance

- Concrete, verifiable success criteria.
- When code changes are involved, include that the project builds, passes lint, and all tests pass.

# Implementation Notes

- File paths and line numbers the implementer should start from.
- References to related tasks (e.g., "the rebase instruction was added in T0029").
- Architectural decisions — which patterns or libraries to adopt and their tradeoffs.
- Technical constraints or edge cases to watch for.
```

---

## Dependency Rules

- When creating a new task, do not add any task that is done to the dependencies list.
- A task is blocked when any dependency is not `done`.
- Blocked state is computed and should never be written to the task file.

---

## Implementation Workflow

When implementing a task:

1. Read the task file first.
2. Read relevant design docs if referenced.
3. Implement only the requested scope.
4. When ready for human review:
   - update task status to `review`
   - stop and wait
5. After receiving explicit `LGTM`:
   - update task status to `done`
   - create exactly one local git commit

Commit message format:

```txt
T0003: Apply shadcn ui primitives
```

Do not:
- push to remote
- merge branches
- delete worktrees
