<?php
/**
 * AIOS Publisher — Design/Reconstruction (Elementor widget-tree storage, design CSS storage, in-body image sideload/reconstruction)
 *
 * Split out of the single-file plugin (Website-Reconstruction Phase 10) for the
 * plugin-ecosystem architecture: Core Connector / Auto Publisher / Design-
 * Reconstruction / Theme Adapter. Pure code-motion — no logic changed; every
 * function body below is byte-identical to the original monolithic file.
 *
 * @package AIOS_Publisher
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

/**
 * Import every <img src="..."> the post body references into this site's OWN media
 * library and rewrite the body to point at the local copies - so a published page
 * never stays dependent on the AIOS server hosting the source images (they are
 * typically the AIOS content-image host, which is not guaranteed to serve forever).
 *
 * Best-effort PER IMAGE: a failed sideload leaves that one <img> unchanged (still
 * pointing at its original URL) rather than failing the whole push. Capped at
 * AIOS_PUBLISHER_MAX_BODY_IMAGES so a pathological draft cannot turn one publish
 * into dozens of blocking outbound fetches.
 *
 * @param int    $post_id The post the sideloaded images attach to.
 * @param string $content The post's HTML content (already wp_kses_post'd).
 * @return string The content with local <img src> URLs, or the ORIGINAL content
 *                unchanged if it has no <img> tags or every sideload failed.
 */
function aios_publisher_sideload_body_images( $post_id, $content ) {
	if ( false === stripos( $content, '<img' ) ) {
		return $content; // fast path: no images at all.
	}

	if ( ! preg_match_all( '/<img\b[^>]*\ssrc=["\']([^"\']+)["\'][^>]*>/i', $content, $matches ) ) {
		return $content;
	}

	// Unique, ordered, capped - a duplicated <img src> is sideloaded once and every
	// occurrence rewritten together.
	$urls = array_slice( array_values( array_unique( $matches[1] ) ), 0, AIOS_PUBLISHER_MAX_BODY_IMAGES );
	if ( empty( $urls ) ) {
		return $content;
	}

	require_once ABSPATH . 'wp-admin/includes/media.php';
	require_once ABSPATH . 'wp-admin/includes/file.php';
	require_once ABSPATH . 'wp-admin/includes/image.php';

	foreach ( $urls as $url ) {
		$clean_url = esc_url_raw( $url );
		if ( '' === $clean_url ) {
			continue;
		}
		$local_url = media_sideload_image( $clean_url, $post_id, null, 'src' );
		if ( is_wp_error( $local_url ) || ! is_string( $local_url ) || '' === $local_url ) {
			continue; // best-effort: this ONE image keeps its original (external) URL.
		}
		$content = str_replace( $url, $local_url, $content );
	}

	return $content;
}
/**
 * Import every image an ELEMENTOR TREE references into this site's own media library,
 * rewriting the tree in place to point at the local copies.
 *
 * WHY THIS EXISTS. `aios_publisher_sideload_body_images()` above only ever sees the post
 * BODY. A design replication puts its entire page in `_elementor_data` and sends a
 * one-line placeholder as the body ("<p>Replicated by AIOS. Open in Elementor to
 * edit.</p>"), so the body sideloader matched nothing and every replicated image stayed
 * hotlinked to the SOURCE domain. Measured on a live replication (2026-09-01): 27 of 27
 * image URLs in the emitted tree still pointed at the source host. That is not a copy of
 * the page - it is a page that borrows its pictures, breaks when the source moves them or
 * blocks hotlinking, and bills the source's bandwidth for the client's traffic.
 *
 * Elementor carries images as `{"url": "...", "id": ...}` under keys like `image` and
 * `background_image`. The `id` matters as much as the url: with a real attachment id
 * Elementor can emit srcset/sizes and its own responsive image handling, which a bare
 * external url cannot do. So this sets BOTH.
 *
 * Best-effort per image, exactly like the body sideloader: one failed import leaves that
 * one image external rather than failing the push. Each distinct URL is fetched once no
 * matter how many nodes reference it, and the whole pass is capped.
 *
 * @param int   $post_id The post the sideloaded images attach to.
 * @param array $tree    The decoded Elementor tree (by reference; rewritten in place).
 * @return int The number of distinct images successfully localized.
 */
