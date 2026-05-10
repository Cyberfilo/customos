# Behavioural profile

_Generated 2026-05-11T06:47:25.974746+00:00  ·  schema 1.0.0_

## Coverage
- 347,015 events from 33 sources, 1,903 active days from 2018-06-26T00:00:00 to 2026-05-08T00:00:00 (active day = ≥10 events)
- Raw range (unclipped): 2002-05-14T02:00:00 to 2031-12-31T01:00:00 — outliers from old photos and future-dated calendar events are excluded above.

## Rhythm
- Workday window: Mon–Fri: core 08:30–12:30 and 14:00–18:30 (peak focus 10:00–16:00). Regular spillover into early evening 17:30–20:30, plus a frequent late pass 21:30–23:00 for mail/web. Lunch dip ~13:00–14:00.
- Leisure window: Evenings 20:30–23:30 (browsing, messaging, media). Weekends: late start ~10:30/11:00 with activity concentrated 15:00–21:00. Occasional midnight media at ~00:00.
- Notable quirks:
  - Daily 00:00 burst of shell commands (~1000) and file access (~700) — looks like scheduled jobs/backups, not interactive work.
  - Calendar events cluster at 01:00–02:00 local — consistent with all‑day items stored in UTC; not actual night meetings.
  - Late-evening triage: mail/web and messages spike around 22:00; activity often continues to ~23:00.
  - Clear lunch lull around 13:00 (screen time and app focus dip), often accompanied by media playback 11:00–14:00.
  - Friday stands out for heavy terminal use (shell_command >> other days) — likely release/maintenance day.
  - Afternoon pattern: brief dip ~16:00, rebound at ~17:00 (web activity).
  - Focus/Do Not Disturb likely toggles around 23:00 (user_focus peak at 23).
  - Photos activity is extremely high across hours/days, likely background sync/indexing noise rather than active use.
  - Midweek (especially Wed–Thu) is the busiest; weekends show a sharp drop in web/screen time but mail still checked.

> Weekdays follow an office-like cadence in Europe/Rome: start ~08:30, strongest work 10:00–16:00, lunch around 13:00, then tapering but often continuing into early evening, with a frequent 22:00–23:00 catch‑up. Weekends are lighter, skewing to afternoon/evening personal use. Nighttime is mostly quiet except for automated jobs at midnight and occasional media at 00:00.

## Work modes
- **Development & AI** — com.apple.terminal, com.apple.safari, com.anthropic.claudefordesktop, com.apple.finder, com.apple.preview
  - Coding, running commands, researching, and using AI side-by-side. Strong co-activity among Terminal, Safari, Finder, Claude, and Preview.
- **Communication & Quick Share** — net.whatsapp.whatsapp, com.apple.control-center, com.apple.camera, com.apple.safari, com.apple.preview
  - Messaging and sending media or links. WhatsApp frequently co-appears with Control Center, Camera, Safari, and sometimes Preview for attachments.
- **Reading & Reference** — com.apple.safari, com.apple.preview, com.apple.finder, com.apple.music
  - Focused reading of web pages and PDFs with files nearby; Music often plays in the background.
- **Errands & Logistics** — com.revolut.youth, com.apple.passbookuiservice, com.apple.findmy, com.google.maps, net.whatsapp.whatsapp, com.apple.control-center
  - Finances, wallet, location checks, and coordinating plans. These apps commonly appear together within the same session.
- **Leisure & Media** — com.apple.music, com.supercell.laser, net.whatsapp.whatsapp, com.apple.control-center, com.apple.safari
  - Music listening, casual gaming, and light browsing/chatting. Frequent co-activity between Music, WhatsApp, Control Center, Supercell, and Safari.

## Top workflows
- (80× ) **chat + quick settings** ⚙️
    `net.whatsapp.whatsapp → com.apple.control-center → net.whatsapp.whatsapp`
    _Rapid back-and-forth between WhatsApp and Control Center suggests adjusting audio/DND while chatting; could be streamlined with keyboard shortcuts, per-app Focus, or a workspace._
- (73× ) **terminal + web docs** ⚙️
    `com.apple.terminal → com.apple.safari → com.apple.terminal`
    _Ping-pong between Terminal and Safari implies running commands while checking docs/search; split view or a dedicated coding workspace would reduce context switches._
