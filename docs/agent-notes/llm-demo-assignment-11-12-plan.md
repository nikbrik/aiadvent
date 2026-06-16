# План выполнения Day 11 + Day 12: memory model и personalization

## Краткая цель

Нужно заменить Day 10 demo с 7 стратегиями контекста на одного ассистента с явной моделью памяти и персонализацией поверх нее.

Итоговый snapshot должен показывать:

- как ассистент делит память на слои;
- что именно сохраняется в каждый слой;
- как эти данные попадают в prompt;
- как память влияет на ответ;
- как user profile автоматически влияет на каждый запрос;
- как один и тот же запрос меняется для разных профилей.

Главный принцип реализации: не "магическая память", а видимая модель памяти: слой -> запись -> причина сохранения -> prompt -> ответ.

## Требования как quality gates

### Day 11: модель памяти

- Есть минимум 3 слоя памяти:
  - short-term memory: текущий диалог;
  - working memory: данные текущей задачи;
  - long-term memory: профиль, предпочтения, решения, знания.
- Разные типы памяти хранятся отдельно.
- Агент явно выбирает, что и куда сохранять.
- UI показывает, какие данные попали в каждый слой.
- Prompt preview показывает, какие слои подключены к LLM-запросу.
- Демо показывает, что память влияет на ответ.

### Day 12: персонализация

- Есть user profile.
- В профиле явно описаны:
  - стиль ответа;
  - формат ответа;
  - ограничения;
  - устойчивые предпочтения пользователя.
- Активный профиль подключается к каждому запросу автоматически.
- Есть несколько профилей для сравнения.
- Демо показывает разные ответы для разных профилей.
- Пользователь не обязан повторять preference в финальном запросе.

### Проектные ограничения

- OpenRouter остается explicit REST через `httpx.post`.
- Не добавлять OpenAI SDK, LangChain, Streamlit, Gradio.
- `OPENROUTER_API_KEY` остается только на backend.
- Не делать реальные OpenRouter calls без разрешения.
- Основные проверки сначала no-network через fake LLM.
- Snapshot model: совместимость со старыми днями не обязательна, если мешает Day 11/12.

## Что изучить перед реализацией

### Backend

- `llm_demo/agent.py`
  - `FileMemoryStore`;
  - `ChatAgent.respond`;
  - `default_memory`;
  - `normalize_memory`;
  - `public_memory`;
  - current Day 10 prompt builders;
  - current profile memory update helpers.
- `llm_demo/server.py`
  - `/api/chat`;
  - `/api/chat/new`;
  - `/api/chat/resume`;
  - `/api/demo/*`;
  - current live demo runner: `start`, `continue-step`, `stop`, resumable `demo_run`.
- `llm_demo/llm_client.py`
  - сохранить текущий `httpx.post` boundary без архитектурных изменений.
- `llm_demo/demo_script.py`
  - заменить Day 10 context-strategy scenario на Day 11/12 memory/persona scenario.

### Frontend

- `llm_demo/static/index.html`
  - сохранить общий cockpit: toolbar, timeline, chat, inspector, comparison table;
  - заменить strategy tabs на profile selector;
  - заменить strategy state renderer на memory layer renderer.
- `llm_demo/static/style.css`
  - переиспользовать панели, timeline, chips, metric grid, table;
  - удалить или переименовать branch/strategy-specific styling.

### Tests

- `llm_demo/test_agent_persistence.py`
  - сохранить подход с `FakeLLM`;
  - заменить Day 10 strategy tests на Day 11/12 memory/profile tests.

### Docs

- `docs/specs/assignment-10-context-strategies.md`
- `docs/agent-notes/llm-demo-assignment-10.md`
- `docs/specs/assignment-6-first-agent.md`
- `docs/specs/assignment-7-context-persistence.md`
- `docs/specs/submission-snapshot-policy.md`
- `docs/README.md`
- `llm_demo/README.md`
- `AGENTS.md`

