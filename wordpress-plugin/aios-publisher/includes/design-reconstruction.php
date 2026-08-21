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
	// Remove any angle brackets: inside <style>, `</style>` is the only way out. No tags,
	// no `<`, no `>` -> the text is inert CSS that cannot escape the style element.
	$css = str_replace( array( '<', '>' ), '', $css );
	$css = trim( $css );
	if ( strlen( $css ) > 40000 ) {
		$css = substr( $css, 0, 40000 );
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
	$css = aios_publisher_sanitize_css( (string) $request->get_param( 'design_css' ) );
	if ( '' !== $css ) {
		update_post_meta( $post_id, AIOS_PUBLISHER_META_DESIGN_CSS, wp_slash( $css ) );
	}
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
	$data = (string) $request->get_param( 'elementor_data' );
	if ( '' === trim( $data ) || ! aios_publisher_is_valid_json( $data ) ) {
		return;
	}
	$decoded = json_decode( $data, true );
	// Elementor's _elementor_data is a JSON ARRAY of top-level sections; a non-array (or
	// empty) payload is not a valid tree, so skip it and leave a normal post.
	if ( ! is_array( $decoded ) || empty( $decoded ) ) {
		return;
	}

	// Constrain the edit mode to the safe set; default to Elementor's "builder".
	$edit_mode = sanitize_key( (string) $request->get_param( 'elementor_edit_mode' ) );
	if ( 'builder' !== $edit_mode ) {
		$edit_mode = 'builder';
	}

	update_post_meta( $post_id, '_elementor_edit_mode', $edit_mode );
	// wp_slash so the JSON survives the DB write exactly as Elementor stores it.
	update_post_meta( $post_id, '_elementor_data', wp_slash( $data ) );
	$version = defined( 'ELEMENTOR_VERSION' ) ? ELEMENTOR_VERSION : '3.0.0';
	update_post_meta( $post_id, '_elementor_version', $version );
	// Elementor renders its own layout, so tell the theme to use a full-width/blank
	// template where supported (best-effort; harmless on themes that ignore it).
	update_post_meta( $post_id, '_wp_page_template', 'elementor_header_footer' );
}
