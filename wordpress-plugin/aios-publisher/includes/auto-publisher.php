<?php
/**
 * AIOS Publisher — Auto Publisher (the AI-content publish endpoint: post creation, categories, SEO meta, featured image, article components)
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
 * Recursively sanitize a WordPress block tree's REAL HTML content (each block's
 * innerContent string chunks - what serialize_block() actually reconstructs the
 * markup from, NOT the derived innerHTML convenience field), leaving the block
 * comment delimiters + JSON attrs alone (serialize_blocks() regenerates those
 * itself from $block['attrs'], so they are never hand-strung back together here).
 *
 * @param array<int,array<string,mixed>> $blocks A parse_blocks() tree.
 * @return array<int,array<string,mixed>> The same tree, HTML content sanitized in place.
 */
function aios_publisher_sanitize_blocks( $blocks ) {
	foreach ( $blocks as &$block ) {
		if ( ! empty( $block['innerBlocks'] ) ) {
			$block['innerBlocks'] = aios_publisher_sanitize_blocks( $block['innerBlocks'] );
		}
		if ( ! empty( $block['innerContent'] ) && is_array( $block['innerContent'] ) ) {
			foreach ( $block['innerContent'] as &$chunk ) {
				// A null entry marks WHERE a nested inner block's own serialized markup
				// goes (handled by the innerBlocks recursion above) - never touch it here,
				// only the literal HTML string chunks belong to THIS block.
				if ( is_string( $chunk ) ) {
					$chunk = wp_kses_post( $chunk );
				}
			}
			unset( $chunk );
		}
	}
	unset( $block );
	return $blocks;
}

/**
 * Sanitize a pushed post body, treating it as DATA (never code) either way.
 *
 * A plain push (a long-form blog/FAQ article - no Gutenberg block markup) runs
 * through the ORIGINAL, unchanged path: a blanket wp_kses_post() over the whole
 * string. A DESIGNED-page push (app.services.gutenberg's native
 * `<!-- wp:kind {...} -->` block markup) CANNOT take that path: wp_kses_post()
 * treats a block comment's JSON attrs as unrecognized "HTML" and strips every `{`
 * `}` `:` `"` out of it, corrupting the attrs and breaking the block editor's parse
 * (WordPress's own kses.php special-cases HTML comments just enough to keep the
 * `<!--`/`-->` delimiters, but still re-filters everything between them as if it
 * were markup). So a block push is parsed into WordPress's OWN block tree
 * (`parse_blocks()` - the exact parser the block editor itself uses), only the
 * REAL HTML content of each block is sanitized (still `wp_kses_post()`, same
 * security posture as before), and `serialize_blocks()` - again, the block
 * editor's own function - rebuilds the comment delimiters + attrs JSON correctly.
 *
 * @param string $raw_content The pushed `content` field, as sent.
 * @return string Sanitized HTML (or block markup), ready for `post_content`.
 */
function aios_publisher_sanitize_content( $raw_content ) {
	// Strip <style>/<script> blocks INCLUDING their contents FIRST, either path:
	// wp_kses_post() removes those tags but KEEPS their inner text, which would dump raw
	// CSS/JS onto the page. Styling is owned by the active theme + this plugin's ENQUEUED
	// article.css (which targets the .aios-page / .aios-layout-* class hooks), never inline.
	$stripped = preg_replace( '#<(style|script)\b[^>]*>.*?</\1>#is', '', $raw_content );
	if ( null !== $stripped ) {
		$raw_content = $stripped;
	}

	if ( false !== strpos( $raw_content, '<!-- wp:' ) ) {
		$blocks = aios_publisher_sanitize_blocks( parse_blocks( $raw_content ) );
		return serialize_blocks( $blocks );
	}

	return wp_kses( $raw_content, aios_publisher_allowed_html() );
}

