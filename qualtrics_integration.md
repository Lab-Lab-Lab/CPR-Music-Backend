I've compared the two and checked whether they merge cleanly. Here's the comparison.

## Your colleague's version and your branch

| | **main: `teleband/research`** (a3a6b0e) | **your branch: `teleband/studies`** (25d5048) |
|---|---|---|
| **What it covers** | Repeated surveys for teachers who already use the app: reminders, completion tracking, a setup checklist | Recruitment and consent: invite a teacher, run the Qualtrics consent survey, create their account, assign their pieces |
| **How someone joins a study** | A researcher adds an existing user as a `StudyParticipant` in admin. Consent happens outside the app. | A researcher enters an email in admin. The app creates the account if needed and emails the study's Qualtrics link. Participants move through statuses (pending → consented/declined/screened_out → active/withdrawn/completed). |
| **Surveys** | Many per study (`Survey` with `due_after_days`), each due a set number of days after the participant's `start_date` | One consent survey per study (`qualtrics_survey_id`) |
| **What Qualtrics sends back** | The end-of-survey redirect hits `/research/surveys/complete/?mcpr=<signed token>&rid=...` in the teacher's browser | Qualtrics calls the server directly (`/api/qualtrics/{slug}/consent`, `/declined`), checked against a per-study `X-Study-Secret` that can be rotated. The browser then goes to `/s/{slug}/onboard`, which keeps checking until the consent call has arrived. |
| **ID that Qualtrics sees** | `signing.dumps({"u": user.pk, "s": survey.pk})`. This is signed but not encrypted, so the internal user pk can be read from it. | A random `pid` (`p_xxxxxxxxxxxx`) that is only used for that one study |
| **Onboarding** | New field `User.onboarded_at` (existing users are backfilled). `/api/users/onboarding/` checks for a course with students. | A consented teacher with no password is sent to allauth's set-password page. `PlannedPiece` assigns the chosen pieces and activities when the teacher creates a course. |
| **Research design** | none | Experimental conditions (balanced by the app or posted by Qualtrics), exclusion based on other studies, `max_enrollment`, withdrawal |
| **Researcher tools** | Superuser status page (survey grid, last login, number of courses and assignments), `/api/surveys/` for the frontend's reminders, `seed_research_demo` command | Admin invite form, "resend invitation" action, edit history (django-reversion) on both models |
| **Tests** | 13 survey tests + onboarding tests | 21 tests |

## Weaknesses in main's version
- **Completing a survey isn't verified.** Anyone with the redirect URL can record a completion, and the token stays valid for 60 days. That's fine for deciding whether to show a reminder, but not as a research record.
- **The internal user pk goes to Qualtrics.** It's readable from the `mcpr` token, which is a privacy and IRB concern your `pid` avoids.
- **The completion view doesn't check much.** `survey_complete_view` doesn't confirm the user still exists or is a participant. A token for a deleted user would hit a foreign-key error (500) instead of the "invalid" redirect.
- **It assumes the teacher already has an account and is logged in**, so it can't handle first contact or consent.

## Weaknesses in your branch
- Only one survey per study, so it can't schedule follow-up surveys.
- No reminder API, status dashboard or `onboarded_at` checklist.

## They can't coexist as they are
- **Text conflicts:** `git merge-tree` shows conflicts in `config/settings/base.py` and `config/urls.py`. They're trivial to resolve.
- **Clashing models:** both apps define `Study` and `StudyParticipant`, and both put `related_name="study_participations"` on the User FK. With both apps installed, Django's system checks fail with a reverse accessor clash (fields.E304/E305), so the merged code won't start until one is renamed.
- **Two different "Study" concepts** would sit in admin side by side, which would confuse researchers.

## Recommendation
The two versions mostly complement each other: yours handles getting teachers in, and main's handles follow-up afterwards. I'd combine them into one app instead of keeping both:
- Keep your `Study` and `StudyParticipant` as the base (pid, statuses, consent, invites).
- Move over their `Survey`/`SurveyCompletion`, attached to your participant row instead of the user, with `consented_at` as day 0.
- Put the `pid` in follow-up survey links instead of the signed user pk.
- Keep their due-surveys API, status page and `onboarded_at` checklist.

Which app name and models survive is something to decide with your colleague, since main already has their migrations. If those migrations have been applied anywhere beyond local dev, replacing them will need a migration plan.
