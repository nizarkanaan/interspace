"""Claim check (docs/superpowers/specs/2026-11-20-claim-check-design.md).

Pure functions: split a saved report into claims (one per cited sentence and reference), attach each claim's source
text from the task corpus, hand pending claims to a judge, and record verdicts. A verdict's quote must appear in the
source text it was judged against. Claim ids are "<n>:<k>": reference n, its k-th citation in reading order, the same
numbering the report reader gives its citation links.
"""
import hashlib
import re

from research import records

V = 1
MAX_CLAIMS = 400
MAX_SENTENCE = 600
MAX_SOURCE = 4000
MAX_BATCH = 20
VERDICTS = ('supported', 'partly', 'not_supported', 'cannot_tell')
NO_SOURCE = 'No source text to judge against: the reference is not in the corpus, or has no abstract.'
CHANGED = 'The report changed since the claim check started. Press Check claims again.'

HEADING = re.compile(r'^\s{0,3}#{1,6}\s+(references|bibliography|works cited|reference list)\s*:?\s*$', re.I)
FENCE = re.compile(r'^\s{0,3}```')
ITEM = re.compile(r'^\s*(?:[-*+]|\d+[.)])\s+(.*)$')
LEAD = re.compile(r'^\s*\[?(\d{1,3})[\].)]\s')
CITE = re.compile(r'\[(\d{1,3}(?:\s*[,–-]\s*\d{1,3})*)\]')
LINK = re.compile(r'\[[^\]\n]+\]\([^)\s]+\)')
CODE = re.compile(r'`[^`\n]+`')
SENTENCE_END = re.compile(r'(?<=[.?!])\s+(?=["“(\[]?[A-Z])')
ABBREVIATIONS = ('et al.', 'e.g.', 'i.e.', 'cf.', 'Fig.', 'fig.', 'vs.', 'Eq.', 'No.')
DOI = re.compile(r'10\.\d{4,9}/[^\s"<>]+', re.I)
ARXIV = re.compile(r'arxiv[:\s/]*(\d{4}\.\d{4,5})', re.I)


