# SEO-CONTENT-OS

A centralized, Claude-Code-native operating system that writes local-SEO web copy for service businesses at a consistently higher grade than a human content shop: ranked, cited by AI answer engines, genuinely human to read, and penalty-proof because every line is written to Google's published rules.

No external APIs. Offline Python tool-scripts for deterministic checks. Live web research at write time to ground every claim.

## What it writes

Six local-SEO page types, each with its own command and a deep playbook trained on real best and worst examples:

- `/write-location-page` - city / location pages
- `/write-service-page` - service pages
- `/write-service-city-page` - service-in-city combo pages (the money pages)
- `/write-homepage` - local service-business homepages
- `/write-about-page` - about / team (E-E-A-T) pages
- `/write-service-area-page` - service-area pages

Plus `/new-client`, `/brief`, and `/qa`.

## How to run

1. `/new-client` - build the client's `brand.yaml` profile (NAP, services, coverage, E-E-A-T assets, voice). Do this once per client.
2. `/brief <page-type> <target query>` - generate the content brief.
3. `/write-<page-type>` - run the full pipeline: research -> outline -> draft -> humanize -> gate -> finalize.
4. Output lands in `output/<client>/<page-slug>/` as a five-file publish-ready package.

Or just invoke a write command directly and it will run the brief step first.

## The non-negotiable

This system does not evade AI detectors and never will (doctrine Law 8: AI-detector score has zero correlation with rankings; Google punishes low-value content, not AI provenance). It humanizes by being substantive, specific, and grounded in real facts, not by laundering text through a paraphraser. If asked for a detector-bypass feature, it refuses.

## Structure

See `CLAUDE.md` for the full operating model, load order, pipeline, and directory map. The build standard is `knowledge/doctrine/seo-system-doctrine.md`.

Built 2026-07-20 PKT. Harvested and adapted from BLOG-OS (pipeline + gates), MARKETING-OS (leaf-artifact playbooks + local GBP method), the AIOS SEO doctrine (governance), and the personal-brand voice system.
