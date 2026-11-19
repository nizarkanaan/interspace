"""Research Wave 0B probe: a handful of real, keyless calls to the research APIs.

Usage: [ONLY=name,name] python3 -I probe.py OUT_DIR [SOURCE ...]

Each call is saved as OUT_DIR/<source>/<name>.json holding the status, the
rate-limit related response headers and the raw body. Nothing about the caller
is sent: the User-Agent is the generic "Interspace-spike" and no key, email or
mailto is attached. Optional credentials (OPENALEX_KEY, UNPAYWALL_EMAIL) are
read from the environment only, are never written to OUT_DIR and are stripped
from the recorded URL.

The output is raw material: fixtures under tests/research/fixtures/ are trimmed
copies made by hand from it.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "Interspace-spike"
KEEP_HEADERS = (
    "content-type", "retry-after", "x-rate-limit-limit", "x-rate-limit-interval",
    "x-concurrency-limit", "x-ratelimit-limit", "x-ratelimit-remaining",
    "x-ratelimit-credits-used", "x-ratelimit-reset", "x-api-pool", "content-length",
)
# Seconds to wait between calls to the same host (arXiv asks for 3).
PACE = {"arxiv": 3.5, "crossref": 1.0, "semantic_scholar": 8.0, "openalex": 0.5, "unpaywall": 0.5}

S2 = "https://api.semanticscholar.org/graph/v1"
S2_FIELDS = ("paperId,externalIds,title,abstract,year,venue,publicationVenue,authors,"
             "citationCount,url,openAccessPdf,isOpenAccess,publicationTypes,publicationDate")
CR = "https://api.crossref.org"
WAKEFIELD = "10.1016/S0140-6736(97)11096-0"   # retracted 2010
LECUN = "10.1038/nature14539"                 # "Deep learning", Nature 2015
VASWANI = "1706.03762"                        # "Attention Is All You Need"
OA = "https://api.openalex.org"
OA_SELECT = ("id,doi,display_name,title,publication_year,ids,authorships,primary_location,"
             "best_oa_location,open_access,cited_by_count,is_retracted,abstract_inverted_index,type")


def q(params):
    return urllib.parse.urlencode(params, safe=":,")


CALLS = {
    "arxiv": [
        ("search_title_2017", "https://export.arxiv.org/api/query?" + q({
            "search_query": 'ti:"attention is all you need" AND submittedDate:[201701010000 TO 201712312359]',
            "max_results": 3})),
        ("lookup_1706.03762", "https://export.arxiv.org/api/query?" + q({"id_list": VASWANI})),
        ("lookup_1706.03762v1", "https://export.arxiv.org/api/query?" + q({"id_list": VASWANI + "v1"})),
        ("lookup_nonexistent", "https://export.arxiv.org/api/query?" + q({"id_list": "2999.99999"})),
        ("lookup_malformed", "https://export.arxiv.org/api/query?" + q({"id_list": "not-an-id"})),
        ("bibtex_1706.03762", "https://arxiv.org/bibtex/" + VASWANI),
    ],
    "crossref": [
        ("search_bibliographic_2015", CR + "/works?" + q({
            "query.bibliographic": "deep learning LeCun Bengio Hinton",
            "filter": "from-pub-date:2015,until-pub-date:2015", "rows": 2,
            "select": "DOI,title,author,issued,container-title,is-referenced-by-count,URL,type,update-to,updated-by"})),
        ("lookup_lecun", CR + "/works/" + LECUN),
        ("lookup_lecun_uppercase", CR + "/works/" + LECUN.upper()),
        ("lookup_wakefield_retracted", CR + "/works/" + WAKEFIELD),
        ("retraction_notices_for_wakefield", CR + "/works?" + q({"filter": "updates:" + WAKEFIELD, "rows": 5})),
        ("lookup_arxiv_datacite_doi", CR + "/works/10.48550/arXiv." + VASWANI),
        ("bibtex_transform_lecun", CR + "/works/" + LECUN + "/transform/application/x-bibtex"),
        ("bibtex_doi_org_lecun", "https://doi.org/" + LECUN, {"Accept": "application/x-bibtex"}),
    ],
    "semantic_scholar": [
        ("search_attention_2017", S2 + "/paper/search?" + q({
            "query": "attention is all you need", "year": "2017", "limit": 3, "fields": S2_FIELDS})),
        ("match_title", S2 + "/paper/search/match?" + q({
            "query": "Attention Is All You Need", "fields": S2_FIELDS})),
        ("lookup_arxiv", S2 + "/paper/ARXIV:" + VASWANI + "?" + q({"fields": S2_FIELDS + ",citationStyles"})),
        ("lookup_doi_lecun", S2 + "/paper/DOI:" + LECUN + "?" + q({"fields": S2_FIELDS})),
        ("citations", S2 + "/paper/ARXIV:" + VASWANI + "/citations?" + q({
            "fields": "paperId,title,year,externalIds", "limit": 2})),
        ("references", S2 + "/paper/ARXIV:" + VASWANI + "/references?" + q({
            "fields": "paperId,title,year,externalIds", "limit": 2})),
        ("lookup_nonexistent", S2 + "/paper/DOI:10.9999/does-not-exist-0b?" + q({"fields": "title"})),
    ],
    "openalex": [
        ("lookup_doi_wakefield", OA + "/works/doi:" + WAKEFIELD),
        ("lookup_arxiv_doi_vaswani", OA + "/works/doi:10.48550/arXiv." + VASWANI + "?" + q({"select": OA_SELECT})),
        ("search_attention_2017", OA + "/works?" + q({
            "search": "attention is all you need", "filter": "publication_year:2017",
            "per_page": 3, "select": OA_SELECT})),
        ("cites_vaswani", OA + "/works?" + q({"filter": "cites:W2626778328", "per_page": 2,
                                              "select": "id,display_name,publication_year"})),
        ("rate_limit", OA + "/rate-limit"),
    ],
    "unpaywall": [
        ("lookup_lecun", "https://api.unpaywall.org/v2/" + LECUN),
        ("lookup_wakefield", "https://api.unpaywall.org/v2/" + WAKEFIELD),
        ("lookup_unknown", "https://api.unpaywall.org/v2/10.9999/does-not-exist-0b"),
    ],
}


def with_secret(source, url, headers):
    if source == "openalex" and os.environ.get("OPENALEX_KEY"):
        headers["Authorization"] = "Bearer " + os.environ["OPENALEX_KEY"]
    if source == "unpaywall":
        email = os.environ.get("UNPAYWALL_EMAIL")
        if not email:
            raise SystemExit("unpaywall needs UNPAYWALL_EMAIL in the environment")
        url += ("&" if "?" in url else "?") + q({"email": email})
    return url, headers


def fetch(source, url, extra):
    headers = {"User-Agent": UA, **extra}
    real_url, headers = with_secret(source, url, dict(headers))
    req = urllib.request.Request(real_url, headers=headers)
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            status, hdrs, body = resp.status, resp.headers, resp.read()
            final = resp.geturl()
    except urllib.error.HTTPError as err:
        status, hdrs, body, final = err.code, err.headers, err.read(), err.url
    for secret in filter(None, (os.environ.get("UNPAYWALL_EMAIL"), os.environ.get("OPENALEX_KEY"))):
        final = (final or "").replace(urllib.parse.quote(secret, safe=""), "REDACTED").replace(secret, "REDACTED")
    text = body.decode("utf-8", "replace")
    try:
        parsed = json.loads(text)
    except ValueError:
        parsed = None
    return {
        "request": {"url": url, "accept": extra.get("Accept")},
        "final_url": final,
        "status": status,
        "elapsed_s": round(time.time() - started, 2),
        "bytes": len(body),
        "headers": {k.lower(): v for k, v in hdrs.items() if k.lower() in KEEP_HEADERS},
        "json": parsed,
        "text": None if parsed is not None else text,
    }


def main(argv):
    out = argv[1]
    sources = argv[2:] or ["arxiv", "crossref", "semantic_scholar"]
    for source in sources:
        os.makedirs(os.path.join(out, source), exist_ok=True)
        only = os.environ.get("ONLY", "").split(",") if os.environ.get("ONLY") else None
        calls = [c for c in CALLS[source] if not only or c[0] in only]
        for i, call in enumerate(calls):
            name, url, extra = (call + ({},))[:3]
            if i:
                time.sleep(PACE[source])
            rec = fetch(source, url, extra)
            if rec["status"] == 429:
                wait = float(rec["headers"].get("retry-after") or 5)
                print(f"{source}/{name}: 429, retry-after={rec['headers'].get('retry-after')}")
                time.sleep(min(wait, 30))  # S2 sends no Retry-After: 5 s default
                retry = fetch(source, url, extra)
                retry["first_attempt"] = {k: rec[k] for k in ("status", "headers", "text", "json")}
                rec = retry
            with open(os.path.join(out, source, name + ".json"), "w") as fh:
                json.dump(rec, fh, indent=1, ensure_ascii=False)
            print(f"{source}/{name}: {rec['status']} {rec['bytes']}B {rec['elapsed_s']}s")


if __name__ == "__main__":
    main(sys.argv)
