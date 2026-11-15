# 3-minute demo script

Setup before you walk up: `make demo-compare` running, app open in the browser, one warm-up question already asked and the session then reset (sidebar, "New session"). Toggle **off**.

Times are cumulative.

## 0:00 to 0:20 · The problem

**Say:** "A third of American adults now ask AI about their health. Every one of those questions is stored in readable form on someone's server, where a breach, an employee or a court order can reach it. Privacy policies are promises. We replaced the promise with math."

## 0:20 to 1:00 · Ask the question

**Do:** type *How is chlamydia treated and can I get it again?* and press **Ask privately**.

**Say while it runs:** "This is a question nobody wants in a log. My laptop turns it into numbers and encrypts them with a key that never leaves this machine. The server scores all 2,101 passages against a question it cannot read."

**When the answer appears, point at:**
- the green **REAL ENCRYPTED SEARCH** badge,
- the numbered sources, each with its MedlinePlus link and the closest sentence from the source,
- "The answer is written here on the laptop by a local model, only from those passages."

## 1:00 to 1:45 · What the server saw

**Do:** flip **Show what the server saw**. Tick **Demo contrast**. Ask the second question: *Can high blood pressure while I'm pregnant hurt my baby?*

**Say:** "Here is the same question on a normal RAG server, read from its log just now." Point at the red box: the question in plain words and the documents it returned.

"And here is our server's log for that question." Point at the other box: a timestamp, an endpoint, a size, a latency. "Four fields. That is everything it keeps. This box above is the question as our server received it: ciphertext."

## 1:45 to 2:15 · The attacker's view

**Do:** open **Attacker console**. Hand the laptop to a judge, or pick yourself.

**Say:** "You now have our server's database and its logs. Which of these five questions did I ask?" After the guess: "One in five, by luck. Nothing on the server tells them apart."

## 2:15 to 2:45 · The numbers and the honest part

**Do:** open the **Evidence** tab.

**Say (read the real numbers off the screen):** "Encrypted search costs about [N] kilobytes and [N] milliseconds per question on this laptop. The encrypted ranking is identical to plaintext ranking; we test that. On our evaluation the right source is in the top ten for [N] of [N] questions, and off-topic questions are declined instead of answered."

**Do:** open **Who sees what**.

**Say:** "What we do not hide: that you asked, when, and your IP address. And this is a research-grade prototype, not medical advice."

## 2:45 to 3:00 · Close

**Say:** "Any hospital, HR team or legal-aid group could run this server over their own documents. And it cannot leak, sell or hand over a question it never had."

## If you have 20 more seconds

Ask *Can my landlord evict me for reporting mold?* and show the amber **No reliable source found** card: "When the library cannot answer, it says so."

## Rules

- Read numbers from the screen. Do not quote figures from memory or from another machine.
- If the badge is not green, stop and say it is the development mock. Never present the mock as private.
- Do not say "zero leakage", "perfectly private" or "the first".
- Fetch is download-all by default: the laptop downloads the whole small library, so there is nothing for the server to observe. Do not call that PIR.
