## Overview

Source: the Confluence page "Todo List User Story" (page id 393233, version 1). It describes a user story for managing a simple task list from the command line, with acceptance criteria for create, view, complete, reopen and delete. The configured `requirements_sources` contain only this page; no Jira issue was configured. Every requirement below is taken from the retrieved page body. The page does not state anything about persistence, CLI syntax or id format (see Open Questions).

## Requirements

### Functional

- **REQ-1**: A user can manage a simple list of tasks from the command line. (Source: 393233)
- **REQ-2**: Creating a task gives it a unique id. (Source: 393233)
- **REQ-3**: A newly created task has status `open`, and the application displays its id, title, and status. (Source: 393233)
- **REQ-4**: On create, repeating a no-op produces a clear message. (Source: 393233; see Open Question 1)
- **REQ-5**: On create, an invalid or unknown id produces a clear error. (Source: 393233; see Open Question 1)
- **REQ-6**: Tasks are shown in creation order. (Source: 393233)
- **REQ-7**: An empty list prints a clear empty-list message. (Source: 393233)
- **REQ-8**: Completing an open task changes its status to `done`. (Source: 393233)
- **REQ-9**: Completing an already-done task prints a no-op message. (Source: 393233)
- **REQ-10**: Completing a task with an unknown id produces a clear error and no change. (Source: 393233)
- **REQ-11**: Reopening a done task changes its status to `open`. (Source: 393233)
- **REQ-12**: Reopening an already-open task prints a no-op message. (Source: 393233)
- **REQ-13**: Reopening a task with an unknown id produces a clear error. (Source: 393233)
- **REQ-14**: Deleting a task removes it. (Source: 393233)
- **REQ-15**: Deleting a task with an unknown id produces a clear error. (Source: 393233)
- **REQ-16**: Task titles are free text. (Source: 393233)

### Non-functional

- **REQ-17**: The solution is a small Python command-line application. (Source: 393233)

## Source Register

| Source | URL | Evidence id | Retrieved via |
|---|---|---|---|
| Confluence page "Todo List User Story" (version 1, space id 229378) | https://rbitestuserrj.atlassian.net/wiki/spaces/~71202025eaf9215838446398153749e55e74f1/pages/393233/Todo+List+User+Story | page id 393233 | Atlassian MCP getConfluenceContent (detail=full) |

Atlassian site cloudId: 14ad8031-52a0-412b-92b0-8a6c4bb8e5a9 (from getAccessibleAtlassianResources). No Jira issues were configured or retrieved.

## Open Questions

1. The Create criterion says "Repeating a no-op produces a clear message; an invalid or unknown id produces a clear error." It is unclear what a no-op or an id means for create, because a new task receives its id automatically. Which operation or input does this refer to?
2. Does the task list need to persist between runs, and if so where is it stored? The page does not say.
3. What command and argument syntax should the CLI use (for example subcommands for add, list, done, reopen, delete)?
4. What is the format of the unique id (for example sequential integer or UUID)? What counts as an "invalid" id as opposed to an "unknown" one?
5. Are there any limits or validation rules for titles, such as empty or very long titles? The page says only that titles are free text.
6. Should the view command show the task id, title and status for each task? The page specifies only the ordering and the empty-list message.
7. No Jira stories were configured in `requirements_sources`. Are there linked Jira issues that should also be treated as sources?
