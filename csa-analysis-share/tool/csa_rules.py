"""Cleaning rules for galaxy classifications, shared by the site and the offline analysis tool.

The same file is main_app/classification.py on the site (used by `manage.py rebuild_clean_data` and
when a new answer is saved) and csa_rules.py in the csa-analysis tool, so the clean tables in the
database and the offline statistics always follow identical rules. Pure Python: no Django, no pandas.

  1. Every spelling of a tag maps to one of 12 features. Listed = yes, "<tag>_No" = no, not listed =
     unknown. The tick-box form used until 16 Feb 2023 never recorded a "no", so its votes only add yeses.
  2. A feature answered both yes and no in one submission becomes unknown.
  3. Free text ("feature not listed") is scanned for morphology and feature mentions; password-like and
     personal text is removed.
  4. A submission with no information at all is not a vote.
  5. One vote per volunteer per image: the first submission that carries information.
  6. Agreement (p_yes) and labels come from the yes/no form only; the mention rate (share of all voters
     who said yes) uses every vote and is comparable across both forms.
"""
import ast
import datetime
import math
import re

# The yes/no form (hsc_data.html) replaced the tick-box form on this day.
NEW_FORM_START = datetime.datetime(2023, 2, 17, tzinfo=datetime.timezone.utc)

FEATURES = ['Spiral', 'Bar', 'Ring', 'Edge-on', 'Smooth', 'Galaxy-Group', 'Tidal-Tails',
            'Interacting', 'Mergers', 'Interacting-or-Merger', 'Dust-lane', 'Shell']
# Asked as yes/no in the current form, so agreement and labels exist for these.
YESNO_FEATURES = FEATURES[:10]
# Database column for each feature.
FIELD = {f: f.lower().replace('-', '_') for f in FEATURES}

# Every spelling seen in the data (lower case, without the _No suffix) -> feature.
TAG_TO_FEATURE = {
    'spiral': 'Spiral',
    'bar': 'Bar',
    'ring': 'Ring',
    'edge on': 'Edge-on', 'edge-on': 'Edge-on',
    'smooth': 'Smooth', 'smooth (no features)': 'Smooth',
    'galaxy-group': 'Galaxy-Group', 'galaxy groups and clusters': 'Galaxy-Group',
    'tidal-tails': 'Tidal-Tails', 'tidal tails': 'Tidal-Tails',
    'interacting-galaxies': 'Interacting',
    'mergers': 'Mergers',
    'interacting galaxies, mergers': 'Interacting-or-Merger',
    'dust lane': 'Dust-lane',
    'shell': 'Shell',
}
# Labels that exist in only one of the two forms; they tell the forms apart around the switch-over.
NEW_FORM_TAGS = {'Interacting-Galaxies', 'Galaxy-Group', 'Tidal-Tails', 'Mergers', 'Smooth', 'Edge-on', 'Edge-On',
                 'Tidal Tails'}
OLD_FORM_TAGS = {'Dust lane', 'Shell', 'Galaxy groups and clusters', 'Edge on', 'Smooth (no features)',
                 'Interacting galaxies, mergers', 'Tidal tails'}

MIN_ANSWERS_FOR_LABEL = 5
# Reliability is scored only where at least this many others answered and they agree 70/30 or clearer.
CLEAR_MAJORITY = 0.2


def parse_tags(raw):
    """The stored list ("['Spiral', 'Bar_No']", or 'None') -> list of tags; None if unreadable."""
    if isinstance(raw, (list, tuple)):  # an answer not yet re-read from the database
        return [str(x) for x in raw]
    try:
        tags = ast.literal_eval(raw or 'None')
    except (ValueError, SyntaxError):
        return None
    return [str(x) for x in tags] if isinstance(tags, (list, tuple)) else []


def encode(tags, answered_at):
    """-> (form, {feature: 1 or 0}, set of contradicted features, list of unrecognised tags)."""
    tagset = set(tags)
    if any(t.endswith('_No') for t in tags) or NEW_FORM_TAGS & tagset:
        form = 'yes/no'
    elif OLD_FORM_TAGS & tagset:
        form = 'tick-box'
    else:
        form = 'yes/no' if answered_at >= NEW_FORM_START else 'tick-box'
    yes, no, unknown = set(), set(), []
    for t in tags:
        is_no = t.endswith('_No')
        feature = TAG_TO_FEATURE.get((t[:-3] if is_no else t).strip().lower())
        if feature is None:
            unknown.append(t)
        else:
            (no if is_no else yes).add(feature)
    both = yes & no
    values = {f: 1 for f in yes - both}
    values.update({f: 0 for f in no - both})
    # The combined old tag and the two separate new ones both feed "Interacting-or-Merger".
    if 'Interacting-or-Merger' not in values and 'Interacting-or-Merger' not in both:
        if values.get('Interacting') == 1 or values.get('Mergers') == 1:
            values['Interacting-or-Merger'] = 1
        elif values.get('Interacting') == 0 and values.get('Mergers') == 0:
            values['Interacting-or-Merger'] = 0
    return form, values, both, unknown