## Что переиспользовать

### Обязательно сохранить

- `FileMemoryStore`
  - per-client JSON under `llm_demo/data/clients/<client_id>.json`;
  - safe client id;
  - atomic save через temp file + `os.replace`.
- `client_id` cookie flow из `server.py`.
- `ChatAgent.respond` как основной orchestration shape:
  - validate input;
  - load memory;
  - build prompt;
  - call `self.llm`;
  - update memory;
  - save memory;
  - return public state.
- `agent_options`
  - модель можно оставить `meta-llama/llama-3-8b-instruct`;
  - reasoning excluded;
  - provider fallback as now.
- `completion_metadata`, token/cost/duration metrics.
- Current UI shell:
  - timeline;
  - transcript;
  - metadata line;
  - prompt preview;
  - comparison table;
  - live demo loop.
- Demo mechanics:
  - `Next step`;
  - `Run active`;
  - `Run all`;
  - `Continue`;
  - `Stop`;
  - recoverable demo errors.

### Можно частично переиспользовать

- Current `profile_summaries` idea:
  - facts;
  - inferences;
  - style;
  - current summary;
  - archived summaries.
- Current `context_leveling` idea:
  - goal;
  - audience;
  - constraints;
  - decisions;
  - open questions;
  - recent focus.
- Current `extract_fact_dict`, `append_unique`, `clean_items`, `clean_messages`, `estimate_tokens_for_messages`, `prompt_to_text`.

## Что убрать из Day 10

### Backend removal/replacement

Удалить как product behavior:

- `STRATEGIES`;
- `STRATEGY_IDS`;
- `STRATEGY_BY_ID`;
- `active_strategy`;
- `strategies` state dict;
- `set_strategy`;
- `reset_strategy`;
- `create_checkpoint`;
- `create_branches`;
- `switch_branch`;
- `build_strategy_prompt`;
- `build_sliding_prompt`;
- `build_sticky_prompt`;
- `build_branching_prompt`;
- `build_token_cut_prompt`;
- `build_context_leveling_prompt`;
- `build_recreation_prompt`;
- `comparison_result_for` по стратегиям.

Удалить routes:

- `POST /api/context/strategy`;
- `POST /api/context/checkpoint`;
- `POST /api/context/branches`;
- `POST /api/context/branch`.

Заменить:

- `comparison_results` по стратегиям -> `profile_comparison_results`;
- `context_report` -> `memory_report`;
- `strategy_state` -> `memory_layers`;
- `active_strategy` -> `active_profile_id`.

### Frontend removal/replacement

Удалить или заменить:

- strategy tabs;
- branch controls;
- branch state rendering;
- strategy state renderer;
- Day 10 comparison columns: Strategy, UX score, lost details by strategy.

Новые UI concepts:

- active profile selector;
- memory layer inspector;
- save event list;
- profile comparison table.

## Архитектура backend

### New memory schema

Предлагаемая версия: `version: 3`.

```json
{
  "version": 3,
  "created_at": "...",
  "updated_at": "...",
  "demo_progress": 0,
  "demo_run": {},
  "profile_comparison_results": [],
  "memory_layers": {
    "short_term": {
      "current_chat": {
        "id": "...",
        "started_at": "...",
        "summary": "",
        "messages": []
      },
      "archived_chats": []
    },
    "working": {
      "goal": "",
      "audience": "",
      "constraints": [],
      "decisions": [],
      "open_questions": [],
      "artifacts": [],
      "recent_focus": ""
    },
    "long_term": {
      "active_profile_id": "concise_engineer",
      "profiles": {
        "concise_engineer": {
          "id": "concise_engineer",
          "name": "Concise engineer",
          "style": "Кратко, структурно, без воды.",
          "format": "Bullets, commands, acceptance criteria.",
          "constraints": [
            "Не повторять очевидное",
            "Сначала риски и решения"
          ],
          "preferences": []
        }
      },
      "user_facts": [],
      "durable_decisions": [],
      "knowledge": [],
      "inferences": []
    }
  },
  "memory_events": [],
  "last_memory_report": {}
}
```

