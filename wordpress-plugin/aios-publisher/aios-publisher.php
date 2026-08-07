<?php
/**
 * Plugin Name:       AIOS Publisher
 * Plugin URI:        https://xegents.ai/aios-publisher
 * Description:        Receives approved content pushed from the AIOS platform and creates it as a draft you publish from WordPress. Uses its OWN endpoint + shared-key auth, so it works even when the host strips the Authorization header and Application Passwords are disabled. Ships a theme-adaptive article template so every published post looks native to the client's site.
 * Version:           1.2.0
 * Requires at least: 5.6
 * Requires PHP:      7.2
 * Author:            Xegents AI
 * Author URI:        https://xegents.ai
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

define( 'AIOS_PUBLISHER_VERSION', '1.2.0' );
define( 'AIOS_PUBLISHER_REST_NAMESPACE', 'aios/v1' );

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

/**
 * Return the merged plugin settings (status / post_type / category / author),
 * falling back to safe defaults for any missing key.
 *
 * @return array<string,mixed>
 */
function aios_publisher_settings() {
	$defaults = array(
		'status'    => 'draft', // draft | pending | publish  (default DRAFT per the flow)
		'post_type' => 'post',  // post | page
		'category'  => 0,       // default category term id (0 = none / Uncategorized)
		'author'    => 0,       // default author user id (0 = current / first admin)
	);
	$stored = get_option( AIOS_PUBLISHER_OPT_SETTINGS, array() );
	if ( ! is_array( $stored ) ) {
		$stored = array();
	}
	return wp_parse_args( $stored, $defaults );
}

/**
 * Generate a fresh, URL-safe 48-char API key.
 *
 * @return string
 */
function aios_publisher_generate_key() {
	// wp_generate_password with special chars off gives a strong alnum secret.
	return wp_generate_password( 48, false, false );
}

/**
 * Ensure an API key exists (called on activation and defensively on read).
 *
 * @return string The current key.
 */
function aios_publisher_ensure_key() {
	$key = (string) get_option( AIOS_PUBLISHER_OPT_KEY, '' );
	if ( '' === $key ) {
		$key = aios_publisher_generate_key();
		update_option( AIOS_PUBLISHER_OPT_KEY, $key, false );
	}
	return $key;
}

/**
 * The public endpoint URL the operator copies into AIOS.
 *
 * @return string
 */
function aios_publisher_endpoint_url() {
	return esc_url_raw( rest_url( AIOS_PUBLISHER_REST_NAMESPACE . '/publish' ) );
}

/* -------------------------------------------------------------------------- *
 * Activation
 * -------------------------------------------------------------------------- */

register_activation_hook( __FILE__, 'aios_publisher_activate' );

/**
 * On activation, mint an API key if none exists and seed the default settings.
 *
 * @return void
 */
function aios_publisher_activate() {
	aios_publisher_ensure_key();
	if ( false === get_option( AIOS_PUBLISHER_OPT_SETTINGS, false ) ) {
		add_option( AIOS_PUBLISHER_OPT_SETTINGS, aios_publisher_settings() );
	}
}

/* -------------------------------------------------------------------------- *
 * REST API — the OWN endpoint + shared-key auth (the header-strip bypass)
 * -------------------------------------------------------------------------- */

add_action( 'rest_api_init', 'aios_publisher_register_routes' );

/**
 * Register the plugin's two REST routes under the `aios/v1` namespace.
 *
 * @return void
 */
function aios_publisher_register_routes() {
	register_rest_route(
		AIOS_PUBLISHER_REST_NAMESPACE,
		'/publish',
		array(
			'methods'             => 'POST',
			'callback'            => 'aios_publisher_rest_publish',
			'permission_callback' => 'aios_publisher_check_key',
		)
	);
	register_rest_route(
		AIOS_PUBLISHER_REST_NAMESPACE,
		'/ping',
		array(
			'methods'             => 'GET',
			'callback'            => 'aios_publisher_rest_ping',
			'permission_callback' => 'aios_publisher_check_key',
		)
	);
}

/**
 * Extract the caller-supplied shared key. BODY FIELD `api_key` is primary because
 * managed hosts strip request headers; the `X-AIOS-Key` header is a secondary path.
 *
 * @param WP_REST_Request $request The REST request.
 * @return string The provided key (empty string if none).
 */
function aios_publisher_provided_key( $request ) {
	// Body / query param first (survives header stripping).
	$key = $request->get_param( 'api_key' );
	if ( is_string( $key ) && '' !== $key ) {
		return $key;
	}
	// Header fallback (WP normalizes X-AIOS-Key -> x_aios_key).
	$header = $request->get_header( 'x_aios_key' );
	if ( is_string( $header ) && '' !== $header ) {
		return $header;
	}
	return '';
}

/**
 * Permission callback: constant-time compare the provided key against the stored
 * key. NEVER trusts a WordPress capability / cookie here — this is a machine-to-
 * machine endpoint authenticated only by the shared key.
 *
 * @param WP_REST_Request $request The REST request.
 * @return true|WP_Error True when the key matches, else a 401 WP_Error.
 */
function aios_publisher_check_key( $request ) {
	$provided = aios_publisher_provided_key( $request );
	$stored   = (string) get_option( AIOS_PUBLISHER_OPT_KEY, '' );

	if ( '' === $stored || '' === $provided || ! hash_equals( $stored, $provided ) ) {
		return new WP_Error(
			'aios_publisher_forbidden',
			__( 'Invalid or missing AIOS Publisher key.', 'aios-publisher' ),
			array( 'status' => 401 )
		);
	}
	return true;
}

/**
 * Connectivity probe — lets AIOS confirm the endpoint + key work.
 *
 * @param WP_REST_Request $request The REST request.
 * @return WP_REST_Response
 */
