# Skills lab: from a stored logbook photo to a skills + time report

## Short answer

Don't look for one model that does everything. There is no ready-made model that takes a photo of a handwritten
attachment logbook and returns "networking, troubleshooting...". Split it into three small jobs, each with its own
model, and keep the student in the loop:

```
stored logbook photo ──► 1. cut into day cells ──► 2. read the handwriting ──► 3. student checks the text
                              (OpenCV, done)          (OCR: the risky part)          (also makes your training data)
                                                                                        │
                    attachment report (.docx) ◄── 5. tally per student ◄── 4. tag with IT skill categories (NLP)
```

| Step | What | Status in this folder |
|---|---|---|
| 1 | Find the ruled table, cut out each day's description cell, erase the grid lines | `ocr.extract_day_cells`: tested on synthetic phone-style photos |
| 2 | Read the handwriting | `TesseractEngine` (offline) and `TrOCREngine` (Hugging Face), same interface |
| 3 | Student confirms or corrects the text | data model ready (`store.py`, `confirmed` flag); screen not built into the GUI yet |
| 4 | Tag text with the 10 categories in `taxonomy.py` | 5 interchangeable backends, benchmark script |
| 5 | Word report | `report.py`, example output: `python -m skills_lab demo` |

## Where Hugging Face fits

Hugging Face (huggingface.co) is a library of pre-trained models you download and run on your own PC. You need it in two places:

**Step 4, tagging (easy, good fit).** Three ways, from least to most effort:
1. *Zero-shot* with a sentence-embedding model (e.g. `sentence-transformers/all-MiniLM-L6-v2`): compares each entry with the category descriptions. No training data. `--backends embed_zeroshot`.
2. *Embeddings + logistic regression*: same model, plus a small classifier trained on your confirmed entries. This is the classifier-head part of SetFit. `--backends embed_logreg`.
3. *Fine-tune with SetFit* once you have roughly 8-16 confirmed examples per category. Not wired in yet because there is no real data to train on.
There is also NLI zero-shot (`facebook/bart-large-mnli`, `--backends nli_zeroshot`): needs no data but is the slowest.

**Step 2, reading handwriting (hard).** `microsoft/trocr-base-handwritten` is the usual starting point. It reads one text line at a time, which is why step 1 cuts the page into cells and `split_lines` cuts the cells into lines. Expect it to be better than Tesseract on handwriting but not perfect on phone photos of student handwriting; the only way to know is to test it on your students' pages. Multimodal "vision-language" models can read whole pages, but they are large, and some have licence limits: check before using one.

## What was and was not tested here

- Tested: cell cutting (5 of 5 rows on tilted, shaded, perspective-distorted synthetic photos), empty-cell detection, Tesseract on *typed* text (5 of 5 rows), the whole pipeline into a Word report, and the Hugging Face wiring using stand-in models.
- **Not tested: any real Hugging Face model.** The sandbox this was built in cannot reach huggingface.co, so no accuracy number for TrOCR, embeddings or NLI is claimed. Run the benchmark below on your own PC.
- **Not tested: real handwriting.** Everything above used synthetic pages. This is the biggest risk in the project.
- The sample dataset (190 entries) was written by the author, not collected from students. It is good for testing the code and for seeding, not for claiming accuracy. On its blind set the offline baselines scored 62% (keywords) and 68% (TF-IDF + logistic regression) top-1. Several of those misses were genuine (e.g. a broken laptop hinge tagged as security).

## Try it on your PC (about 20 minutes)

```
pip install -r requirements.txt -r skills_lab/requirements.txt
pip install sentence-transformers transformers torch     # the Hugging Face part, ~2 GB
python -m skills_lab evaluate --backends all --per-category
python -m skills_lab ocr  some_logbook_photo.jpg --engine tesseract
python -m skills_lab ocr  some_logbook_photo.jpg --engine trocr
python -m skills_lab demo --out sample_report.docx
```

Then the useful experiment: take 5-10 real logbook photos (with the students' permission), type the correct text for each
day into a CSV (`text,labels`, labels separated by `;`, keys from `taxonomy.py`), and run
`python -m skills_lab evaluate --data my.csv --cv 5 --backends all`. Compare OCR output against your typed text too. That
tells you which models are worth it for *your* students' handwriting, rather than which look best in a paper.

## Recommended plan

1. Ship the offline version first (Tesseract + keyword/TF-IDF) with the **student confirming the text and tags**. Even if the OCR is weak, confirmed entries are what make the report trustworthy, and they are your training set.
2. Collect confirmed entries for a cohort. Re-run the benchmark. If TrOCR clearly beats Tesseract on your pages, switch the default engine.
3. When you have about 8-16 confirmed examples per category, fine-tune (SetFit, or embeddings + logistic regression) and compare against the baselines. Keep whichever wins on entries the model has never seen.

## Report and hours

The report is built only from what is in `tracker.db`. The app does not record working hours, so the report leaves hours
as "to be completed" unless you pass `--hours 8` (days logged x hours per day), and says how that figure was worked out.
Supervisor and institution signatures are blank lines. The paper logbook stays the official record.

## Privacy

Logbook photos and face photos are personal data, and logbook text can name colleagues and clients. Get consent, keep
processing local where you can (everything here runs on the PC; Hugging Face models are downloaded once and run
offline), and check what your institution and Kenya's Data Protection Act, 2019 require. This is a pointer, not legal advice.

## Limits to tell students and supervisors

- OCR and tagging both make mistakes; that's why the student confirms.
- A category tag says the entry *mentions* that kind of work, not that the student is competent at it.
- The categories are written for this project (not copied from SFIA, which is copyrighted). Edit `taxonomy.py` freely and map them to your institution's competency list if needed.