### Memory layers

#### short_term

Назначение: текущий диалог.

Хранит:

- current chat messages;
- current chat summary;
- archived chats for resume.

Правила:

- каждый user/assistant turn попадает сюда;
- bounded by `MAX_STORED_MESSAGES`;
- `POST /api/chat/new` сбрасывает current chat, но не сбрасывает working/long-term.

#### working

Назначение: данные текущей задачи.

Хранит:

- goal;
- audience;
- constraints;
- decisions;
- open questions;
- artifacts;
- recent focus.

Правила:

- сюда попадают task-specific facts;
- noise сюда не попадает;
- working memory живет между чатами, пока пользователь не очистит память или demo reset.

#### long_term

Назначение: устойчивые данные о пользователе и персонализация.

Хранит:

- profiles;
- active profile;
- user facts;
- durable decisions;
- knowledge;
- inferences.

Правила:

- сюда попадают stable preferences and identity facts;
- active profile подключается к каждому prompt;
- inferences маркируются как tentative, не как facts.

### Memory event

Каждое явное сохранение создает event:

```json
{
  "layer": "working",
  "type": "constraint",
  "key": "offline_first",
  "value": "Приложение должно работать offline-first",
  "source": "user_message",
  "reason": "User stated task constraint",
  "created_at": "..."
}
```

UI должен показывать последние events как доказательство явного выбора.

## Memory routing

### Router function

Добавить deterministic helper:

```python
def route_memory_items(memory, user_message, assistant_reply=None):
    ...
```

Он возвращает список save operations/events и применяет их к memory.

### Routing rules

#### short_term

Всегда:

- user message;
- assistant reply.

#### working

Если user message содержит task data:

- `цель`, `задача`, `продукт`, `ТЗ` -> `working.goal`;
- `аудитория`, `пользователи`, `для кого` -> `working.audience`;
- `ограничение`, `нельзя`, `без`, `только`, `обязательно`, `критично` -> `working.constraints`;
- `решили`, `фиксируем`, `выбираем` -> `working.decisions`;
- `вопрос`, `неясно`, `открыто`, `под вопросом` -> `working.open_questions`;
- `артефакт`, `итог`, `документ`, `план` -> `working.artifacts`.

#### long_term

Если user message содержит stable profile data:

- `я предпочитаю`, `отвечай`, `пиши`, `формат`, `стиль` -> active profile preferences/style/format;
- `меня зовут`, `я работаю`, `мой проект`, `я учусь` -> `long_term.user_facts`;
- устойчивые решения пользователя -> `long_term.durable_decisions`;
- broad inferred behavior -> `long_term.inferences` only if clearly tentative.

#### no-save

Шум:

- late unrelated details;
- jokes;
- one-off comments;
- demo noise.

Такой текст остается в short-term only.

## Prompt architecture

### Prompt order

`build_memory_prompt(memory, user_message)` должен строить messages так:

1. System instructions:
   - Russian-speaking educational assistant;
   - do not invent facts;
   - say when memory is missing;
   - current user message wins over memory.
2. Active profile:
   - style;
   - format;
   - constraints;
   - preferences.
3. Long-term memory:
   - user facts;
   - durable decisions;
   - knowledge;
   - tentative inferences.
4. Working memory:
   - goal;
   - audience;
   - constraints;
   - decisions;
   - open questions;
   - artifacts;
   - recent focus.
5. Short-term memory:
   - recent current chat messages.
6. Current user message.

### Memory report

Каждый response должен обновлять `last_memory_report`:

