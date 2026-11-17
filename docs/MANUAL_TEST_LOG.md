# Manual test log

This document records tests whose **acceptance criterion is determined by a
person** through direct inspection. A tool may generate or display the data,
but an AI evaluation does not replace human review or approval. Record only
observations reported by the reviewer; do not assume results or include
sensitive data.

Automated tests, commands, and technical results are recorded separately in
[TEST_LOG.md](TEST_LOG.md).

## MT-001 — Visual placement of OCR words

| Field | Value |
|---|---|
| Record date | 2026-11-15 |
| Reviewer | Project user; name not provided |
| Result | **Approved by the reviewer**, for the inspected document |
| Original document | `sample_pdfs/meeting_minutes.pdf` |
| Visual evidence | `docs_dev/meeting_minutes_ocr_visual.pdf`, local copy excluded from Git |
| Scope | OCR word boxes on both pages |

### Preparation and separation of responsibilities

The OCR service generated the boxes, and a script prepared with the assistant's
help was used to draw them on a copy of the PDF. The **evaluation recorded below
is the observation reported by the user**, not an automated approval or a result
inferred by AI. The current automated verification scope is summarized in
[TEST_LOG.md](TEST_LOG.md).

### Manual procedure

1. Open the local copy with the red boxes overlaid.
2. Visually inspect both pages, zooming in when necessary.
3. Verify that the boxes cover the words without clipping them or becoming
   misaligned.
4. Review the visible names and look for words without boxes or boxes over
   empty space.

### Observations reported by the reviewer

- The boxes cover the words and do not clip them, although not all of them are
  the same size.
- The visible names reviewed, including those mentioned during the test, are
  correctly enclosed.
- The words are surrounded by rectangles, even when they include symbols such
  as `-`, `,`, `:` or `.`.

### Limitations

- One sample PDF was reviewed; this does not validate all documents or all
  rotation or cropping cases.
- The rectangles correspond to **OCR words**. This earlier review does not
  validate the full-name boxes that were implemented later.
- Visual inspection of boxes alone does not verify that the recognized text
  matches character by character, nor does it establish an accuracy metric.

## MT-002 — Visual placement of full names

| Field | Value |
|---|---|
| Preparation date | 2026-11-15 |
| Reviewer | Project user |
| Result | **Approved for the reviewed example**, based on the user's detailed review |
| Original document | `sample_pdfs/meeting_minutes.pdf` |
| Visual evidence | `docs_dev/meeting_minutes_names_visual.pdf`, local copy excluded from Git |
| Intended scope | Full-name boxes returned by `/api/extract` on both pages |

### Proposed procedure

1. Open the local copy with the red boxes and compare it with the original PDF.
2. Review both pages: each box must surround the corresponding name without
   including distant names or becoming misaligned. Look for possible omissions
   and false positives from the NER model.
3. Report the review results so they can be recorded here. Generating the
   evidence and running automated tests **do not** constitute approval.

### Stage review reported by the user

After the recovery correction, the user visually reviewed the stage outputs and
reported:

- **OCR: 100% correct.**
- **NER: 95%:** it did not find Elizabeth Park in several locations.
- **Recovery 1: 100%:** it found the other Elizabeth Park locations and marked
  them with green boxes distinguishing recovered results.
- **Final: 100%:** identical to recovery 1.

The user confirmed that both pages were reviewed in detail. These percentages
are the user's visual assessment of the example, not metrics calculated from an
annotated dataset; the approval does not establish general model accuracy.

### Earlier preliminary observation

The user reported that a name can be visible in OCR and detected as a person
at one location while a later occurrence is not surrounded by a name box.
The exact document positions were not supplied. This is an observation of an
omission, not a completed evaluation of all boxes, false positives or accuracy.
The later stage review above records the user's observations after the recovery
change; it should not be interpreted as an evaluation of other documents.

The file was generated from the real endpoint response; the command and
technical count are recorded in [TEST_LOG.md](TEST_LOG.md). The copy remains
outside Git and does not guarantee behavior for other documents or rotations.

## Template for future manual tests

```markdown
## MT-XXX — Test name
- Date:
- Reviewer:
- Environment and version or commit:
- Objective and scope:
- Tools used to prepare and view the evidence:
- Steps performed by the reviewer:
- Expected result:
- Observations reported by the reviewer:
- Result: approved / failed / partial / pending.
- Available evidence and location:
- Limitations and outstanding actions:
```
