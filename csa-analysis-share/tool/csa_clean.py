"""Clean the galaxy-classification answers exported from the CSA dashboard.

    python csa_clean.py --answers Answers_<date>.csv --registrations Registrations_<date>.csv --out results

Writes to --out:
    votes_clean.csv      one row per volunteer per image: 12 features as 1 (yes) / 0 (no) / empty (unknown)
    volunteers.csv       activity, speed and reliability per volunteer, plus age/gender/occupation/education/state
    image_consensus.csv  per image and feature: votes, agreement (p_yes) with 95% interval, mention rate, label
    training_images.csv  one row per image, ready to use as targets for a machine-learning model
    training_votes.csv   votes_clean without usernames (volunteer_id instead), for training on individual votes
    cleaning_log.json    how many rows each cleaning rule removed or changed

Cleaning rules (defined in csa_rules.py, the same file the site uses as main_app/classification.py):
  1. Every spelling of a tag is mapped to one of 12 features. Listed = yes, "<tag>_No" = no, anything not
     listed = unknown. This holds for both survey forms: the tick-box form used until Feb 2023 never
     recorded a "no", so its votes only contribute yes answers.
  2. A feature answered both yes and no in the same submission becomes unknown.
  3. Free text ("feature not listed") is scanned for morphology (elliptical, E0-E7, lenticular, irregular,
     Hubble spiral classes) and feature mentions; password-like and personal text is removed.
  4. Submissions with no information at all (nothing answered, nothing usable in the free text) are dropped.
  5. One vote per volunteer per image: their first submission that carries information.
  6. Agreement (p_yes) and labels come from the yes/no form only (17 Feb 2023 onwards); the mention rate
     (share of all voters who said yes) uses every vote and is comparable across both forms.

Only age, gender, occupation, education and state are taken from the registrations file; names, emails,
phone numbers and PIN codes are never read into the outputs.
"""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from csa_rules import (FEATURES, YESNO_FEATURES, MIN_ANSWERS_FOR_LABEL, CLEAR_MAJORITY,  # noqa: F401
                       parse_tags, encode, clean_free_text)


def wilson(k, n, z=1.96):
    """95% Wilson score interval for k successes out of n (vectorised)."""
    k = np.asarray(k, dtype=float)
    n = np.asarray(n, dtype=float)
    with np.errstate(invalid='ignore', divide='ignore'):
        p = k / n
        denom = 1 + z * z / n
        centre = (p + z * z / (2 * n)) / denom
        half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return centre - half, centre + half


# --------------------------------------------------------------------------------------------- volunteers

def load_registrations(path):
    """Only the fields used for statistics; no names, emails, phones or PIN codes."""
    reg = pd.read_csv(path, dtype=str, keep_default_na=False,
                      usecols=['username', 'date_of_birth', 'gender', 'occupation', 'education', 'state'])
    reg['username_key'] = reg['username'].str.strip()
    reg = reg.drop_duplicates('username_key')
    dob = pd.to_datetime(reg['date_of_birth'], errors='coerce')
    reg['birth_year'] = dob.dt.year.where(dob.dt.year.between(1920, 2020))
    for col in ('gender', 'occupation', 'education'):
        reg[col] = reg[col].str.strip().str.lower().replace({'': 'not given', 'none': 'not given'})
    reg['state'] = (reg['state'].str.strip().str.title()
                    .replace({'': 'Not given', 'None': 'Not given', 'Orissa': 'Odisha',
                              'Pondicherry': 'Puducherry', 'Delhi Ncr': 'Delhi', 'New Delhi': 'Delhi'}))
    return reg[['username_key', 'birth_year', 'gender', 'occupation', 'education', 'state']]


def age_band(age):
    if pd.isna(age):
        return 'not given'
    for limit, label in ((13, 'under 13'), (18, '13-17'), (23, '18-22'), (30, '23-29'), (45, '30-44'), (60, '45-59')):
        if age < limit:
            return label
    return '60+'


