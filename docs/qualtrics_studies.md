# Qualtrics Study Onboarding

How to set up a study whose teachers consent through a Qualtrics survey before they get into MusicCPR, and the follow-up surveys they're reminded to take afterwards. Code lives in `teleband/studies/`. (`teleband/research/` is a retired app kept only for its migrations; its last migration copies its data into `studies` and drops its tables.) The design follows Lab-Lab-Lab/cloud-architecture-dev-ops#11.

## How it works

```
Researcher (Django admin) ── invites teacher by email ──► StudyParticipant (pid, status=pending)
                                                              │
Teacher ◄── email with {qualtrics_base_url}/jfe/form/{survey_id}?pid=…&study={slug}
                                                              │
Qualtrics consented branch ── Web Service POST ──► /api/qualtrics/{slug}/consent  (status=consented)
                                                              │
Qualtrics End of Survey ── redirect ──► /s/{slug}/onboard?pid=…
                                                              │
                     no password yet ──► allauth set-password page
                     has a password  ──► "You're enrolled" + link to STUDIES_APP_HOME_URL
```

- Consent is recorded only by the server-to-server callback. The browser redirect only moves the teacher along.
- A `pid` is created per (person × study). It is the only ID Qualtrics ever sees.
- Teachers who already have an account can also start from `/s/{slug}/join` while logged in.

## 1. Create the study in admin

**Admin → Studies → Add**

