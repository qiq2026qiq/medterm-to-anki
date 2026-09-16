---
name: medterm-to-anki
description: Create or revise medical-English Anki cards in the user's minimal style. Use for medical vocabulary lists, lesson terminology, or requests for the user's preferred Anki style. Produces one card per input entry with General American IPA, concise Chinese explanations, optional user-requested audio, and an optional Cleveland Clinic image. Import through AnkiConnect by default; create an .apkg only when explicitly requested. Do not use for general Anki troubleshooting.
---

# MedTerm to Anki

Create compact, medically accurate cards. Preserve every supplied input entry unless the user requests selection or deduplication. Ask for the destination deck/subdeck before importing if none is given. The default note type is `Minimal Vocabulary with Audio and Image v2`.

## Card contract

Create one forward card per note:

- Front: exactly one input entry as provided and matching General American IPA. The existing pronunciation control may remain in the note template, but the card's Audio field is blank unless the user explicitly requests audio.
- Back: the Chinese meaning, one concise Memory Note, and, only when available, one medically relevant Cleveland Clinic image with linked attribution.
- Preserve the existing 20px grayscale light/dark layout, transparent image container, natural aspect ratio, and orientation-aware image bounds.
- Do not generate, download, synthesize, or attach audio unless the user explicitly requests audio. By default, leave the Audio field empty so the user can provide it later.
- When the user explicitly requests generated audio, use American English unless another variety is requested. When the user supplies audio, preserve that file instead of replacing it with generated speech.

## IPA notation

Use compact General American broad IPA between slashes, with primary/secondary stress marks as needed (for example, `epiphysis` `/ɪˈpɪfəsɪs/`). Do not switch to Merriam-Webster-style respelling or add syllable separators by default.

For this user's cards, render an unstressed rhotic schwa as `ər` rather than `ɚ` (for example, `percentile` `/pərˈsɛntaɪl/`) because it is easier to read in the card font. This is a narrowly scoped display convention: retain the rest of the IPA style, and do not automatically replace the distinct stressed vowel `ɝ`.

## Memory Note style

Write a concise Chinese Memory Note that adds learning value beyond repeating the Meaning field. Usually use one sentence; use two short sentences only when needed for a decisive distinction.

Choose the most useful angle for each entry rather than forcing the same formula onto every card:

- Explain a medically useful prefix, root, suffix, or literal word formation when it genuinely helps decode or remember the term.
- State the decisive clinical or conceptual distinction from an easily confused or closely related term.
- Highlight the most recognizable mechanism, finding, use, or diagnostic association when that is the best retrieval cue.
- Use a short natural memory hook only when it is accurate and genuinely memorable; never invent etymology or a misleading mnemonic.

When the supplied list contains a natural comparison set, coordinate the Notes so each card expresses its own distinguishing feature in parallel wording. Prefer discriminating cues over dictionary-style mini-definitions, but include a compact definition when the Chinese Meaning alone does not identify the concept clearly. Avoid empty remarks, redundant restatement, long encyclopedic explanations, and unsupported clinical claims.

## Medical judgment

Make one independent card for every supplied input entry. Do not automatically split parenthetical abbreviations, slash-separated aliases, or synonyms; keep them on the same card. Split only when the user explicitly requests it or the input already contains separate entries. Preserve the supplied wording unless correction is needed for medical or linguistic accuracy.

Use the LLM for terminology interpretation, IPA, Chinese meaning, concise notes, medically specific Cleveland Clinic image queries, and final image/source judgment. Let `scripts/build_deck.py` handle deterministic formatting, escaping, paths, hashes, caches, TTS, concurrency, media, packaging, and validation.

## Media rules

Use images from Cleveland Clinic only; never use another website and never generate or synthesize an image. Search only Cleveland Clinic for each cache miss. Use an image only when it directly and accurately represents the medical entry and has adequate teaching value. Avoid decorative photos, busy collages, arbitrary thumbnails, and weak matches. If Cleveland Clinic has no suitable image, set `no_image: true` and create the card with empty Image and Source fields; do not continue searching elsewhere. Never reuse image content in the same deck unless requested.

Use cache-first image handling. The default cache is `~/.cache/medterm-to-anki/` (`audio/`, `images/`, `metadata/`); `MEDTERM_TO_ANKI_CACHE` or `--cache-dir` may override it. Image identity is the normalized full input entry plus normalized `image_query`; uncertainty is a cache miss. A valid negative cache means a successful Cleveland Clinic search confirmed no suitable image within the last 90 days; it may be reused until expiry. Every new term, expired negative entry, and uncertain result must be searched. Network errors, blocked downloads, empty/failed tool responses, or incomplete review are search failures—not evidence of no image—and must remain cache misses for later retry. Use `refresh_image_cache: true` to bypass either positive or negative cache. Never accept a weak image when a medically suitable candidate has not been found.