function aios_publisher_localize_elementor_images( $post_id, &$tree ) {
	require_once ABSPATH . 'wp-admin/includes/media.php';
	require_once ABSPATH . 'wp-admin/includes/file.php';
	require_once ABSPATH . 'wp-admin/includes/image.php';

	$seen      = array(); // original url => array('url' => local, 'id' => attachment id)
	$localized = 0;
	$budget    = AIOS_PUBLISHER_MAX_TREE_IMAGES;

	// AN IMAGE ALREADY ON THIS SITE IS NOT SIDELOADED. It is already ours, and
	// re-importing it would create a duplicate attachment - on EVERY delivery.
	//
	// That was harmless while this ran only on the single-page publish path, which
	// creates a new post each time. It is not harmless on the whole-site `/site`
	// route, which is deliberately idempotent and re-run for things like a navigation
	// rebuild: without this guard, each rebuild would import a fresh copy of every
	// image on every page and grow the client's media library without bound. A local
	// URL still matches `^https?://`, so the scheme test alone does not catch it.
	$own_host = wp_parse_url( home_url(), PHP_URL_HOST );
	$own_host = is_string( $own_host ) ? strtolower( $own_host ) : '';

	$visit = function ( &$node ) use ( &$visit, &$seen, &$localized, &$budget, $post_id, $own_host ) {
		if ( ! is_array( $node ) ) {
			return;
		}
		// An Elementor image value: an array carrying a 'url' that points off-site.
		if ( isset( $node['url'] ) && is_string( $node['url'] ) && array_key_exists( 'id', $node ) ) {
			$url       = $node['url'];
			$url_host  = wp_parse_url( $url, PHP_URL_HOST );
			$url_host  = is_string( $url_host ) ? strtolower( $url_host ) : '';
			$is_ours   = ( '' !== $own_host && $url_host === $own_host );
			if ( ! $is_ours && ! isset( $seen[ $url ] ) && $budget > 0 && preg_match( '#^https?://#i', $url ) ) {
				--$budget;
				$seen[ $url ] = false;
				$attachment_id = media_sideload_image( esc_url_raw( $url ), $post_id, null, 'id' );
				if ( ! is_wp_error( $attachment_id ) && $attachment_id ) {
					$local = wp_get_attachment_url( (int) $attachment_id );
					if ( is_string( $local ) && '' !== $local ) {
						$seen[ $url ] = array(
							'url' => $local,
							'id'  => (int) $attachment_id,
						);
						++$localized;
					}
				}
			}
			if ( ! empty( $seen[ $url ] ) ) {
				$node['url'] = $seen[ $url ]['url'];
				$node['id']  = $seen[ $url ]['id'];
			}
		}
		foreach ( $node as &$child ) {
			if ( is_array( $child ) ) {
				$visit( $child );
			}
		}
		unset( $child );
	};

	$visit( $tree );
	return $localized;
}

/**
 * Sanitize a caller-supplied CSS string for safe emission inside a <style> block.
 *
 * The CSS is DATA, never markup: strip every angle bracket so a hostile payload cannot
 * close the <style> tag and inject a <script> (the only real breakout vector for text
 * placed inside <style>), and hard-cap the length so a runaway payload cannot bloat every
 * page render. Returns '' when nothing usable remains. Note: no wp_unslash here - the REST
 * JSON body param and get_post_meta both return unslashed text, and unslashing would strip
 * legitimate CSS escape sequences (e.g. content: "\2022").
 *
 * @param string $css Raw CSS text (no <style> wrapper).
 * @return string Sanitized CSS, or ''.
 */
