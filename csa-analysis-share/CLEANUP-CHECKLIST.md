# Clean-up checklist: CSA classification data on acrux

Status on 3 Nov 2026: the analysis has been run on the export of the same date. Nothing in the acrux
database has been changed yet. The step-6 kit (`csa-migration/scripts/06_clean_data_acrux.sh`)
is ready and was tested on MySQL 5.6 with the full data.

## A. Decisions for the team (please comment)

Each of these is a single rule in `csa_rules.py` / `main_app/classification.py`. After they are
decided, the database's clean tables and the offline statistics are rebuilt with the same rule.

| # | Question | Current setting | Recommendation | Where to see the effect |
|---|---|---|---|---|
| 1 | In the yes/no form, does a **skipped question** count as unknown or as "no"? | Unknown | **No** (for votes that answered at least one question). Skipped = unknown inflates yes shares by 13-34 points; skipped = no stays within 3-12 points of the volunteers who answered everything. | Report: "Skipped questions" section |
| 2 | In the old **tick-box form**, does an unticked feature count as unknown or "no"? | Unknown | **No**, for the same reason as 1. Old-form votes would then also count towards agreement, not only the mention rate. | Report: "Does the form change the answers?" |
| 3 | **Label rule**: when is an image "yes" for a feature? | 95% interval entirely above 50%, at least 5 answers | Keep the rule for reports, but train models on the vote fractions (`p_yes`), not on labels | Report: label charts |
| 4 | **Repeat submissions**: which one counts? | The volunteer's first | Keep the first | Cleaning steps |
| 5 | **45 flagged volunteers** (`data/flagged_volunteers.xlsx`): what happens to their votes? | Kept, with less weight | Keep with less weight; exclude only clear cases (e.g. the 8 who average under 3 seconds per image) after a look | Flagged volunteers sheet |
| 6 | Add **Elliptical / Lenticular / Irregular** as answers in the survey form? | Free text only (6,293 votes named one) | Yes | Report: free-text section |
| 7 | Make **all nine questions required** in the survey form? | Optional | Yes: future data then needs no rule for skips | Report: findings 2 and 6 |
| 8 | Ask again about **Dust lane** and **Shell** (tick-box form only)? | Not asked since Feb 2023 | Team's call (science need) | Feature statistics |
| 9 | The volunteer who typed password-like text 864 times: blank those texts in the raw table? | Kept in the raw table and in backups | Contact them (sheet "Typed password-like text"). Blank the texts in the live raw table; the untouched copy stays in the restricted raw archive | Flagged volunteers file |

## B. Changes on acrux, in order

1. **Keep an off-server copy of the originals** before anything else:
   - `/data/csa-migration-backups/20261103-003936-final/` on www-pkc (the final pre-migration backup)
   - the dashboard exports of 3 Nov 2026 (Answers and Registrations CSVs)
   
   Check the checksums (`sha256sum -c SHA256SUMS` in the backup folder).
2. **Run step 6** on acrux: `sudo bash ~/csa-migration/scripts/06_clean_data_acrux.sh`. It:
   - archives a full raw dump and the current code to `/srv/csa/backups/raw-archive/`, which is never auto-deleted;
   - creates `clean_votes`, `clean_image_consensus` and `clean_volunteers`, and fills them;
   - fixes the survey form's Edge-On value, refuses empty submissions, and never stores a password typed into the free-text box;
   - adds the Clean votes and Image consensus exports to the dashboard;
   - installs the nightly rebuild (03:15).
3. **Copy the raw archive off acrux** (`/srv/csa/backups/raw-archive/`) to the same place as item 1.
4. **Apply the decisions from section A**:
   1. Edit `main_app/classification.py`, keeping the same file as `csa_rules.py` in the analysis tool.
   2. Copy it to `/srv/csa/app/citizen_science/main_app/`.
   3. Run `cd /srv/csa/deploy && sudo docker compose exec webapp python manage.py rebuild_clean_data`.
   4. Re-run the analysis tool on a fresh export and check that the clean-vote counts match the database.
5. **Survey form changes** (if A6/A7 are agreed): edit `hsc_data.html` and add any new answer values to `TAG_TO_FEATURE` in the rules, then rebuild. Note the date of the change; it starts a third form version.
6. **Password-like text** (A9): once the raw archive is safely stored, blank those texts in `main_app_answers`, contact the volunteer, then rebuild the clean tables.
7. **Dashboard:** consider showing the clean-vote count next to the raw "Answers" count, which is 26% higher because of repeats and empty submissions.
8. **Left over from the migration:**
   - revoke the old SendGrid key;
   - delete the staging certificate (`sudo certbot delete --cert-name staging.pkc.org.in`) and its DNS record;
   - on www-pkc, run `sudo docker update --restart=no citizen-science_database_1 citizen-science_webapp_1`;
   - decommission www-pkc after about two weeks without problems.

## C. Files to tidy afterwards

- Delete working copies of exports with personal data once they are stored safely: the Answers and Registrations CSVs on the Desktop, and any downloaded copies of this package.
- Keep this package on an access-controlled share only. It contains names, emails and usernames (`data/flagged_volunteers.xlsx`, `data/votes_clean.csv`, `data/volunteers.csv`). The report page (`index.html`) itself shows volunteer numbers only.