function aios_publisher_rest_ping( $request ) {
	unset( $request );
	return new WP_REST_Response(
		array(
			'ok'             => true,
			'site'           => esc_url_raw( home_url() ),
			'name'           => sanitize_text_field( get_bloginfo( 'name' ) ),
			'plugin_version' => AIOS_PUBLISHER_VERSION,
		),
		200
	);
}

/**
 * Create a post from an AIOS push. Treats the payload as DATA (never code): every
 * field is sanitized, the body is run through wp_kses_post, the image URL through
 * esc_url_raw. The post is created at the configured default status (DRAFT), so a
 * human still presses Publish on the WordPress side.
 *
 * @param WP_REST_Request $request The REST request.
 * @return WP_REST_Response|WP_Error
 */
function aios_publisher_rest_publish( $request ) {
	$settings = aios_publisher_settings();

	$title = sanitize_text_field( (string) $request->get_param( 'title' ) );
	if ( '' === $title ) {
		return new WP_Error(
			'aios_publisher_bad_request',
			__( 'A title is required.', 'aios-publisher' ),
			array( 'status' => 400 )
		);
	}

	// Body is HTML — wp_kses_post strips scripts/disallowed tags but keeps markup.
	$raw_content = (string) $request->get_param( 'content' );
	$content     = wp_kses_post( $raw_content );

	// Status is constrained to the safe set; default from settings (draft).
	$status = sanitize_key( (string) $request->get_param( 'status' ) );
	$allowed_status = array( 'draft', 'pending', 'publish', 'private' );
	if ( ! in_array( $status, $allowed_status, true ) ) {
		$status = (string) $settings['status'];
	}

	// Post type is constrained to post|page; default from settings (post).
	$post_type = sanitize_key( (string) $request->get_param( 'post_type' ) );
	if ( ! in_array( $post_type, array( 'post', 'page' ), true ) ) {
		$post_type = (string) $settings['post_type'];
	}

	$slug    = sanitize_title( (string) $request->get_param( 'slug' ) );
	$excerpt = sanitize_textarea_field( (string) $request->get_param( 'excerpt' ) );

	$postarr = array(
		'post_title'   => $title,
		'post_content' => $content,
		'post_status'  => $status,
		'post_type'    => $post_type,
	);
	if ( '' !== $slug ) {
		$postarr['post_name'] = $slug;
	}
	if ( '' !== $excerpt ) {
		$postarr['post_excerpt'] = $excerpt;
	}
	$author = absint( $settings['author'] );
	if ( $author > 0 ) {
		$postarr['post_author'] = $author;
	}

	$post_id = wp_insert_post( wp_slash( $postarr ), true );
	if ( is_wp_error( $post_id ) ) {
		return new WP_Error(
			'aios_publisher_insert_failed',
			$post_id->get_error_message(),
			array( 'status' => 500 )
		);
	}

	// --- Elementor-editable output: write the builder post-meta when AIOS supplied an
	// Elementor widget TREE, so the page opens FULLY EDITABLE (drag-and-drop) in
	// Elementor rather than as flat HTML. GUARDED: only when a valid `elementor_data`
	// JSON array is present; otherwise the post is a normal post (the flat `content`
	// HTML above is always written, so a site without Elementor still renders it). ---
	aios_publisher_store_elementor_data( $post_id, $request );

	// --- SEO meta for BOTH Yoast and Rank Math (works with whichever is active) ---
	$meta_title = sanitize_text_field( (string) $request->get_param( 'meta_title' ) );
	$meta_desc  = sanitize_textarea_field( (string) $request->get_param( 'meta_description' ) );
	$focus_kw   = sanitize_text_field( (string) $request->get_param( 'focus_keyword' ) );

	if ( '' !== $meta_title ) {
		update_post_meta( $post_id, '_yoast_wpseo_title', $meta_title );
		update_post_meta( $post_id, 'rank_math_title', $meta_title );
	}
	if ( '' !== $meta_desc ) {
		update_post_meta( $post_id, '_yoast_wpseo_metadesc', $meta_desc );
		update_post_meta( $post_id, 'rank_math_description', $meta_desc );
	}
	if ( '' !== $focus_kw ) {
		update_post_meta( $post_id, '_yoast_wpseo_focuskw', $focus_kw );
		update_post_meta( $post_id, 'rank_math_focus_keyword', $focus_kw );
	}

	// --- JSON-LD schema: store raw and emit it in wp_head for this post ---
	$schema = (string) $request->get_param( 'schema_jsonld' );
	if ( '' !== trim( $schema ) && aios_publisher_is_valid_json( $schema ) ) {
		// wp_slash so the JSON survives the DB write; wp_kses is NOT used (this is a
		// JSON string echoed inside a <script type="application/ld+json"> block, not
		// HTML) — it is re-validated + emitted safely in aios_publisher_head_schema.
		update_post_meta( $post_id, AIOS_PUBLISHER_META_SCHEMA, wp_slash( $schema ) );
	}

	// --- Article template components (key takeaways / FAQ / CTA) ---
	// Stored as structured post meta and rendered by the theme-adaptive article
	// template (aios_publisher_render_article) + emitted as FAQPage JSON-LD. All are
	// optional: an absent field simply skips that component.
	aios_publisher_store_article_components( $post_id, $request );

	// --- Categories: assign (create if missing) for a 'post' only ---
	$categories = $request->get_param( 'categories' );
	if ( 'post' === $post_type && is_array( $categories ) && ! empty( $categories ) ) {
		$term_ids = aios_publisher_resolve_categories( $categories );
		if ( ! empty( $term_ids ) ) {
			wp_set_post_terms( $post_id, $term_ids, 'category' );
		}
	} elseif ( 'post' === $post_type && absint( $settings['category'] ) > 0 ) {
		wp_set_post_terms( $post_id, array( absint( $settings['category'] ) ), 'category' );
	}

	// --- Featured image sideload (best-effort; a failure never fails the push) ---
	$image_url = esc_url_raw( (string) $request->get_param( 'featured_image_url' ) );
	if ( '' !== $image_url ) {
		aios_publisher_sideload_featured_image( $post_id, $image_url );
	}

	// --- Tag the post as AIOS-managed so the "AIOS Content" list can find it ---
	update_post_meta( $post_id, AIOS_PUBLISHER_META_MANAGED, 1 );
	update_post_meta( $post_id, AIOS_PUBLISHER_META_PUSHED_AT, current_time( 'mysql' ) );

	$final_status = get_post_status( $post_id );

	// NOTE: get_edit_post_link() returns '' for an anonymous REST caller (there is no
	// logged-in user on this shared-key request), so build the wp-admin edit link
	// directly — this is the link the admin clicks to publish the draft on the site.
	$edit_url = admin_url( 'post.php?post=' . $post_id . '&action=edit' );

	return new WP_REST_Response(
		array(
			'ok'          => true,
			'post_id'     => (int) $post_id,
			'status'      => $final_status,
			'url'         => get_permalink( $post_id ),
			'edit_url'    => $edit_url,
			'preview_url' => get_preview_post_link( $post_id ),
		),
		201
	);
}

