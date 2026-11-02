# CSA classification statistics

Cleans the galaxy-classification answers exported from the CSA dashboard and produces statistics,
findings and training-ready tables. Re-run it on any future export.

## Run it

```bash
python -m venv venv
venv/Scripts/pip install pandas openpyxl          # on Linux/macOS: venv/bin/pip
venv/Scripts/python csa_clean.py --answers Answers_<date>.csv --registrations Registrations_<date>.csv --out results
venv/Scripts/python csa_report.py --results results
venv/Scripts/python csa_flagged.py --results results --registrations Registrations_<date>.csv   # names/emails of flagged volunteers
venv/Scripts/python csa_report.py --results results --package ../csa-analysis-share.zip         # shareable folder + zip
```

`--package` builds a folder (and zip) with `index.html` (the report, linking to the data), `data/` and `tool/`;
host it on any web server or open `index.html` directly. Run `csa_flagged.py` first so the flagged list is included.

Both CSVs come from the dashboard: Answers → "Export in CSV (raw)", Applications → "Export in CSV".
Open `results/report.html` in a browser; the same tables are in `results/csa_analysis.xlsx`.

## Outputs (in `results/`)

| File | What it is |
|---|---|
| `report.html` | Findings, charts and tables (volunteer ids only, no usernames) |
| `csa_analysis.xlsx` | Findings, cleaning log, feature stats, form comparison, correlations, demographics, monthly activity, volunteers, image consensus |
| `votes_clean.csv` | One vote per volunteer per image; 12 features as 1 / 0 / empty; form; morphology from free text |
| `image_consensus.csv` | Per image and feature: answers, yes, no, `p_yes`, 95% interval, weighted `p_yes`, label, mention rate; plus `p_yes_skip_no` / `label_skip_no` with a skipped question read as no |
| `training_images.csv` | One row per image: `p_yes`, answer count and label per feature; the targets for a model |
| `training_votes.csv` | `votes_clean.csv` with volunteer ids instead of usernames, for training on individual votes |
| `volunteers.csv` | Activity, speed, agreement and flags per volunteer, with age band, gender, occupation, education, state |
| `cleaning_log.json` | How many rows each rule removed or changed |
| `flagged_volunteers.xlsx` | From `csa_flagged.py`: flagged volunteers with name, email and reasons; volunteers who typed password-like text (internal) |
| `personal_text_users.csv` | Usernames whose free text was removed as password-like or personal, with counts (never the text) |

`votes_clean.csv` and `volunteers.csv` contain usernames; keep them internal. Names, emails,
phone numbers and PIN codes are never read from the registrations file.

## Rules

They live in `csa_rules.py`, an identical copy of `main_app/classification.py` on the site, so
these files and the site's clean tables (`clean_votes`, `clean_image_consensus`) always agree.
If you change a rule, change both copies.

1. **Tags:** every spelling maps to one of 12 features. For example, `Edge on` / `Edge-on` / `Edge-On` → Edge-on, `Smooth (no features)` → Smooth, and `Galaxy groups and clusters` → Galaxy-Group. Listed = yes, `<tag>_No` = no, not listed = unknown.
2. **The two survey forms:** the tick-box form (until 16 Feb 2023) never recorded a "no", so its votes add only yeses. Its combined "Interacting galaxies, mergers" answer goes to the **Interacting-or-Merger** feature, which the yes/no form also fills (yes if either is yes).
3. **Contradictions:** a feature answered both yes and no in one submission becomes unknown.
4. **Free text:** scanned for Elliptical (with E0–E7), Lenticular, Irregular, Hubble spiral classes (SBb, SABc…) and feature mentions. Password-like text, emails, phone numbers and the volunteer's own name are removed.
5. **Empty submissions:** a submission with nothing usable is dropped.
6. **One vote per volunteer per image:** their first submission that carries information.
7. **Agreement:** `p_yes`, the labels and volunteer reliability use the yes/no form only. The **mention rate** (the share of all voters who said yes) uses every vote and is the only measure comparable across both forms.
8. **Labels:** "yes" or "no" when the 95% Wilson interval of `p_yes` lies entirely above or below 50%. "Uncertain" when it straddles 50%. "Too few answers" under 5 yes/no answers.
9. **Reliability:** how often a volunteer agrees with the others where the others clearly agree (at least 5 other answers, split 70/30 or clearer). `p_yes_weighted` weights each vote by that, shrunk towards 0.5 for volunteers with few scored answers.

## For the machine-learning step

- **Targets:** use `training_images.csv`. The `*_p_yes` columns work as soft targets, and `*_answers` can serve as sample weights. Images labelled "uncertain" are genuinely ambiguous; drop them, or keep them with their soft target.
- **Image files:** the images live under `media/images/questions/` on the site, matched by the `image` column.
- **Two features need more data:** Dust-lane and Shell exist only in the tick-box form (mention rate only). Interacting, Mergers and Tidal-Tails have few confident "yes" images.
