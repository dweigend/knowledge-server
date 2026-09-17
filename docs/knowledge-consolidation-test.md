# Knowledge consolidation experiment

Historical private pilot, 2026-09-15. The corpus and raw logs are not published;
these observations are not an independently reproducible benchmark.

The pipeline works, but meaningful integration of the new literature into the
existing notes was not demonstrated. Preserve this negative result: successful
execution and valid citations do not establish useful synthesis.

## Purpose

Improve existing knowledge before creating additional entries. Test the installed
Hermes agent with `gpt-5.6-luna`, using ten existing sources followed by ten new
research reports and scholarly chapters from the supplied inbox. The extension
is not a sample of ten new journal articles or a systematic literature review.

## Small workflow

1. Consolidate existing permanent notes and the wiki without creating new notes.
2. Transfer legacy PDF ownership to verified Zotero attachments.
3. Extract bounded page chunks from explicitly selected additional documents.
4. Compare each extracted contribution against existing claim candidates.
5. Reuse a matching claim, create a distinct claim, or explicitly skip it.
6. Reassess changed evidence and consolidate existing notes again.

Zotero owns literature metadata and PDFs. The database retains Zotero identities,
PDF hashes, immutable extracted page text and derived knowledge. Old JSON source
revisions remain historical audit records, not an editable literature catalog.
New PDF preparation uses temporary files. Original inbox files are not deleted.

For this small pilot, matching receives every existing claim up to a hard budget
of 40 candidates. No embeddings, vector database or additional retrieval service
is required. The workflow stops explicitly if that budget is exceeded. Matching
still requires compatible population, intervention, outcome and time horizon;
similar wording is insufficient.

## Model boundary

Each task uses a fresh bounded Hermes call with no tools, external memory or
project context. Instructions and source data are separated. The application
checks schema validity, candidate identities, exact quotations, revision pins,
evidence completeness and note citations. One repair attempt is allowed.

The installed Codex provider previously rejected native Structured Outputs.
JSON instructions and Pydantic validation remain the actual enforcement here.
No model self-rating is treated as proof of quality. The model explains its
chosen action briefly; hidden internal reasoning is not collected.

## Observation and recovery

Private run directories contain timestamped `events.jsonl`, exact model requests
and responses, validation outcomes, note proposals and unified text diffs. These
artifacts support debugging and resuming this experiment; they are not another
literature database and require no parallel metadata maintenance. Pending import
snapshots are removed after their contributions are accepted.

Database receipts make accepted contributions idempotent. Note revisions retain
entity identity and history. Human-authored or previously approved notes receive
proposals without automatic replacement. No record merging or deletion occurs.

## Corpus and outcome

| Current records | Before | After |
| --- | ---: | ---: |
| Sources | 10 | 20 |
| Claims | 10 | 24 |
| Evidence relations | 26 | 41 |
| Assessments | 10 | 24 |
| Notes, including the wiki | 21 | 21 |
| Total | 77 | 130 |

The final ledger contains 178 immutable revisions. No human approvals were
created. Existing IDs and old citations remain readable.

The ten additional documents are the US Department of Education AI report
(2023), Adult Education Survey report (2024), chapters on wisdom (2019) and civic
reflection (2017), Pew reports on teenagers and AI (2026), AI experts and the
public (2025), and STEM diversity (2021), the AI Index diversity chapter (2024),
and scholarly texts on design thinking skills and neuroscience of collaboration.
The exact paths and cover-removal choices are in the private import manifest.
Six PDFs retain their first page and reuse one original/clean attachment.

Seventeen reconciliation decisions produced 14 new claims, one reuse and two
skips. The reuse connected two passages within the newly imported US Department
of Education report; it did not add evidence to an original claim. One skip
avoided treating a method description as a result. The wisdom skip may have
missed a useful contribution: no existing match alone should not imply skipping.
The prompt now states that distinction explicitly.