# ---------------------------------------------------------------------------------------------- free text

NO_CONTENT = re.compile(r"^(yes|no|none|nil|na|n/a|ok|okay|listed|nothing|not sure|unknown|"
                        r"yes\.? ?i see that|yes\.? ?there is tidal tails missing|[.\-?!]+)$")
PASSWORD_LIKE = re.compile(r"^[\w.\- ]{0,30}@\s*\d+\S*$")
EMAIL = re.compile(r"\S+@\S+\.\w+")
PHONE = re.compile(r"(?<!\d)\d{10}(?!\d)")
MORPHOLOGY = [  # first match wins
    ('Elliptical', re.compile(r"\bell?[ie]p?[ts]?i?c|\belip|\belep|\bell\d|\be\s?[0-7]\b|\be[0-7]/")),
    ('Lenticular', re.compile(r"lent+i|\bs0\b")),
    ('Irregular', re.compile(r"irr?[ei]g|\birr\b|peculiar")),
    ('Spiral-class', re.compile(r"\bs(?:ab|ba|a|b)[a-dm]?\b|\bs[cdm]\b")),
]
HUBBLE = re.compile(r"\b(?:e|ell)\s?([0-7])\b|\(e([0-7])\)")
SPIRAL_CLASS = re.compile(r"\b(s(?:ab|ba|a|b)[a-dm]?|s[cdm])\b")
TEXT_MENTIONS = {
    'shell': re.compile(r"\bshell"),
    'dust-lane': re.compile(r"\bdust"),
    'group/cluster': re.compile(r"clust|clusyer|\bgroup"),
    'ring': re.compile(r"\bring"),
    'edge-on': re.compile(r"edge\s?-?on"),
    'merger/interaction': re.compile(r"merg|interact|satellite|disturb|distort"),
    'tidal-tail': re.compile(r"tidal|tail"),
    'bulge/nucleus': re.compile(r"bulge|nucle|central|centre|center"),
    'star-formation': re.compile(r"star.?form"),
}


def looks_personal(text, username=''):
    """Password-like text ("name@123"), an email, a phone number, or a word from the person's username."""
    low = re.sub(r'\s+', ' ', (text or '').strip().lower())
    user_words = {w for w in re.split(r'[^a-z]+', (username or '').lower()) if len(w) >= 4}
    return bool(PASSWORD_LIKE.match(low) or EMAIL.search(low) or PHONE.search(low) or low in user_words)


def clean_free_text(text, username=''):
    """-> (text to keep, morphology, Hubble class, ';'-joined mentions, reason removed or '')."""
    t = (text or '').strip()
    if t in ('', 'None'):
        return '', '', '', '', ''
    low = re.sub(r'\s+', ' ', t.lower())
    if looks_personal(t, username):
        return '', '', '', '', 'personal'
    if NO_CONTENT.match(low):
        return '', '', '', '', 'no content'
    morph = next((name for name, rx in MORPHOLOGY if rx.search(low)), '')
    hubble = ''
    if morph == 'Elliptical':
        m = HUBBLE.search(low)
        hubble = f'E{m.group(1) or m.group(2)}' if m else ''
    elif morph == 'Spiral-class':
        # de Vaucouleurs style: family in capitals (SA, SB, SAB), stage in lower case (a-d, m): SABc, SBb, Sc.
        m = SPIRAL_CLASS.search(low)
        parts = re.fullmatch(r's(ab|ba|a|b)?([a-dm])?', m.group(1)) if m else None
        if parts:
            family = {'ba': 'AB'}.get(parts.group(1), (parts.group(1) or '').upper())
            hubble = 'S' + family + (parts.group(2) or '')
    mentions = ';'.join(k for k, rx in TEXT_MENTIONS.items() if rx.search(low))
    return t, morph, hubble, mentions, ''


def clean_submission(listed, unlisted, answered_at, username=''):
    """One raw answer -> dict for a clean vote, or None if it carries no information (rule 4)."""
    tags = parse_tags(listed) or []
    form, values, both, _ = encode(tags, answered_at)
    text, morph, hubble, mentions, _ = clean_free_text(unlisted, username)
    if not values and not morph and not mentions:
        return None
    return {'form': form, 'values': values, 'contradicted': ';'.join(sorted(both)),
            'morphology_text': morph, 'hubble_class_text': hubble, 'text_mentions': mentions, 'free_text': text}


# ---------------------------------------------------------------------------------------------- consensus

def wilson(k, n, z=1.96):
    """95% Wilson score interval for k yes out of n."""
    if not n:
        return None, None
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return centre - half, centre + half


def label(feature, yes, answered):
    if feature not in YESNO_FEATURES:
        return 'tick-box only'
    if answered < MIN_ANSWERS_FOR_LABEL:
        return 'too few answers'
    low, high = wilson(yes, answered)
    return 'yes' if low > 0.5 else 'no' if high < 0.5 else 'uncertain'
