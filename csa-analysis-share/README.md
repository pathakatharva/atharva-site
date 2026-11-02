# CSA galaxy classifications: analysis package (internal)

Open `index.html` in a browser, or put this whole folder on any web server (it is static: no
database or scripts needed) and share the link. The page links to the files in `data/`.

**Internal use only.** `data/flagged_volunteers.xlsx`, `data/votes_clean.csv` and
`data/volunteers.csv` contain names, emails and usernames. If you host the folder, use an
access-controlled location, or remove those three files first. The report page itself shows
volunteer numbers only.

| Path | Contents |
|---|---|
| `index.html` | The report: findings, skipped = unknown vs no comparison, all charts and tables |
| `CLEANUP-CHECKLIST.md` | Decisions for the team and the planned changes on acrux |
| `data/csa_analysis.xlsx` | Every table in the report, plus volunteers, flagged volunteers and per-image consensus |
| `data/flagged_volunteers.xlsx` | 45 flagged volunteers with name, email and reasons; volunteer who typed password-like text |
| `data/image_consensus.csv` | Per image and feature: answers, p_yes, 95% interval, label, under both readings of a skip |
| `data/training_images.csv` | One row per image: targets for a model, both readings |
| `data/training_votes.csv` | Every clean vote with volunteer ids |
| `data/votes_clean.csv` | Every clean vote with usernames and free text |
| `data/volunteers.csv` | Per volunteer: activity, agreement, flags, demographics |
| `data/cleaning_log.json` | What each cleaning rule removed or changed |
| `tool/` | The scripts that produced all of this; `tool/README.md` explains how to re-run them |

Source: the dashboard exports of 3 Nov 2026 (403,853 raw answers, 2,330 registrations).