| Field                     | Value                                                                                                                                                                     |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `slug`                    | Used in every URL, e.g. `pilot-2026`                                                                                                                                      |
| `status`                  | `draft` while testing. `recruiting`: consent callbacks and `/join` work. `closed`: no new participants, but consented ones still get follow-up surveys. `ended`: nothing. |
| `qualtrics_survey_id`     | `SV_xxxxxxxx`                                                                                                                                                             |
| `qualtrics_base_url`      | Your Qualtrics domain, e.g. `https://jmu.qualtrics.com` (or `https://jmu.co1.qualtrics.com`). The emailed survey link is built from this.                                 |
| `current_consent_version` | e.g. `v2-2026-10-01`. Used when Qualtrics doesn't send `consentVersion`.                                                                                                  |
| `config`                  | JSON; see [Study config](#study-config)                                                                                                                                   |
| `max_enrollment`          | Optional cap on consented/active/completed participants                                                                                                                   |
| `qualtrics_api_token_ref` | Stored but not used yet                                                                                                                                                   |

## 2. Copy the callback secret

When you save a new study, the admin generates its callback secret and shows it once in a message at the top of the page. Copy it into the Qualtrics `X-Study-Secret` header (step 3). Only a SHA-256 hash is stored, so the secret can't be shown again.

**Rotation:** if the secret is lost or leaked, select the study in **Admin → Studies** and run **Rotate callback secret**. The new secret is shown once, and the previous one stays valid so callbacks keep working. Update the header in Qualtrics, then run **Revoke previous callback secret**. To cut off a leaked secret right away, run both actions back to back.

## 3. Build the Qualtrics survey

Build this once, save it to the Qualtrics Library, and copy it for each study.

**Survey Flow, top to bottom:**

1. **Embedded Data:** `pid` and `study` (leave blank so they are read from the URL), `consent_version` (fixed value, e.g. `v2-2026-10-01`), `condition`.
2. **Block: Consent.**
3. **Branch: consent = No.** Optionally add a Web Service to `/api/qualtrics/<slug>/declined` (see below), then end the survey or redirect to `https://<backend>/s/${e://Field/study}/onboard?pid=${e://Field/pid}`, which shows "Not enrolled".
4. **Blocks: intake and screening.** For a screen-out, branch the same way as a decline, posting `reason=screened_out`.
5. *(Optional)* **Randomizer** that sets `condition`, only if the study's config has `"assignment": "qualtrics"`.
6. **Web Service** (consented and eligible branch only):
   - URL: `https://<backend>/api/qualtrics/<slug>/consent`
   - Method: `POST`, JSON body
   - Body: `pid=${e://Field/pid}`, `responseId=${e://Field/ResponseID}`, `consentVersion=${e://Field/consent_version}`, `condition=${e://Field/condition}`
   - Header: `X-Study-Secret: <secret>`
7. **Pre-experiment questionnaire blocks.** Put them before the Web Service instead if the app should open only after they're done.
8. **End of Survey:** redirect to `https://<backend>/s/${e://Field/study}/onboard?pid=${e://Field/pid}`

**Survey options:**

- Turn on "Prevent multiple submissions" and allow resuming partial responses.
- Turn off "Anonymize responses". It strips the ResponseID linkage.

**Per-study changes after copying:** the slug in the Web Service URL(s), the `X-Study-Secret` header, `consent_version`, and the survey content.

### Declined / screened-out callback

`POST https://<backend>/api/qualtrics/<slug>/declined`, same header, body `pid=${e://Field/pid}`, `responseId=${e://Field/ResponseID}`, and `reason=screened_out` for a screen-out (anything else is recorded as `declined`).

### Callback responses

| Code | Meaning                                                                                    |
| ---- | ------------------------------------------------------------------------------------------ |
| 200  | Recorded, or the same call was already recorded (safe to retry)                            |
| 400  | `condition` isn't one of the study's conditions (`"assignment": "qualtrics"` only)         |
| 401  | Missing or wrong `X-Study-Secret`                                                          |
| 404  | Study isn't `recruiting`, or the `pid` doesn't belong to this study                        |
| 409  | Participant is no longer pending, or the ResponseID is already used by another participant |

## 4. Invite teachers

**Admin → Study participants → Add:** pick the study and enter the teacher's email.

If consent was obtained outside Qualtrics, tick **Consent obtained outside the app** instead. The teacher must already have an account. No email is sent; they become `active` right away and follow-up surveys count from today.

- An account is created if none exists (username = email, no password, email marked verified) and added to the `Teacher` group.
- After saving, add **pieces and activities to assign** on the participant's page. They are assigned to each course the teacher creates while consented or active.
- The invitation email (`teleband/templates/studies/email/`) is sent when the participant is created. Use the **Resend invitation email** action for pending participants.

After consenting, a teacher with no password is sent to allauth's set-password page. That link is valid until their password changes.

## 5. Follow-up surveys

Add them on the study's admin page under **follow-up surveys**: a title, the survey's Qualtrics anonymous link, and `due_after_days` (counted from the day the participant consented; 0 = right away). They're shown to participants whose status is `consented` or `active` while the study is `recruiting` or `closed`.

The app adds `pid` and `study` to the link. In each follow-up survey:

1. **Embedded Data:** `pid` and `study`, blank so they're read from the URL.
2. **Survey blocks.**
3. **Web Service** at the end of the flow:
   - URL: `https://<backend>/api/qualtrics/<slug>/surveys/<survey id>/complete` (the id is shown in the survey's admin URL)
   - Method: `POST`, JSON body
   - Body: `pid=${e://Field/pid}`, `responseId=${e://Field/ResponseID}`
   - Header: `X-Study-Secret: <the study's secret>`
4. **End of Survey:** redirect to `https://<backend>/s/${e://Field/study}/surveys/done`, which thanks the teacher and links to `STUDIES_APP_HOME_URL`.

The callback is what records completion; the redirect only moves the teacher along. It returns 200 (also on a repeat), 401 for a bad secret, 404 if the study isn't `recruiting`/`closed` or the pid or survey isn't in this study, and 409 if the participant has withdrawn or hasn't consented.

**Reminders:** `GET /api/surveys/` (logged in) lists the teacher's due, uncompleted surveys with their personal links. `GET /api/users/onboarding/` reports setup progress, including how many surveys are due.

**Status page:** `/s/status/` (superusers) shows each recruiting or closed study's participants with pid, status, condition, consent date, last login, setup, courses, assignments and each survey's state.

## Study config

`Study.config` is JSON. All keys are optional.

```json
{
  "conditions": ["control", "treatment"],
  "assignment": "app",
  "exclude_if_enrolled_in": ["pilot-2026"],
  "allow_anonymous": false
}
```

| Key                      | Effect                                                                                                                                                                              |
| ------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `conditions`             | Experimental arms. If empty, whatever Qualtrics posts as `condition` is stored as-is.                                                                                               |
| `assignment`             | `"app"` (default): the app assigns the arm with the fewest enrolled participants, ties broken at random. `"qualtrics"`: the posted `condition` is used and must be in `conditions`. |
| `exclude_if_enrolled_in` | Study slugs; a user enrolled in any of them is turned away at `/join`                                                                                                               |
| `allow_anonymous`        | Let `/join` start a participation without a login (otherwise it redirects to login)                                                                                                 |

## Settings

| Variable               | Default | Purpose                                                                                                         |
| ---------------------- | ------- | --------------------------------------------------------------------------------------------------------------- |
| `STUDIES_APP_HOME_URL` | `/`     | Where "Continue to MusicCPR" goes for an enrolled teacher who already has a password (usually the frontend URL) |

## Local demo

`python manage.py seed_research_demo` (DEBUG only) creates a `demo` study with three follow-up surveys and a teacher `meteacher1` / `meteacher1` who consented 8 days ago. Its callback secret is `demo-secret`.

## Testing a new study

1. Create the study as `draft`, invite yourself, and note the participant's `pid`.
2. Set it to `recruiting`, then send a test callback:

   ```bash
   curl -i -X POST https://<backend>/api/qualtrics/<slug>/consent \
     -H "Content-Type: application/json" \
     -H "X-Study-Secret: <secret>" \
     -d '{"pid": "<pid>", "responseId": "R_test1"}'
   ```

3. Open `https://<backend>/s/<slug>/onboard?pid=<pid>`. You should land on the set-password page (or "You're enrolled").
4. Run the real survey end to end with a second test participant, then delete the test participants before recruiting.

## Troubleshooting

- **Onboard page stuck on "Finishing up…":** it polls for about 15 seconds, then shows a "Check again" button. If it never clears, the callback didn't arrive. Check the Web Service URL/slug, that the study is `recruiting`, and backend logs for `Bad X-Study-Secret`.
- **401 from the callback:** the header matches neither the study's current secret nor an unrevoked previous one. If nobody has the secret any more, rotate it (see [step 2](#2-copy-the-callback-secret)).
- **Wrong domain in the emailed link:** fix `qualtrics_base_url` on the study.

## Not implemented yet

- Verifying a response through the Qualtrics API (`qualtrics_api_token_ref` is stored but unused).
- A nightly job that checks participants stuck in `pending` against Qualtrics.