```json
{
  "included_layers": ["profile", "long_term", "working", "short_term"],
  "context_blocks": ["System", "Active profile", "Working memory", "Recent messages"],
  "saved_events": [],
  "prompt_preview": "...",
  "estimated_prompt_tokens": 0,
  "actual_prompt_tokens": null,
  "actual_total_tokens": null,
  "included_messages": 0,
  "discarded_messages": 0,
  "influence_notes": [
    "Profile requested concise bullet format",
    "Working memory supplied offline-first constraint"
  ]
}
```

## ChatAgent flow

### `respond(client_id, message)`

Target flow:

1. Validate non-empty message.
2. Load memory.
3. Normalize schema v3.
4. Route pre-response memory from user message:
   - working task facts;
   - long-term preferences/facts.
5. Build prompt with active profile and memory layers.
6. Call LLM via `self.llm(messages=messages, **agent_options())`.
7. Extract visible reply.
8. Append user/assistant turn to short-term.
9. Optionally route post-response data if needed.
10. Build memory report:
    - prompt preview;
    - saved events;
    - included layers;
    - token metadata.
11. Save memory.
12. Return public state + `reply` + `metadata`.

### No extra LLM call by default

Current Day 10 profile strategy uses an auxiliary LLM call for memory update. For Day 11/12, prefer deterministic routing first.

Reason:

- no-network tests easier;
- explicit save rules more visible;
- lower OpenRouter cost;
- quality gate asks to explicitly choose what goes where.

Optional later: add auxiliary memory-update call only if deterministic routing is insufficient. Not needed for this assignment.

## Public API

### Keep

- `GET /api/chat`
- `POST /api/chat`
- `POST /api/chat/new`
- `POST /api/chat/resume`
- `DELETE /api/chat`
- `POST /api/demo/reset`
- `POST /api/demo/next`
- `POST /api/demo/start-active`
- `POST /api/demo/start-all`
- `POST /api/demo/continue-step`
- `POST /api/demo/stop`

### Add

#### `POST /api/profile`

Request:

```json
{
  "profile_id": "teacher"
}
```

Response:

- same public memory state as `GET /api/chat`;
- active profile changed.

### Replace semantics

#### `POST /api/demo/start-active`

Run full memory demo for current active profile.

#### `POST /api/demo/start-all`

Run same scenario across all demo profiles and populate profile comparison.

#### `comparison_results`

Rename or reinterpret as `profile_comparison_results`.

## Public response shape

`GET /api/chat` and `POST /api/chat` should return:

```json
{
  "active_profile_id": "concise_engineer",
  "profiles": [],
  "messages": [],
  "memory_layers": {
    "short_term": {},
    "working": {},
    "long_term": {}
  },
  "memory_events": [],
  "memory_report": {},
  "profile_comparison_results": [],
  "archived_chats": [],
  "demo_progress": 0,
  "demo_run": {}
}
```

For `POST /api/chat`, also:

```json
{
  "reply": "...",
  "metadata": {}
}
```

## Frontend architecture

### Layout

Keep current page structure:

- hero;
- toolbar;
- workspace with chat + inspector;
- comparison table.

Change labels:

- title: `AI Advent День 11+12`;
- heading: `Память и персонализация`;
- lead: `Один ассистент явно раскладывает память по слоям и отвечает с учетом профиля.`

### Toolbar

Replace `strategy-tabs` with profile selector:

- `Concise engineer`;
- `Teacher`;
- `Strict reviewer`.

Buttons:

- `Reset demo`;
- `Next step`;
- `Run profile`;
- `Run all profiles`;
- `Continue`;
- `Stop`.

### Chat panel

Keep:

- messages;
- textarea;
- send;
- new chat;
- clear memory;
- metadata.

Change active title:

- show active profile name.

### Inspector panel

Replace `Context sent to model` with `Memory sent to model`.

Show:

- included layers chips;
- metrics;
- prompt preview.

Add sections:

- `Saved this turn`
  - last memory events.
- `Influence`
  - profile/memory influence notes.

### Memory state panel