/**
 * The tags a pushed page may use: everything `wp_kses_post()` allows, plus INLINE SVG.
 *
 * WHY SVG HAD TO BE ADDED. A designed page draws its card icons, its checklist ticks and
 * its FAQ chevrons as inline `<svg>`, and `wp_kses_post()` does not allow SVG at all - it
 * is not in WordPress's `$allowedposttags` and never has been. So every icon was silently
 * deleted on the way into the database: the icon tiles published as empty grey squares,
 * the hero bullets lost their ticks, and the accordion lost its chevron. MEASURED on a
 * real push: six SVGs in, zero out. Nothing reported it, because stripping is what kses is
 * for - it had simply been pointed at markup nobody had told it about.
 *
 * THE ALLOW-LIST IS DELIBERATELY SMALL, and what is left out is the point:
 *
 *  - no `<script>`, `<foreignObject>`, `<use>` or `<image>` - those are the elements that
 *    make SVG an execution and inclusion vector rather than a drawing;
 *  - no `href`/`xlink:href` on any of them, so nothing can reference an external document;
 *  - no `on*` handlers - kses strips unlisted attributes, and none are listed.
 *
 * What remains is geometry and stroke: shapes, a path, and the attributes that colour
 * them. The content is also already stripped of `<style>`/`<script>` blocks before this
 * runs, and only reaches here behind the shared-key check.
 *
 * @return array<string,array<string,bool>> A kses allow-list.
 */
function aios_publisher_allowed_html() {
	$allowed = wp_kses_allowed_html( 'post' );

	$shape = array(
		'fill'             => true,
		'stroke'           => true,
		'stroke-width'     => true,
		'stroke-linecap'   => true,
		'stroke-linejoin'  => true,
		'stroke-dasharray' => true,
		'opacity'          => true,
		'class'            => true,
		'transform'        => true,
	);

	$allowed['svg'] = array_merge(
		$shape,
		array(
			'xmlns'       => true,
			'viewbox'     => true,
			'viewBox'     => true,
			'width'       => true,
			'height'      => true,
			'aria-hidden' => true,
			'role'        => true,
			'focusable'   => true,
		)
	);
	$allowed['g']        = $shape;
	$allowed['title']    = array( 'class' => true );
	$allowed['path']     = array_merge( $shape, array( 'd' => true ) );
	$allowed['circle']   = array_merge( $shape, array( 'cx' => true, 'cy' => true, 'r' => true ) );
	$allowed['ellipse']  = array_merge( $shape, array( 'cx' => true, 'cy' => true, 'rx' => true, 'ry' => true ) );
	$allowed['line']     = array_merge( $shape, array( 'x1' => true, 'y1' => true, 'x2' => true, 'y2' => true ) );
	$allowed['polyline'] = array_merge( $shape, array( 'points' => true ) );
	$allowed['polygon']  = array_merge( $shape, array( 'points' => true ) );
	$allowed['rect']     = array_merge(
		$shape,
		array( 'x' => true, 'y' => true, 'width' => true, 'height' => true, 'rx' => true, 'ry' => true )
	);

	/**
	 * Filter the tags an AIOS push may use.
	 *
	 * @param array<string,array<string,bool>> $allowed The kses allow-list.
	 */
	return apply_filters( 'aios_publisher_allowed_html', $allowed );
}