def report_hash(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _plain(text):
    return re.sub(r'\s+', ' ', re.sub(r'[*_]{1,2}', '', text)).strip()


def references(text):
    """The report's own reference list: {n: entry text}. List items, or numbered lines when there is no list."""
    lines = text.split('\n')
    start = next((i for i, line in enumerate(lines) if HEADING.match(line)), None)
    if start is None:
        return {}
    section = []
    for line in lines[start + 1:]:
        if re.match(r'^\s{0,3}#{1,6}\s', line):
            break
        section.append(line)
    items = [m.group(1) for m in (ITEM.match(line) for line in section) if m]
    if not items:
        items = [line for line in section if LEAD.match(line)]
        return {int(LEAD.match(line).group(1)): _plain(LEAD.sub('', line, 1)) for line in items}
    found = {}
    for i, item in enumerate(items):
        lead = LEAD.match(item)
        n = int(lead.group(1)) if lead else i + 1
        if n not in found:
            found[n] = _plain(LEAD.sub('', item, 1) if lead else item)
    return found


NOT_A_REPORT = ('This is not a finished report, so it was not saved. A report starts with a title heading (# Title), '
                'presents the findings, and ends with a References section (## References) listing its sources as a '
                'numbered list that matches the [n] citations. Answer the user in your reply instead; save only the '
                'finished report.')
MIN_REPORT = 200


def report_problem(text):
    """Why `text` is not a report, or None. Only a finished report may become report.md
    (docs/superpowers/specs/2026-11-20-save-report-design.md, "Only reports")."""
    lines = [line for line in str(text or '').split('\n') if line.strip()]
    if not lines or not re.match(r'^\s{0,3}#\s+\S', lines[0]):
        return NOT_A_REPORT
    if len(text.strip()) < MIN_REPORT or not references(text):
        return NOT_A_REPORT
    return None


def _body_paragraphs(text):
    """The report's reading text before its References heading, without code, one entry per paragraph or item."""
    out, block, fenced = [], [], False
    for line in text.split('\n'):
        if FENCE.match(line):
            fenced = not fenced
            continue
        if fenced:
            continue
        if HEADING.match(line):
            break
        if not line.strip() or ITEM.match(line) or re.match(r'^\s{0,3}#{1,6}\s', line):
            if block:
                out.append(' '.join(block))
            block = []
            if line.strip():
                block = [ITEM.match(line).group(1) if ITEM.match(line) else re.sub(r'^\s{0,3}#{1,6}\s+', '', line)]
            continue
        block.append(line.strip())
    if block:
        out.append(' '.join(block))
    return out


def _sentences(paragraph):
    guarded = paragraph
    for i, abbreviation in enumerate(ABBREVIATIONS):
        guarded = guarded.replace(abbreviation, abbreviation.replace('.', '\u0000%d' % i))
    parts = SENTENCE_END.split(guarded)
    restored = []
    for part in parts:
        for i, abbreviation in enumerate(ABBREVIATIONS):
            part = part.replace(abbreviation.replace('.', '\u0000%d' % i), abbreviation)
        restored.append(part)
    return restored


def split(text):
    """Claims from a report: [{id, n, k, sentence, reference}] in reading order, at most MAX_CLAIMS."""
    refs = references(text)
    counts, claims = {}, []
    for paragraph in _body_paragraphs(text):
        for sentence in _sentences(paragraph):
            scan = CODE.sub(' ', LINK.sub(' ', sentence))
            for group in CITE.finditer(scan):
                for token in re.findall(r'\d+', group.group(1)):
                    n = int(token)
                    if n not in refs:
                        continue
                    counts[n] = counts.get(n, 0) + 1
                    if len(claims) < MAX_CLAIMS:
                        claims.append({'id': '%d:%d' % (n, counts[n]), 'n': n, 'k': counts[n],
                                       'sentence': _plain(sentence)[:MAX_SENTENCE], 'reference': refs[n]})
    return claims


def _norm_title(text):
    return re.sub(r'[^a-z0-9]+', ' ', re.sub(r'^\s*retracted\s*[:\-–—]\s*', '', str(text or '').lower())).strip()


def source_for(reference, corpus):
    """The corpus paper a reference names, by DOI, then arXiv ID, then a title of 20+ characters in its text."""
    doi = DOI.search(reference or '')
    doi = doi.group(0).rstrip('.,;:)]').lower() if doi else None
    arxiv = ARXIV.search(reference or '')
    arxiv = arxiv.group(1) if arxiv else None
    text = _norm_title(reference)
    for entry in (corpus or {}).get('papers') or []:
        paper = entry.get('paper') or {}
        if doi and str(paper.get('doi') or '').lower() == doi:
            return paper
        if arxiv and str(paper.get('arxiv_id') or '').startswith(arxiv):
            return paper
        title = _norm_title(paper.get('title'))
        if len(title) >= 20 and title in text:
            return paper
    return None


def start(report_text, corpus, at):
    """A new claims file for this report: every claim pending, or can't tell when there is no source text."""
    claims = []
    for claim in split(report_text):
        paper = source_for(claim['reference'], corpus)
        abstract = records.clean_text(paper.get('abstract'), MAX_SOURCE) if paper and isinstance(paper.get('abstract'), str) else None
        entry = dict(claim, paper={'title': paper.get('title'), 'doi': paper.get('doi'), 'arxiv_id': paper.get('arxiv_id'),
                                   'oa_url': paper.get('oa_url')} if paper else None,
                     abstract=abstract, source=abstract, source_kind='abstract' if abstract else None, fulltext_tried=False,
                     status='pending', verdict=None, reason=None, quote=None, by=None, at=None)
        # Full text may still come (2026-11-20-claim-fulltext-design.md): only a paper with nothing at all is can't tell.
        if not abstract and not (paper and (paper.get('arxiv_id') or paper.get('oa_url'))):
            entry.update(status='judged', verdict='cannot_tell', reason=NO_SOURCE, by='interspace', at=at)
        claims.append(entry)
    return {'v': V, 'report_sha': report_hash(report_text), 'started_at': at, 'claims': claims}


def counts(value):
    claims = (value or {}).get('claims') or []
    out = {'claims': len(claims), 'pending': sum(1 for c in claims if c.get('status') == 'pending')}
    for verdict in VERDICTS:
        out[verdict] = sum(1 for c in claims if c.get('verdict') == verdict)
    return out


def next_ids(value, limit=MAX_BATCH):
    """The ids of the next pending claims a judge will get."""
    if type(limit) is not int or not 1 <= limit <= MAX_BATCH:
        raise ValueError('limit must be from 1 to 20.')
    return [c['id'] for c in (value or {}).get('claims') or [] if c.get('status') == 'pending'][:limit]


def attach(claim, text, error, at):
    """Give one claim its source text: the abstract plus the full-text passages that best match the sentence."""
    from research import fulltext
    claim['fulltext_tried'] = True
    found = fulltext.passages(text, claim['sentence']) if text else []
    if found:
        claim['source'] = '\n\n'.join(([claim['abstract']] if claim.get('abstract') else []) + found)
        claim['source_kind'] = 'full text'
    elif not claim.get('abstract'):
        claim.update(status='judged', verdict='cannot_tell', by='interspace', at=at,
                     reason=(error or 'The full text has no passage about this sentence.')[:300])


def pending(value, limit=MAX_BATCH, ids=None):
    """Pending claims for a judge, with the only text it may judge against."""
    wanted = next_ids(value, limit) if ids is None else list(ids)
    index = {c['id']: c for c in (value or {}).get('claims') or []}
    batch = [{'id': c['id'], 'sentence': c['sentence'], 'reference': c['reference'],
              'source': {'title': (c.get('paper') or {}).get('title'), 'kind': c.get('source_kind') or 'abstract',
                         'text': c.get('source')}}
             for c in (index[i] for i in wanted if i in index) if c.get('status') == 'pending']
    return {'claims': batch, 'counts': counts(value),
            'instructions': 'Judge each sentence only against its source text (the abstract, plus passages of the '
                            'full paper when kind is "full text"). supported: the text backs the sentence as written; '
                            'partly: it backs part of it or a weaker version; not_supported: it does not back it or '
                            'says otherwise; cannot_tell: the text does not cover it. Quote the words your verdict '
                            'rests on exactly as they appear in the text.'}


def _squash(text):
    return re.sub(r'\s+', ' ', str(text or '')).strip().lower()


def record(value, report_text, results, by, at):
    """Store verdicts. Returns {recorded, rejected: [{id, error}], counts}. Refuses all when the report changed."""
    if value is None:
        raise ValueError('No claim check has started. Press Check claims in the Report tab.')
    if report_hash(report_text) != value.get('report_sha'):
        raise ValueError(CHANGED)
    if not isinstance(results, list) or not 1 <= len(results) <= 50:
        raise ValueError('results must be a list of 1 to 50 verdicts.')
    index = {c['id']: c for c in value.get('claims') or []}
    recorded, rejected = 0, []
    for item in results:
        cid = item.get('id') if isinstance(item, dict) else None
        claim = index.get(cid)
        error = None
        if claim is None:
            error = 'Unknown claim.'
        elif claim.get('status') != 'pending':
            error = 'This claim was already judged.'
        elif item.get('verdict') not in VERDICTS:
            error = 'verdict must be supported, partly, not_supported or cannot_tell.'
        elif not isinstance(item.get('reason'), str) or not 1 <= len(item['reason'].strip()) <= 300:
            error = 'reason must be 1 to 300 characters.'
        else:
            quote = item.get('quote')
            if item['verdict'] != 'cannot_tell' or quote:
                if not isinstance(quote, str) or not quote.strip() or len(quote) > 500:
                    error = 'A quote from the source is required for this verdict.'
                elif _squash(quote) not in _squash(claim.get('source')):
                    error = 'The quote is not in the source text.'
        if error:
            rejected.append({'id': cid, 'error': error})
            continue
        claim.update(status='judged', verdict=item['verdict'], reason=item['reason'].strip(),
                     quote=(item.get('quote') or '').strip() or None, by=by, at=at)
        recorded += 1
    return {'recorded': recorded, 'rejected': rejected, 'counts': counts(value)}


def public(value):
    """The claims file for the UI: verdicts, reasons and quotes, without the source text."""
    if not value:
        return {'claims': [], 'counts': counts(None), 'started_at': None}
    return {'started_at': value.get('started_at'), 'counts': counts(value),
            'claims': [{k: c.get(k) for k in ('id', 'n', 'k', 'sentence', 'reference', 'paper', 'status', 'verdict',
                                              'reason', 'quote', 'by', 'at', 'source_kind')} for c in value.get('claims') or []]}
