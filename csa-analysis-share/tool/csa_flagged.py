"""List the volunteers flagged by csa_clean.py, with their name and email, for follow-up. A second sheet lists
volunteers who typed password-like or personal text in the free-text box (counts only, never the text).

    python csa_flagged.py --results results --registrations Registrations_<date>.csv

Writes results/flagged_volunteers.xlsx and .csv. Contains personal details: keep it internal.
Names and emails are read only for the flagged usernames.
"""
import argparse
from pathlib import Path

import pandas as pd

REASONS = [
    ('agrees with others less than half the time',
     lambda v: (v['answers_scored'] >= 30) & (v['agreement_rate'] < 0.5)),
    ('under 3 seconds per image', lambda v: (v['votes'] >= 20) & (v['median_seconds_per_image'] < 3)),
    ('same answer for 90% or more of images', lambda v: (v['votes'] >= 20) & (v['share_identical_answer'] >= 0.9)),
]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--results', default='results')
    ap.add_argument('--registrations', required=True)
    args = ap.parse_args()
    res = Path(args.results)

    vol = pd.read_csv(res / 'volunteers.csv', parse_dates=['first_vote', 'last_vote'])
    reasons = pd.DataFrame({name: rule(vol) for name, rule in REASONS})
    vol['reasons'] = reasons.apply(lambda r: '; '.join(n for n, hit in r.items() if hit), axis=1)
    flagged = vol[vol['reasons'] != ''].copy()

    reg = pd.read_csv(args.registrations, dtype=str, keep_default_na=False, usecols=['name', 'username', 'email'])
    reg['username'] = reg['username'].str.strip()
    flagged = flagged.merge(reg.drop_duplicates('username'), on='username', how='left')
    for c in ('first_vote', 'last_vote'):
        flagged[c] = flagged[c].dt.tz_localize(None).dt.strftime('%Y-%m-%d')
    cols = ['volunteer_id', 'username', 'name', 'email', 'reasons', 'votes', 'answers_scored', 'agreement_rate',
            'median_seconds_per_image', 'share_identical_answer', 'first_vote', 'last_vote', 'active_days']
    flagged = flagged[cols].sort_values(['votes'], ascending=False)
    flagged[['name', 'email']] = flagged[['name', 'email']].fillna('(not registered)')
    flagged.to_csv(res / 'flagged_volunteers.csv', index=False, float_format='%.3f')
    with pd.ExcelWriter(res / 'flagged_volunteers.xlsx', engine='openpyxl') as xw:
        flagged.to_excel(xw, sheet_name='Flagged volunteers', index=False)
        typed = res / 'personal_text_users.csv'
        if typed.exists():
            t = pd.read_csv(typed, dtype={'username': str}).merge(reg.drop_duplicates('username'), on='username',
                                                                 how='left')
            t[['name', 'email']] = t[['name', 'email']].fillna('(not registered)')
            t[['username', 'name', 'email', 'submissions']].to_excel(
                xw, sheet_name='Typed password-like text', index=False)
            print(f'{len(t)} volunteers typed password-like or personal text (sheet "Typed password-like text")')
        pd.DataFrame({'rule': [n for n, _ in REASONS],
                      'volunteers': [int(reasons.loc[vol['reasons'] != '', n].sum()) for n, _ in REASONS]}) \
            .to_excel(xw, sheet_name='Rules', index=False)
        for ws in xw.book.worksheets:
            ws.freeze_panes = 'B2'
            for col in ws.columns:
                width = max(len(str(c.value)) if c.value is not None else 0 for c in col)
                ws.column_dimensions[col[0].column_letter].width = min(max(10, width + 2), 60)
    print(f'{len(flagged)} flagged volunteers written to {res / "flagged_volunteers.xlsx"}')
    print(flagged['reasons'].value_counts().to_string())


if __name__ == '__main__':
    main()