Audio is opt-in. Do not invoke TTS or audio-preparation code merely because the default note type contains an Audio field. Leave that field blank unless the user explicitly requests audio or supplies an audio file.

When generated audio is explicitly requested, the script uses macOS offline `say` + `afconvert`, caches pronunciation-dependent output, and defaults to 8 concurrent TTS workers. Reduce with `--audio-workers` if the machine becomes unstable; do not replace this with network TTS.

## Workflow

1. Process the full input list in one semantic pass. Return compact structured JSON with one card per supplied input entry, all semantic content, and a stable, medically specific Cleveland Clinic `image_query` for every card. Do not spend turns narrating intermediate drafting.
2. Inspect the whole image cache. For every miss, search the exact entry independently through the same Cleveland Clinic site-search index used by `https://my.clevelandclinic.org/search`; run these independent searches concurrently (default 8 workers) so accuracy does not require serial execution. Do not combine several entries into one query. Use `semantic_identity` only when the written entry does not identify the concept well enough for search. The bundled candidate finder opens exactly the top three official results concurrently and removes known site logos and shared placeholder images. Treat those three relevance-ranked results as the complete review scope; do not expand to lower-ranked results, which are usually incidental mentions, department pages, podcasts, or other noise. Medically judge candidates for every term individually; a clearly identified subtype may illustrate a broader entry when it is accurate and useful (for example, an orbital-cellulitis illustration for `cellulitis`). If none of the three contains a suitable image, record a confirmed no-image decision. For each completed search, either add `image`, `source_name`, and `source_url` for an approved Cleveland Clinic image, or set `no_image: true`, `no_image_reason: "confirmed_no_suitable_cleveland_image"`, and a timezone-aware ISO-8601 `image_search_checked_at`. A `search-failed` or `incomplete` result means the search is unresolved and cannot justify `no_image`; retry only that entry, without slowing or repeating successful entries. Do not search another source:

   ```bash
   python3 scripts/build_deck.py spec.json --inspect-image-cache
   python3 scripts/search_cleveland_images.py misses.json --output candidates.json --workers 8
   ```

   `search_cleveland_images.py` accepts optional `candidate_pages` arrays, queries each cache miss separately through Cleveland Clinic's site-search index, opens the top three pages concurrently (default 8 card workers), removes known nonmedical site chrome, and permits only `clevelandclinic.org` page and image URLs in its output. Keep concurrency at 6–8 under normal conditions; reduce it only after observed throttling. Do not increase `--results-per-term` above 3 in the normal workflow. Its candidates never replace medical review.

3. Build an explicitly requested package:

   ```bash
   python3 scripts/build_deck.py spec.json --output deck.apkg
   ```

4. For live AnkiConnect import, prepare deterministic media and fields first. In the default no-audio mode, do not run any command that generates audio; import notes with an empty Audio field. If the user explicitly requested generated audio, the script can prepare media in parallel where safe; the actual image web search remains tool-dependent:

   ```bash
   python3 scripts/build_deck.py spec.json --prepare-media prepared-media.json
   ```

   Upload the manifest rather than reconstructing paths, attribution, or HTML. Use one preparation/upload pass for the batch. Verify the exact deck/subdeck, note count, model compatibility, one distinct Cleveland Clinic image only where available, blank Image and Source fields for `no_image` cards, uploaded media, source links, and resulting content/scheduling. For audio, verify that every Audio field is blank by default; require audio on each note only when the user explicitly requested it.

## Spec fields

Each card requires `word`, `ipa`, `meaning`, and either `note` or backward-compatible `note_html`. `word` represents exactly one input entry and must contain no newline; parentheses, slashes, and synonyms within that entry are kept together. Repeated entries are allowed and receive separate stable card IDs. Use plain `note` by default. Optional fields: `semantic_identity` (only when the written front does not fully identify the medical concept), `audio_text` (only when generated audio was explicitly requested), `audio_path` (only for user-supplied audio), `refresh_image_cache`, and `no_image`. For a cache miss, provide either an approved Cleveland Clinic `image` with `source_name` and `source_url`, or the complete confirmed-no-image fields described above; never provide both. The source URL must use `clevelandclinic.org` or one of its subdomains.

Example:

```json
{"deck_title":"MT::示例","cards":[{"word":"fracture","ipa":"/.../","meaning":"骨折","note":"骨或软骨的连续性中断。","image_query":"site:clevelandclinic.org fracture medical illustration","no_image":true,"no_image_reason":"confirmed_no_suitable_cleveland_image","image_search_checked_at":"2026-09-11T12:00:00+08:00"}]}
```

Save `.apkg` files only to the user-named location or the current task output directory; copy to Downloads only when explicitly requested.