/**
 * Validate that a string is well-formed JSON (used to gate the schema meta write
 * and the wp_head emission).
 *
 * @param string $json Candidate JSON string.
 * @return bool
 */
function aios_publisher_is_valid_json( $json ) {
	if ( ! is_string( $json ) || '' === trim( $json ) ) {
		return false;
	}
	json_decode( $json );
	return ( JSON_ERROR_NONE === json_last_error() );
}

/**
 * Resolve an array of category names/ids to term ids, creating any missing ones.
 *
 * @param array<int|string> $categories Category names or ids.
 * @return int[] Term ids.
 */
function aios_publisher_resolve_categories( $categories ) {
	$ids = array();
	foreach ( $categories as $cat ) {
		if ( is_numeric( $cat ) ) {
			$term = get_term( absint( $cat ), 'category' );
			if ( $term && ! is_wp_error( $term ) ) {
				$ids[] = (int) $term->term_id;
			}
			continue;
		}
		$name = sanitize_text_field( (string) $cat );
		if ( '' === $name ) {
			continue;
		}
		$existing = get_term_by( 'name', $name, 'category' );
		if ( $existing && ! is_wp_error( $existing ) ) {
			$ids[] = (int) $existing->term_id;
			continue;
		}
		$created = wp_insert_term( $name, 'category' );
		if ( ! is_wp_error( $created ) && isset( $created['term_id'] ) ) {
			$ids[] = (int) $created['term_id'];
		}
	}
	return array_values( array_unique( array_filter( $ids ) ) );
}

/**
 * Sideload a remote image and set it as the post's featured image. Best-effort:
 * any failure is swallowed (the post is already created).
 *
 * @param int    $post_id   The post to attach the image to.
 * @param string $image_url The remote image URL (already esc_url_raw'd).
 * @return void
 */
function aios_publisher_sideload_featured_image( $post_id, $image_url ) {
	// These files are only loaded in admin by default; the REST call runs on the
	// front controller, so require them explicitly before media_sideload_image.
	require_once ABSPATH . 'wp-admin/includes/media.php';
	require_once ABSPATH . 'wp-admin/includes/file.php';
	require_once ABSPATH . 'wp-admin/includes/image.php';

	$attachment_id = media_sideload_image( $image_url, $post_id, null, 'id' );
	if ( ! is_wp_error( $attachment_id ) && $attachment_id ) {
		set_post_thumbnail( $post_id, (int) $attachment_id );
	}
}

/* -------------------------------------------------------------------------- *
 * Front end — emit the stored JSON-LD schema in <head> for a managed post
 * -------------------------------------------------------------------------- */

add_action( 'wp_head', 'aios_publisher_head_schema' );

/**
 * Output the post's stored JSON-LD (if any) inside a schema script block.
 *
 * @return void
 */
function aios_publisher_head_schema() {
	if ( ! is_singular() ) {
		return;
	}
	$post_id = get_queried_object_id();
	if ( ! $post_id ) {
		return;
	}
	$schema = (string) get_post_meta( $post_id, AIOS_PUBLISHER_META_SCHEMA, true );
	if ( '' === trim( $schema ) || ! aios_publisher_is_valid_json( $schema ) ) {
		return;
	}
	// Re-encode through decode/encode to guarantee well-formed, safe JSON output
	// (no raw passthrough of stored bytes into the page).
	$decoded = json_decode( $schema, true );
	if ( null === $decoded ) {
		return;
	}
	echo "\n<script type=\"application/ld+json\">" .
		wp_json_encode( $decoded ) .
		"</script>\n"; // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped -- wp_json_encode produces safe JSON for a ld+json block.
}

/* -------------------------------------------------------------------------- *
 * Front end — the theme-adaptive ARTICLE TEMPLATE
 * --------------------------------------------------------------------------
 * A polished, best-practice article skin applied to managed posts. The scoped
 * stylesheet (templates/article.css) styles the content using the ACTIVE THEME's
 * own `--wp--preset--*` tokens, so every published post looks native to the
 * client's site; the renderer wraps the body in `.aios-article` and adds the E-E-A-T
 * meta line, an auto table of contents, and the key-takeaways / FAQ / CTA components
 * (from the structured post meta the push stored). FAQ also emits FAQPage JSON-LD.
 * -------------------------------------------------------------------------- */

