"""Statistics, findings and charts from the output of csa_clean.py.

    python csa_report.py --results results

Writes results/report.html (open in any browser, works offline) and results/csa_analysis.xlsx.
The report uses volunteer ids, not usernames; the Excel workbook's Volunteers sheet has usernames
so flagged accounts can be looked up.
"""
import argparse
import html
import json
from pathlib import Path

import numpy as np
import pandas as pd

from csa_clean import FEATURES, YESNO_FEATURES, MIN_ANSWERS_FOR_LABEL

MAIN = ['Spiral', 'Bar', 'Ring', 'Edge-on', 'Smooth', 'Galaxy-Group', 'Tidal-Tails', 'Interacting', 'Mergers']
LABEL_ORDER = ['yes', 'uncertain', 'no', 'too few answers']


# ---------------------------------------------------------------------------------------------- stats

def compute(res):
    log = json.loads((res / 'cleaning_log.json').read_text())
    votes = pd.read_csv(res / 'votes_clean.csv', parse_dates=['answer_time'], low_memory=False,
                        dtype={'contradicted': str, 'hubble_class_text': str, 'morphology_text': str,
                               'text_mentions': str, 'free_text': str})
    cons = pd.read_csv(res / 'image_consensus.csv')
    vol = pd.read_csv(res / 'volunteers.csv', parse_dates=['first_vote', 'last_vote'])
    s = {'log': log}

    # Feature summary, vote level and image level.
    rows = []
    yn = votes[votes['form'] == 'yes/no']
    tb = votes[votes['form'] == 'tick-box']
    for f in FEATURES:
        c = cons[cons['feature'] == f]
        labels = c['label'].value_counts()
        explicit = yn[f].dropna()
        sure = c[c['answered'] >= MIN_ANSWERS_FOR_LABEL]
        rows.append({
            'feature': f,
            'yes/no answers': len(explicit),
            'share answering yes': explicit.mean() if len(explicit) else np.nan,
            'share of yes/no voters who skipped it': 1 - len(explicit) / len(yn) if f in YESNO_FEATURES else np.nan,
            'mentioned in tick-box votes': tb[f].fillna(0).mean(),
            'mentioned in yes/no votes': yn[f].fillna(0).mean() if f in YESNO_FEATURES else np.nan,
            'images labelled yes': int(labels.get('yes', 0)),
            'images uncertain': int(labels.get('uncertain', 0)),
            'images labelled no': int(labels.get('no', 0)),
            'images with too few answers': int(labels.get('too few answers', 0)),
            'images with >=80% agreement': ((sure['p_yes'] - 0.5).abs() >= 0.3).mean() if len(sure) else np.nan,
        })
    s['features'] = pd.DataFrame(rows)

    # A skipped question in the yes/no form: unknown (default) or no? Votes that answered at least one of
    # the nine questions; volunteers who answered all nine are the reference, since they skipped nothing.
    answered = yn[MAIN].notna()
    voted = yn[answered.any(axis=1)]
    complete = yn[answered.all(axis=1)]
    def yes_share(df, f, skip_as_no):
        if f == 'Interacting-or-Merger':
            col = df[f] if not skip_as_no else ((df['Interacting'] == 1) | (df['Mergers'] == 1)).astype(float)
        else:
            col = df[f].fillna(0) if skip_as_no else df[f]
        return col.dropna().mean()
    skip_rows = []
    for f in YESNO_FEATURES:
        c = cons[cons['feature'] == f]
        a, b = c['label'], c['label_skip_no']
        skip_rows.append({
            'feature': f,
            'yes share: skipped = unknown': yes_share(voted, f, False),
            'yes share: skipped = no': yes_share(voted, f, True),
            'yes share: complete answers (reference)': yes_share(complete, f, False),
            'confident yes (unknown)': int((a == 'yes').sum()), 'confident yes (no)': int((b == 'yes').sum()),
            'uncertain (unknown)': int((a == 'uncertain').sum()), 'uncertain (no)': int((b == 'uncertain').sum()),
            'confident no (unknown)': int((a == 'no').sum()), 'confident no (no)': int((b == 'no').sum()),
            'too few answers (unknown)': int((a == 'too few answers').sum()),
            'too few answers (no)': int((b == 'too few answers').sum()),
            'images whose label changes': int((a != b).sum()),
            'median answers per image (unknown)': c.loc[c['answered'] > 0, 'answered'].median(),
            'median answers per image (no)': c.loc[c['answered_skip_no'] > 0, 'answered_skip_no'].median(),
        })
    s['skip'] = pd.DataFrame(skip_rows)
    n_ans = answered.sum(axis=1)
    single = voted[n_ans[answered.any(axis=1)] == 1]
    s['skip_meta'] = {'votes': len(voted), 'single': len(single),
                      'single_yes': int((single[MAIN].sum(axis=1) == 1).sum()), 'complete': len(complete)}
    wide_no = cons[cons['feature'].isin(MAIN) & (cons['answered_skip_no'] >= 10)].pivot(
        index='image', columns='feature', values='p_yes_skip_no')[MAIN]
    s['corr_no'] = wide_no.corr(min_periods=50)

    # Same images seen in both forms: does the form change how often a feature is reported?
    both = cons[(cons['voters_tick_box'] >= 10) & (cons['voters_yes_no'] >= 10)]['image'].unique()
    def mention(df):
        return df[df['image'].isin(both)].groupby('image')[MAIN].apply(lambda x: x.fillna(0).mean()).mean()
    era = pd.DataFrame({'tick-box form': mention(tb), 'yes/no form': mention(yn)})
    era['change (percentage points)'] = (era['yes/no form'] - era['tick-box form']) * 100
    s['era'] = era.reset_index().rename(columns={'index': 'feature'})
    s['era_images'] = len(both)

    # How features go together: correlation of p_yes across images.
    wide = cons[cons['feature'].isin(MAIN) & (cons['answered'] >= 10)].pivot(index='image', columns='feature',
                                                                             values='p_yes')[MAIN]
    corr = wide.corr(min_periods=50)
    pairs = [(a, b, corr.loc[a, b]) for i, a in enumerate(MAIN) for b in MAIN[i + 1:] if pd.notna(corr.loc[a, b])]
    s['corr'] = corr
    s['pairs'] = sorted(pairs, key=lambda p: -abs(p[2]))

    # Free-text morphology.
    mt = votes.loc[votes['morphology_text'].notna(), ['morphology_text', 'hubble_class_text']]
    s['morph'] = mt['morphology_text'].value_counts()
    s['hubble'] = mt['hubble_class_text'].dropna().value_counts()
    mentions = votes['text_mentions'].dropna().str.split(';').explode().value_counts()
    s['mentions'] = mentions

    # Images: votes per image and coverage.
    per_image = votes.groupby('image').size()
    s['per_image'] = per_image
    s['images_100'] = int((per_image >= 100).sum())
    yes_no_per_image = votes[votes['form'] == 'yes/no'].groupby('image').size()
    s['images_yesno_20'] = int((yes_no_per_image >= 20).sum())

    # Volunteers.
    vv = vol.sort_values('votes', ascending=False)
    top10 = vv.head(max(1, len(vv) // 10))['votes'].sum() / vv['votes'].sum()
    s['top10_share'] = top10
    s['one_day'] = (vol['active_days'] == 1).mean()
    s['median_votes'] = vol['votes'].median()
    s['agreement'] = vol.loc[vol['answers_scored'] >= 30, 'agreement_rate']
    s['vol'] = vol

    def by(col, order=None):
        g = vol.groupby(col).agg(volunteers=('volunteer_id', 'size'), votes=('votes', 'sum'))
        rel = vol[vol['answers_scored'] >= 30].groupby(col)['agreement_rate']
        g['median agreement (volunteers with 30+ scored answers)'] = rel.median()
        g['volunteers scored'] = rel.size()
        g['share of votes'] = g['votes'] / g['votes'].sum()
        if order:
            g = g.reindex([o for o in order if o in g.index] + [i for i in g.index if i not in order])
        else:
            g = g.sort_values('votes', ascending=False)
        return g.reset_index()
    s['by_age'] = by('age_band', ['under 13', '13-17', '18-22', '23-29', '30-44', '45-59', '60+', 'not given'])
    s['by_gender'] = by('gender')
    s['by_occupation'] = by('occupation')
    s['by_education'] = by('education')
    s['by_state'] = by('state').head(15)

    # Activity over time.
    m = votes.set_index('answer_time')
    monthly = pd.DataFrame({'votes': m.resample('MS').size(),
                            'active volunteers': m.resample('MS')['volunteer_id'].nunique()})
    monthly.index = monthly.index.strftime('%Y-%m')
    s['monthly'] = monthly
    s['latest'] = votes['answer_time'].max().strftime('%d %b %Y')
    s['cons'] = cons
    return s


# ---------------------------------------------------------------------------------------------- findings

def findings(s):
    log, f, era = s['log'], s['features'].set_index('feature'), s['era'].set_index('feature')
    out = []
    removed = log['rows in export'] - log['clean votes']
    out.append(f"<b>{removed / log['rows in export']:.0%} of the exported rows were not usable as independent votes.</b> "
               f"{log['repeat submissions of the same image (dropped)']:,} were repeat submissions of an image "
               f"by the same volunteer ({log['  of which within 2 seconds (double submits)']:,} within 2 seconds, i.e. "
               f"double submits on the old site) and {log['submissions without any information (dropped)']:,} carried no "
               f"answer. The dashboard's \"Answers\" count overstates the real number of classifications.")
    sk, meta = s['skip'].set_index('feature'), s['skip_meta']
    unk, no_, ref = (sk['yes share: skipped = unknown'], sk['yes share: skipped = no'],
                     sk['yes share: complete answers (reference)'])
    out.append(f"<b>How a skipped question is read changes the results more than anything else.</b> "
               f"{meta['single'] / meta['votes']:.0%} of yes/no votes answer only one of the nine questions, and "
               f"{meta['single_yes'] / meta['single']:.0%} of those single answers are a yes: volunteers click the "
               f"feature they see. Read as unknown, skips inflate the yes share (Spiral {unk['Spiral']:.0%}, Smooth "
               f"{unk['Smooth']:.0%}); read as no, it is Spiral {no_['Spiral']:.0%}, Smooth {no_['Smooth']:.0%}. The "
               f"{meta['complete']:,} votes that answered all nine (no skips) give Spiral {ref['Spiral']:.0%}, Smooth "
               f"{ref['Smooth']:.0%}: much closer to skipped = no, which slightly under-counts. See the comparison below.")
    lab = f.loc[MAIN, ['images labelled yes', 'images uncertain', 'images labelled no']]
    decided = (lab['images labelled yes'] + lab['images labelled no']) / lab.sum(axis=1)
    dec_no = (sk.loc[MAIN, 'confident yes (no)'] + sk.loc[MAIN, 'confident no (no)']) / (
        sk.loc[MAIN, ['confident yes (no)', 'uncertain (no)', 'confident no (no)']].sum(axis=1))
    out.append(f"<b>Some features are clear-cut, others contested (if skipped = unknown).</b> "
               f"Interacting and Mergers are decided (confident yes or no) for {decided['Interacting']:.0%} and "
               f"{decided['Mergers']:.0%} of images, but only {decided['Galaxy-Group']:.0%} for Galaxy-Group, "
               f"{decided['Bar']:.0%} for Bar and {decided['Smooth']:.0%} for Smooth. If skipped = no, "
               f"{dec_no.min():.0%}-{dec_no.max():.0%} of images are decided for every feature, almost all as \"no\".")
    sp, sm = sk.loc['Spiral'], sk.loc['Smooth']
    out.append(f"<b>Spiral and Smooth are the most common features either way.</b> Confidently spiral: "
               f"{int(sp['confident yes (unknown)']):,} images (skipped = unknown) or {int(sp['confident yes (no)']):,} (skipped = no); "
               f"confidently smooth: {int(sm['confident yes (unknown)']):,} or {int(sm['confident yes (no)']):,}.")
    c = dict(((a, b), r) for a, b, r in s['pairs'])
    neg = min(s['pairs'], key=lambda p: p[2])
    pos = max(s['pairs'], key=lambda p: p[2])
    cn = s['corr_no']
    out.append(f"<b>The labels behave physically sensibly under both readings.</b> Across images, the strongest "
               f"opposite pair is {neg[0]} vs {neg[1]} (correlation {neg[2]:+.2f}; {cn.loc[neg[0], neg[1]]:+.2f} if "
               f"skipped = no) and the strongest pair that goes together is {pos[0]} and {pos[1]} ({pos[2]:+.2f}; "
               f"{cn.loc[pos[0], pos[1]]:+.2f}).")
    skipped = f.loc[MAIN, 'share of yes/no voters who skipped it']
    out.append(f"<b>Volunteers skip most questions.</b> In the yes/no form, each feature is left unanswered by "
               f"{skipped.min():.0%}-{skipped.max():.0%} of voters (Spiral is skipped least). Making all nine questions "
               f"required in the form would remove the need to choose how to read a skip in future data.")
    big = era['change (percentage points)'].abs().sort_values(ascending=False)
    if len(big):
        k = big.index[0]
        out.append(f"<b>The form itself changed the answers.</b> On the {s['era_images']} images classified in both "
                   f"forms, {k} was mentioned by {era.loc[k, 'tick-box form']:.0%} of tick-box voters but "
                   f"{era.loc[k, 'yes/no form']:.0%} of yes/no voters. Tick-box and yes/no data should not be pooled "
                   f"naively; the outputs keep them apart.")
    mo = s['morph']
    if len(mo):
        out.append(f"<b>The free text adds a morphology the form lacks.</b> {mo.sum():,} votes name a class in the "
                   f"\"not listed\" box: {', '.join(f'{k} {v:,}' for k, v in mo.items())}. Elliptical is by far the "
                   f"most requested missing option; adding Elliptical/Lenticular/Irregular to the form would capture it.")
    agr = s['agreement']
    out.append(f"<b>Volunteers are mostly reliable.</b> Volunteers with 30+ scored answers agree with the clear "
               f"majority {agr.median():.0%} of the time (median); {int((agr < 0.5).sum())} of {len(agr)} agree less "
               f"than half the time. Their votes are kept but carry less weight in <i>p_yes_weighted</i>.")
    out.append(f"<b>A small core does most of the work.</b> The most active 10% of volunteers cast "
               f"{s['top10_share']:.0%} of all votes; {s['one_day']:.0%} of volunteers took part on a single day only.")
    rare = ', '.join(f"{k} {int(sk.loc[k, 'confident yes (unknown)'])}/{int(sk.loc[k, 'confident yes (no)'])}"
                     for k in ('Interacting', 'Mergers', 'Tidal-Tails', 'Bar'))
    out.append(f"<b>Training-set readiness.</b> {s['images_yesno_20']:,} of {s['log']['images']:,} images have at "
               f"least 20 yes/no votes. Hard yes/no labels are scarce for rare features (confident \"yes\" images, "
               f"unknown/no: {rare}), so train on the vote fractions (soft targets) rather than labels. "
               f"training_images.csv has both readings: <i>*_p_yes</i> and <i>*_p_yes_skip_no</i>.")
    return out


# ---------------------------------------------------------------------------------------------- html

CSS = """
:root{--bg:#f7f7f5;--card:#fff;--ink:#1d1d1f;--mute:#6b6b70;--line:#e3e3e0;--c1:#3b6fd8;--c2:#d8843b;--c3:#9a9aa0;--c4:#c9c9cc;--yes:#2f8f5b;--no:#c2453d;--unc:#d9a53a}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#141416;--card:#1d1d20;--ink:#ececee;--mute:#9a9aa2;--line:#303034;--c1:#7aa2f7;--c2:#f0a35e;--c3:#77777e;--c4:#4a4a50;--yes:#4fbf82;--no:#e26a62;--unc:#e8bd5c}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1060px;margin:0 auto;padding:28px 16px 60px}h1{font-size:26px;margin:0 0 4px}h2{font-size:19px;margin:36px 0 10px}
.sub{color:var(--mute);margin:0 0 20px}.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:18px;margin:12px 0}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px}.kpi{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px}
.kpi b{display:block;font-size:24px}.kpi span{color:var(--mute);font-size:13px}
ol.find li{margin:0 0 10px}table{border-collapse:collapse;width:100%;font-size:13.5px}th,td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
th:first-child,td:first-child{text-align:left}th{color:var(--mute);font-weight:600}.scroll{overflow-x:auto}
svg text{fill:var(--ink);font-size:12px}svg .mute{fill:var(--mute)}.legend{display:flex;gap:14px;flex-wrap:wrap;font-size:13px;color:var(--mute);margin:6px 0}
.sw{display:inline-block;width:11px;height:11px;border-radius:2px;margin-right:5px;vertical-align:-1px}.note{color:var(--mute);font-size:13px}
"""


def esc(x):
    return html.escape(str(x))


def fmt(v, pct=False):
    if isinstance(v, (float, np.floating)):
        if pd.isna(v):
            return '–'
        return f'{v:.0%}' if pct else (f'{v:,.0f}' if abs(v) >= 100 or float(v).is_integer() else f'{v:.2f}')
    if isinstance(v, (int, np.integer)):
        return f'{v:,}'
    return esc(v)


def table(df, pct_cols=()):
    head = ''.join(f'<th>{esc(c)}</th>' for c in df.columns)
    body = ''.join('<tr>' + ''.join(f'<td>{fmt(v, c in pct_cols)}</td>' for c, v in zip(df.columns, r)) + '</tr>'
                   for r in df.itertuples(index=False))
    return f'<div class="scroll"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def hbars(items, color='var(--c1)', pct=False, width=640):
    """items: [(label, value)] -> horizontal bar chart."""
    items = [(k, float(v)) for k, v in items if pd.notna(v)]
    if not items:
        return ''
    mx = max(v for _, v in items) or 1
    lw, row = 170, 24
    h = row * len(items) + 6
    parts = [f'<svg viewBox="0 0 {width} {h}" width="100%" role="img">']
    for i, (k, v) in enumerate(items):
        y = i * row + 3
        w = (width - lw - 70) * v / mx
        label = f'{v:.0%}' if pct else f'{v:,.0f}'
        parts.append(f'<text x="{lw - 8}" y="{y + 15}" text-anchor="end">{esc(k)}</text>'
                     f'<rect x="{lw}" y="{y + 3}" width="{max(w, 1):.1f}" height="{row - 8}" rx="3" fill="{color}"/>'
                     f'<text x="{lw + w + 6:.1f}" y="{y + 15}" class="mute">{label}</text>')
    return ''.join(parts) + '</svg>'


def stacked(rows, keys, colors, width=640):
    """rows: [(label, {key: value})] -> 100% stacked bars."""
    lw, row = 170, 26
    h = row * len(rows) + 6
    parts = [f'<svg viewBox="0 0 {width} {h}" width="100%" role="img">']
    for i, (label, vals) in enumerate(rows):
        y = i * row + 3
        tot = sum(vals.get(k, 0) for k in keys) or 1
        x = lw
        parts.append(f'<text x="{lw - 8}" y="{y + 16}" text-anchor="end">{esc(label)}</text>')
        for k, c in zip(keys, colors):
            w = (width - lw - 10) * vals.get(k, 0) / tot
            if w > 0:
                parts.append(f'<rect x="{x:.1f}" y="{y + 3}" width="{w:.1f}" height="{row - 8}" fill="{c}">'
                             f'<title>{esc(label)}: {esc(k)} {vals.get(k, 0):,}</title></rect>')
                if w > 34:
                    parts.append(f'<text x="{x + w / 2:.1f}" y="{y + 16}" text-anchor="middle" '
                                 f'style="fill:#fff;font-size:11px">{vals.get(k, 0) / tot:.0%}</text>')
            x += w
    legend = ''.join(f'<span><i class="sw" style="background:{c}"></i>{esc(k)}</span>' for k, c in zip(keys, colors))
    return f'<div class="legend">{legend}</div>' + ''.join(parts) + '</svg>'


def columns(series, color='var(--c1)', width=1000, height=180):
    vals = series.values.astype(float)
    n = len(vals)
    mx = vals.max() or 1
    bw = (width - 50) / n
    parts = [f'<svg viewBox="0 0 {width} {height + 24}" width="100%" role="img">',
             f'<text x="0" y="12" class="mute">{mx:,.0f}</text>']
    for i, v in enumerate(vals):
        h = (height - 20) * v / mx
        x = 45 + i * bw
        parts.append(f'<rect x="{x:.1f}" y="{height - h:.1f}" width="{max(bw - 1, 1):.1f}" height="{h:.1f}" '
                     f'fill="{color}"><title>{esc(series.index[i])}: {v:,.0f}</title></rect>')
        if series.index[i].endswith('-01'):
            parts.append(f'<text x="{x:.1f}" y="{height + 16}" class="mute">{esc(series.index[i][:4])}</text>')
    return ''.join(parts) + '</svg>'


def heat(corr):
    n = len(corr)
    cell, lw = 46, 110
    w = lw + cell * n
    parts = [f'<svg viewBox="0 0 {w} {lw + cell * n}" width="100%" style="max-width:{w}px" role="img">']
    for j, b in enumerate(corr.columns):
        parts.append(f'<text transform="translate({lw + j * cell + cell / 2},{lw - 6}) rotate(-45)">{esc(b)}</text>')
    for i, a in enumerate(corr.index):
        parts.append(f'<text x="{lw - 6}" y="{lw + i * cell + cell / 2 + 4}" text-anchor="end">{esc(a)}</text>')
        for j, b in enumerate(corr.columns):
            r = corr.loc[a, b]
            if pd.isna(r):
                continue
            color = f'rgba(59,111,216,{abs(r):.2f})' if r > 0 else f'rgba(194,69,61,{abs(r):.2f})'
            parts.append(f'<rect x="{lw + j * cell}" y="{lw + i * cell}" width="{cell - 2}" height="{cell - 2}" '
                         f'fill="{color}"/><text x="{lw + j * cell + cell / 2 - 1}" y="{lw + i * cell + cell / 2 + 4}" '
                         f'text-anchor="middle" style="font-size:11px">{r:+.2f}</text>')
    return ''.join(parts) + '</svg>'


def grouped(rows, keys, colors, width=640):
    """rows: [(label, {key: share})] -> one small bar per key, grouped by label (shares 0-1)."""
    lw, bar, gap = 170, 9, 10
    h = len(rows) * (bar * len(keys) + gap) + 6
    parts = [f'<svg viewBox="0 0 {width} {h}" width="100%" role="img">']
    y = 3
    for label, vals in rows:
        parts.append(f'<text x="{lw - 8}" y="{y + bar * len(keys) / 2 + 4}" text-anchor="end">{esc(label)}</text>')
        for k, c in zip(keys, colors):
            v = vals.get(k)
            if pd.notna(v):
                w = (width - lw - 50) * v
                parts.append(f'<rect x="{lw}" y="{y}" width="{max(w, 1):.1f}" height="{bar - 1}" fill="{c}">'
                             f'<title>{esc(label)}, {esc(k)}: {v:.0%}</title></rect>'
                             f'<text x="{lw + w + 4:.1f}" y="{y + bar - 1}" class="mute" style="font-size:10px">{v:.0%}</text>')
            y += bar
        y += gap
    legend = ''.join(f'<span><i class="sw" style="background:{c}"></i>{esc(k)}</span>' for k, c in zip(keys, colors))
    return f'<div class="legend">{legend}</div>' + ''.join(parts) + '</svg>'


def skip_section(s):
    sk, meta = s['skip'], s['skip_meta']
    shares = ['yes share: skipped = unknown', 'yes share: skipped = no', 'yes share: complete answers (reference)']
    share_chart = grouped([(r['feature'], {k: r[k] for k in shares}) for _, r in sk.iterrows()],
                          shares, ['var(--c2)', 'var(--c1)', 'var(--c3)'])
    lab = lambda suffix: [(r['feature'], {'yes': r[f'confident yes ({suffix})'], 'uncertain': r[f'uncertain ({suffix})'],
                                          'no': r[f'confident no ({suffix})'],
                                          'too few answers': r[f'too few answers ({suffix})']})
                          for _, r in sk.iterrows()]
    colors = ['var(--yes)', 'var(--unc)', 'var(--no)', 'var(--c4)']
    t = sk.set_index('feature')
    gap = (t['yes share: skipped = unknown'] - t['yes share: complete answers (reference)']) * 100
    gap_no = (t['yes share: skipped = no'] - t['yes share: complete answers (reference)']) * 100
    unc_u = t.loc[MAIN, 'uncertain (unknown)'].sum()
    unc_n = t.loc[MAIN, 'uncertain (no)'].sum()
    lost = ', '.join(f"{k} {int(t.loc[k, 'confident yes (unknown)']):,} → {int(t.loc[k, 'confident yes (no)']):,}"
                     for k in ('Spiral', 'Smooth', 'Edge-on', 'Bar', 'Interacting'))
    med_u = t.loc[MAIN, 'median answers per image (unknown)'].median()
    med_n = t.loc[MAIN, 'median answers per image (no)'].median()
    cons_items = [
        f"<b>Yes shares.</b> Read as unknown, the share answering yes is {gap.min():.0f}-{gap.max():.0f} points above "
        f"the no-skip reference (votes that answered all nine). Read as no, it is {gap_no.min():+.0f} to "
        f"{gap_no.max():+.0f} points from it: a small under-count instead of a large over-count.",
        f"<b>Labels.</b> Read as unknown, {unc_u:,} image-feature pairs are uncertain; read as no, {unc_n:,}. Almost "
        f"every image becomes decided, mostly as \"no\". Confident \"yes\" images: {lost}.",
        f"<b>Evidence per image.</b> Read as no, every vote counts for every feature, so the median number of answers "
        f"behind a feature on an image rises from {med_u:.0f} to {med_n:.0f} and the intervals narrow.",
        "<b>What stays the same.</b> Which features go together (heatmaps), the cleaning counts, the form comparison, "
        "free-text morphology, activity and demographics do not depend on this choice.",
        "<b>What would also change if adopted.</b> Volunteer agreement scores and flags (computed here with skipped = "
        "unknown), the weighted p_yes, and the site's clean_image_consensus table.",
        "<b>For machine learning.</b> Both readings are in training_images.csv (<i>*_p_yes</i> and "
        "<i>*_p_yes_skip_no</i>). Vote fractions as soft targets suit either; hard labels from skipped = no are "
        "nearly all \"no\" for rare features.",
    ]
    tbl = sk[['feature'] + shares + ['confident yes (unknown)', 'confident yes (no)', 'uncertain (unknown)',
                                     'uncertain (no)', 'confident no (unknown)', 'confident no (no)',
                                     'images whose label changes']]
    return f"""<h2>Skipped questions: read as "unknown" or as "no"?</h2><div class="card">
<p>In the yes/no form a volunteer may skip any of the nine questions. {meta['single'] / meta['votes']:.0%} of the
{meta['votes']:,} yes/no votes answer only one, and {meta['single_yes'] / meta['single']:.0%} of those single answers are a
yes: people click the feature they see. The rest of this report reads a skip as <b>unknown</b>; this section shows
what changes if a skip is read as <b>no</b>. The {meta['complete']:,} votes that answered all nine questions skipped
nothing and serve as the reference.</p>
<h3>Share answering yes</h3>{share_chart}
<h3>Image labels, skipped = unknown</h3>{stacked(lab('unknown'), LABEL_ORDER, colors)}
<h3>Image labels, skipped = no</h3>{stacked(lab('no'), LABEL_ORDER, colors)}
<h3>Consequences</h3><ul class="find">{''.join(f'<li>{x}</li>' for x in cons_items)}</ul>
<h3>Side by side</h3>{table(tbl, set(shares))}
<h3>Which features go together, skipped = no</h3>{heat(s['corr_no'])}
<p class="note">Same label rule for both readings: "yes"/"no" when the 95% interval of the share answering yes lies
entirely above/below 50%. Images labelled differently: per feature, the label under one reading differs from the other.</p></div>
"""


DOWNLOADS = [
    ('data/csa_analysis.xlsx', 'Every table in this report, plus volunteers and per-image consensus'),
    ('data/flagged_volunteers.xlsx', 'Flagged volunteers with name, email and reason; who typed password-like text (internal)'),
    ('data/image_consensus.csv', 'Per image and feature: answers, p_yes, interval and label, both readings of a skip'),
    ('data/training_images.csv', 'One row per image: targets for a model (both readings)'),
    ('data/training_votes.csv', 'Every clean vote, volunteer ids instead of usernames'),
    ('data/votes_clean.csv', 'Every clean vote with usernames and free text (internal)'),
    ('data/volunteers.csv', 'Per volunteer: activity, agreement, flags, demographics (internal)'),
    ('data/cleaning_log.json', 'What each cleaning rule removed or changed'),
    ('CLEANUP-CHECKLIST.md', 'Decisions for the team and the planned clean-up on acrux'),
    ('tool/README.md', 'How to re-run the analysis on a new export'),
]


def render(s, path, downloads=False):
    log, f = s['log'], s['features']
    kpi = lambda v, t: f'<div class="kpi"><b>{v}</b><span>{esc(t)}</span></div>'
    removed = log['rows in export'] - log['clean votes']
    lab_rows = [(r['feature'], {'yes': r['images labelled yes'], 'uncertain': r['images uncertain'],
                                'no': r['images labelled no'], 'too few answers': r['images with too few answers']})
                for _, r in f[f['feature'].isin(YESNO_FEATURES)].iterrows()]
    era = s['era']
    log_tbl = pd.DataFrame([(k, v) for k, v in log.items() if not isinstance(v, dict)], columns=['step', 'rows'])
    ft = f[['feature', 'yes/no answers', 'share answering yes', 'share of yes/no voters who skipped it',
            'mentioned in tick-box votes', 'mentioned in yes/no votes', 'images with >=80% agreement']]
    pct = {'share answering yes', 'share of yes/no voters who skipped it', 'mentioned in tick-box votes',
           'mentioned in yes/no votes', 'images with >=80% agreement', 'tick-box form', 'yes/no form',
           'share of votes', 'median agreement (volunteers with 30+ scored answers)'}
    vol = s['vol']
    flagged = vol[vol['flag'].notna()][['volunteer_id', 'votes', 'agreement_rate', 'median_seconds_per_image',
                                        'share_identical_answer', 'flag']].sort_values('votes', ascending=False)
    per_image = s['per_image']
    bins = pd.cut(per_image, [0, 9, 49, 99, 199, 499, 10 ** 6],
                  labels=['1-9', '10-49', '50-99', '100-199', '200-499', '500+']).value_counts().sort_index()
    agr_bins = pd.cut(s['agreement'], [-0.01, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
                      labels=['<50%', '50-60%', '60-70%', '70-80%', '80-90%', '90-100%']).value_counts().sort_index()
    demo = lambda key, title: (f'<h3>{title}</h3>' + table(s[key], pct))
    dl = ''
    if downloads:
        items = ''.join(f'<tr><td><a href="{esc(p)}" download>{esc(p.split("/")[-1])}</a></td><td style="text-align:left;white-space:normal">{esc(d)}</td></tr>'
                        for p, d in DOWNLOADS if (path.parent / p).exists())
        dl = f'<h2>Data files</h2><div class="card"><div class="scroll"><table><tbody>{items}</tbody></table></div></div>'
    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>CSA Classification Statistics</title><style>{CSS}</style></head><body><main>
<h1>Galaxy classifications: clean data and statistics</h1>
<p class="sub">Citizen Science Activity (csa.pkc.org.in) · latest answer {esc(s['latest'])} · generated by csa_report.py</p>
<div class="kpis">{kpi(f"{log['clean votes']:,}", 'clean votes (one per volunteer per image)')}
{kpi(f"{log['volunteers']:,}", 'volunteers who classified')}{kpi(f"{log['images']:,}", 'galaxy images classified')}
{kpi(f"{int(per_image.median())}", 'median votes per image')}{kpi(f"{removed:,}", 'exported rows removed in cleaning')}
{kpi(f"{s['images_yesno_20']:,}", 'images with 20+ yes/no votes')}</div>

<h2>Findings</h2><div class="card"><ol class="find">{''.join(f'<li>{x}</li>' for x in findings(s))}</ol></div>

{skip_section(s)}
{dl}
<h2>How confidently each feature is decided (skipped = unknown)</h2><div class="card">{stacked(lab_rows, LABEL_ORDER, ['var(--yes)', 'var(--unc)', 'var(--no)', 'var(--c4)'])}
<p class="note">Per image, from the yes/no form only. "yes"/"no": the 95% interval of the share answering yes lies entirely above/below 50%.
"uncertain": it straddles 50%. "too few": under {MIN_ANSWERS_FOR_LABEL} yes/no answers.</p></div>

<h2>Feature statistics</h2><div class="card">{table(ft, pct)}
<p class="note">"Mentioned" = share of all voters who said yes (unanswered counts as not mentioned), the only measure comparable across both forms.
Dust-lane and Shell were asked only in the tick-box form.</p></div>

<h2>Does the form change the answers?</h2><div class="card">{table(era, pct)}
<p class="note">Mention rates on the {s['era_images']} images that have at least 10 votes in each form.</p></div>

<h2>Which features go together</h2><div class="card">{heat(s['corr'])}
<p class="note">Correlation of the share answering yes across images (images with 10+ answers for both features). Blue: tend to occur together; red: tend to exclude each other.</p></div>

<h2>What volunteers wrote in "feature not listed"</h2><div class="card">
<h3>Morphology named</h3>{hbars(list(s['morph'].items()), 'var(--c2)')}
<h3>Hubble classes given</h3>{hbars(list(s['hubble'].head(20).items()), 'var(--c2)')}
<h3>Features mentioned</h3>{hbars(list(s['mentions'].items()), 'var(--c3)')}</div>

<h2>Images</h2><div class="card"><h3>Votes per image</h3>{hbars(list(bins.items()))}
<p class="note">{s['images_100']:,} images have 100 or more votes (the new survey stops showing an image after 100).</p></div>

<h2>Volunteers</h2><div class="card">
<p>Median {s['median_votes']:.0f} votes per volunteer; the top 10% cast {s['top10_share']:.0%} of all votes; {s['one_day']:.0%} took part on one day only.</p>
<h3>Agreement with the clear majority (volunteers with 30+ scored answers)</h3>{hbars(list(agr_bins.items()), 'var(--c1)')}
{demo('by_age', 'By age at first vote')}{demo('by_gender', 'By gender')}{demo('by_occupation', 'By occupation')}
{demo('by_education', 'By education')}{demo('by_state', 'Top 15 states')}
<h3>Flagged for review ({len(flagged)}; votes kept, weighted down)</h3>{table(flagged, {'agreement_rate', 'share_identical_answer'})}</div>

<h2>Activity over time</h2><div class="card"><h3>Votes per month</h3>{columns(s['monthly']['votes'])}
<h3>Active volunteers per month</h3>{columns(s['monthly']['active volunteers'], 'var(--c2)')}</div>

<h2>Cleaning steps</h2><div class="card">{table(log_tbl)}</div>
<p class="note">Method: tags normalised to 12 features (all spellings merged); listed = yes, "_No" = no, otherwise unknown;
contradictions set to unknown; first informative submission per volunteer and image kept; agreement and labels from the yes/no form
(from 17 Feb 2023); free text scanned for morphology, personal text removed.</p>
</main></body></html>"""
    path.write_text(doc, encoding='utf-8')


def excel(s, res):
    with pd.ExcelWriter(res / 'csa_analysis.xlsx', engine='openpyxl') as xw:
        pd.DataFrame({'finding': [html.unescape(pd.Series([x]).str.replace(r'<[^>]+>', '', regex=True)[0])
                                  for x in findings(s)]}).to_excel(xw, sheet_name='Findings', index=False)
        pd.DataFrame([(k, v) for k, v in s['log'].items() if not isinstance(v, dict)],
                     columns=['step', 'rows']).to_excel(xw, sheet_name='Cleaning', index=False)
        s['features'].to_excel(xw, sheet_name='Features', index=False)
        s['skip'].to_excel(xw, sheet_name='Skipped unknown vs no', index=False)
        s['era'].to_excel(xw, sheet_name='Form comparison', index=False)
        s['corr'].to_excel(xw, sheet_name='Correlations')
        s['morph'].rename('votes').to_excel(xw, sheet_name='Free-text morphology')
        s['hubble'].rename('votes').to_excel(xw, sheet_name='Hubble classes')
        for k, name in (('by_age', 'By age'), ('by_gender', 'By gender'), ('by_occupation', 'By occupation'),
                        ('by_education', 'By education'), ('by_state', 'By state')):
            s[k].to_excel(xw, sheet_name=name, index=False)
        s['monthly'].to_excel(xw, sheet_name='Monthly')
        v = s['vol'].copy()
        for c in ('first_vote', 'last_vote'):
            v[c] = v[c].dt.tz_localize(None)
        v.to_excel(xw, sheet_name='Volunteers', index=False)
        if (res / 'flagged_volunteers.csv').exists():
            pd.read_csv(res / 'flagged_volunteers.csv').to_excel(xw, sheet_name='Flagged volunteers', index=False)
        s['cons'].to_excel(xw, sheet_name='Image consensus', index=False)
        for ws in xw.book.worksheets:
            ws.freeze_panes = 'B2'
            for col in ws.columns:
                width = max(len(str(c.value)) if c.value is not None else 0 for c in col[:200])
                ws.column_dimensions[col[0].column_letter].width = min(max(10, width + 2), 60)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--results', default='results')
    ap.add_argument('--package', metavar='ZIP',
                    help='also build a shareable folder and zip: index.html (the report, with links to the data), '
                         'data/ and tool/. Host the folder on any web server or open index.html directly.')
    args = ap.parse_args()
    res = Path(args.results)
    s = compute(res)
    render(s, res / 'report.html')
    excel(s, res)
    print('\n'.join(pd.Series(findings(s)).str.replace(r'<[^>]+>', '', regex=True)))
    print(f'\nwritten {res / "report.html"} and {res / "csa_analysis.xlsx"}')
    if args.package:
        package(s, res, Path(args.package))


def package(s, res, zip_path):
    import shutil
    import zipfile
    here = Path(__file__).resolve().parent
    root = zip_path.with_suffix('')
    if root.exists():
        shutil.rmtree(root)
    (root / 'data').mkdir(parents=True)
    (root / 'tool').mkdir()
    for p, _ in DOWNLOADS:
        src = res / Path(p).name
        if p.startswith('data/') and src.exists():
            shutil.copy2(src, root / p)
    for name in ('csa_clean.py', 'csa_report.py', 'csa_rules.py', 'csa_flagged.py', 'README.md', 'requirements.txt'):
        shutil.copy2(here / name, root / 'tool' / name)
    shutil.copy2(here / 'CLEANUP-CHECKLIST.md', root / 'CLEANUP-CHECKLIST.md')
    shutil.copy2(here / 'PACKAGE-README.md', root / 'README.md')
    render(s, root / 'index.html', downloads=True)
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as z:
        for f in sorted(root.rglob('*')):
            if f.is_file():
                z.write(f, Path(root.name) / f.relative_to(root))
    print(f'packaged {root} and {zip_path}')


if __name__ == '__main__':
    main()
