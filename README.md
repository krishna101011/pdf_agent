# Study Agent (gpt-oss on Groq, or xAI Grok)

A personal AI helper that runs on **your own computer**. Its brain is any OpenAI-style service. By default that is **Groq running OpenAI's gpt-oss model**; xAI Grok works too. You choose in the app's Settings page.

What it can do:

- **Chat** like a normal AI: answer questions, write code, essays, explanations.
- **PDF study buddy**: open a PDF (a physics book, say), flip to a page, ask "explain this solved example" and it answers using the text of *that page*.
- **Draw diagrams** (flowcharts, mind maps) from a plain request.
- **Publish to GitHub** and **put a simple website on Vercel** (it always asks you first).
- **Write emails** (drafts are free; sending asks you first).
- **Remember** things about you ("remember that I study physics").

## Start it

**Linux / macOS** (in a terminal, inside the folder):

```
./setup.sh       # once
./run_app.sh     # every time, then open http://localhost:8501
```

**Windows:** double-click `setup.bat` once, then `run_app.bat`.

Then open the **Settings** page (left bar):

1. Pick the service (Groq / xAI Grok / Custom). The address and model fill in by themselves.
2. Paste up to **5 API keys**, press **Test** on each, then **Save settings**.
3. Go back to **Study** and chat.

Look around first with no key? `./run_demo.sh` (or `run_demo.bat`) starts a pretend AI.
Prefer the terminal? `python cli.py`. To test all your keys from the terminal: `python check_grok.py`.

## Several keys that switch by themselves

- The agent starts with Key 1. If a key **hits its limit**, **runs out of credits**, or is **rejected**, it moves to the next key and tells you in the chat ("Key 1 hit its usage limit, so I switched to Key 3").
- A key that hit a per-minute or per-day limit **rests** for the time the service asks for, then comes back by itself. A rejected key stays off until you fix it in Settings.
- If every key is resting, it waits up to 30 seconds for the first one to return; otherwise it tells you plainly what to do.
- The Settings page shows a live status for each key (in use, ready, resting, rejected) and the tokens it used this session.
- Keys are saved only on your computer, in `data/settings.json`. That file is ignored by git, so it is never uploaded.
- Use keys from accounts you own. The daily token cap below still applies to the whole agent.

## Using the PDF study buddy

1. In the left bar, upload a PDF (or paste its path on your computer).
2. Use the arrows to go to the page you're reading.
3. Ask your question on the right: "Explain solved example 3.2 step by step."
   The agent is handed the text of the page you're looking at. Tick **"Also show the previous page"** if the example continues from before.
   You can paste a specific highlighted bit into the box under the page.

**Honest limits:** the agent reads the *text* on the page. Pictures, graphs, and scanned pages (photos of pages) can't be read. The app warns you when a page has almost no text. Type or paste the part you mean.

## The safety rails (so it can't run away with your credits or files)

- **Step limit:** one request is allowed at most `MAX_STEPS` loops (default 8, never more than 30).
- **Token limits:** each request has a cap (`MAX_TOKENS_PER_TASK`) and there is a daily cap (`DAILY_TOKEN_LIMIT`). When hit, it stops and tells you in plain words.
- **Pause between steps** (`DELAY_SECONDS`) and automatic retry when the AI service says "slow down".
- These limits protect your own credits. They are not a way around the provider's limits; if the service rate-limits you, the agent waits, retries a few times, then tells you.
- **Asks before acting:** publishing to GitHub, deploying to Vercel and sending email always show you exactly what will happen, with Approve / Deny buttons.
- **Stays in one folder:** file tools can only touch the `workspace` folder.
- **Secret scanner:** it refuses to upload, deploy, email or save anything that looks like a password or key, and never touches `.env`.
- GitHub repos are **private** unless you say otherwise.

## Optional setup for the extras (in `.env`)

| For | Put in `.env` | Where to get it |
|---|---|---|
| GitHub | `GITHUB_TOKEN=` | github.com/settings/tokens (classic, tick `repo`) |
| Vercel | `VERCEL_TOKEN=` | vercel.com/account/tokens |
| Email (Gmail) | `SMTP_USER=` and `SMTP_PASSWORD=` | Google Account > Security > App passwords (not your normal password) |

Vercel deploys simple websites only (a folder with `index.html`, CSS, JS, images).

## Folders

- `workspace/` – the only place the agent reads and writes files (diagrams, drafts, code it writes).
- `data/` – memory (`memory.json`) and today's token count. Delete `memory.json` to wipe memory.
- `agent/` – the code. `app.py` is the screen, `cli.py` the terminal chat.
- `tests/` – automated checks. Run `run_tests.bat` any time you change something.

## If something goes wrong

- **"No API key yet"**: open Settings, paste a key, Test, Save.
- **"rejected the API key"** or **"Incorrect API key provided"**: wrong key for the chosen service (a Groq `gsk_` key needs the Groq option) or a typo. Pick the right service in Settings and Test again.
- **"doesn't know the model"**: Settings > "Show models my key can use", copy a name into Model name.
- **"kept refusing or timing out"**: slow down, check your xAI credits, check your internet.
- **Diagram doesn't draw**: the picture loads a small drawing library from the internet, so you need to be online. The `.mmd` file is saved in `workspace/diagrams` regardless.
