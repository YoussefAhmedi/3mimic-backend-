# 3Mimic — Backend

Django + DRF API for the 3Mimic app (*Listen. Mimic. Master.*): Shadowing, Listening, placement quiz, dictionary.

## Run
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # then edit
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver 0.0.0.0:8000
python manage.py test           # 105 tests
```
Without `DB_NAME` exported in the environment the project uses SQLite.

## Levels
12 internal levels, 6 visible: `A1, A1.1, A2, A2.1, B1, B1.1, B2, B2.1, C1, C1.1, C2, C2.1`
(Level 1, 1.1, … 6, 6.1). A `.1` level has `parent` = its base level and is **shown to users as the base level**
(`display_name` / `display_level_number` in every level payload).

**Progression** (`learning_services/progression.py`)
* 300 clips heard in the base level → moved to the `.1` level (no time condition).
* 300 clips heard in the `.1` level **and** ≥ 60 days since entering the level → moved to the next base level.
  Otherwise the user stays in the `.1` level and its clips repeat.
* Home progress % = the slower of the two conditions (clips / days). `LEVEL_SNIPPETS_PER_STAGE`, `LEVEL_MIN_DAYS` in `.env`.
* "Heard" = completed once per clip per cycle (Shadowing: played to the end then Next; Listening: question answered).

## Content: the clips JSON
Admin → Videos → **Import clips (JSON: captions + quiz)**, or `python manage.py import_clips file.json [--dry-run]`.
```json
{
  "video": "https://youtu.be/FkZo43H39OY",
  "lang": "en",
  "clips": [
    {"time": ["00:00:30", "00:00:40"], "level": ["B1", "B1.1"], "captions": ["Automatic"]},
    {"time": ["00:03:22", "00:03:39"], "level": ["B1.1"],
     "captions": [["00:03:22", "00:03:24", "Where's the dragon warrior?"], "Automatic",
                  ["00:03:27", "00:03:30", "You think I'm a fool?"]],
     "quiz": "1", "question": "…", "options": ["right answer", "wrong", "wrong"]}
  ]
}
```
* One snippet is created per (clip, level). Re-importing updates captions/quiz instead of duplicating.
* `"Automatic"` = YouTube captions fetched **live** (cached in memory 24 h, never stored). Manual lines win where they overlap.
  A manual line can carry `"translations": {"ar": "…"}`.
* `quiz` (`"quiz": "1"` + sibling `question` / `options` keys, or a nested `{"question", "options"}` object) marks a clip
  for the placement quiz. **The right answer is always the FIRST option** (add `"correct": 2` only to override); the app
  shows the options in a random order. Quiz clips are also listed in admin → **Quiz snippets**.
* The text may be pasted as-is: unquoted URL, `Automatic` without quotes, trailing commas, a ```json fence.
* Level codes must exist (`B1.2` does not). Everything is validated first; nothing is saved if anything is wrong.

## Placement quiz (`learning_services/placement.py`)
One random quiz clip per level in this order: `A1.1 A2 A2.1 B1 B1.1 B2 B2.1 C1 C1.1 C2`; options are shuffled per attempt.
* all right → `C2.1`
* otherwise the **lowest level answered wrongly**, **but the lowest wrong answer is forgiven once if it is an isolated slip**
  (the next question was right): wrong `B1.1 B2 B2.1` → `B1.1`; wrong `A2` only → `C2.1`; wrong `B1` and `B2.1` → `B2.1`
* first three all wrong → `A1.1` and the quiz stops
Grading is server-side; correct answers are never sent before the end. `placement_result()` is a small pure function — tweak it freely.

## Endpoints (all under `/api/`, JWT unless noted)
| | |
|--|--|
| `GET languages/`, `GET levels/` (public) | languages (with flag), 12 levels |
| `POST auth/google/`, `POST auth/refresh/`, `POST auth/logout/` | login = register |
| `GET/PATCH me/`, `POST me/change-level/`, `GET me/progress/` | profile, native/learning language, level card |
| `GET snippets/queue/?count=3&exclude=1,2` | next clips in advance (no state change) |
| `POST snippets/{id}/complete/ {mode}`, `skip/`, `replay/` | progress; `complete` returns `level_event` |
| `GET snippets/{id}/captions/` | synchronized captions + native translation |
| `GET snippets/{id}/listening/` | fill-in-the-missing-word question (3 options) |
| `POST transcribe/` (multipart `audio`, `snippet`) | Shadowing recording → text + match score vs the captions |
| `POST placement/start/`, `POST placement/{id}/answer/`, `GET placement/{id}/review/`, `POST placement/{id}/accept/` | quiz |
| `GET dictionary/lookup/?word=&context=` | word popup |
| `GET/POST words/`, `DELETE words/{entry}/` | Words tab |
| `GET/POST favorites/`, `DELETE favorites/{snippet}/` | Favorites tab |

Swagger: `/api/docs/`.

## Notes
* Captions come from the `youtube-transcript-api` package. YouTube often blocks datacenter IPs — if captions return
  `"status": "unavailable"` from your server, type the lines by hand (`captions`) or proxy the requests.
* **Dictionary — free, no AI, no API key.** Wiktionary (part of speech, IPA, example) + `deep-translator`
  (meaning in the user's native language). Each word is looked up once, then stored (`DictionaryEntry`, editable in the admin).
  Try it: `python manage.py lookup_word como es ar`. If Wiktionary has no page the translation alone is used;
  if the network fails nothing is cached and the app says "dictionary unavailable". `DICTIONARY_PROVIDER=none` disables lookups.
  deep-translator uses Google Translate's free web endpoint: fine for one request per new word, but not an official quota.
* **Caption translation:** hand-written `translations` first, then YouTube's translated track (only for `Automatic` captions),
  then the free translator (Google's free endpoint, then MyMemory). Every sentence is translated ONCE and kept in the
  database (`CachedTranslation`, admin → Vocabulary), so restarts, rate limits and blocked IPs never cost a second translation.
  Captions are returned instantly; translations come from `GET snippets/{id}/translations/` (`"complete": false` = ask again later).
  **Translate everything up front** (recommended, safe to stop and re-run):
  `python manage.py translate_captions --native ar --sleep 2`
  Optional `.env`: `MYMEMORY_EMAIL=you@example.com` raises MyMemory from 5 000 to 50 000 characters/day.
* **Listening hint:** `translation` is the translation of the sentence *with the blank* (safe before answering),
  `translation_full` is shown only after answering.
* **Speech-to-text (Shadowing recordings):** `faster-whisper` (open source, runs on this server, no limits).
  `.env`: `TRANSCRIPTION_PROVIDER=whisper|none`, `WHISPER_MODEL=tiny|base|small|medium` (downloaded on first use; `base` is
  a good start on CPU). `pip install -r requirements.txt` installs it; the first recording takes longer while the model downloads.