/**
 * Create a post from an AIOS push. Treats the payload as DATA (never code): every
 * field is sanitized, the body is run through wp_kses_post (or, for a Gutenberg
 * block push, sanitized block-by-block - see aios_publisher_sanitize_content()),
 * the image URL through esc_url_raw. The post is created at the configured default
 * status (DRAFT), so a human still presses Publish on the WordPress side.
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

	$content = aios_publisher_sanitize_content( (string) $request->get_param( 'content' ) );

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
	// Tags (the post_tag taxonomy the active theme displays/links) - the same keyword
	// research the content job already ran. wp_insert_post() creates any tag that
	// doesn't exist yet. Only 'post' has post_tag registered by default - 'page'
	// silently ignores tags_input, so this is safe to pass either way.
	$tags = $request->get_param( 'tags' );
	if ( is_array( $tags ) ) {
		$clean_tags = array();
		foreach ( $tags as $tag ) {
			$tag = sanitize_text_field( (string) $tag );
			if ( '' !== $tag ) {
				$clean_tags[] = $tag;
			}
		}
		if ( ! empty( $clean_tags ) ) {
			$postarr['tags_input'] = $clean_tags;
		}
	}

	// UPDATE THE POST THIS PAGE ALREADY IS, when the platform names one.
	//
	// Every push used to create a new post, so re-pushing a page after a fix left the
	// previous attempt behind as an orphan draft - two pushes of two pages put four
	// drafts on the site, and the operator has to work out which is current. Naming the
	// post makes a re-push what it reads as: the same page, corrected.
	//
	// GUARDED THREE WAYS, because this is the one parameter that can overwrite existing
	// content rather than add some: the id must resolve to a real post, that post must
	// carry OUR managed marker (so a caller can never target a page a human wrote), and
	// it must not be in the trash (restoring something an editor deleted is not an
	// update). Anything else falls through to creating a new post, which is safe.
	$requested = absint( $request->get_param( 'post_id' ) );
	$target    = 0;
	if ( $requested > 0 ) {
		$existing = get_post( $requested );
		if (
			$existing instanceof WP_Post
			&& 'trash' !== $existing->post_status
			&& get_post_meta( $requested, AIOS_PUBLISHER_META_MANAGED, true )
		) {
			$target = $requested;
		}
	}

	if ( $target > 0 ) {
		$postarr['ID'] = $target;
		// The status a human already chose on the site wins. A page an editor published
		// must not silently drop back to draft because the platform pushed a correction.
		$postarr['post_status'] = get_post_status( $target );
		$post_id = wp_update_post( wp_slash( $postarr ), true );
	} else {
		$post_id = wp_insert_post( wp_slash( $postarr ), true );
	}
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

	// --- SEO meta for BOTH Yoast and Rank Math (works with whichever is active),
	// plus the Open Graph / Twitter Card values. ONE implementation, shared with the
	// whole-site route — see aios_publisher_apply_seo_meta(). ---
	aios_publisher_apply_seo_meta(
		$post_id,
		array(
			'meta_title'       => (string) $request->get_param( 'meta_title' ),
			'meta_description' => (string) $request->get_param( 'meta_description' ),
			'focus_keyword'    => (string) $request->get_param( 'focus_keyword' ),
			'og_title'         => (string) $request->get_param( 'og_title' ),
			'og_description'   => (string) $request->get_param( 'og_description' ),
			'og_image_url'     => (string) $request->get_param( 'og_image_url' ),
			'twitter_card'     => (string) $request->get_param( 'twitter_card' ),
		)
	);

	// --- JSON-LD schema: store raw and emit it in wp_head for this post ---
	aios_publisher_apply_schema_jsonld( $post_id, (string) $request->get_param( 'schema_jsonld' ) );

	// --- Article template components (key takeaways / FAQ / CTA) ---
	// Stored as structured post meta and rendered by the theme-adaptive article
	// template (aios_publisher_render_article) + emitted as FAQPage JSON-LD. All are
	// optional: an absent field simply skips that component.
	aios_publisher_store_article_components( $post_id, $request );

	// --- Design CSS: store the analyzed-site / template styling so it can be enqueued in
	// <head> on the front end (see aios_publisher_enqueue_article_assets). Sanitized as CSS
	// (no markup) before storage; absent -> the theme + article.css style the page. ---
	aios_publisher_store_design_css( $post_id, $request );
	// Whether the pushed body is a COMPLETE design page or a long-form article the plugin
	// should decorate. See aios_publisher_is_self_contained() for what turns on it.
	if ( $request->get_param( 'self_contained' ) ) {
		update_post_meta( $post_id, AIOS_PUBLISHER_META_SELF_CONTAINED, 1 );
	} else {
		delete_post_meta( $post_id, AIOS_PUBLISHER_META_SELF_CONTAINED );
	}

	// --- Full-width flag: a landing page renders across the full page width (article.css
	// adds .aios-article--full); a long-form article keeps the narrow reading measure. ---
	aios_publisher_apply_full_width( $post_id, (bool) $request->get_param( 'full_width' ) );

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

	// --- In-body image sideload: import every <img> the body references into THIS
	// site's media library and rewrite the body to point at the local copies, so the
	// published page is never left depending on the AIOS server hosting the source
	// images. Best-effort per image; a failed sideload just leaves that ONE <img>
	// pointing at its original URL rather than failing the whole push. ---
	$localized_content = aios_publisher_sideload_body_images( $post_id, $content );
	if ( $localized_content !== $content ) {
		wp_update_post(
			wp_slash(
				array(
					'ID'           => $post_id,
					'post_content' => $localized_content,
				)
			)
		);
	}

	// --- Tag the post as AIOS-managed so the "AIOS Content" list can find it ---
	aios_publisher_mark_managed( $post_id );

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
/* -------------------------------------------------------------------------- *
 * SHARED per-page writes.
 *
 * WHY THESE EXIST AS FUNCTIONS TAKING AN ARRAY. Until 1.14.0 the SEO meta, the
 * JSON-LD and the full-width flag were written INLINE inside
 * aios_publisher_rest_publish(), reading straight off the WP_REST_Request. The
 * whole-site route (`/site`, 1.9.0) therefore had no way to write any of them: it
 * receives a LIST of pages, not one request per page. The measurable consequence
 * was that a page delivered as part of a site arrived with no SEO title, no meta
 * description, no focus keyword and no schema, while the identical page pushed
 * one-at-a-time through `/publish` got all four.
 *
 * So the writes take a plain array and both routes call them. A field that is
 * absent or empty is NOT WRITTEN — never blanked — because both routes can
 * legitimately deliver a page without knowing its meta (a structural nav rebuild
 * knows slugs and hierarchy and nothing else), and overwriting a good SEO title
 * with '' would be worse than leaving it.
 * -------------------------------------------------------------------------- */

