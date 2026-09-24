# AGENTS.md

## Project Instructions

This project is developed primarily through AI coding agents.

Before making changes:

1. Inspect the existing repository structure.
2. Read existing project documentation.
3. If CLAUDE.md exists, read it for project context and conventions.
4. Preserve the existing architecture unless there is a clear reason to change it.

## Autonomous Development

When given a development or code-review task:

1. Understand the requested goal.
2. Inspect all relevant existing code before modifying it.
3. Create an implementation plan internally.
4. Execute the plan continuously.
5. Do not stop after completing an intermediate step.
6. Do not ask the user whether to continue.
7. If additional problems are discovered while working, investigate and fix them when they are clearly within scope.
8. Run relevant tests after modifications.
9. If tests fail, diagnose the failure, fix it, and run the tests again.
10. Continue until the requested task is fully implemented and validated.

## Code Review Workflow

For repository-wide review tasks, use this loop:

Review
→ Find issues
→ Fix issues
→ Run tests
→ Review again
→ Fix remaining issues
→ Run regression tests

Do not stop merely because one review pass found several issues.

A review task is complete only when:
- the relevant code has been reviewed;
- clearly actionable issues have been fixed;
- tests pass;
- a final verification pass finds no additional clear issues.

## Validation

When available, run:

- pytest
- lint
- type checking
- project-specific validation commands

Do not claim success when tests are failing.

## User Interaction

Only stop and ask the user when:

- a required product decision cannot be inferred;
- credentials or secrets are required;
- an operation may cause irreversible data loss;
- there are multiple materially different implementation choices requiring a product decision.

Otherwise make a reasonable engineering decision and continue.

## Git Safety

- Do not delete or overwrite unrelated user changes.
- Do not modify unrelated untracked files.
- Inspect `git status` before and after significant changes.
- Do not commit or push unless explicitly requested.

## Completion Report

When the entire task is complete, report:

1. What was changed
2. Problems found and fixed
3. Tests/validation performed
4. Remaining known risks
5. Git status summary
