"""Two-agent evidence table (docs/superpowers/specs/2026-11-20-evidence-table-design.md).

Pure functions: columns and rows, each provider's values with quotes that must appear in the row's source text, the
comparison of the two providers' values, the user's resolutions, and the CSV export.
"""
import csv
import io
import re

from research import claims, records

V = 1
MAX_COLUMNS = 10
MAX_ROWS = 50
MAX_SOURCE = 9000
MAX_VALUE = 300
MAX_BATCH = 10
NOT_REPORTED = 'Not reported'
PRESETS = (
    {'id': 'design', 'name': 'Study design', 'instruction': 'The kind of study: experiment, survey, simulation, '
                                                            'case study, review, standard or other.', 'numeric': False},
    {'id': 'sample', 'name': 'Sample size', 'instruction': 'How many participants, devices, calls, sites or cases '
                                                           'were studied. A number.', 'numeric': True},
    {'id': 'setting', 'name': 'Setting or population', 'instruction': 'Where, and on whom or what, the study was '
                                                                      'done.', 'numeric': False},
    {'id': 'method', 'name': 'Method', 'instruction': 'The main method or measurement used.', 'numeric': False},
    {'id': 'outcome', 'name': 'Main outcome', 'instruction': 'The main outcome or metric measured.', 'numeric': False},
    {'id': 'finding', 'name': 'Key finding', 'instruction': 'The main result, in one sentence.', 'numeric': False},
)


def columns(value):
    """Checked columns: 1–10 of `{id?, name, instruction, numeric?}`; ids are made unique."""
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_COLUMNS:
        raise ValueError('Choose 1 to 10 columns.')
    out, seen = [], set()
    for i, column in enumerate(value):
        if not isinstance(column, dict):
            raise ValueError('Each column needs a name and an instruction.')
        name, instruction = column.get('name'), column.get('instruction')
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 60:
            raise ValueError('A column name must be 1 to 60 characters.')
        if not isinstance(instruction, str) or not 1 <= len(instruction.strip()) <= 300:
            raise ValueError('A column instruction must be 1 to 300 characters.')
        base = re.sub(r'[^a-z0-9]+', '-', str(column.get('id') or name).lower()).strip('-')[:24] or 'c%d' % (i + 1)
        cid, n = base, 2
        while cid in seen:
            cid, n = '%s-%d' % (base, n), n + 1
        seen.add(cid)
        out.append({'id': cid, 'name': name.strip(), 'instruction': instruction.strip(),
                    'numeric': column.get('numeric') is True})
    return out


def _paper(paper):
    keep = ('title', 'authors', 'year', 'venue', 'doi', 'arxiv_id', 'oa_url', 'abstract')
    return {k: paper.get(k) for k in keep}


def rows_from(mode, report_text, corpus):
    """The papers a new table covers: 'cited' (the report's references found in the corpus) or 'checked'."""
    papers = []
    if mode == 'cited':
        if not report_text:
            raise ValueError('Save a report first, or choose every checked paper.')
        for _, reference in sorted(claims.references(report_text).items()):
            paper = claims.source_for(reference, corpus)
            if paper:
                papers.append(paper)
    elif mode == 'checked':
        papers = [e['paper'] for e in (corpus or {}).get('papers') or []
                  if (e.get('check') or {}).get('status') in ('verified', 'retracted')]
    else:
        raise ValueError("rows must be 'cited' or 'checked'.")
    out, seen = [], []
    for paper in papers:
        if any(records.same_paper(paper, other) for other in seen):
            continue
        seen.append(paper)
        out.append(paper)
    if not out:
        raise ValueError('No papers to fill: the report cites none from the corpus.' if mode == 'cited'
                         else 'No papers to fill: the citation checker has not confirmed any yet.')
    return out[:MAX_ROWS]


def start(cols, papers, at):
    rows = [{'id': 'r%d' % (i + 1), 'paper': _paper(p), 'source': None, 'source_kind': None, 'fulltext_tried': False}
            for i, p in enumerate(papers)]
    return {'v': V, 'started_at': at, 'columns': cols, 'rows': rows,
            'cells': {r['id']: {c['id']: {'values': {}, 'resolved': None} for c in cols} for r in rows}}


def attach(row, text, cols):
    """A row's source text: the abstract, plus the best full-text passages for each column."""
    from research import fulltext
    row['fulltext_tried'] = True
    abstract = row['paper'].get('abstract') if isinstance(row['paper'].get('abstract'), str) else ''
    found = []
    for column in cols:
        for passage in fulltext.passages(text or '', column['name'] + ' ' + column['instruction'], k=2):
            if passage not in found:
                found.append(passage)
    parts = ([records.clean_text(abstract, 4000)] if abstract else []) + found[:6]
    row['source'] = '\n\n'.join(p for p in parts if p)[:MAX_SOURCE] or None
    row['source_kind'] = 'full text' if found else ('abstract' if abstract else None)


def _mine(table, row_id, provider):
    return all(provider in cell['values'] for cell in table['cells'][row_id].values())


def pending_rows(table, provider, limit=MAX_BATCH):
    if type(limit) is not int or not 1 <= limit <= MAX_BATCH:
        raise ValueError('limit must be from 1 to 10.')
    return [r['id'] for r in table['rows'] if not _mine(table, r['id'], provider)][:limit]


