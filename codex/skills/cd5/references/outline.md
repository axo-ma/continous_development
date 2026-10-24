# OUTLINE: the project plan

OUTLINE.md is the single readable plan for the human and LLM. Write in the user's language; keep stable milestone IDs. Detailed protocols and history belong in linked artifacts.

## Structure

Preserve this meaning and order; adapt section names to the user's language:

1. Product context, or task context when there is no separate product. Do not invent one.
2. This project's task and scope: its contribution, subject and exclusions.
3. Expected result: the concrete output and decision it enables.
4. Project constraints that affect the solution.
5. Risks.
6. Project milestones.
7. Current milestone plan.

Describe the project, not the CD5 operating procedure. Roles, models, write permissions, STOP, quotas, rotations, installations/downloads, external-directory access and automations remain in their designated instructions or operational records. Do not copy them into OUTLINE or relocate their authoritative sources casually. Omit commentary about preparing an example and generic agent disclaimers; qualify a specific uncertain claim beside that claim.

## Risks and order

A risk threatens feasibility, acceptable cost, or requires a substantial change of approach. A research question or check alone is not a risk. For each material risk describe the threat, consequences, known grounds and uncertainty, response and effect on work order. Do not invent probabilities. Address critical risks before expensive dependent work; independent useful work may proceed. Performing an experiment does not itself resolve a risk.

## Milestones

Each milestone has a stable ID, understandable title, goal/result, entry conditions or dependencies, observable completion criteria, explicit status and meaningful outcome as work proceeds, with dated evidence where available. Future milestones are concise but more than titles; do not freeze every future experiment in advance.

For the active milestone explain what is closed, what remains, main questions and the path through them, order and dependencies. State whether a blocker affects one branch or the whole milestone. Keep the broad sequence here. The exact nearest action, its link to the milestone/unresolved question, ownership and operational state belong in CHECKPOINT without duplication in OUTLINE.

Check completion against the result of the whole milestone. An accepted report, completed CU or one successful substep does not close a broader outcome. If scope expands, reopen the milestone with an explanation while preserving the previous outcome and history. For research, sufficient negative or inconclusive findings may inform a decision; being blocked alone is not completion. Label newly formulated criteria as new; never attribute them retrospectively to old experiments or invent human acceptance.

## Maintenance

Before substantive execution establish the milestone map; expand the current milestone before its next stage. After a significant accepted result or scope change update affected risks, milestones, dependencies and the current plan. Reconcile with CHECKPOINT while preserving the content boundary. Existing plans need evidence-based reconciliation, not guessed historical percentages or silent closure. Updating the skill does not automatically replace a live project's plan.

## Readable Markdown and progress

Use ordinary Markdown. Milestones can be level-three headings under `## Вехи проекта` or `## Milestones`, with labelled paragraphs and criteria lists. The legacy checkbox-list format remains supported. Do not introduce English service fields just to satisfy a parser. Example below is synthetic; its criteria are not accepted criteria for an existing project:

```markdown
## Вехи проекта

### MS-01. Проверить реализуемость

**Статус:** в работе.

**Результат:** решение о допустимом подходе.

**Условие начала:** доступны исходные требования.

**Критерии завершения:** критические ограничения проверены; решение обосновано свидетельствами.

**Что получено:** проверена одна часть; остальные ещё открыты.

## План текущей вехи MS-01

Сначала проверить критическое ограничение, затем зависимые варианты. Свести закрытые и оставшиеся вопросы.
```

Progress is derived from explicit milestone IDs and statuses, not guessed from prose or experiment completion. Preserve the five canonical records; reports are derived views, not an additional plan.
