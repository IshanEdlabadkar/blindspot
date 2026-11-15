# Demo runbook

## Cold start (about 3 minutes)

On the demo Mac, in Terminal:

```bash
cd ~/blindspot
git pull
make stop                # clears any old server or helper
make demo-compare        # server + key helper + plaintext contrast server + UI
```

Wait for the browser to open. `make demo` (without `-compare`) skips the plaintext server if you do not need the side-by-side log.

In a second Terminal tab:

```bash
cd ~/blindspot && make preflight
```

It must end with **READY FOR THE DEMO**. A `FAIL` line names the fix. `SKIP` lines mean a model was switched off: not acceptable for the real demo.

## Warm up (do this every time)

1. Ask *How is chlamydia treated and can I get it again?* once. The first question downloads the public scoring hint (17 MB) and loads the language model, so it is the slow one.
2. Check the badge is green: **REAL ENCRYPTED SEARCH**.
3. Check the three health dots under the title are green.
4. Sidebar (arrow, top left) → **New session** to clear the history.

## If something fails

The app never falls back to a weaker mode by itself. It shows a red box naming the stage and the fix.

| Symptom | Fix |
| --- | --- |
| Red dot: Document server | `make stop`, then `make demo-compare` |
| Red dot: Key helper | same |
| Red dot: Local model | `brew services start ollama`; if the model is missing, `ollama pull llama3.2:3b` |
| "No module named streamlit" | Use `make demo`, not `python3 -m streamlit`. On this Mac `python3` is the wrong Python; `python3.12` has the packages |
| "Refusing to send an unencrypted question" | You started the UI in mock mode against the real server. Use `make demo` |
| Server says 409 or scores look wrong after a pull | `make stop`, then `make demo`: an old server was still running |
| First question takes very long | Model and hint downloads. Needs internet once; after that it works offline |
| Contrast box says the plaintext server is unreachable | You ran `make demo`, not `make demo-compare` |
| Nothing works and you are on in two minutes | Play the backup recording |

Venue network down: everything runs on the laptop. Only the first-ever model and hint download needs internet, so do the warm-up before you leave a working network.

## Record the backup (do this once the pre-flight passes)

1. Warm up as above, then **New session**.
2. Press **Cmd+Shift+5**, choose "Record Selected Portion", frame the browser window, press Record.
3. Perform [SCRIPT.md](SCRIPT.md) in full, speaking the lines.
4. Stop from the menu bar. Save as `demo/backup-recording.mov` on the laptop. Do not commit it: it is large. Keep a copy on a USB stick or in the team drive.
5. Watch it once. If the badge was not green or an answer was wrong, record again.

## Screenshots to capture on the Mac (real mode)

Use **Cmd+Shift+4**, then Space, then click the browser window. Save into `demo/screenshots/`.

| File name | What is on screen |
| --- | --- |
| `1-answer.png` | Question 1 answered, green badge, sources with excerpts |
| `2-server-contrast.png` | Toggle on, contrast ticked, both log boxes visible |
| `3-attacker.png` | Attacker console open with the five options |
| `4-evidence.png` | Evidence tab after `make measure` has run |
| `5-decline.png` | The landlord question with the amber decline card |

Then replace the two images in `docs/img/` used by the main README.
