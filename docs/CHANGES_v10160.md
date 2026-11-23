# v10.16.0 - AI standards check: violence, sexual content and distress that is not blurred

## What it adds
A **🛡 Standards check (AI)** button, next to Check quality / Frames / Describe with AI / Scan for nudity, on a clip that is on Nitro. Press it and Storigen:
1. cuts about **one still picture every 2 seconds** from the Nitro file (at most 30 per clip; a long clip gets a wider gap, which is reported), 480 px tall, in memory;
2. sends them to **Groq's vision model** in batches of 5 with strict instructions: for each picture and each category say **none**, **blurred** (present but the sensitive part cannot be made out) or **visible** (present, not blurred). *If unsure, answer visible.*
   * **violence**: blood, wounds, injured or dead people, a weapon used on someone, a fight with visible injury;
   * **sexual**: exposed genitals, buttocks or breasts, a sexual act;
   * **distress** ("heartbreak"): a person crying out or breaking down in grief or pain, the bereaved at a body, an injured or dead child, a close-up of a victim in anguish.
   Your own newsroom standard can be added in words (`STANDARDS_NOTE`), and categories can be limited (`STANDARDS_CATEGORIES`).
3. shows a **flag list**, worst first, each with the time range, the picture and the AI's note:
   * **NOT BLURRED: violence / sexual content / distressing scene** (red);
   * **AI says it is blurred: ... (check by eye)** (amber): the AI's judgement of blur is shown, never trusted;
   * **NOT CHECKED: look at this part yourself** (amber): an answer that could not be read, a batch Groq refused or could not be reached for, a picture that could not be taken, or the hourly or time limit: **never treated as fine**.

## It is a help, not a gate
Nothing in the panel ever says a clip is clear: a clip with no flags is **not clearance**. It says "nothing was flagged", plus that the AI sees still pictures only, can miss things, can misjudge "blurred enough", and that someone should watch the clip. Graphic scenes can make a vision model refuse: that shows up as NOT CHECKED.

## Off until an admin switches it on
**Users > Features > AI standards check** (the same switches as the Missing-clip board and the smoke test, kept in the database, logged as `feature_changed`). It starts **OFF** because **still pictures of possibly graphic footage go to Groq, an outside service**; the button asks for a confirmation the first time in each session. Needs `GROQ_API_KEY` (the same key as Describe with AI); without it the button is greyed out and says why. Admins see the switch; every user's page follows within a few seconds.

## Privacy and limits
* Nothing is stored by Storigen: no picture, no result. One event line (`standards_check`) says who ran it and the counts (frames, visible, blurred, not checked): no notes, no pictures.
* The key never reaches the browser, the logs or an error message. A wrong key or an unusable model name stops the check at once with a clear message; a rate limit or an outage in the middle keeps what was already found and lists the rest as NOT CHECKED.
* Cost and speed: 30 pictures = 6 Groq calls, so the default `GROQ_MAX_PER_HOUR=60` allows about 10 clips an hour: raise it if needed. A check takes roughly 10 to 40 seconds.
* The model name is a setting (`GROQ_VISION_MODEL`); Groq changes its list.

## Also in this version
`Storigen-v10_15_0` (Missing-clip board, Bulletin smoke test, Features switches) is the base. The Features page now also drives this feature; the page redraws an open clip when a switch changes.

## Tested, and what is not
`tests/test_standards.py` (14 tests): the frame plan, the prompt, strict parsing (anything unreadable stays unreadable, never "none"), the judge (runs of frames, order, counts), the real check on frames cut from generated clips with a stand-in Groq (batches of 5, the refused batch, a wrong key, a 429 half way, Groq down, the hourly and the time limit, nothing written), the switch (off by default, admin only, logged, kept), the endpoint (gated, 503 without a key, counts-only event, 401, 404), the page wording, and the whole flow in real Chromium. **Not tested: the real Groq.** No internet on the build machine, so whether the live vision model answers in this JSON form, how often it refuses graphic pictures, and how good its "is it blurred enough" judgement is are for you to try on clips you know (graphic, blurred, ordinary) before the desk relies on it. If answers come back unreadable, they show as NOT CHECKED: tell me the model name and I will adjust the prompt.