add_action( 'wp_enqueue_scripts', 'aios_publisher_enqueue_article_assets' );
add_filter( 'the_content', 'aios_publisher_render_article', 20 );
add_action( 'wp_head', 'aios_publisher_head_faq_schema' );

/**
 * Is the CURRENT main query a singular, AIOS-managed post? (Gate for the front-end
 * article template so it never touches the rest of the site.)
 *
 * @return int The managed post id, or 0.
 */
function aios_publisher_current_managed_post() {
	if ( is_admin() || ! is_singular() ) {
		return 0;
	}
	$post_id = get_queried_object_id();
	if ( ! $post_id || ! get_post_meta( $post_id, AIOS_PUBLISHER_META_MANAGED, true ) ) {
		return 0;
	}
	return (int) $post_id;
}

/**
 * Enqueue the article stylesheet ONLY on a singular managed post.
 *
 * @return void
 */
function aios_publisher_enqueue_article_assets() {
	if ( ! aios_publisher_current_managed_post() ) {
		return;
	}
	wp_enqueue_style(
		'aios-publisher-article',
		plugins_url( 'templates/article.css', __FILE__ ),
		array(),
		AIOS_PUBLISHER_VERSION
	);
}

/**
 * Wrap + enhance a managed post's content: `.aios-article` wrapper, E-E-A-T meta
 * line, auto TOC, and the key-takeaways / FAQ / CTA components. Non-managed posts
 * (and feeds/excerpts/admin) pass through untouched.
 *
 * @param string $content The post content.
 * @return string
 */
function aios_publisher_render_article( $content ) {
	if ( ! in_the_loop() || ! is_main_query() ) {
		return $content;
	}
	$post_id = aios_publisher_current_managed_post();
	if ( ! $post_id ) {
		return $content;
	}

	$read_time = aios_publisher_read_time( $content );
	list( $content, $toc ) = aios_publisher_build_toc( $content );

	$meta      = aios_publisher_article_meta_line( $post_id, $read_time );
	$takeaways = aios_publisher_render_takeaways( get_post_meta( $post_id, AIOS_PUBLISHER_META_TAKEAWAYS, true ) );
	$faq       = aios_publisher_render_faq( get_post_meta( $post_id, AIOS_PUBLISHER_META_FAQ, true ) );
	$cta       = aios_publisher_render_cta( get_post_meta( $post_id, AIOS_PUBLISHER_META_CTA, true ) );

	return '<div class="aios-article">'
		. $meta
		. $takeaways
		. $toc
		. '<div class="aios-article__body">' . $content . '</div>'
		. $faq
		. $cta
		. '</div>';
}

/**
 * Estimate reading time in minutes (~200 wpm) from rendered content.
 *
 * @param string $content The post content (HTML).
 * @return int Minutes (>= 1).
 */
function aios_publisher_read_time( $content ) {
	$words = str_word_count( wp_strip_all_tags( $content ) );
	return max( 1, (int) ceil( $words / 200 ) );
}

/**
 * Build the E-E-A-T meta line: "By {author} · {date} · {n} min read".
 *
 * @param int $post_id   The post id.
 * @param int $read_time Minutes.
 * @return string
 */
function aios_publisher_article_meta_line( $post_id, $read_time ) {
	$author = get_the_author_meta( 'display_name', (int) get_post_field( 'post_author', $post_id ) );
	$date   = get_the_date( '', $post_id );

	$parts = array();
	if ( $author ) {
		/* translators: %s: author display name. */
		$parts[] = esc_html( sprintf( __( 'By %s', 'aios-publisher' ), $author ) );
	}
	if ( $date ) {
		$parts[] = esc_html( $date );
	}
	/* translators: %d: estimated reading time in minutes. */
	$parts[] = esc_html( sprintf( _n( '%d min read', '%d min read', $read_time, 'aios-publisher' ), $read_time ) );

	return '<div class="aios-article__meta">'
		. implode( '<span class="aios-article__meta-sep">&middot;</span>', $parts )
		. '</div>';
}

/**
 * Inject stable ids into the body H2s and build a table of contents from them.
 * Returns [content-with-ids, toc-html]; the TOC is empty when there are fewer than
 * three H2s (a short post needs no TOC).
 *
 * @param string $content The post content (HTML).
 * @return array{0:string,1:string}
 */
function aios_publisher_build_toc( $content ) {
	$items    = array();
	$used     = array();
	$original = $content;

	$content = preg_replace_callback(
		'/<h2\b([^>]*)>(.*?)<\/h2>/is',
		function ( $m ) use ( &$items, &$used ) {
			$attrs = $m[1];
			$text  = trim( wp_strip_all_tags( $m[2] ) );
			if ( '' === $text ) {
				return $m[0];
			}
			if ( preg_match( '/\bid=("|\')(.*?)\1/i', $attrs, $idm ) ) {
				$id = $idm[2];
			} else {
				$base = sanitize_title( $text );
				if ( '' === $base ) {
					$base = 'section';
				}
				$id = $base;
				$n  = 2;
				while ( isset( $used[ $id ] ) ) {
					$id = $base . '-' . $n;
					$n++;
				}
				$attrs .= ' id="' . esc_attr( $id ) . '"';
			}
			$used[ $id ] = true;
			$items[]     = array(
				'id'   => $id,
				'text' => $text,
			);
			return '<h2' . $attrs . '>' . $m[2] . '</h2>';
		},
		$content
	);

	// A PCRE failure returns null; fall back to the untouched content, no TOC.
	if ( null === $content ) {
		return array( $original, '' );
	}
	if ( count( $items ) < 3 ) {
		return array( $content, '' );
	}

	$lis = '';
	foreach ( $items as $it ) {
		$lis .= '<li><a href="#' . esc_attr( $it['id'] ) . '">' . esc_html( $it['text'] ) . '</a></li>';
	}
	$toc = '<nav class="aios-article__toc" aria-label="' . esc_attr__( 'Table of contents', 'aios-publisher' ) . '">'
		. '<div class="aios-article__toc-title">' . esc_html__( 'On this page', 'aios-publisher' ) . '</div>'
		. '<ol>' . $lis . '</ol></nav>';

	return array( $content, $toc );
}

