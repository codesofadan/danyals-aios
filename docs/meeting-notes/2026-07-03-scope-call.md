# AIOS Scope Call - Meeting Notes

**Source:** Fathom recording - https://fathom.video/share/3ox1nGxPXayK7nNoF3jmyZdn2yzaesFu
**Title:** Impromptu Google Meet Meeting
**Date:** 2026-07-03
**Duration:** 61 minutes
**Attendees:** Danyal (client / agency owner), Muhammad Adan (developer - VPS setup), Zain Saeed (founder, Xegents AI)

---

## Meeting Purpose
Review the proposed SEO automation system and define the project scope.

## Key Takeaways
- **System Architecture:** Cloud-based system with three core modules - Audit, Content, and a Client Portal. Cloud chosen to manage the high API costs of running automated processes.
- **Automation Goal:** ~90% automation for content creation and page publishing, reducing manual effort from hours to minutes per page.
- **Client Portal:** Central hub for clients to view reports, track milestones, and access upsell opportunities. Decision: link upsells to **Fiverr gigs**, not internal services, to maintain the agency's public brand identity (currently centered on Fiverr).
- **Project Scope:** Initial build = Audit, Content, and Portal modules. **Off-Page module is out of scope for now** and will be documented for a future discussion.

---

## System Overview & Architecture
Cloud-based platform to automate SEO tasks. Cloud chosen over local to manage high API costs.

**Modules:**
- **Audit** - Generates comprehensive SEO reports.
- **Content** - Automates content generation and publishing.
- **Client Portal** - The client-facing dashboard.
- **Reporting** - Integrates with Google Sheets for data visualization.

## Audit Module
Generates comprehensive SEO audits (20-30+ pages) covering on-page, off-page, technical, local, and AI elements.

**Report Types:**
- **Financial:** Estimates market capacity and potential revenue.
- **Technical:** Analyzes domains and technical issues.
- **Actionable:** Pinpoints specific pages and suggests improvements (e.g., title tags, NAP).

**Client Access:** Clients can run free or paid audits directly from the portal.

## Content Module
Cloud-based AI system for generating content, chosen to manage API costs.

**Functionality:**
- Generates various content types (service pages, blogs) using frameworks like AIDA.
- Includes automated schema markup.

**Automation Workflow:**
- **Option 1 (Manual):** Generates content as a PDF for manual publishing.
- **Option 2 (Automated):** Connects via WordPress API to publish content, metadata, and images directly.

**Goal:** ~90% automation, reducing manual effort from hours to minutes per page.
**Cost:** Estimated ~$10-$50 per page, depending on complexity.

## Client Portal
Central dashboard for clients to view progress and access services.

**Client View:**
- **Reports:** Access audit reports (as web pages or downloadable PDFs).
- **Milestones:** Track project progress, updated automatically.
- **Upsells:** Discover additional services via clickable buttons.

**Upsell Strategy:**
- **Decision:** Upsells link to Fiverr gigs, not internal services.
- **Rationale:** Maintains the agency's public brand identity, currently centered on Fiverr.

**Admin View:**
- Super-admin dashboard for the agency owner to monitor team activity and client status.

## Project Logistics
- **Timeline:** Initial build estimated at 3-5 weeks.
- **Scope Management:** New feature requests documented for a future phase to avoid delaying the core project.
- **VPS Access:** Muhammad Adan requires VPS access to begin setup.
- **Fiverr Data:** Future discussion on how to import client data from Fiverr into the new system.

---

## Next Steps
**Danyal:**
- Provide VPS access to Muhammad Adan.
- Document the Off-Page module for a future discussion.
- Share Fiverr client data for analysis.

**Muhammad Adan:**
- Set up the VPS upon receiving access.

**Zain:**
- Schedule the next call in 1-2 weeks to review the Off-Page module documentation.

---

## Action Items (from Fathom)
- Send VPS/hosting requirements to Danyal; then Danyal provisions VPS and shares access - **Muhammad Adan** @ 54:24
- Send Slack email to Danyal; then Danyal added to Slack - **Zain Saeed** @ 59:27

## Open Questions Raised In Call
- Running cost of reports / API cost of the system.
- Total system cost estimate.
- Schema handling specifics in the Content module.
- Whether the existing portal can be reused/provided.
- What exactly happens in the Off-Page module phase (deferred).
- Whether clients and team members can both run the tools.
