<?php
/**
 * Plugin Name:       AIOS Publisher
 * Description:        Receives approved content pushed from the AIOS platform and creates it as a draft you publish from WordPress. Uses its OWN endpoint + shared-key auth, so it works even when the host strips the Authorization header and Application Passwords are disabled. Ships a theme-adaptive article template so every published post looks native to the client's site.
 * Version:           1.13.0
 * Requires at least: 5.6
 * Requires PHP:      7.2
 * Author:            AIOS
 * License:           GPL-2.0-or-later
 * License URI:       https://www.gnu.org/licenses/gpl-2.0.html
 * Text Domain:       aios-publisher
 *
 * WHY THIS PLUGIN EXISTS
 * ----------------------
 * Some managed hosts (Hostinger, and sites behind an aggressive WAF / anti-bot
 * layer) STRIP the HTTP Authorization header before it reaches WordPress and/or
 * DISABLE Application Passwords (the REST endpoint returns 501). The standard
 * WordPress REST publish path (Basic auth / Application Passwords / XML-RPC) is
 * therefore unusable on those sites. This plugin BYPASSES all of that: it exposes
 * its OWN REST namespace (`aios/v1`) authenticated by a shared key sent in the JSON
 * REQUEST BODY (primary, because the body is never stripped) or the `X-AIOS-Key`
 * header (secondary). No Authorization header, no Application Password, no XML-RPC.
 *
 * @package AIOS_Publisher
 */

// Hard exit if called directly (never expose this file to a browser).
if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

// The MAIN plugin file's own path - the includes need THIS (not their own __FILE__,
// which would resolve to their own location under includes/) for anything that must
// be plugin-root-relative: register_activation_hook() and plugins_url() lookups.
define( 'AIOS_PUBLISHER_FILE', __FILE__ );

define( 'AIOS_PUBLISHER_VERSION', '1.13.0' );
define( 'AIOS_PUBLISHER_REST_NAMESPACE', 'aios/v1' );

// A hard cap on how many <img> tags a single push will sideload into the media
// library, so a pathological draft cannot turn one publish into dozens of blocking
// outbound image fetches.
define( 'AIOS_PUBLISHER_MAX_BODY_IMAGES', 20 );
// The same cap for images referenced by an ELEMENTOR TREE rather than by the post
// body. Higher than the body cap because a replicated full page legitimately carries
// far more imagery than an article does - a measured live replication referenced 27
// distinct images, which the body cap of 20 would have silently cut short. Each is
// fetched once no matter how many nodes reference it.
define( 'AIOS_PUBLISHER_MAX_TREE_IMAGES', 60 );
// Ceiling for a pushed design stylesheet. 200,000 rather than the previous 40,000:
// a real design system measured in production is 93,622 bytes, so the old cap
// truncated it mid-rule and shipped a broken block with no error.
define( 'AIOS_PUBLISHER_MAX_DESIGN_CSS', 200000 );

// wp_options keys. The API key lives in its own option so a "regenerate" is a
// focused write; the operator-tunable defaults live in one options array.
define( 'AIOS_PUBLISHER_OPT_KEY', 'aios_publisher_api_key' );
define( 'AIOS_PUBLISHER_OPT_SETTINGS', 'aios_publisher_options' );

// Post-meta keys this plugin owns (used by the managed-posts list + wp_head schema
// + the article template renderer).
define( 'AIOS_PUBLISHER_META_MANAGED', '_aios_managed' );
define( 'AIOS_PUBLISHER_META_PUSHED_AT', '_aios_pushed_at' );
define( 'AIOS_PUBLISHER_META_SCHEMA', '_aios_schema_jsonld' );
define( 'AIOS_PUBLISHER_META_TAKEAWAYS', '_aios_key_takeaways' );
define( 'AIOS_PUBLISHER_META_FAQ', '_aios_faq' );
define( 'AIOS_PUBLISHER_META_CTA', '_aios_cta' );
// The analyzed-site (or template) design CSS, enqueued in <head> on a managed post so the
// flat-HTML body matches the design on ANY theme (a plain default theme, no Elementor).
define( 'AIOS_PUBLISHER_META_DESIGN_CSS', '_aios_design_css' );
// Whether this is a FULL-WIDTH landing page (breaks out of the theme's narrow content
// column) rather than a narrow long-form article. Set by the push for non-article pages.
define( 'AIOS_PUBLISHER_META_FULL_WIDTH', '_aios_full_width' );


/* -------------------------------------------------------------------------- *
 * Plugin ecosystem: split into 4 focused includes rather than one monolithic
 * file (spec section 19). Each owns one responsibility; WordPress loads all
 * four during plugin bootstrap (before any hook fires), so cross-file function
 * calls (e.g. auto-publisher's rest_publish() calling core-connector's
 * aios_publisher_settings()) resolve fine regardless of include order.
 * -------------------------------------------------------------------------- */
require_once __DIR__ . '/includes/core-connector.php';
require_once __DIR__ . '/includes/auto-publisher.php';
require_once __DIR__ . '/includes/design-reconstruction.php';
require_once __DIR__ . '/includes/theme-adapter.php';
// 1.9.0: whole-site delivery (pages + hierarchy + menu + front page). Loaded LAST
// because it reuses aios_publisher_sanitize_content() and aios_publisher_settings()
// from the files above; it adds no hooks that run before rest_api_init.
require_once __DIR__ . '/includes/site-assembler.php';