function aios_publisher_sanitize_css( $css ) {
	$css = (string) $css;
	// Strip `<` ONLY - not `>`.
	//
	// The security property is unchanged: an HTML tag cannot form without `<`, so with
	// every `<` removed the text cannot close the surrounding <style> element or open
	// any other. A bare `>` is inert in that context.
	//
	// Removing `>` as well was silently corrupting real stylesheets. MEASURED on a
	// production design system: 130 of its 557 selectors (23%) use the `>` child
	// combinator, and every one of them was being rewritten into a DESCENDANT selector -
	// which still parses, still applies, and matches far more than it should. That is
	// the worst kind of failure: no error, no warning, subtly wrong styling.
	$css = str_replace( '<', '', $css );
	$css = trim( $css );
	// 40,000 was below what a real design system needs - the same measured stylesheet is
	// 93,622 bytes, so the old cap truncated it mid-rule and shipped a broken block.
	if ( strlen( $css ) > AIOS_PUBLISHER_MAX_DESIGN_CSS ) {
		$css = substr( $css, 0, AIOS_PUBLISHER_MAX_DESIGN_CSS );
	}
	return $css;
}
/**
 * Sanitize + store the design CSS from a publish request (the analyzed-site / template
 * styling). Stored as post meta and enqueued in <head> on the front end so the flat-HTML
 * body matches the design on any theme. Absent / empty -> nothing stored (degrade).
 *
 * @param int             $post_id The created post id.
 * @param WP_REST_Request $request The REST request.
 * @return void
 */
function aios_publisher_store_design_css( $post_id, $request ) {
	aios_publisher_apply_design_css( $post_id, (string) $request->get_param( 'design_css' ) );
	aios_publisher_store_design_fonts( $post_id, $request->get_param( 'design_fonts' ) );
}

/**
 * Sanitize + store the TYPEFACE NAMES the pushed design CSS asks for.
 *
 * WHY THIS EXISTS. The design CSS names its families (`font-family: Poppins, …`) and that
 * is not the same as the site HAVING them: on a site that never loaded Poppins the page
 * renders in whatever comes next in the stack, which is normally the theme's font. The
 * page then looks nothing like the design it was built from and nothing reports a
 * problem, because the CSS is exactly right. Storing the names lets the front end load
 * them from Google Fonts (see aios_publisher_enqueue_design_fonts).
 *
 * Names are restricted to letters, digits, spaces and hyphens - which is every real
 * family name and nothing that could escape a URL - and capped at eight.
 *
 * @param int   $post_id  The created post id.
 * @param mixed $families Caller-supplied list of family names.
 * @return void
 */
function aios_publisher_store_design_fonts( $post_id, $families ) {
	if ( ! is_array( $families ) ) {
		return;
	}
	$clean = array();
	foreach ( $families as $family ) {
		if ( ! is_string( $family ) ) {
			continue;
		}
		$name = trim( preg_replace( '/[^A-Za-z0-9 \-]/', '', $family ) );
		if ( '' !== $name && ! in_array( $name, $clean, true ) ) {
			$clean[] = $name;
		}
		if ( count( $clean ) >= 8 ) {
			break;
		}
	}
	if ( empty( $clean ) ) {
		return; // Never blank a stored list: a push that carries no fonts is not a reset.
	}
	update_post_meta( $post_id, AIOS_PUBLISHER_META_DESIGN_FONTS, $clean );
}

/**
 * Sanitize + store design CSS from a raw value (the `/site` route's per-page form).
 *
 * The request-taking wrapper above is kept as-is because it is on the shipped
 * single-page publish path; this is the same write, reachable with a plain string so
 * the whole-site route can perform it too. Empty -> nothing stored, never blanked: a
 * structural re-delivery that carries no CSS must not strip the styling off a page.
 *
 * @param int    $post_id Target post.
 * @param string $css     Raw CSS text (no <style> wrapper).
 * @return bool Whether CSS was stored.
 */
function aios_publisher_apply_design_css( $post_id, $css ) {
	$css = aios_publisher_sanitize_css( (string) $css );
	if ( '' === $css ) {
		return false;
	}
	update_post_meta( $post_id, AIOS_PUBLISHER_META_DESIGN_CSS, wp_slash( $css ) );
	return true;
}
/**
 * Write the Elementor builder post-meta when the push carried an Elementor widget TREE.
 *
 * Makes the published page FULLY EDITABLE (drag-and-drop) in Elementor rather than flat
 * HTML: WordPress needs `_elementor_edit_mode = "builder"` plus `_elementor_data` (the
 * JSON widget tree) on the post. GUARDED — only runs when `elementor_data` is present and
 * decodes to a non-empty JSON ARRAY (Elementor's top-level shape is a list of sections);
 * otherwise the post is left as a normal post (the flat `content` HTML is always written,
 * so a site without Elementor still renders it). `wp_slash` keeps the JSON intact through
 * the DB write (Elementor reads it back with `wp_unslash`), mirroring Elementor's own save.
 *
 * @param int             $post_id The created post id.
 * @param WP_REST_Request $request The REST request.
 * @return void
 */