/**
 * Render the "Key takeaways" callout from a list of plain-text points.
 *
 * @param mixed $list Array of strings (or empty).
 * @return string
 */
function aios_publisher_render_takeaways( $list ) {
	if ( ! is_array( $list ) || empty( $list ) ) {
		return '';
	}
	$items = '';
	foreach ( $list as $point ) {
		$point = trim( (string) $point );
		if ( '' !== $point ) {
			$items .= '<li>' . esc_html( $point ) . '</li>';
		}
	}
	if ( '' === $items ) {
		return '';
	}
	return '<aside class="aios-article__takeaways" aria-label="' . esc_attr__( 'Key takeaways', 'aios-publisher' ) . '">'
		. '<div class="aios-article__takeaways-title">' . esc_html__( 'Key takeaways', 'aios-publisher' ) . '</div>'
		. '<ul>' . $items . '</ul></aside>';
}

/**
 * Render the FAQ as accessible details/summary rows.
 *
 * @param mixed $faq Array of { question, answer } (or empty).
 * @return string
 */
function aios_publisher_render_faq( $faq ) {
	if ( ! is_array( $faq ) || empty( $faq ) ) {
		return '';
	}
	$rows = '';
	foreach ( $faq as $qa ) {
		if ( ! is_array( $qa ) ) {
			continue;
		}
		$q = isset( $qa['question'] ) ? trim( (string) $qa['question'] ) : '';
		$a = isset( $qa['answer'] ) ? trim( (string) $qa['answer'] ) : '';
		if ( '' === $q || '' === $a ) {
			continue;
		}
		$rows .= '<details class="aios-article__faq-item"><summary>' . esc_html( $q ) . '</summary>'
			. '<div class="aios-article__faq-answer">' . wp_kses_post( wpautop( $a ) ) . '</div></details>';
	}
	if ( '' === $rows ) {
		return '';
	}
	return '<section class="aios-article__faq">'
		. '<h2 class="aios-article__faq-title">' . esc_html__( 'Frequently asked questions', 'aios-publisher' ) . '</h2>'
		. $rows . '</section>';
}

/**
 * Render the closing CTA banner from a { heading, text, button_label, button_url }.
 *
 * @param mixed $cta The CTA config (or empty).
 * @return string
 */
function aios_publisher_render_cta( $cta ) {
	if ( ! is_array( $cta ) ) {
		return '';
	}
	$heading = isset( $cta['heading'] ) ? trim( (string) $cta['heading'] ) : '';
	$text    = isset( $cta['text'] ) ? trim( (string) $cta['text'] ) : '';
	$label   = isset( $cta['button_label'] ) ? trim( (string) $cta['button_label'] ) : '';
	$url     = isset( $cta['button_url'] ) ? trim( (string) $cta['button_url'] ) : '';

	if ( '' === $heading && '' === $text ) {
		return '';
	}
	$out = '<aside class="aios-article__cta">';
	if ( '' !== $heading ) {
		$out .= '<div class="aios-article__cta-heading">' . esc_html( $heading ) . '</div>';
	}
	if ( '' !== $text ) {
		$out .= '<p class="aios-article__cta-text">' . esc_html( $text ) . '</p>';
	}
	if ( '' !== $label && '' !== $url ) {
		$out .= '<a class="aios-article__cta-btn" href="' . esc_url( $url ) . '">' . esc_html( $label ) . '</a>';
	}
	$out .= '</aside>';
	return $out;
}

/**
 * Sanitize + store the structured article components from a publish request.
 *
 * @param int             $post_id The created post id.
 * @param WP_REST_Request $request The REST request.
 * @return void
 */
