# yt-sub

Bulk-subscribe to YouTube channels from a plain-text list of URLs, using
the official YouTube Data API v3. Progress is tracked in a local SQLite
database and the script is **resumable** — it picks up where it left off
when the daily API quota resets.

Useful for migrating subscriptions between Google accounts, restoring subs
from a [Google Takeout](https://takeout.google.com/) export (YouTube →
*subscriptions.csv*), or sharing a curated channel list with someone else.

## Features

- Official API — no browser automation, no scraping, no ToS gray area.
- Resumable: state stored in SQLite, re-runs continue from the first pending URL.
- Handles the common error cases sensibly:
  - **Already subscribed** → marked `done` (no quota wasted on retries).
  - **Channel deleted / terminated** → marked `skipped`.
  - **Quota / rate-limit** → script exits cleanly; just run again tomorrow.
- OAuth token cached after the first run; no browser on subsequent runs.
- No external state — everything lives in the project directory.

## Requirements

- Python 3.9+
- A Google Cloud project with the YouTube Data API v3 enabled
- An OAuth 2.0 Desktop-app client credential

## Quickstart

Linux / macOS:

```bash
git clone https://github.com/arekm/yt-sub.git
cd yt-sub
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Windows (PowerShell):

```powershell
git clone https://github.com/arekm/yt-sub.git
cd yt-sub
py -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Then on any OS:

1. Put your channel URLs in `input.txt` (one per line).
2. Drop `client_secret.json` (from Google Cloud Console) into this folder.
3. Run `python yt-sub.py`.

On the first run a browser tab opens for OAuth; subsequent runs are headless.

## Google Cloud setup (one time)

The YouTube Data API requires OAuth 2.0 with user consent. Takes about
five minutes.

> The OAuth UI in Google Cloud Console was reorganized in 2024–2025.
> What used to live under *APIs & Services → OAuth consent screen* /
> *Credentials* is now under the **Google Auth Platform** section, split
> across sub-pages: **Branding**, **Audience**, **Data Access**, and
> **Clients**. The steps below use the current naming; older tutorials
> may point at the legacy paths, which still redirect to the same pages.

### 1. Create a project