The initial consolidation revised all eleven permanent/wiki notes. After the
extension, it revised eight and kept three. All eleven still have zero direct
or transitive references to the ten new sources. The broader source selection
also limits how much direct overlap with the original claims can be expected.

## Qualitative review

- The wiki now explains that the Harvard Crossover counts 142/174 are not
  independent parallel groups. Its remaining text stayed unchanged.
- The Bastani note adds the statistical-significance qualification to the 17%
  disadvantage while preserving its numbers and scope.
- The self-explanation note changes only its title to a more cautious claim.
- The Noy note lost the original 10–20% control-group contamination detail in
  the baseline pass, replacing it with vague wording. The second pass did not
  restore it. The prompt now requires preservation of quantitative details;
  that instruction does not prove the problem solved.
- The cognitive-tutor note adds a partly redundant causal limitation and makes
  author attribution less clear. More cautious prose is not always better prose.

These remaining note issues were left visible for review rather than silently
counted as successful improvements. The original versions remain available.

## Observed failures and concrete changes

1. A note cited an entity absent from its reference list. The database rejected
   the write. The same citation check now runs during bounded model repair.
2. One import stopped after two invalid JSON responses. Syntax repair now sends
   the schema, invalid response and errors without repeating the large source.
   Domain-validation repairs still retain their source context.
3. Luna mistook officials on the US Department of Education masthead for authors.
   The explicit corporate citation was corrected in Zotero only. AES author/date
   metadata appeared near the end of the PDF; it was also corrected in Zotero.
   Extraction now fills missing metadata from later chunks and logs conflicts.
4. Three material claim errors were corrected with explicit curator revisions:
   an invented 20-year horizon in a Pew trust question; exams misdescribed as
   participants in the AI Index; and unsupported causal wording in the design
   thinking report. Old claims and evidence pins remain in history. These are
   curator corrections, not independent Luna successes.
5. Matching rationale was incorrectly reused as new evidence rationale. New
   claims now preserve their extraction rationale. Reused claims receive a
   relation, rationale and directness for the selected target. One broad human
   oversight relation was explicitly corrected to indirect, partial support.
6. Body-only diffs hid title changes. Diffs now include title, text and references.
   Supplemental complete diffs were appended to the existing logs without
   rewriting the original events or changing database records.

A separate narrow passage check now compares attribution, quantities, scope
and causal language against the quote and its page. In a retrospective audit,
it flagged all three selected original errors. It passed 14 of 15 current
passages; the remaining indirect-support issue passed after explicit correction
and clearer instructions. This small selected test is not an accuracy estimate.

Across these experiment logs, 101 model attempts were recorded: 94 passed
structural/domain validation and seven were rejected. Validation success is not
factual correctness. Model calls and explicit curator work are distinct events.

## Verification limits and next evaluation

The original private pilot checked idempotent replay, source hashes, derivative
page mappings, citation access and isolated backup restoration. The detailed
machine-specific runbooks and inspection paths are retained locally and are not
part of this public repository. Historical test counts do not describe the
current suite; use CI for current code verification.

The smallest next evaluation is a manually identified, genuinely relevant
new-source-to-note pair: check whether Luna finds and incorporates that specific
contribution without broad rewriting. Do not add vector infrastructure or force
new citations merely to make this experiment appear successful.

## References

- [OpenAI prompt engineering][prompting]: explicit tasks, context and examples.
- [OpenAI evaluation practices][evals]: task-specific cases and observed failures.
- [Hermes Python library][hermes]: bounded programmatic agent instances.
- [Zotero local API][zotero]: authorized writes and stored attachment access.

[prompting]: https://developers.openai.com/api/docs/guides/prompt-engineering
[evals]: https://developers.openai.com/api/docs/guides/evaluation-best-practices
[hermes]: https://hermes-agent.nousresearch.com/docs/guides/python-library/
[zotero]: https://www.zotero.org/support/dev/web_api/v3/local_api