function aios_publisher_store_article_components( $post_id, $request ) {
	// Key takeaways: array of plain-text strings.
	$takeaways = $request->get_param( 'key_takeaways' );
	if ( is_array( $takeaways ) ) {
		$clean = array();
		foreach ( $takeaways as $point ) {
			$point = sanitize_text_field( (string) $point );
			if ( '' !== $point ) {
				$clean[] = $point;
			}
		}
		if ( ! empty( $clean ) ) {
			update_post_meta( $post_id, AIOS_PUBLISHER_META_TAKEAWAYS, $clean );
		}
	}

	// FAQ: array of { question, answer }.
	$faq = $request->get_param( 'faq' );
	if ( is_array( $faq ) ) {
		$clean = array();
		foreach ( $faq as $qa ) {
			if ( ! is_array( $qa ) ) {
				continue;
			}
			$q = isset( $qa['question'] ) ? sanitize_text_field( (string) $qa['question'] ) : '';
			$a = isset( $qa['answer'] ) ? wp_kses_post( (string) $qa['answer'] ) : '';
			if ( '' !== $q && '' !== $a ) {
				$clean[] = array(
					'question' => $q,
					'answer'   => $a,
				);
			}
		}
		if ( ! empty( $clean ) ) {
			update_post_meta( $post_id, AIOS_PUBLISHER_META_FAQ, wp_slash( $clean ) );
		}
	}

	// CTA: a single { heading, text, button_label, button_url }.
	$cta = $request->get_param( 'cta' );
	if ( is_array( $cta ) ) {
		$clean = array(
			'heading'      => isset( $cta['heading'] ) ? sanitize_text_field( (string) $cta['heading'] ) : '',
			'text'         => isset( $cta['text'] ) ? sanitize_text_field( (string) $cta['text'] ) : '',
			'button_label' => isset( $cta['button_label'] ) ? sanitize_text_field( (string) $cta['button_label'] ) : '',
			'button_url'   => isset( $cta['button_url'] ) ? esc_url_raw( (string) $cta['button_url'] ) : '',
		);
		if ( '' !== $clean['heading'] || '' !== $clean['text'] ) {
			update_post_meta( $post_id, AIOS_PUBLISHER_META_CTA, $clean );
		}
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

/**
 * Emit FAQPage JSON-LD for a managed post that carries FAQ meta (in addition to the
 * Article/BlogPosting JSON-LD handled by aios_publisher_head_schema).
 *
 * @return void
 */
function aios_publisher_head_faq_schema() {
	$post_id = aios_publisher_current_managed_post();
	if ( ! $post_id ) {
		return;
	}
	$faq = get_post_meta( $post_id, AIOS_PUBLISHER_META_FAQ, true );
	if ( ! is_array( $faq ) || empty( $faq ) ) {
		return;
	}
	$entities = array();
	foreach ( $faq as $qa ) {
		if ( ! is_array( $qa ) ) {
			continue;
		}
		$q = isset( $qa['question'] ) ? trim( (string) $qa['question'] ) : '';
		$a = isset( $qa['answer'] ) ? trim( wp_strip_all_tags( (string) $qa['answer'] ) ) : '';
		if ( '' === $q || '' === $a ) {
			continue;
		}
		$entities[] = array(
			'@type'          => 'Question',
			'name'           => $q,
			'acceptedAnswer' => array(
				'@type' => 'Answer',
				'text'  => $a,
			),
		);
	}
	if ( empty( $entities ) ) {
		return;
	}
	$schema = array(
		'@context'   => 'https://schema.org',
		'@type'      => 'FAQPage',
		'mainEntity' => $entities,
	);
	echo "\n<script type=\"application/ld+json\">" .
		wp_json_encode( $schema ) .
		"</script>\n"; // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped -- wp_json_encode produces safe JSON for a ld+json block.
}

/* -------------------------------------------------------------------------- *
 * Admin — settings page + the "AIOS Content" managed-posts list
 * -------------------------------------------------------------------------- */

add_action( 'admin_menu', 'aios_publisher_admin_menu' );

/**
 * Register the top-level "AIOS Publisher" menu + the "AIOS Content" submenu.
 *
 * @return void
 */
function aios_publisher_admin_menu() {
	add_menu_page(
		__( 'AIOS Publisher', 'aios-publisher' ),
		__( 'AIOS Publisher', 'aios-publisher' ),
		'manage_options',
		'aios-publisher',
		'aios_publisher_render_settings',
		'dashicons-rss',
		81
	);
	add_submenu_page(
		'aios-publisher',
		__( 'Settings', 'aios-publisher' ),
		__( 'Settings', 'aios-publisher' ),
		'manage_options',
		'aios-publisher',
		'aios_publisher_render_settings'
	);
	add_submenu_page(
		'aios-publisher',
		__( 'AIOS Content', 'aios-publisher' ),
		__( 'AIOS Content', 'aios-publisher' ),
		'manage_options',
		'aios-publisher-content',
		'aios_publisher_render_content_list'
	);
}

/* --- admin-post handlers (nonce + capability protected) --- */

add_action( 'admin_post_aios_publisher_save', 'aios_publisher_handle_save' );
add_action( 'admin_post_aios_publisher_regenerate', 'aios_publisher_handle_regenerate' );
add_action( 'admin_post_aios_publisher_publish_post', 'aios_publisher_handle_publish_post' );

/**
 * Save the default settings (status / post_type / category / author).
 *
 * @return void
 */
function aios_publisher_handle_save() {
	if ( ! current_user_can( 'manage_options' ) ) {
		wp_die( esc_html__( 'You are not allowed to do this.', 'aios-publisher' ) );
	}
	check_admin_referer( 'aios_publisher_save' );

	$status    = isset( $_POST['aios_status'] ) ? sanitize_key( wp_unslash( $_POST['aios_status'] ) ) : 'draft';
	$post_type = isset( $_POST['aios_post_type'] ) ? sanitize_key( wp_unslash( $_POST['aios_post_type'] ) ) : 'post';
	$category  = isset( $_POST['aios_category'] ) ? absint( wp_unslash( $_POST['aios_category'] ) ) : 0;
	$author    = isset( $_POST['aios_author'] ) ? absint( wp_unslash( $_POST['aios_author'] ) ) : 0;

	if ( ! in_array( $status, array( 'draft', 'pending', 'publish' ), true ) ) {
		$status = 'draft';
	}
	if ( ! in_array( $post_type, array( 'post', 'page' ), true ) ) {
		$post_type = 'post';
	}

	update_option(
		AIOS_PUBLISHER_OPT_SETTINGS,
		array(
			'status'    => $status,
			'post_type' => $post_type,
			'category'  => $category,
			'author'    => $author,
		)
	);

	aios_publisher_redirect_back( 'aios-publisher', 'saved' );
}

/**
 * Regenerate the API key (invalidates the old one immediately).
 *
 * @return void
 */
function aios_publisher_handle_regenerate() {
	if ( ! current_user_can( 'manage_options' ) ) {
		wp_die( esc_html__( 'You are not allowed to do this.', 'aios-publisher' ) );
	}
	check_admin_referer( 'aios_publisher_regenerate' );

	update_option( AIOS_PUBLISHER_OPT_KEY, aios_publisher_generate_key(), false );

	aios_publisher_redirect_back( 'aios-publisher', 'regenerated' );
}

/**
 * Publish (go live) a single AIOS-managed post from the "AIOS Content" list.
 *
 * @return void
 */
function aios_publisher_handle_publish_post() {
	if ( ! current_user_can( 'publish_posts' ) ) {
		wp_die( esc_html__( 'You are not allowed to publish posts.', 'aios-publisher' ) );
	}
	$post_id = isset( $_GET['post'] ) ? absint( wp_unslash( $_GET['post'] ) ) : 0;
	check_admin_referer( 'aios_publisher_publish_' . $post_id );

	if ( $post_id > 0 && current_user_can( 'publish_post', $post_id ) ) {
		wp_update_post(
			array(
				'ID'          => $post_id,
				'post_status' => 'publish',
			)
		);
	}

	aios_publisher_redirect_back( 'aios-publisher-content', 'published' );
}

/**
 * Redirect back to a plugin admin page with a status flag, then exit.
 *
 * @param string $page   The admin page slug.
 * @param string $notice The notice flag.
 * @return void
 */
function aios_publisher_redirect_back( $page, $notice ) {
	wp_safe_redirect(
		add_query_arg(
			array(
				'page'         => $page,
				'aios_notice'  => $notice,
			),
			admin_url( 'admin.php' )
		)
	);
	exit;
}

/**
 * Render the settings page: the API key + endpoint (to copy into AIOS), a
 * regenerate button, and the default status / type / category / author controls.
 *
 * @return void
 */
function aios_publisher_render_settings() {
	if ( ! current_user_can( 'manage_options' ) ) {
		return;
	}
	$key       = aios_publisher_ensure_key();
	$endpoint  = aios_publisher_endpoint_url();
	$settings  = aios_publisher_settings();
	$notice    = isset( $_GET['aios_notice'] ) ? sanitize_key( wp_unslash( $_GET['aios_notice'] ) ) : ''; // phpcs:ignore WordPress.Security.NonceVerification.Recommended -- display-only flag.
	?>
	<div class="wrap">
		<h1><?php esc_html_e( 'AIOS Publisher', 'aios-publisher' ); ?></h1>

		<?php if ( 'saved' === $notice ) : ?>
			<div class="notice notice-success is-dismissible"><p><?php esc_html_e( 'Settings saved.', 'aios-publisher' ); ?></p></div>
		<?php elseif ( 'regenerated' === $notice ) : ?>
			<div class="notice notice-success is-dismissible"><p><?php esc_html_e( 'A new API key was generated. Update it in AIOS.', 'aios-publisher' ); ?></p></div>
		<?php endif; ?>

		<h2><?php esc_html_e( 'Connect AIOS to this site', 'aios-publisher' ); ?></h2>
		<p class="description">
			<?php esc_html_e( 'Copy the endpoint URL and API key into the AIOS platform (per-client WordPress settings). AIOS pushes approved content here as a draft that you publish from the "AIOS Content" screen.', 'aios-publisher' ); ?>
		</p>
		<table class="form-table" role="presentation">
			<tr>
				<th scope="row"><label for="aios-endpoint"><?php esc_html_e( 'Endpoint URL', 'aios-publisher' ); ?></label></th>
				<td>
					<input type="text" id="aios-endpoint" class="large-text code" readonly value="<?php echo esc_attr( $endpoint ); ?>" onclick="this.select();" />
				</td>
			</tr>
			<tr>
				<th scope="row"><label for="aios-key"><?php esc_html_e( 'API Key', 'aios-publisher' ); ?></label></th>
				<td>
					<input type="text" id="aios-key" class="large-text code" readonly value="<?php echo esc_attr( $key ); ?>" onclick="this.select();" />
					<p class="description"><?php esc_html_e( 'Send this in the JSON body field "api_key" (or the X-AIOS-Key header). Regenerating invalidates the old key immediately.', 'aios-publisher' ); ?></p>
					<form method="post" action="<?php echo esc_url( admin_url( 'admin-post.php' ) ); ?>" style="margin-top:8px;">
						<input type="hidden" name="action" value="aios_publisher_regenerate" />
						<?php wp_nonce_field( 'aios_publisher_regenerate' ); ?>
						<button type="submit" class="button" onclick="return confirm('<?php echo esc_js( __( 'Regenerate the API key? AIOS will need the new key to keep publishing.', 'aios-publisher' ) ); ?>');">
							<?php esc_html_e( 'Regenerate key', 'aios-publisher' ); ?>
						</button>
					</form>
				</td>
			</tr>
		</table>

		<hr />

		<h2><?php esc_html_e( 'Defaults for pushed content', 'aios-publisher' ); ?></h2>
		<form method="post" action="<?php echo esc_url( admin_url( 'admin-post.php' ) ); ?>">
			<input type="hidden" name="action" value="aios_publisher_save" />
			<?php wp_nonce_field( 'aios_publisher_save' ); ?>
			<table class="form-table" role="presentation">
				<tr>
					<th scope="row"><label for="aios_status"><?php esc_html_e( 'Default post status', 'aios-publisher' ); ?></label></th>
					<td>
						<select name="aios_status" id="aios_status">
							<?php
							$statuses = array(
								'draft'   => __( 'Draft (recommended — you publish)', 'aios-publisher' ),
								'pending' => __( 'Pending review', 'aios-publisher' ),
								'publish' => __( 'Publish immediately (live)', 'aios-publisher' ),
							);
							foreach ( $statuses as $value => $label ) {
								printf(
									'<option value="%1$s" %2$s>%3$s</option>',
									esc_attr( $value ),
									selected( $settings['status'], $value, false ),
									esc_html( $label )
								);
							}
							?>
						</select>
					</td>
				</tr>
				<tr>
					<th scope="row"><label for="aios_post_type"><?php esc_html_e( 'Default post type', 'aios-publisher' ); ?></label></th>
					<td>
						<select name="aios_post_type" id="aios_post_type">
							<option value="post" <?php selected( $settings['post_type'], 'post' ); ?>><?php esc_html_e( 'Post', 'aios-publisher' ); ?></option>
							<option value="page" <?php selected( $settings['post_type'], 'page' ); ?>><?php esc_html_e( 'Page', 'aios-publisher' ); ?></option>
						</select>
					</td>
				</tr>
				<tr>
					<th scope="row"><label for="aios_category"><?php esc_html_e( 'Default category', 'aios-publisher' ); ?></label></th>
					<td>
						<?php
						wp_dropdown_categories(
							array(
								'name'             => 'aios_category',
								'id'               => 'aios_category',
								'selected'         => absint( $settings['category'] ),
								'show_option_none' => __( '— None —', 'aios-publisher' ),
								'option_none_value' => 0,
								'hide_empty'       => 0,
							)
						);
						?>
					</td>
				</tr>
				<tr>
					<th scope="row"><label for="aios_author"><?php esc_html_e( 'Default author', 'aios-publisher' ); ?></label></th>
					<td>
						<?php
						wp_dropdown_users(
							array(
								'name'            => 'aios_author',
								'id'              => 'aios_author',
								'selected'        => absint( $settings['author'] ),
								'show_option_none' => __( '— Current / default —', 'aios-publisher' ),
								'option_none_value' => 0,
								'who'             => 'authors',
							)
						);
						?>
					</td>
				</tr>
			</table>
			<?php submit_button( __( 'Save settings', 'aios-publisher' ) ); ?>
		</form>
	</div>
	<?php
}

/**
 * Render the "AIOS Content" list — every AIOS-managed post with publish/edit/view
 * actions (this is the "publish it from WordPress itself" step of the flow).
 *
 * @return void
 */
function aios_publisher_render_content_list() {
	if ( ! current_user_can( 'edit_posts' ) ) {
		return;
	}
	$notice = isset( $_GET['aios_notice'] ) ? sanitize_key( wp_unslash( $_GET['aios_notice'] ) ) : ''; // phpcs:ignore WordPress.Security.NonceVerification.Recommended -- display-only flag.

	$query = new WP_Query(
		array(
			'post_type'      => array( 'post', 'page' ),
			'post_status'    => array( 'draft', 'pending', 'publish', 'private', 'future' ),
			'meta_key'       => AIOS_PUBLISHER_META_MANAGED, // phpcs:ignore WordPress.DB.SlowDBQuery.slow_db_query_meta_key -- bounded admin list.
			'meta_value'     => '1', // phpcs:ignore WordPress.DB.SlowDBQuery.slow_db_query_meta_value -- bounded admin list.
			'posts_per_page' => 50,
			'orderby'        => 'date',
			'order'          => 'DESC',
		)
	);
	?>
	<div class="wrap">
		<h1><?php esc_html_e( 'AIOS Content', 'aios-publisher' ); ?></h1>
		<p class="description"><?php esc_html_e( 'Content pushed from AIOS. Review a draft, then Publish it to take it live on this site.', 'aios-publisher' ); ?></p>

		<?php if ( 'published' === $notice ) : ?>
			<div class="notice notice-success is-dismissible"><p><?php esc_html_e( 'Post published.', 'aios-publisher' ); ?></p></div>
		<?php endif; ?>

		<table class="wp-list-table widefat fixed striped">
			<thead>
				<tr>
					<th scope="col"><?php esc_html_e( 'Title', 'aios-publisher' ); ?></th>
					<th scope="col"><?php esc_html_e( 'Status', 'aios-publisher' ); ?></th>
					<th scope="col"><?php esc_html_e( 'Pushed', 'aios-publisher' ); ?></th>
					<th scope="col"><?php esc_html_e( 'Actions', 'aios-publisher' ); ?></th>
				</tr>
			</thead>
			<tbody>
			<?php if ( $query->have_posts() ) : ?>
				<?php
				while ( $query->have_posts() ) :
					$query->the_post();
					$post_id     = get_the_ID();
					$status      = get_post_status( $post_id );
					$pushed_at   = (string) get_post_meta( $post_id, AIOS_PUBLISHER_META_PUSHED_AT, true );
					$publish_url = wp_nonce_url(
						add_query_arg(
							array(
								'action' => 'aios_publisher_publish_post',
								'post'   => $post_id,
							),
							admin_url( 'admin-post.php' )
						),
						'aios_publisher_publish_' . $post_id
					);
					?>
					<tr>
						<td><strong><?php echo esc_html( get_the_title() ); ?></strong></td>
						<td><?php echo esc_html( $status ); ?></td>
						<td><?php echo esc_html( $pushed_at ); ?></td>
						<td>
							<?php if ( 'publish' !== $status ) : ?>
								<a class="button button-primary" href="<?php echo esc_url( $publish_url ); ?>"><?php esc_html_e( 'Publish', 'aios-publisher' ); ?></a>
							<?php else : ?>
								<span class="dashicons dashicons-yes" style="color:#46b450;"></span>
							<?php endif; ?>
							<a class="button" href="<?php echo esc_url( get_edit_post_link( $post_id ) ); ?>"><?php esc_html_e( 'Edit', 'aios-publisher' ); ?></a>
							<a class="button" href="<?php echo esc_url( get_permalink( $post_id ) ); ?>" target="_blank" rel="noopener"><?php esc_html_e( 'View', 'aios-publisher' ); ?></a>
						</td>
					</tr>
					<?php
				endwhile;
				wp_reset_postdata();
				?>
			<?php else : ?>
				<tr><td colspan="4"><?php esc_html_e( 'No content has been pushed from AIOS yet.', 'aios-publisher' ); ?></td></tr>
			<?php endif; ?>
			</tbody>
		</table>
	</div>
	<?php
}
