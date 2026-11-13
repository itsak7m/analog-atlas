# Pitch video (30 seconds) · Team Cosmic Cats

Rules (Space Apps 2026 Project Submission Guide, read on 13 Nov 2026): the demo is a video of **30 seconds or less** or a deck of **7 slides or less**; English (a spoken video in another language needs English subtitles); hosted on a public link that needs no login (YouTube, Google Drive, GitHub…). SI-generated images and video must carry a **visible watermark**: both videos and every slide show "SI-assisted" (the drawings, slide backgrounds and music were made by code written with Claude; the photos are real).

## Main video · "Earth plays space" advert (ready-made)

- `analog-atlas-pitch-promo30.webm`: 30 s for the submission (1920×1080, about 29 fps, with music). All words are English text on screen, so the text counts as the subtitles.
- `analog-atlas-pitch-promo60.webm`: 60 s for social media.
- Made by `promo.html` (real photos of the app's places, drawn spacecraft, music synthesized in code). The video has no numbers and no percentages (team decision). Most place tags only ask a question about looks ("THE MOON?" over Iceland); they are not data results. Two scenes give a result in words. **"A MOON BASE?"** over the McMurdo Dry Valleys says "our closest twin of Malapert" (in the app the Dry Valleys are the #1 Earth twin of the Malapert Moon base site, full analog match, default weights). **"MARS?"** over Wadi Rum says "Wadi Rum · looks like Mars" and then "Our closest twin of Jezero: Harrat al-Shaam" (added on 26 October): Wadi Rum only looks like Mars, the app ranks it near the bottom for every Mars target, and Harrat al-Shaam is the app's #1 Earth twin of Jezero (full analog match, default weights). The end card now credits the Earth views as NASA Blue Marble and Black Marble (NASA GIBS), because the Earth clip shows night-side city lights.
- **Re-make it after any change to `promo.html`** (recorded again on 13 November 2026 with the "SI-assisted" watermark in the top right corner: 29.99 s and 60.02 s, 1920 x 1080. Before that, on 26 October, with a headless Chrome recorder, from the current `promo.html`: 29.99 s and 59.97 s, 1920 x 1080, with the Harrat al-Shaam line in the "MARS?" scene and the Black Marble credit on the end card). Run `start.bat`, open `http://localhost:8080/pitch/promo.html`, click **Save 30 s** or **Save 60 s**, confirm, and wait until it ends. The page says "saved pitch/…" only when the server wrote and checked the whole file. If a save fails, the page says "NOT saved (the old video was not changed)" and why, and the old video stays as it was. `?record=1` also asks before it records; only a headless Chrome recorder can skip the question, with `?record=1&overwrite=1`. `?t=12` shows one still frame. **Play 30 s** only plays it and changes no file.
- Photo credits and the note "photos cropped and colour-graded, drawings added" are on the end card. YouTube, Google Drive and Clipchamp accept WebM; if a site needs MP4, export it once from Clipchamp.
- Sizes: 30 s about 26.1 MB, 60 s about 50.6 MB. They are in the GitHub repository (pushed with git, so the 25 MB browser-upload limit does not apply) and play in the browser from the GitHub Pages site. You can also play and scrub them at `http://localhost:8080/pitch/analog-atlas-pitch-promo30.webm`.

## Older option · screen recording of the app

The app has a **pitch mode** that plays the 30 seconds by itself, with the English text on screen (the text counts as the subtitles). Every number in its captions is computed from the data when it runs.

## Version 1 · text on screen + music (no voice)

1. Run `start.bat`. Open **http://localhost:8080/?demo** in Chrome.
2. Wait until the globe is loaded. Press **F11** (full screen).
3. Start Windows recording: **Win + Alt + R** (Xbox Game Bar). It records the browser window.
4. Wait until Mars is on screen behind the Start box, then click **Start**. The sequence runs for 30 seconds and ends on the title card.
5. Stop recording: **Win + Alt + R** again. The file is in `Videos\Captures`.
6. Open the file in **Clipchamp** (built into Windows 11): cut the start before "Start" was pressed and keep exactly 30 seconds. Add a free track from Clipchamp's music library (royalty-free) at low volume. Export 1080p.

Tip: run `?demo` once before recording, so the Mars images are already loaded (cached) and the camera moves stay smooth.

## Version 2 · English voice

Same recording, then record the voice in Clipchamp (Record → Audio) while watching it, or record on a phone and drop it in. Read slowly; each line must finish inside its time slot.

| Time | On screen | Voice (English) |
|---|---|---|
| 0–4 s | Title over Mars | "Where on Earth can crews train for the Moon and Mars?" |
| 4–9 s | Mars, Jezero Crater | "We compare Earth with thirteen Moon and Mars sites, using open, sourced data." |
| 9–17 s | Earth sites, then #1 twin | "Nineteen Earth sites, five pillars. Jordan's Harrat al-Shaam is the closest twin of Jezero Crater." |
| 17–22.5 s | Discover Jordan squares | "Then we score all of Jordan the same way. The data agrees with our pick." |
| 22.5–26.5 s | Twin photos | "Satellites show what the ground is made of. Next, our field kit." |
| 26.5–30 s | End card | "Analog Atlas, by Cosmic Cats." |

About 70 words: speak calmly, about 2.5 words per second. The subtitle file `subtitles_en.srt` has the same lines and timing (upload it to YouTube with the video, or keep the on-screen text as the subtitles). The clips in `voice/` (line1.wav to line6.wav) were made on 11 October from an earlier version of these lines: lines 1, 2, 4 and 5 have changed since (line 1 now says "crews", the same word as the title card), so record those four again before you use them.

Why these words: the data is real and sourced (measured where possible, "not measured" otherwise), not "measured only"; Discover Jordan confirms our hand-picked Jordan sites rather than finding new analogs by itself; and the satellite readings of the ground are shown next to the score, never used in it, so they show the ground, they do not "confirm" it.

## Before uploading

- Exactly 30 s or less. English text visible. No copyrighted music (use Clipchamp's library or no music).
- The team decides where to upload; the link must be public.
- Never show `config.js` or `earthdata_token.txt` in a recording.