Go to the [Google Cloud Console](https://console.cloud.google.com/) and
create a new project (or reuse an existing one). Make sure it is selected
in the project picker at the top of the page.

### 2. Enable the YouTube Data API v3

**APIs & Services → Library** → search *"YouTube Data API v3"* → **Enable**.

### 3. Configure the Google Auth Platform

Open **☰ Menu → Google Auth Platform**. On the first visit you'll be
prompted to configure it; fill in the basics and then fine-tune:

- **Branding** — App name (e.g. `yt-sub`), user support email, developer
  contact email. No logo or homepage needed for a Testing-mode app.
- **Audience** — this is the important page:
  - **User type:** `External`.
  - **Publishing status:** keep as **Testing**. Do **not** publish —
    verification is only required for Production apps, and Testing mode
    supports up to 100 test users indefinitely.
  - **Test users:** click **+ Add users** and add the exact email of
    the Google account you will subscribe with. Only listed test users
    can complete the OAuth flow while the app is in Testing.
- **Data Access** — you can leave scopes empty; the script requests
  `https://www.googleapis.com/auth/youtube` at runtime. (Adding it
  explicitly is harmless.)

### 4. Create the OAuth client

**Google Auth Platform → Clients → + Create client** (equivalent to the
legacy *APIs & Services → Credentials → Create Credentials → OAuth client
ID*):

- **Application type:** `Desktop app`
- **Name:** anything
- Click **Create**, then download the JSON from the client's detail page
  (**⬇ Download JSON** button or the download icon in the Clients list).
- Save the downloaded file as `client_secret.json` in the project root
  (next to `yt-sub.py`).

> **Heads-up — 7-day refresh tokens in Testing mode.** While the app's
> publishing status is *Testing* and it requests a sensitive scope
> (which `.../auth/youtube` is), the refresh token Google issues expires
> after **7 days**. At the default API quota (~200 subscribes/day) the
> whole run finishes in about 4 days, so this usually doesn't bite —
> but if you pause for a week or request a large quota increase, you'll
> need to delete `token.json` and re-run the OAuth flow.

## Input format

`input.txt` — one YouTube channel URL per line. Blank lines and lines
starting with `#` are ignored. Only URLs containing `/channel/UC…` are
supported (the standard channel ID form, as exported by Google Takeout):

```
http://www.youtube.com/channel/UC_-S-4Paa9ve6U8-L3xaTwg
http://www.youtube.com/channel/UC_4YBM08hcpJqLl3vvgTqXg
# comments are ignored
```

Re-running after adding new lines is safe — only new URLs are inserted
into the database.

## Usage

```bash
python yt-sub.py
```

Example output:

```
input: +720 new | pending: 720 | done: 0 | skipped: 0 | error: 0
[1/720] ok   UC_-S-4Paa9ve6U8-L3xaTwg
[2/720] dup  UC_4YBM08hcpJqLl3vvgTqXg
[3/720] ok   UC_7aK9PpYTqt08ERh1MewlQ
...
[201/720] stop UCxxx: 403 quotaExceeded — re-run later
```

Status markers:

| Marker | Meaning                                                |
|--------|--------------------------------------------------------|
| `ok`   | Successfully subscribed                                |
| `dup`  | Already subscribed on this account                     |
| `skip` | Channel no longer exists (deleted, terminated, etc.)   |
| `err`  | Unexpected error                                       |
| `stop` | Daily quota or rate limit hit — script exits cleanly   |

### First run (OAuth)

A browser window opens. Sign in with the same account you added as a
test user. Google shows *"Google hasn't verified this app"* — this is
expected for Testing-mode apps. Click **Advanced → Go to {app name}
(unsafe) → Allow**. The resulting OAuth token is cached in `token.json`
and reused on subsequent runs.

## Daily quota

The default YouTube Data API quota is **10,000 units per day**, and each
`subscriptions.insert` call costs **50 units**. That works out to
**~200 subscribes per day**.

The script exits cleanly when the quota is exhausted; just re-run it
after the quota resets (approximately midnight Pacific Time, i.e.
~08:00–09:00 CE(S)T). Subscribing to 720 channels takes about **four
days** at the default quota.

You can request a quota increase at **APIs & Services → YouTube Data
API v3 → Quotas → Queries per day → Edit quota**. Increases are free
but typically take a few days to be approved.

## Checking progress

```bash
python yt-sub.py --status
```

Example:

```
total: 720 | done: 199 (28%) | pending: 520 | skipped: 0 | error: 1

previous errors (1):
  http://www.youtube.com/channel/UC2wNN-Zqiq4J1PLPnyMBWUg  404 publisherNotFound
```

`--status` is read-only — it doesn't call the API and doesn't touch the quota.

## Starting over

Delete `state.db` and `token.json` from the project folder (`rm` on Linux
/ macOS, `del` in cmd, or `Remove-Item` in PowerShell). This forgets all
progress and re-runs the OAuth flow on the next run.

## Troubleshooting

**"Access blocked: *app* has not completed the Google verification process"**
(or *"Dostęp zablokowany"*).
The Google account you signed in with isn't on the test-users list, or
the app was accidentally moved to *In production*. Go to **Google Auth
Platform → Audience**, set publishing status back to **Testing**, and
add the account under **Test users**. Then delete `token.json` and re-run.

**`missing client_secret.json`**.
Download the Desktop-type OAuth client JSON from **Google Auth Platform
→ Clients** (click the client, then ⬇ Download JSON) and save it as
`client_secret.json` in the project root.

**Every call fails with `quotaExceeded`**.
Either today's quota is already used up, or the YouTube Data API isn't
enabled on the project — check **APIs & Services → Enabled APIs**.

**`invalid_grant` / token expired after about a week**.
In Testing mode with sensitive scopes, Google issues refresh tokens that
expire after 7 days. Delete `token.json` and re-run to redo the OAuth
flow.

**`subscriberNotFound`**.
The account doesn't have a YouTube channel / profile yet. Visit
youtube.com in a browser with that account once to initialize it, then
re-run the script.

**Google Workspace account is blocked by admin**.
Workspace admins can block third-party OAuth apps org-wide. Options:
use a personal `@gmail.com` account, ask the admin to allow the app,
or make the project *Internal* and owned by the Workspace organization.

**Browser didn't open for OAuth.**
The console prints the authorization URL — copy it into any browser
manually. The redirect lands on a local loopback port handled by the
script.

## License

Public domain — [The Unlicense](https://unlicense.org/). Do whatever
you want with this code. See [`LICENSE`](LICENSE) for the full text.