# --------------------------------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--answers', required=True)
    ap.add_argument('--registrations', required=True)
    ap.add_argument('--out', default='results')
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    log = {}

    raw = pd.read_csv(args.answers, dtype=str, keep_default_na=False)
    log['rows in export'] = len(raw)
    raw['answer_time'] = pd.to_datetime(raw['answer_time'], utc=True, format='ISO8601')
    raw['username'] = raw['user'].str.strip()

    # Rules 1-3: tags and free text, row by row.
    records, unknown_tags, personal_users = [], {}, {}
    contradicted = text_removed_personal = text_removed_empty = unparseable = 0
    for row in raw.itertuples(index=False):
        tags = parse_tags(row.listed_features)
        if tags is None:
            unparseable += 1
            tags = []
        form, values, both, unknown = encode(tags, row.answer_time)
        contradicted += bool(both)
        for t in unknown:
            unknown_tags[t] = unknown_tags.get(t, 0) + 1
        text, morph, hubble, mentions, removed = clean_free_text(row.unlisted_features, row.username)
        text_removed_personal += removed == 'personal'
        if removed == 'personal':
            personal_users[row.username] = personal_users.get(row.username, 0) + 1
        text_removed_empty += removed == 'no content'
        records.append({'username': row.username, 'image': row.image_name, 'answer_time': row.answer_time,
                        'form': form, **values, 'contradicted': ';'.join(sorted(both)),
                        'morphology_text': morph, 'hubble_class_text': hubble, 'text_mentions': mentions,
                        'free_text': text})
    votes = pd.DataFrame.from_records(records)
    for f in FEATURES:
        if f not in votes:
            votes[f] = np.nan
    votes[FEATURES] = votes[FEATURES].astype('Float64')
    votes['n_answered'] = votes[FEATURES].notna().sum(axis=1)
    log['unparseable feature lists'] = unparseable
    log['submissions with a feature marked both yes and no (set to unknown)'] = contradicted
    log['free texts removed as personal (password-like, email, phone, own name)'] = text_removed_personal
    log['free texts removed as meaningless ("yes", "listed", ...)'] = text_removed_empty
    log['tags not recognised'] = unknown_tags

    # Rule 4: no information at all.
    has_info = (votes['n_answered'] > 0) | (votes['morphology_text'] != '') | (votes['text_mentions'] != '')
    log['submissions without any information (dropped)'] = int((~has_info).sum())
    votes = votes[has_info]

    # Rule 5: first informative submission per volunteer and image.
    votes = votes.sort_values(['username', 'image', 'answer_time'], kind='stable')
    prev_time = votes.groupby(['username', 'image'])['answer_time'].shift()
    repeat = prev_time.notna()
    gap = (votes['answer_time'] - prev_time).dt.total_seconds()
    log['repeat submissions of the same image (dropped)'] = int(repeat.sum())
    log['  of which within 2 seconds (double submits)'] = int((repeat & (gap < 2)).sum())
    log['  of which more than a day later'] = int((repeat & (gap > 86400)).sum())
    votes = votes[~repeat].sort_values('answer_time', kind='stable').reset_index(drop=True)
    log['clean votes'] = len(votes)
    log['volunteers'] = int(votes['username'].nunique())
    log['images'] = int(votes['image'].nunique())
    log['clean votes from the tick-box form (until 16 Feb 2023)'] = int((votes['form'] == 'tick-box').sum())
    log['clean votes from the yes/no form (from 17 Feb 2023)'] = int((votes['form'] == 'yes/no').sum())

    # Volunteer ids (stable within one run; used instead of usernames in training files).
    order = votes.groupby('username')['answer_time'].min().sort_values().index
    vid = pd.Series(np.arange(1, len(order) + 1), index=order)
    votes.insert(0, 'volunteer_id', votes['username'].map(vid))
    votes.insert(0, 'vote_id', np.arange(1, len(votes) + 1))

    # Rule 6: consensus. Long format: one row per explicit answer.
    long = votes.melt(id_vars=['vote_id', 'volunteer_id', 'image', 'form'], value_vars=FEATURES,
                      var_name='feature', value_name='value').dropna(subset=['value'])
    long['value'] = long['value'].astype(float)
    yn = long[(long['form'] == 'yes/no') & long['feature'].isin(YESNO_FEATURES)].copy()

    # Volunteer reliability: agreement with everyone else's majority on the same image and feature,
    # counted only where the others clearly agree (at least 5 other answers, 70/30 or clearer).
    g = yn.groupby(['image', 'feature'])['value']
    yn['others_n'] = g.transform('count') - 1
    yn['others_yes'] = (g.transform('sum') - yn['value']) / yn['others_n'].replace(0, np.nan)
    clear = (yn['others_n'] >= MIN_ANSWERS_FOR_LABEL) & ((yn['others_yes'] - 0.5).abs() >= CLEAR_MAJORITY)
    scored = yn[clear]
    agree = ((scored['value'] == 1) == (scored['others_yes'] > 0.5)).groupby(scored['volunteer_id'])
    rel = pd.DataFrame({'answers_scored': agree.size(), 'agreements': agree.sum()})
    rel['agreement_rate'] = rel['agreements'] / rel['answers_scored']
    # Weight for weighted consensus: agreement shrunk towards 0.5 for volunteers with few scored answers.
    rel['weight'] = (rel['agreements'] + 1) / (rel['answers_scored'] + 2)

    # Per-image consensus.
    n_voters = votes.groupby('image').agg(voters=('vote_id', 'size'),
                                         voters_tick_box=('form', lambda s: int((s == 'tick-box').sum())),
                                         voters_yes_no=('form', lambda s: int((s == 'yes/no').sum())))
    yn['weight'] = yn['volunteer_id'].map(rel['weight']).fillna(0.5)
    yn['wvalue'] = yn['weight'] * yn['value']
    cons = yn.groupby(['image', 'feature']).agg(yes=('value', 'sum'), answered=('value', 'size'),
                                                wsum=('wvalue', 'sum'), w=('weight', 'sum')).reset_index()
    cons['no'] = cons['answered'] - cons['yes']
    cons['p_yes'] = cons['yes'] / cons['answered']
    cons['ci_low'], cons['ci_high'] = wilson(cons['yes'], cons['answered'])
    cons['p_yes_weighted'] = cons['wsum'] / cons['w']
    cons['label'] = np.select(
        [cons['answered'] < MIN_ANSWERS_FOR_LABEL, cons['ci_low'] > 0.5, cons['ci_high'] < 0.5],
        ['too few answers', 'yes', 'no'], 'uncertain')
    mentions = (long[long['value'] == 1].groupby(['image', 'feature']).size().rename('yes_all_forms')
                .reset_index())

    # Alternative reading, reported side by side: in a yes/no-form vote that answered at least one of the
    # nine questions, a skipped question counts as "no" (most volunteers click only the feature they see).
    main9 = YESNO_FEATURES[:9]
    answered_any = votes[main9].notna().any(axis=1)
    sn = votes.loc[(votes['form'] == 'yes/no') & answered_any, ['image'] + main9].copy()
    sn[main9] = sn[main9].fillna(0).astype(float)
    sn['Interacting-or-Merger'] = ((sn['Interacting'] == 1) | (sn['Mergers'] == 1)).astype(float)
    sn_long = sn.melt(id_vars='image', var_name='feature', value_name='value')
    cons_no = sn_long.groupby(['image', 'feature']).agg(yes_skip_no=('value', 'sum'),
                                                        answered_skip_no=('value', 'size')).reset_index()
    cons_no['p_yes_skip_no'] = cons_no['yes_skip_no'] / cons_no['answered_skip_no']
    lo, hi = wilson(cons_no['yes_skip_no'], cons_no['answered_skip_no'])
    cons_no['label_skip_no'] = np.select(
        [cons_no['answered_skip_no'] < MIN_ANSWERS_FOR_LABEL, lo > 0.5, hi < 0.5],
        ['too few answers', 'yes', 'no'], 'uncertain')

    full = (pd.MultiIndex.from_product([n_voters.index, FEATURES], names=['image', 'feature'])
            .to_frame(index=False)
            .merge(cons.drop(columns=['wsum', 'w']), on=['image', 'feature'], how='left')
            .merge(cons_no.drop(columns='yes_skip_no'), on=['image', 'feature'], how='left')
            .merge(mentions, on=['image', 'feature'], how='left')
            .merge(n_voters, left_on='image', right_index=True))
    full['yes_all_forms'] = full['yes_all_forms'].fillna(0).astype(int)
    full['mention_rate'] = full['yes_all_forms'] / full['voters']
    for c in ('label', 'label_skip_no'):
        full.loc[~full['feature'].isin(YESNO_FEATURES), c] = 'tick-box only'
        full[c] = full[c].fillna('too few answers')
    for c in ('yes', 'no', 'answered', 'answered_skip_no'):
        full[c] = full[c].fillna(0).astype(int)
    image_num = pd.to_numeric(full['image'].str.extract(r'(\d+)')[0], errors='coerce')
    full = full.assign(_n=image_num).sort_values(['_n', 'image', 'feature']).drop(columns='_n')
    cols = ['image', 'feature', 'voters', 'voters_tick_box', 'voters_yes_no', 'answered', 'yes', 'no',
            'p_yes', 'ci_low', 'ci_high', 'p_yes_weighted', 'label', 'answered_skip_no', 'p_yes_skip_no',
            'label_skip_no', 'yes_all_forms', 'mention_rate']
    full[cols].to_csv(out / 'image_consensus.csv', index=False, float_format='%.4f')

    # Training targets: one row per image.
    wide = full.pivot(index='image', columns='feature',
                      values=['p_yes', 'answered', 'label', 'p_yes_skip_no', 'answered_skip_no', 'label_skip_no',
                              'mention_rate'])
    train = pd.DataFrame(index=wide.index)
    for f in YESNO_FEATURES:
        train[f'{f}_p_yes'] = wide[('p_yes', f)]
        train[f'{f}_answers'] = wide[('answered', f)]
        train[f'{f}_label'] = wide[('label', f)]
        train[f'{f}_p_yes_skip_no'] = wide[('p_yes_skip_no', f)]
        train[f'{f}_answers_skip_no'] = wide[('answered_skip_no', f)]
        train[f'{f}_label_skip_no'] = wide[('label_skip_no', f)]
    for f in ('Dust-lane', 'Shell'):
        train[f'{f}_mention_rate'] = wide[('mention_rate', f)]
    train = n_voters.join(train)
    tv = votes.groupby('image')['morphology_text'].agg(lambda s: s[s != ''].value_counts().idxmax()
                                                         if (s != '').any() else '')
    train['most_common_free_text_morphology'] = tv
    train = train.assign(_n=pd.to_numeric(train.index.str.extract(r'(\d+)')[0].values, errors='coerce'))
    train = train.sort_values('_n').drop(columns='_n')
    train.to_csv(out / 'training_images.csv', index_label='image', float_format='%.4f')

    # Volunteers.
    v = votes.groupby(['volunteer_id', 'username']).agg(
        votes=('vote_id', 'size'), first_vote=('answer_time', 'min'), last_vote=('answer_time', 'max'),
        votes_tick_box=('form', lambda s: int((s == 'tick-box').sum())),
        active_days=('answer_time', lambda s: s.dt.date.nunique()),
        mean_features_answered=('n_answered', 'mean')).reset_index()
    gaps = votes.sort_values('answer_time').groupby('volunteer_id')['answer_time'].diff().dt.total_seconds()
    v['median_seconds_per_image'] = v['volunteer_id'].map(gaps[gaps < 600].groupby(votes['volunteer_id']).median())
    sig = votes[FEATURES].fillna(-1).astype('int64').astype(str).agg('|'.join, axis=1)
    same = sig.groupby(votes['volunteer_id']).agg(lambda s: s.value_counts().iloc[0] / len(s))
    v['share_identical_answer'] = v['volunteer_id'].map(same)
    v = v.merge(rel[['answers_scored', 'agreement_rate']], left_on='volunteer_id', right_index=True, how='left')
    v['answers_scored'] = v['answers_scored'].fillna(0).astype(int)
    reg = load_registrations(args.registrations)
    v = v.merge(reg, left_on='username', right_on='username_key', how='left').drop(columns='username_key')
    v['registered'] = v['gender'].notna()
    v['age_at_first_vote'] = v['first_vote'].dt.year - v['birth_year']
    v['age_band'] = v['age_at_first_vote'].map(age_band)
    for c in ('gender', 'occupation', 'education'):
        v[c] = v[c].fillna('not given')
    v['state'] = v['state'].fillna('Not given')
    v['flag'] = np.select(
        [(v['votes'] >= 20) & (v['share_identical_answer'] >= 0.9),
         (v['votes'] >= 20) & (v['median_seconds_per_image'] < 3),
         (v['answers_scored'] >= 30) & (v['agreement_rate'] < 0.5)],
        ['same answer for >=90% of images', 'under 3 s per image', 'agrees with others <50%'], '')
    v = v.drop(columns='birth_year')
    v.to_csv(out / 'volunteers.csv', index=False, float_format='%.4f')
    log['volunteers found in the registrations file'] = int(v['registered'].sum())
    log['volunteers flagged for review (kept in the data)'] = int((v['flag'] != '').sum())

    votes.to_csv(out / 'votes_clean.csv', index=False)
    votes.drop(columns=['username', 'free_text']).to_csv(out / 'training_votes.csv', index=False)
    # Who typed password-like or personal text (counts only, never the text), so they can be told.
    typed = pd.Series(personal_users, name='submissions', dtype=int).rename_axis('username')
    typed.sort_values(ascending=False).to_csv(out / 'personal_text_users.csv')
    (out / 'cleaning_log.json').write_text(json.dumps(log, indent=2))
    for k, val in log.items():
        print(f'{k}: {val}')
    print(f'\nwritten to {out.resolve()}')


if __name__ == '__main__':
    main()