Replace `State`/strategy renderer with:

- `Short-term`
  - current messages count;
  - current summary;
  - archived chats count.
- `Working`
  - goal;
  - audience;
  - constraints;
  - decisions;
  - open questions;
  - artifacts.
- `Long-term`
  - active profile;
  - user facts;
  - durable decisions;
  - knowledge;
  - inferences.

### Comparison table

Columns:

- `Profile`;
- `Style/format`;
- `Memory used`;
- `Tokens`;
- `Cost/time`;
- `Final answer`.

Rows are produced by `Run all profiles`.

## Demo scenario

Replace Day 10 `DEMO_MESSAGES` with Day 11/12 scenario.

Suggested 10-step scenario:

1. User identity/preference:
   - "Меня зовут Никита. Отвечай кратко, структурно, без воды."
   - Expected: long-term profile/user facts.
2. Task goal:
   - "Готовим ТЗ для Android-приложения: семейный задачник для родителей и детей 7-12."
   - Expected: working goal/audience.
3. Constraints:
   - "MVP нужен за 3 недели, offline-first, бюджет маленький, без ML."
   - Expected: working constraints.
4. Decisions:
   - "Фиксируем роли: родитель, ребенок, админ семьи."
   - Expected: working decisions.
5. MVP scope:
   - "Must-have: списки дел, назначение задач, дедлайны, локальные напоминания."
   - Expected: working artifacts/decisions.
6. Noise:
   - "Шум для проверки: вчера я смотрел видео про дизайн кофеварок."
   - Expected: short-term only, not working/long-term.
7. Open questions:
   - "Открытые вопросы: синхронизация, конфликты offline-first, уведомления детям."
   - Expected: working open questions.
8. Memory check:
   - "Что ты сохранил в краткосрочную, рабочую и долговременную память?"
   - Expected: answer references layers.
9. New chat boundary:
   - demo runner calls `start_new_chat` before or after this step.
   - User asks: "Собери итоговое ТЗ по текущей задаче."
   - Expected: short-term reset visible, working/long-term still used.
10. Personalization check:
   - "Дай финальный план так, как мне удобно."
   - Expected: active profile style applied automatically.

For `Run all profiles`, final step runs under each profile.

## Demo profiles

### `concise_engineer`

- Style: кратко, технически, без вводных.
- Format: bullets, acceptance criteria, risks.
- Constraints: не пересказывать весь диалог.

Expected answer:

- compact;
- implementation-oriented;
- checklists.

### `teacher`

- Style: понятно, пошагово.
- Format: sections with short explanations.
- Constraints: avoid jargon without explanation.

Expected answer:

- more explanatory;
- clearer transitions;
- learner-friendly.

### `strict_reviewer`

- Style: skeptical, acceptance-first.
- Format: quality gates, risks, missing data.
- Constraints: call out gaps.

Expected answer:

- starts with acceptance criteria or blockers;
- highlights missing details and risks.

## Backend implementation steps

### Step 1: schema helpers

In `agent.py`:

- add `MEMORY_SCHEMA_VERSION = 3`;
- add `DEFAULT_PROFILE_ID`;
- add `PROFILE_DEFINITIONS`;
- add:
  - `empty_memory_layers`;
  - `empty_short_term`;
  - `empty_working_memory`;
  - `empty_long_term_memory`;
  - `default_profiles`;
  - `default_memory_report`.

### Step 2: migration

Update `normalize_memory`:

- v3 data loads normally;
- old v2 current chat messages migrate to `memory_layers.short_term.current_chat.messages`;
- old `profile` and `profile_summaries` migrate to long-term where possible;
- old Day 10 `strategies` ignored except maybe profile data;
- invalid/corrupt JSON still falls back to default memory.

### Step 3: public state

Replace `public_memory`:

- return `active_profile_id`;
- return list of profiles;
- return active profile;
- return memory layers;
- return recent memory events;
- return memory report;
- return archived chats;
- return demo metadata.

