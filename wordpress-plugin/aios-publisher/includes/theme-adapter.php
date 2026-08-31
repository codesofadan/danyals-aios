<?php
/**
 * AIOS Publisher — Theme Adapter (front-end rendering: article template, TOC/takeaways/FAQ/CTA HTML, asset enqueue, JSON-LD schema output)
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
 * Is this post an Elementor-built page?
 *
 * WHY THIS EXISTS (a live defect, found 2026-08-25): `aios_publisher_render_article`
 * is hooked on `the_content` at priority 20 and Elementor renders at priority 9, so
 * EVERY Elementor page this plugin has ever pushed was being wrapped in
 * `.aios-article`, prefixed with a "By admin - date - N min read" byline, and given
 * an auto-TOC built by injecting ids into its H2s. A faithful design was corrupted on
 * arrival, on the client's live site, by us.
 *
 * The article template is for the FLAT-HTML publishing path. An Elementor page renders
 * its own layout and must be left exactly as Elementor emitted it.
 *
 * @param int $post_id Post to test.
 * @return bool
 */
function aios_publisher_is_elementor_page( $post_id ) {
	// The post meta ALONE is not enough, and trusting it broke every site without
	// Elementor. The AIOS push writes `_elementor_edit_mode = builder` on every page
	// it sends (the platform's Elementor flag defaults on and the payload always
	// carries a tree), so on a site where Elementor is not installed this returned
	// true, and the plugin then skipped BOTH article.css and the whole
	// aios_publisher_render_article() wrapper. The result: no `.aios-article`, no
	// `.aios-article--full` breakout, no TOC/takeaways/FAQ/CTA - WordPress rendered
	// the raw post_content in the theme's narrow column. That is a complete,
	// independent cause of "generated pages are not full width", with no width
	// setting involved at all.
	//
	// ELEMENTOR_VERSION is the same probe core-connector.php already trusts, and for
	// the reason stated there: it beats is_plugin_active(), which needs wp-admin
	// includes and reports an active-but-erroring plugin as available.
	if ( ! defined( 'ELEMENTOR_VERSION' ) ) {
		return false;
	}
	return 'builder' === get_post_meta( (int) $post_id, '_elementor_edit_mode', true );
}

/**
 * Enqueue the article stylesheet ONLY on a singular managed post.
 *
 * @return void
 */
function aios_publisher_enqueue_article_assets() {
	$post_id = aios_publisher_current_managed_post();
	if ( ! $post_id ) {
		return;
	}
	// An Elementor page renders its own layout, so article.css must not load over it -
	// but the design CSS still must. Registering a STANDALONE empty handle gives the
	// inline styles somewhere to hang without dragging in the article template's
	// stylesheet, which would fight Elementor's own rules.
	$elementor = aios_publisher_is_elementor_page( $post_id );
	$handle    = $elementor ? 'aios-publisher-design' : 'aios-publisher-article';
	if ( $elementor ) {
		wp_register_style( $handle, false, array(), AIOS_PUBLISHER_VERSION );
		wp_enqueue_style( $handle );
	} else {
		wp_enqueue_style(
			$handle,
			// AIOS_PUBLISHER_FILE (the MAIN plugin file, defined in the loader) - NOT
			// this include's own __FILE__ - so the URL resolves to <plugin root>/
			// templates/article.css, not <plugin root>/includes/templates/article.css.
			plugins_url( 'templates/article.css', AIOS_PUBLISHER_FILE ),
			array(),
			AIOS_PUBLISHER_VERSION
		);
	}
	// The analyzed-site / template design CSS (colours, fonts, layout, component styling),
	// attached as an INLINE stylesheet AFTER article.css so it wins on specificity/order.
	// This is the seam that makes a published page match the analyzed design on ANY theme
	// (a plain default theme, no Elementor): the CSS is emitted in <head>, never in the post
	// body where wp_kses_post would strip a <style> tag. Scoped to .aios-page by the sender.
	$design_css = (string) get_post_meta( $post_id, AIOS_PUBLISHER_META_DESIGN_CSS, true );
	$design_css = aios_publisher_sanitize_css( $design_css );
	if ( '' !== $design_css ) {
		wp_add_inline_style( $handle, $design_css );
	}
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
	// Elementor already rendered this page's own layout at priority 9. Wrapping it,
	// prefixing a byline and injecting a TOC into its headings corrupts the design.
	if ( aios_publisher_is_elementor_page( $post_id ) ) {
		return $content;
	}

	$read_time = aios_publisher_read_time( $content );
	list( $content, $toc ) = aios_publisher_build_toc( $content );

	$meta      = aios_publisher_article_meta_line( $post_id, $read_time );
	$takeaways = aios_publisher_render_takeaways( get_post_meta( $post_id, AIOS_PUBLISHER_META_TAKEAWAYS, true ) );
	$faq       = aios_publisher_render_faq( get_post_meta( $post_id, AIOS_PUBLISHER_META_FAQ, true ) );
	$cta       = aios_publisher_render_cta( get_post_meta( $post_id, AIOS_PUBLISHER_META_CTA, true ) );

	// A landing page renders full-width (breaks out of the theme's narrow content column);
	// a long-form article keeps the narrow reading measure.
	$classes = 'aios-article';
	if ( get_post_meta( $post_id, AIOS_PUBLISHER_META_FULL_WIDTH, true ) ) {
		$classes .= ' aios-article--full';
	}

	return '<div class="' . esc_attr( $classes ) . '">'
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