/**
 * Write the SEO + social meta for BOTH Yoast and Rank Math.
 *
 * WRITING BOTH VOCABULARIES IS DELIBERATE and predates this refactor: the platform
 * cannot know which SEO plugin a given client runs, both ignore the other's keys,
 * and a wrong guess means the page ships with no SEO title at all.
 *
 * OPEN GRAPH / TWITTER (new in 1.14.0). Both plugins DERIVE a social card from the
 * SEO title + description when no explicit value is set, which is why this was not
 * visibly broken — but the derivation runs through each plugin's own title TEMPLATE
 * ("%%title%% %%sep%% %%sitename%%"), so the card was neither controllable nor
 * predictable, and AIOS's own audit engine (TECH-086 / TECH-087) flags pages for
 * incomplete Open Graph — including pages this plugin had just created. Writing the
 * values explicitly makes the card deterministic. `og:url` and `og:type` are NOT
 * written: both plugins always emit those two themselves, correctly, and a
 * hand-written og:url on a replica would point at the source site.
 *
 * FALLING BACK TO THE SEO FIELDS is intentional rather than lazy: a caller that
 * supplies only meta_title/meta_description gets a social card that matches its
 * search snippet, which is what it meant.
 *
 * @param int                  $post_id Target post.
 * @param array<string,mixed>  $fields  meta_title, meta_description, focus_keyword,
 *                                      og_title, og_description, og_image_url,
 *                                      twitter_card. Any may be absent/empty.
 * @return void
 */