### Step 4: prompt builder

Add:

- `build_memory_prompt(memory, user_message)`;
- `format_active_profile`;
- `format_working_memory`;
- `format_long_term_memory`;
- `format_recent_messages`.

Remove strategy builder dispatch.

### Step 5: routing

Add:

- `route_memory_items`;
- `save_memory_event`;
- `set_working_value`;
- `append_working_item`;
- `append_long_term_item`;
- `update_active_profile_from_text`.

Keep simple deterministic rules. Do not add NLP dependencies.

### Step 6: respond

Rewrite `ChatAgent.respond` around memory layers.

Keep:

- metadata extraction;
- empty reply fallback;
- save flow;
- public response.

### Step 7: profile switching

Add `ChatAgent.set_profile(client_id, profile_id)`.

Validate profile id exists.

### Step 8: chat archive

Update:

- `start_new_chat`;
- `resume_chat`;
- `archive_current_chat`.

They should operate on `memory_layers.short_term`, not top-level `current_chat`.

### Step 9: comparison

Replace `comparison_result_for` with `profile_result_for(snapshot)`:

- profile id/name;
- style/format;
- final answer;
- memory used;
- token/cost/time.

### Step 10: demo runner

Update `server.py` imports and demo loops:

- no `STRATEGY_IDS`;
- use `PROFILE_IDS`;
- `start-active` runs active profile;
- `start-all` iterates profiles;
- `continue_all_one_step` switches profile and resets demo state per profile;
- remove branch-specific code.

## Frontend implementation steps

### Step 1: static labels

Update hero, toolbar, table headers.

### Step 2: profile selector

Replace `renderStrategies` with `renderProfiles`.

Expected button data:

- `data-profile-id`.

Click calls:

- `POST /api/profile`.

### Step 3: render state

Update `renderState`:

- `renderProfiles(data)`;
- `renderTimeline(data)`;
- `renderMessages(data.messages || [])`;
- `renderMemoryReport(data.memory_report || {})`;
- `renderMemoryLayers(data.memory_layers || {})`;
- `renderComparison(data.profile_comparison_results || [])`;
- `renderDemoButtons(data)`.

### Step 4: memory report

Replace `renderContext` with `renderMemoryReport`.

Show:

- included layer chips;
- estimated/actual tokens;
- included/discarded messages;
- saved events;
- influence notes;
- prompt preview.

### Step 5: memory layers

Replace strategy-specific rendering with generic layer renderer.

Use JSON/pre/list renderers already present.

### Step 6: comparison

Update table rendering:

- profile name;
- style/format;
- memory used;
- tokens;
- cost/time;
- final answer.

### Step 7: event handlers

Remove:

- `/api/context/*` handlers;
- branch controls.

Add:

- `/api/profile` handler.

Keep:

- chat submit;
- reset;
- next step;
- run active;
- run all;
- continue;
- stop;
- new chat;
- clear.

## Tests to add/replace

### Memory model tests

- `test_memory_layers_receive_different_data`
  - preference goes long-term;
  - task constraint goes working;
  - normal turn goes short-term.
- `test_noise_does_not_enter_working_or_long_term`
  - noise appears only in short-term messages.
- `test_new_chat_resets_short_term_only`
  - current messages cleared;
  - working and long-term remain.
- `test_memory_report_shows_prompt_layers`
  - active profile, working, long-term, short-term present in report/prompt.
- `test_persisted_memory_survives_agent_restart`
  - v3 JSON reload keeps all layers.

### Personalization tests

- `test_active_profile_is_included_in_every_prompt`
  - switch profile;
  - respond;
  - captured prompt contains profile style/format.
- `test_profile_switch_changes_prompt`
  - same final user message under two profiles;
  - prompts differ.
- `test_profile_preference_saved_from_user_message`
  - "отвечай кратко" updates active profile preference.