def pending(table, provider, ids):
    rows = {r['id']: r for r in table['rows']}
    return {'columns': [{k: c[k] for k in ('id', 'name', 'instruction', 'numeric')} for c in table['columns']],
            'rows': [{'id': i, 'title': rows[i]['paper'].get('title'), 'year': rows[i]['paper'].get('year'),
                      'source': {'kind': rows[i].get('source_kind') or 'none', 'text': rows[i].get('source') or ''},
                      'missing': [c for c, cell in table['cells'][i].items() if provider not in cell['values']]}
                     for i in ids if i in rows],
            'counts': counts(table),
            'instructions': 'Fill each listed column for each row only from that row\'s source text. Give a short '
                            'value and quote the exact words it rests on. If the text does not say, give the value '
                            '"Not reported" with no quote. Numbers: copy them exactly as written.'}


def _squash(text):
    return re.sub(r'\s+', ' ', str(text or '')).strip().lower()


def record(table, provider, results, at):
    if not isinstance(results, list) or not 1 <= len(results) <= 100:
        raise ValueError('results must be a list of 1 to 100 cells.')
    rows = {r['id']: r for r in table['rows']}
    recorded, rejected = 0, []
    for item in results:
        rid = item.get('row') if isinstance(item, dict) else None
        cid = item.get('column') if isinstance(item, dict) else None
        error = None
        if rid not in rows or cid not in (table['cells'].get(rid) or {}):
            error = 'Unknown row or column.'
        elif provider in table['cells'][rid][cid]['values']:
            error = 'You already filled this cell.'
        else:
            value = item.get('value')
            quote = item.get('quote')
            if not isinstance(value, str) or not 1 <= len(value.strip()) <= MAX_VALUE:
                error = 'value must be 1 to 300 characters.'
            elif _squash(value) != _squash(NOT_REPORTED):
                if not isinstance(quote, str) or not quote.strip() or len(quote) > 500:
                    error = 'A quote from the source is required for this value.'
                elif _squash(quote) not in _squash(rows[rid].get('source')):
                    error = 'The quote is not in the source text.'
        if error:
            rejected.append({'row': rid, 'column': cid, 'error': error})
            continue
        not_reported = _squash(item['value']) == _squash(NOT_REPORTED)
        table['cells'][rid][cid]['values'][provider] = {
            'value': NOT_REPORTED if not_reported else item['value'].strip(),
            'quote': None if not_reported else item['quote'].strip(), 'at': at}
        recorded += 1
    return {'recorded': recorded, 'rejected': rejected, 'counts': counts(table)}


def _norm(value):
    text = re.sub(r'\s+', ' ', str(value or '')).strip().lower().strip('.,;: ')
    number = re.fullmatch(r'[~≈]?\s*(\d{1,3}(?:[,\s]\d{3})+|\d+)(?:\.(\d+))?\s*%?', text)
    if number:
        whole = re.sub(r'[,\s]', '', number.group(1))
        return float(whole + ('.' + number.group(2) if number.group(2) else ''))
    return text


def status(cell, column, providers=2):
    """agree, check (a numeric agreement), disagree, not_reported, one_source, waiting or resolved."""
    if cell.get('resolved'):
        return 'resolved'
    values = [v['value'] for v in cell['values'].values()]
    if len(values) < 2:
        return 'one_source' if values and providers < 2 else 'waiting'
    normed = {_norm(v) for v in values}
    if normed == {_norm(NOT_REPORTED)}:
        return 'not_reported'
    if len(normed) == 1:
        return 'check' if column.get('numeric') else 'agree'
    return 'disagree'


def counts(table, providers=2):
    out = {'cells': 0, 'agree': 0, 'check': 0, 'disagree': 0, 'not_reported': 0, 'waiting': 0, 'resolved': 0,
           'one_source': 0}
    cols = {c['id']: c for c in table.get('columns') or []}
    for row in (table.get('cells') or {}).values():
        for cid, cell in row.items():
            out['cells'] += 1
            out[status(cell, cols.get(cid, {}), providers)] += 1
    return out


def resolve(table, row, column, value, at):
    cell = (table.get('cells') or {}).get(row, {}).get(column)
    if cell is None:
        raise ValueError('Unknown row or column.')
    if value is None:
        cell['resolved'] = None
        return
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= MAX_VALUE:
        raise ValueError('A value must be 1 to 300 characters.')
    cell['resolved'] = {'value': value.strip(), 'at': at}


def final(cell, column):
    if cell.get('resolved'):
        return cell['resolved']['value']
    if status(cell, column) in ('agree', 'check', 'not_reported'):
        return next(iter(cell['values'].values()))['value']
    return ''


def _safe(text):
    text = str(text or '')
    return "'" + text if text[:1] in ('=', '+', '-', '@') else text


def to_csv(table):
    out = io.StringIO()
    writer = csv.writer(out)
    cols = table.get('columns') or []
    writer.writerow(['Paper'] + [c['name'] for c in cols] + [c['name'] + ' status' for c in cols])
    for row in table.get('rows') or []:
        paper = row['paper']
        label = '%s (%s)' % (paper.get('title') or 'Untitled', paper.get('year')) if paper.get('year') else paper.get('title')
        cells = table['cells'][row['id']]
        writer.writerow([_safe(label)] + [_safe(final(cells[c['id']], c)) for c in cols]
                        + [status(cells[c['id']], c) for c in cols])
    return out.getvalue()


def public(table, providers=2):
    if not table:
        return {'table': None, 'presets': list(PRESETS)}
    cols = {c['id']: c for c in table['columns']}
    view = {'started_at': table.get('started_at'), 'columns': table['columns'], 'counts': counts(table, providers),
            'rows': [{'id': r['id'], 'paper': {k: r['paper'].get(k) for k in ('title', 'year', 'authors', 'doi')},
                      'source_kind': r.get('source_kind'),
                      'cells': {cid: dict(cell, status=status(cell, cols[cid], providers))
                                for cid, cell in table['cells'][r['id']].items()}} for r in table['rows']]}
    return {'table': view, 'presets': list(PRESETS)}