function aios_publisher_apply_seo_meta( $post_id, $fields ) {
	$get = function ( $key ) use ( $fields ) {
		return isset( $fields[ $key ] ) ? (string) $fields[ $key ] : '';
	};

	$meta_title = sanitize_text_field( $get( 'meta_title' ) );
	$meta_desc  = sanitize_textarea_field( $get( 'meta_description' ) );
	$focus_kw   = sanitize_text_field( $get( 'focus_keyword' ) );

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

	// --- Open Graph + Twitter, falling back to the search snippet. ---
	$og_title = sanitize_text_field( $get( 'og_title' ) );
	if ( '' === $og_title ) {
		$og_title = $meta_title;
	}
	$og_desc = sanitize_textarea_field( $get( 'og_description' ) );
	if ( '' === $og_desc ) {
		$og_desc = $meta_desc;
	}
	$og_image = esc_url_raw( $get( 'og_image_url' ) );

	if ( '' !== $og_title ) {
		update_post_meta( $post_id, '_yoast_wpseo_opengraph-title', $og_title );
		update_post_meta( $post_id, '_yoast_wpseo_twitter-title', $og_title );
		update_post_meta( $post_id, 'rank_math_facebook_title', $og_title );
		update_post_meta( $post_id, 'rank_math_twitter_title', $og_title );
	}
	if ( '' !== $og_desc ) {
		update_post_meta( $post_id, '_yoast_wpseo_opengraph-description', $og_desc );
		update_post_meta( $post_id, '_yoast_wpseo_twitter-description', $og_desc );
		update_post_meta( $post_id, 'rank_math_facebook_description', $og_desc );
		update_post_meta( $post_id, 'rank_math_twitter_description', $og_desc );
	}
	if ( '' !== $og_image ) {
		update_post_meta( $post_id, '_yoast_wpseo_opengraph-image', $og_image );
		update_post_meta( $post_id, '_yoast_wpseo_twitter-image', $og_image );
		update_post_meta( $post_id, 'rank_math_facebook_image', $og_image );
		update_post_meta( $post_id, 'rank_math_twitter_image', $og_image );
	}
	if ( '' !== $og_title || '' !== $og_desc || '' !== $og_image ) {
		// Rank Math MIRRORS the Facebook values onto Twitter unless this is 'off', in
		// which case the rank_math_twitter_* keys written above are what it uses. Set
		// it only when we actually wrote something, so a page nobody gave social
		// values to keeps whatever the site had configured.
		update_post_meta( $post_id, 'rank_math_twitter_use_facebook', 'off' );
	}

	// The card TYPE: only the two values X documents, and only when named. An image
	// implies the large card, which is what a page with a hero image wants.
	$card = sanitize_text_field( $get( 'twitter_card' ) );
	if ( ! in_array( $card, array( 'summary', 'summary_large_image' ), true ) ) {
		$card = ( '' !== $og_image ) ? 'summary_large_image' : '';
	}
	if ( '' !== $card ) {
		update_post_meta( $post_id, 'rank_math_twitter_card_type', $card );
	}
}

/**
 * Store a JSON-LD block for wp_head emission, when it is valid JSON.
 *
 * @param int    $post_id Target post.
 * @param string $schema  The raw JSON-LD string ('' skips).
 * @return bool Whether a block was stored.
 */
function aios_publisher_apply_schema_jsonld( $post_id, $schema ) {
	$schema = (string) $schema;
	if ( '' === trim( $schema ) || ! aios_publisher_is_valid_json( $schema ) ) {
		return false;
	}
	// wp_slash so the JSON survives the DB write; wp_kses is NOT used (this is a
	// JSON string echoed inside a <script type="application/ld+json"> block, not
	// HTML) — it is re-validated + emitted safely in aios_publisher_head_schema.
	update_post_meta( $post_id, AIOS_PUBLISHER_META_SCHEMA, wp_slash( $schema ) );
	return true;
}

/**
 * Set (or clear) the full-width landing-page flag.
 *
 * Unlike every other field here this one is CLEARED when false, because it is a
 * boolean the caller always knows: a page re-delivered as a narrow article must stop
 * rendering full-width, and leaving a stale flag would keep the old layout.
 *
 * @param int  $post_id    Target post.
 * @param bool $full_width Whether this page renders full width.
 * @return void
 */
function aios_publisher_apply_full_width( $post_id, $full_width ) {
	if ( $full_width ) {
		update_post_meta( $post_id, AIOS_PUBLISHER_META_FULL_WIDTH, 1 );
	} else {
		delete_post_meta( $post_id, AIOS_PUBLISHER_META_FULL_WIDTH );
	}
}

/**
 * Mark a post as AIOS-managed and stamp when it was pushed.
 *
 * @param int $post_id Target post.
 * @return void
 */
function aios_publisher_mark_managed( $post_id ) {
	update_post_meta( $post_id, AIOS_PUBLISHER_META_MANAGED, 1 );
	update_post_meta( $post_id, AIOS_PUBLISHER_META_PUSHED_AT, current_time( 'mysql' ) );
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