- (64× ) **web docs + terminal** ⚙️
    `com.apple.safari → com.apple.terminal → com.apple.safari`
    _Back-and-forth reference between browser and shell; suggests side-by-side layout or automation to focus the right pane instead of app hopping._
- (37× ) **intensive coding with docs** ⚙️
    `com.apple.safari → com.apple.terminal → com.apple.safari → com.apple.terminal`
    _Repeated A↔B toggling indicates inefficient context switching; a tiling workspace and hotkeys would help._
- (35× ) **share/check location for chat** ⚙️
    `net.whatsapp.whatsapp → com.apple.findmy → net.whatsapp.whatsapp`
    _Switching WhatsApp ↔ Find My suggests looking up a location to message; share sheets or side-by-side would reduce toggles._
- (32× ) **terminal + web docs (loop)** ⚙️
    `com.apple.terminal → com.apple.safari → com.apple.terminal → com.apple.safari`
    _High-frequency alternating between shell and browser; create a coding workspace to avoid repeated app swaps._
- (30× ) **quick settings during chat** ⚙️
    `com.apple.control-center → net.whatsapp.whatsapp → com.apple.control-center`
    _Toggling Control Center around WhatsApp implies adjusting audio/network; map to hardware keys or automate per-app settings._
- (23× ) **payment details for chat** ⚙️
    `net.whatsapp.whatsapp → com.revolut.youth → net.whatsapp.whatsapp`
    _Likely checking Revolut details and pasting into WhatsApp; use share/copy automation or a split workspace._
- (23× ) **capture/share photo for chat** ⚙️
    `net.whatsapp.whatsapp → com.apple.camera → net.whatsapp.whatsapp`
    _Switch to Camera then back to WhatsApp suggests taking a photo or scanning; consider in-app capture or a shortcut._
- (21× ) **extended chat + settings toggles** ⚙️
    `net.whatsapp.whatsapp → com.apple.control-center → net.whatsapp.whatsapp → com.apple.control-center`
    _Repeated WhatsApp ↔ Control Center cycling indicates ongoing adjustments; Focus automations or keyboard control could help._

## Inferred projects
- ● **Daily workspace and file management** (deep-build)
  - `/Users/filippomattiamenghi`
  - `/Users/filippomattiamenghi/Downloads`
  - `/Users/filippomattiamenghi/Desktop`
  - `/Users/filippomattiamenghi/Documents`
  - `/Users/filippomattiamenghi/Library`
  - _Very high and frequent activity (home 730, Downloads 537, Desktop 103) with last use 3–6 days ago indicates ongoing daily work._
- ◌ **Powairx website and assets** (dormant)
  - `/Users/filippomattiamenghi/Desktop/Powairx-website`
  - `/Users/filippomattiamenghi/Downloads/powairx-imageless`
  - `/Users/filippomattiamenghi/Downloads/powairx-imageless 2`
  - _Moderate touches (6–7 each) but no activity for 138–187 days._
- ◌ **BetterDock (iOS + router)** (dormant)
  - `/Users/filippomattiamenghi/Desktop/BetterDock_ios`
  - `/Users/filippomattiamenghi/Desktop/betterdock_router`
  - _Total ~15 touches with last access 164 days ago._
- ◌ **UFADE** (dormant)
  - `/Users/filippomattiamenghi/Desktop/UFADE`
  - _15 touches but inactive for 188 days._
- ◌ **Jota Racing (Real version)** (dormant)
  - `/Users/filippomattiamenghi/Downloads/Jota Racing Real version`
  - _10 touches; last activity 185 days ago._
- ◌ **Flask ToDo app** (dormant)
  - `/Users/filippomattiamenghi/Desktop/Flask_todo_main`
  - _5 touches; last activity 167 days ago._
- ◌ **Liquid Glass** (dormant)
  - `/Users/filippomattiamenghi/Desktop/Liquid Glass`
  - _6 touches; last activity 328 days ago._
- ◌ **Personal portfolio site** (dormant)
  - `/Users/filippomattiamenghi/Desktop/Portfolio `
  - _3 touches; last activity 171 days ago._
- ○ **Smart-IGCSE platform** (early-explore)
  - `/Users/filippomattiamenghi/Downloads/Smart-igcse-platform`
  - _Recent activity (5 days ago) with low volume (4 touches) suggests initial exploration._
