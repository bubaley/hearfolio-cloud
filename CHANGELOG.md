# Changelog

All notable changes to this project are documented in this file.
It is generated from conventional commits by the release job; do not edit it by hand.

## [0.3.0] - 2026-11-14

### Features
- **web:** unify the page shell and rework the recording pages (a2de16d)
## [0.2.0] - 2026-11-13

### Features
- **web:** cleaner list pages, tag dialog, app logo and quieter controls (1247bf7)
## [0.1.0] - 2026-11-13

### Features
- **organization:** add membership roles and product spec (17007d2)
- **ai:** add organization AI settings, summary templates and transcription engine (ad1da81)
- **organization:** add roles enforcement, invites, OAuth PKCE and server discovery (d83e163)
- **library:** add projects, tags, recordings, uploads, sync and share links (91efa08)
- **ai:** add recording processing pipeline, summaries and retry/retranscribe (05ec18a)
- **web:** add sidebar shell, organization settings, invite and OAuth consent pages (e4a5026)
- **web:** add projects sidebar and page, project and tag settings, public share page (f1481ee)
- **web:** add recordings list, recording page, browser upload and quick search (127ac38)
- **web:** polish settings, sign-in, landing and shell UX (a98c139)
- **web:** recordings, projects, player and ⌘K UX review fixes (1ea94b8)
- **deploy:** add Dokploy compose that builds from the repository (57c1035)
- close API gaps for the web client and drop its workarounds (7b12042)

### Bug fixes
- **library,ai:** close review findings on privacy, pipeline, uploads and sync (8577b93)
- **ai:** give summary template description a database default so upgrades with existing templates migrate (5873d35)
