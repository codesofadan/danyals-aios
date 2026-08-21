=== AIOS Publisher ===
Contributors: xegentsai
Tags: content, rest-api, publishing, seo, automation
Requires at least: 5.6
Tested up to: 6.6
Requires PHP: 7.2
Stable tag: 1.5.0
License: GPLv2 or later
License URI: https://www.gnu.org/licenses/gpl-2.0.html

Receives approved content pushed from the AIOS platform and creates it as a draft you publish from WordPress — even when the host strips the Authorization header and Application Passwords are disabled.

== Description ==

AIOS Publisher is a tiny companion plugin for the AIOS SEO platform. When an
operator approves a generated content page in AIOS, AIOS PUSHES it to this plugin,
which creates it on your site as a DRAFT. You then review it and press Publish from
the "AIOS Content" screen — content only ever goes live when a human on the site
says so.

= Why not just use the WordPress REST API / Application Passwords? =

Many managed hosts (for example Hostinger) STRIP the HTTP Authorization header
before it reaches WordPress, DISABLE Application Passwords (the endpoint returns
501), and run an anti-bot layer that blocks non-browser requests. On those sites
the normal REST publish path simply does not work.

This plugin BYPASSES all of that. It exposes its OWN REST endpoint authenticated by
a shared key sent in the JSON REQUEST BODY (which is never stripped) — not the
Authorization header, not an Application Password, and not XML-RPC. It works on
effectively every host.

= What it does =

* Adds one REST endpoint: `POST /wp-json/aios/v1/publish` (shared-key auth).
* Adds a connectivity probe: `GET /wp-json/aios/v1/ping`.
* Creates each pushed page as a DRAFT (configurable) so you publish it yourself.
* Sets the SEO title / meta description / focus keyword for BOTH Yoast SEO and
  Rank Math, so it works with whichever you have installed.
* Stores the JSON-LD schema AIOS generated and outputs it in the page `<head>`.
* Sideloads a featured image when one is supplied and assigns categories.
* Lists all AIOS-pushed content on an "AIOS Content" admin screen with Publish,
  Edit and View actions.
* Ships a polished, THEME-ADAPTIVE article template: pushed posts are skinned to look
  native to the client's site by reading the ACTIVE theme's own colour/font tokens
  (the `--wp--preset--*` custom properties), with a readable measure, an E-E-A-T
  author/date/read-time line, an auto table of contents, a "Key takeaways" callout,
  an accessible FAQ (details/summary) + FAQPage schema, and a closing CTA banner.

== The article template ==

Every pushed post is wrapped in `.aios-article` and styled by `templates/article.css`.
That stylesheet is deliberately brand-agnostic: it reads the ACTIVE theme's design
tokens (`--wp--preset--color--*`, `--wp--preset--font-family--*`, and
`--wp--style--global--content-size`) with neutral fallbacks, so the same template
renders in each client's own palette and fonts with no per-site editing. It is
enqueued ONLY on singular posts marked `_aios_managed=1`, so it never affects the rest
of the site. To re-brand, edit the `--aios-*` variables at the top of the stylesheet.

== Installation ==

1. Zip the `aios-publisher` folder (or upload it directly) and install it from
   **Plugins → Add New → Upload Plugin**, then **Activate**.
2. Open **AIOS Publisher** in the left admin menu.
3. Copy the **Endpoint URL** and the **API Key** shown there.
4. Paste them into AIOS (the client's WordPress settings / Key Vault): the endpoint
   URL as the site URL and the API key as the AIOS Publisher key.
5. (Optional) Set the default post status (Draft recommended), post type, category
   and author, then **Save settings**.
6. In AIOS, approve a content page. It appears under **AIOS Publisher → AIOS
   Content** as a draft. Review it and click **Publish** to take it live.

== Security ==

* The endpoint is authenticated by a constant-time (`hash_equals`) comparison of a
  shared key. Regenerating the key in Settings invalidates the old one immediately.
* All pushed content is treated as DATA: text fields are sanitized, the post body
  is filtered through `wp_kses_post`, image URLs through `esc_url_raw`, and the
  JSON-LD is validated before it is stored or emitted.
* Every admin action is protected by a capability check and a nonce.

== Changelog ==

= 1.5.0 =
* Architecture: split into a Core Connector / Auto Publisher / Design-Reconstruction /
  Theme Adapter ecosystem (`includes/*.php`), loaded by a thin main file. Pure
  reorganization — no behavior changed.
* In-body images are now sideloaded into the SAME site's media library and the post
  body is rewritten to point at the local copies, instead of staying hotlinked to the
  AIOS content-image host indefinitely (capped at 20 images per push, best-effort per
  image — a failed sideload just leaves that one image external).
* The push now sends `featured_image_url` for the draft's hero image, which is
  sideloaded and set as the post's featured image automatically.

= 1.4.0 =
* Design fidelity on ANY theme: the push now sends a `design_css` field (the analyzed
  site's / template's palette, fonts, layout and spacing) which is enqueued in the page
  `<head>` — so a published page matches the analyzed design even on a plain default theme
  with no Elementor. The CSS is sanitized as inert CSS (angle brackets stripped, length
  capped) and scoped to `.aios-page`, and never rides inside the post body.
* Full-width landing pages: a new `full_width` flag adds `.aios-article--full`, which
  breaks the page out of a narrow theme content column and renders it across the full page
  width. Long-form articles (blog / FAQ) keep the narrow reading measure.

= 1.3.0 =
* Hardened styling: strip any `<style>`/`<script>` block (tag and contents) from the
  pushed body before sanitizing, and moved the `.aios-page` layout styles into the enqueued
  `templates/article.css` — so pushed CSS can never leak onto the page as visible text.

= 1.2.0 =
* Elementor-editable output: when the push includes an `elementor_data` widget tree, write
  the Elementor builder post-meta so the page opens fully editable in Elementor. Falls back
  to the flat HTML body on sites without Elementor.

= 1.1.0 =
* Added the theme-adaptive article template (`templates/article.css` + renderer):
  `.aios-article` wrapper styled from the active theme's `--wp--preset--*` tokens,
  E-E-A-T meta line, auto table of contents, "Key takeaways" callout, accessible FAQ
  (details/summary) with FAQPage JSON-LD, and a closing CTA banner. Enqueued only on
  managed posts. The push payload now accepts `key_takeaways`, `faq` and `cta`.

= 1.0.0 =
* Initial release: shared-key `aios/v1/publish` + `aios/v1/ping` endpoints, Yoast +
  Rank Math meta, JSON-LD schema output, featured-image sideload, categories, and
  the "AIOS Content" managed-posts screen.
