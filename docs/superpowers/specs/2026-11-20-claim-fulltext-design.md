# Full text for the claim check

Date: 2026-11-20
Status: approved in conversation (option B, any open-access PDF behind an "Ask" permission)
Size: project

## Intent

With abstracts only, many claims come back "can't tell", because the detail is in the paper's body. The checker should judge each claim against the passages of the full paper that bear on it, wherever a legal open-access copy exists.

## Where the text comes from

- **arXiv papers:** `https://arxiv.org/html/<id>`, through the existing arXiv source and its fixed host. This needs no new permission.
- **Every other paper with an open-access copy:** the paper's `oa_url` from Unpaywall, OpenAlex or Semantic Scholar, through a new research permission, **`fulltext`** ("Open-access full text"), set to allow, ask or off.
  - New research scopes get `fulltext: ask`.
  - A scope without the key treats it as off. The scope editor lists it, so it can be added to an existing task.
  - Each download is authorized like any research call, as `{category: research, source: fulltext, tool: claims_pending}`. With ask, the agent pauses on an ask card until the user answers, and "Add to scope" switches it to allow.
- **Download rules for open-access copies** (`research/fulltext.py`):
  - https only;
  - the host is resolved first, and every address must be public (`ipaddress.is_global`), so loopback, private, link-local and multicast addresses are refused;
  - the connection goes to the checked address, with the hostname used for TLS;
  - up to 5 redirects, each checked the same way;
  - a 10 MiB cap and a 60-second limit;
  - a generic User-Agent, with no cookies and no credentials;
  - PDF or HTML only.
- **Turning it into text:**
  - HTML through the standard library's parser, without scripts, styles or navigation;
  - PDF through macOS PDFKit, over the native bridge: a new `pdf_text` request, which only reads files inside app data. Without the bridge, as in tests or a non-Mac build, PDFs are skipped.
  - Text is cached in `tasks/<root>/fulltext/<key>.txt`, and the downloaded file is deleted after extraction.

## Using it in the claim check

- **Pending, not "can't tell".** `claims_start` keeps a claim pending when its paper has an abstract, an arXiv ID or an `oa_url`. It marks the claim "can't tell" only when none of the three exists.
- **Text arrives with the next batch.** `claims_pending` fetches the full text once per paper for the claims in its batch, outside the scheduler lock, then attaches to each claim:
  - the abstract;
  - the 3 passages of about 1,200 characters that best match the claim's words.

  A claim whose paper ends up with no text at all is recorded as "can't tell" by Interspace.
- **Quotes still have to match.** The quote rule is unchanged: a quote must appear in the text the judge was given.
- **The verdict says what it was judged from.** Each claim records `source_kind`, either `full text` or `abstract`. The Claims to look at list shows "Judged from the full text" or "Judged from the abstract".

## Calls made by the designer

- Europe PMC is not added as a source; its open-access PDFs arrive through Unpaywall's links.
- 3 passages of about 1,200 characters each, scored by overlap of content words.
- PDFs are read by PDFKit, with no Python PDF library.
- The extracted text is capped at 2 MB, and the downloaded file is deleted after reading.