function aios_publisher_store_elementor_data( $post_id, $request ) {
	aios_publisher_apply_elementor_tree(
		$post_id,
		(string) $request->get_param( 'elementor_data' ),
		(string) $request->get_param( 'elementor_edit_mode' ),
		(string) $request->get_param( 'template' )
	);
}

/**
 * Write an Elementor widget tree onto a post, from raw values.
 *
 * THE ONE IMPLEMENTATION. `site-assembler.php` carried its own copy of this, written
 * from the same four `update_post_meta` calls but WITHOUT the image-localization pass
 * — so a page delivered through `/site` kept rendering its imagery from whatever
 * server the source tree pointed at, while the identical page pushed through
 * `/publish` had every image imported into the client's own media library. Two copies
 * of a write is how that divergence happened, so there is now one.
 *
 * @param int    $post_id   Target post.
 * @param string $data      The `_elementor_data` JSON (a top-level array of sections).
 * @param string $edit_mode Elementor edit mode; anything but 'builder' becomes 'builder'.
 * @param string $template  'elementor_canvas' | 'elementor_header_footer' (else the latter).
 * @return bool Whether a tree was written.
 */
function aios_publisher_apply_elementor_tree( $post_id, $data, $edit_mode = 'builder', $template = '' ) {
	$data = (string) $data;
	if ( '' === trim( $data ) || ! aios_publisher_is_valid_json( $data ) ) {
		return false;
	}
	$decoded = json_decode( $data, true );
	// Elementor's _elementor_data is a JSON ARRAY of top-level sections; a non-array (or
	// empty) payload is not a valid tree, so skip it and leave a normal post.
	if ( ! is_array( $decoded ) || empty( $decoded ) ) {
		return false;
	}

	// Constrain the edit mode to the safe set; default to Elementor's "builder".
	$edit_mode = sanitize_key( (string) $edit_mode );
	if ( 'builder' !== $edit_mode ) {
		$edit_mode = 'builder';
	}

	// TAKE OWNERSHIP OF THE IMAGERY before the tree is stored. Without this the
	// replicated page renders entirely from the source site's servers - see
	// aios_publisher_localize_elementor_images(). Re-encode from the rewritten tree
	// rather than storing the original $data string.
	$localized = aios_publisher_localize_elementor_images( $post_id, $decoded );
	if ( $localized > 0 ) {
		$reencoded = wp_json_encode( $decoded );
		if ( is_string( $reencoded ) && '' !== $reencoded ) {
			$data = $reencoded;
		}
	}

	update_post_meta( $post_id, '_elementor_edit_mode', $edit_mode );
	// wp_slash so the JSON survives the DB write exactly as Elementor stores it.
	update_post_meta( $post_id, '_elementor_data', wp_slash( $data ) );
	update_post_meta( $post_id, '_aios_images_localized', (int) $localized );
	$version = defined( 'ELEMENTOR_VERSION' ) ? ELEMENTOR_VERSION : '3.0.0';
	update_post_meta( $post_id, '_elementor_version', $version );
	// Elementor renders its own layout, so tell the theme to use a full-width/blank
	// template where supported (best-effort; harmless on themes that ignore it).
	// The caller may name the template: a full replica carries its OWN navbar and
	// footer as page sections, and the theme's chrome must not double up around
	// them - that is `elementor_canvas`. Anything outside the safe set falls back
	// to the header/footer template this plugin has always written.
	$template = sanitize_text_field( (string) $template );
	if ( ! in_array( $template, array( 'elementor_canvas', 'elementor_header_footer' ), true ) ) {
		$template = 'elementor_header_footer';
	}
	update_post_meta( $post_id, '_wp_page_template', $template );
	return true;
}