### Demo tests

- `test_demo_scenario_populates_all_layers`
  - run all demo messages through fake LLM;
  - assert short/working/long-term populated.
- `test_same_demo_runs_for_all_profiles`
  - run profile comparison;
  - assert result count equals profile count.

### REST boundary tests

- Existing code inspection is likely enough, but add or keep simple test if useful:
  - `llm_client.chat_completion` uses `httpx.post`;
  - request body contains `messages`;
  - API key read from env only in backend.

## Commands to run

No network:

```bash
python -m unittest llm_demo.test_agent_persistence
python -m py_compile llm_demo/server.py llm_demo/llm_client.py llm_demo/agent.py
git diff --check
```

Optional manual smoke after implementation, only local server:

```bash
cd llm_demo
HOST=127.0.0.1 PORT=5050 .\.venv\Scripts\python.exe server.py
```

Then open:

```text
http://127.0.0.1:5050/
```

Do not run real OpenRouter calls without permission.

## Docs updates

Add:

- `docs/specs/assignment-11-memory-model.md`;
- `docs/specs/assignment-12-personalization.md`;
- `docs/agent-notes/llm-demo-assignment-11-12.md`.

Update:

- `docs/README.md`;
- `llm_demo/README.md`;
- `AGENTS.md` if commands/docs map changes.

Docs should say:

- current snapshot is Day 11+12;
- Day 10 strategies intentionally removed;
- memory layers and profiles are current acceptance surface;
- no-network tests first;
- OpenRouter calls still explicit REST.

## Acceptance checklist

- UI no longer shows 7 context strategies.
- UI shows 3 memory layers.
- UI shows active profile.
- UI shows saved memory events.
- Prompt preview includes active profile on every request.
- Prompt preview includes working memory when task facts exist.
- New chat clears current transcript but keeps working/long-term.
- Demo shows at least one item saved to each memory layer.
- Demo shows noise not saved to working/long-term.
- Run all profiles produces multiple final answers.
- Final answers differ according to profile.
- Tests pass no-network.
- `git diff --check` clean.

## Risks and mitigations

### Risk: schema migration breaks old local data

Mitigation:

- `normalize_memory` accepts v2 and invalid data;
- tests cover legacy migration;
- data dir is gitignored, snapshot review uses fresh state.

### Risk: routing feels too heuristic

Mitigation:

- keep rules simple and visible;
- show save events;
- demo uses phrases that map clearly to rules.

### Risk: personalization invisible

Mitigation:

- active profile always shown in UI;
- prompt preview shows profile;
- comparison table shows different profile outputs.

### Risk: accidental real OpenRouter cost

Mitigation:

- no-network tests first;
- warning before `Run all profiles`;
- do not start server or run real calls unless asked.

### Risk: old Day 10 leftovers confuse reviewer

Mitigation:

- remove strategy tabs/routes;
- update README/docs;
- rename reports and comparison labels.

### Risk: UI grows too busy

Mitigation:

- keep current cockpit layout;
- compact chips/lists;
- show JSON only in contained panels;
- no decorative redesign.

## Suggested implementation order

1. Replace backend schema and public snapshot.
2. Replace prompt builder and memory routing.
3. Replace server profile/demo loops.
4. Replace demo script.
5. Replace frontend renderers and labels.
6. Replace tests.
7. Update docs.
8. Run no-network checks.
9. Optional local UI smoke only after user asks to run server.

## Handoff notes

- Worktree was clean before this plan file was added.
- No implementation files were edited for this planning step.
- No server was started.
- No network calls were made.
- Main target files for implementation:
  - `llm_demo/agent.py`;
  - `llm_demo/server.py`;
  - `llm_demo/demo_script.py`;
  - `llm_demo/static/index.html`;
  - `llm_demo/static/style.css`;
  - `llm_demo/test_agent_persistence.py`;
  - docs under `docs/specs` and `docs/agent-notes`.