- ◌ **English First Language IGCSE materials** (dormant)
  - `/Users/filippomattiamenghi/Downloads/English First Language IGCSE`
  - _3 touches; last activity 222 days ago._
- ◌ **GoPro media import** (dormant)
  - `/Users/filippomattiamenghi/Downloads/100GOPRO`
  - _83 touches on a single day; no activity since (266 days)._
- ◌ **Obsidian knowledge base** (polish)
  - `/Users/filippomattiamenghi/Documents/Obsidian Vault`
  - _Occasional updates (8 touches) with moderate recency (49 days) indicate maintenance/organizing rather than active build._
- ◌ **Chat prototype** (dormant)
  - `/Users/filippomattiamenghi/Desktop/chat`
  - _6 touches clustered over two days; inactive for 82 days._
- ◌ **Checkout prototype** (dormant)
  - `/Users/filippomattiamenghi/Desktop/checkout`
  - _4 touches on one day; inactive for 93 days._

## Browsing
- Style: **Reference-heavy student–developer who bounces between coding tools and school resources, punctuated by social/entertainment bursts. Heavy use of Google as a hub, frequent dev dashboards and AI assistance, and split comms via Gmail/Outlook/Snapchat. Likely a rapid context-switcher with moderate-to-high tab persistence.**
- Research / Leisure / Reference share: 8% / 24% / 38%
- Tab-hoarding score: **0.62** / 1.0

## Idiosyncrasies
- Peak focus sits 10:00–16:00 with intense Terminal ↔ Safari back‑and‑forth during coding/research.
- Fridays show outsized Terminal activity (deploy/build/railway workflows) — likely a release/maintenance cadence.
- A large automated burst of shell commands and file opens fires right at 00:00 (backups/jobs), with little/no user input — not real usage.
- Late‑evening triage window 21:30–23:00: Gmail-in-Safari + WhatsApp spike; Focus/DND often toggled near 23:00.
- Clear lunch lull around 13:00 with Music playing between ~11:00–14:00.
- Frequent WhatsApp ⇄ Control Center toggles (audio/DND adjustments), often alongside headphone proximity events.
- WhatsApp is frequently paired with Find My (location lookup/share) and Camera (quick capture → share).
- Photos background indexing is noisy across hours/days and inflates perceived “Photos usage.”
- Weekday login pattern quickly flows into Safari then Terminal (startup-to-work ramp).

## Customisation hooks
LLM-suggested customisation hooks were moved out of `profile.json` and now live in `output/hook_suggestions.json`. They are advisory — triggers reference predicates that may not yet be computable by any CustomOS subsystem. Treat them as inspiration for future automation work, not as a contract.

## Top apps (raw)
- ●  5938× — com.apple.terminal
- ●  5495× — com.apple.safari
- ●  4421× — net.whatsapp.whatsapp
- ●  2279× — com.anthropic.claudefordesktop
- ●  1933× — com.apple.finder
- ●   996× — com.apple.control-center
- ●   969× — com.apple.music
- ●   722× — com.apple.preview
- ●   606× — md.obsidian
- ●   399× — com.apple.loginwindow
- ●   379× — com.apple.camera
- ●   299× — com.supercell.laser
- ●   207× — com.apple.findmy
- ●   203× — com.revolut.youth
- ●   185× — com.brave.browser

## Top domains (raw)
- 15304 visits — www.google.com  ·  _reference_
-  7792 visits — www.instagram.com  ·  _leisure_
-  5131 visits — railway.com  ·  _reference_
-  4695 visits — www.icloud.com  ·  _tooling_
-  4639 visits — github.com  ·  _tooling_
-  3948 visits — www.tiktok.com  ·  _leisure_
-  2950 visits — maths.sparx-learning.com  ·  _research_
-  1409 visits — music-mind-git-staging-cyberfilos-projects.vercel.app  ·  _tooling_
-  1333 visits — ebook.sanoma.it  ·  _reference_
-  1146 visits — igcse.menghi.dev  ·  _research_
-  1138 visits — accounts.google.com  ·  _tooling_
-  1114 visits — www.chunkbase.com  ·  _leisure_
-   956 visits — mail.google.com  ·  _communication_
-   938 visits — claude.ai  ·  _tooling_
-   846 visits — powairx.it  ·  _reference_
