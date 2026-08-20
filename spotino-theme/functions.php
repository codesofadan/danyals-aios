<?php
/**
 * Spotino theme functions.
 *
 * @package Spotino
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

if ( ! defined( 'SPOTINO_VERSION' ) ) {
	define( 'SPOTINO_VERSION', '1.0.0' );
}

/**
 * Theme setup.
 */
function spotino_setup() {
	load_theme_textdomain( 'spotino', get_template_directory() . '/languages' );

	add_theme_support( 'automatic-feed-links' );
	add_theme_support( 'title-tag' );
	add_theme_support( 'post-thumbnails' );
	add_theme_support( 'custom-logo', array(
		'height'      => 60,
		'width'       => 240,
		'flex-height' => true,
		'flex-width'  => true,
	) );
	add_theme_support( 'html5', array(
		'search-form', 'comment-form', 'comment-list', 'gallery', 'caption', 'style', 'script',
	) );
	add_theme_support( 'responsive-embeds' );
	add_theme_support( 'align-wide' );
	add_theme_support( 'editor-styles' );
	add_editor_style( 'style.css' );

	register_nav_menus( array(
		'primary' => __( 'Primary Menu', 'spotino' ),
		'footer'  => __( 'Footer Menu', 'spotino' ),
	) );
}
add_action( 'after_setup_theme', 'spotino_setup' );

/**
 * Content width.
 */
function spotino_content_width() {
	$GLOBALS['content_width'] = 760;
}
add_action( 'after_setup_theme', 'spotino_content_width', 0 );

/**
 * Enqueue styles + scripts (Google Fonts: Space Grotesk headings, Inter body).
 */
function spotino_assets() {
	wp_enqueue_style(
		'spotino-fonts',
		'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Space+Grotesk:wght@500;600;700&display=swap',
		array(),
		null
	);
	wp_enqueue_style( 'spotino-style', get_stylesheet_uri(), array( 'spotino-fonts' ), SPOTINO_VERSION );
	wp_enqueue_script( 'spotino-nav', get_template_directory_uri() . '/assets/nav.js', array(), SPOTINO_VERSION, true );

	if ( is_singular() && comments_open() && get_option( 'thread_comments' ) ) {
		wp_enqueue_script( 'comment-reply' );
	}
}
add_action( 'wp_enqueue_scripts', 'spotino_assets' );

/**
 * Register the sidebar + footer widget areas.
 */
function spotino_widgets_init() {
	register_sidebar( array(
		'name'          => __( 'Sidebar', 'spotino' ),
		'id'            => 'sidebar-1',
		'description'   => __( 'Main sidebar widgets.', 'spotino' ),
		'before_widget' => '<section id="%1$s" class="widget %2$s">',
		'after_widget'  => '</section>',
		'before_title'  => '<h2 class="widget-title">',
		'after_title'   => '</h2>',
	) );
	register_sidebar( array(
		'name'          => __( 'Footer', 'spotino' ),
		'id'            => 'footer-1',
		'description'   => __( 'Footer widgets.', 'spotino' ),
		'before_widget' => '<section id="%1$s" class="widget %2$s">',
		'after_widget'  => '</section>',
		'before_title'  => '<h4 class="widget-title">',
		'after_title'   => '</h4>',
	) );
}
add_action( 'widgets_init', 'spotino_widgets_init' );

/**
 * Nicer excerpt length + "read more".
 */
function spotino_excerpt_length( $length ) {
	return 26;
}
add_filter( 'excerpt_length', 'spotino_excerpt_length' );

function spotino_excerpt_more( $more ) {
	return '&hellip;';
}
add_filter( 'excerpt_more', 'spotino_excerpt_more' );

/**
 * Body classes.
 */
function spotino_body_classes( $classes ) {
	if ( ! is_singular() ) {
		$classes[] = 'archive-view';
	}
	return $classes;
}
add_filter( 'body_class', 'spotino_body_classes' );

/**
 * Pretty permalinks out of the box.
 *
 * On activation, if the site is still on the default "plain" permalinks
 * (?p=123), switch it to the "post name" structure so posts AND pages get
 * clean, root-level URLs like spotino.org/best-ai-agents-for-seo-agencies-in-2026
 * — then flush the rewrite rules so they work immediately.
 */
function spotino_pretty_permalinks() {
	$structure = get_option( 'permalink_structure' );
	if ( empty( $structure ) ) {
		global $wp_rewrite;
		$wp_rewrite->set_permalink_structure( '/%postname%/' );
		update_option( 'permalink_structure', '/%postname%/' );
		$wp_rewrite->flush_rules( true );
	} else {
		flush_rewrite_rules( false );
	}
}
add_action( 'after_switch_theme', 'spotino_pretty_permalinks' );

/**
 * Fallback menu when no "primary" menu is assigned: a simple list of pages.
 */
function spotino_fallback_menu() {
	echo '<ul>';
	wp_list_pages( array( 'title_li' => '', 'depth' => 1 ) );
	echo '</ul>';
}

/**
 * Human-friendly reading time for a post.
 */
function spotino_reading_time( $post_id = null ) {
	$content = get_post_field( 'post_content', $post_id ? $post_id : get_the_ID() );
	$words   = str_word_count( wp_strip_all_tags( $content ) );
	$minutes = max( 1, (int) ceil( $words / 220 ) );
	/* translators: %d: reading time in minutes. */
	return sprintf( _n( '%d min read', '%d min read', $minutes, 'spotino' ), $minutes );
}

/* -------------------------------------------------------------------------- *
 * SEO plumbing
 * -------------------------------------------------------------------------- */

/**
 * Is a dedicated SEO plugin active? If so the theme steps ASIDE and lets it own
 * meta/OG (no double tags). Covers Yoast, Rank Math, All in One SEO, SEOPress.
 *
 * @return bool
 */
function spotino_has_seo_plugin() {
	return defined( 'WPSEO_VERSION' )
		|| class_exists( 'WPSEO_Options' )
		|| defined( 'RANK_MATH_VERSION' )
		|| defined( 'AIOSEO_VERSION' )
		|| defined( 'SEOPRESS_VERSION' );
}

/**
 * Output meta description + Open Graph + Twitter Card tags — ONLY when no SEO
 * plugin is active (so Yoast/Rank Math win when present). Uses the featured image
 * as the social image. Hooked early on wp_head.
 *
 * @return void
 */
function spotino_seo_meta() {
	if ( spotino_has_seo_plugin() ) {
		return;
	}
	$site = get_bloginfo( 'name' );

	if ( is_singular() ) {
		$post_id = get_queried_object_id();
		$title   = get_the_title( $post_id );
		$desc    = has_excerpt( $post_id )
			? get_the_excerpt( $post_id )
			: wp_trim_words( wp_strip_all_tags( (string) get_post_field( 'post_content', $post_id ) ), 30, '' );
		$desc = trim( (string) $desc );
		$url  = get_permalink( $post_id );
		$type = is_singular( 'post' ) ? 'article' : 'website';
		$img  = get_the_post_thumbnail_url( $post_id, 'full' );
	} else {
		$title = wp_get_document_title();
		$desc  = get_bloginfo( 'description' );
		$url   = home_url( '/' );
		$type  = 'website';
		$img   = '';
	}

	if ( '' !== $desc ) {
		echo '<meta name="description" content="' . esc_attr( $desc ) . '">' . "\n";
	}
	echo '<meta property="og:site_name" content="' . esc_attr( $site ) . '">' . "\n";
	echo '<meta property="og:type" content="' . esc_attr( $type ) . '">' . "\n";
	echo '<meta property="og:title" content="' . esc_attr( $title ) . '">' . "\n";
	if ( '' !== $desc ) {
		echo '<meta property="og:description" content="' . esc_attr( $desc ) . '">' . "\n";
	}
	echo '<meta property="og:url" content="' . esc_url( $url ) . '">' . "\n";
	if ( $img ) {
		echo '<meta property="og:image" content="' . esc_url( $img ) . '">' . "\n";
	}
	echo '<meta name="twitter:card" content="' . ( $img ? 'summary_large_image' : 'summary' ) . '">' . "\n";
	echo '<meta name="twitter:title" content="' . esc_attr( $title ) . '">' . "\n";
	if ( '' !== $desc ) {
		echo '<meta name="twitter:description" content="' . esc_attr( $desc ) . '">' . "\n";
	}
	if ( $img ) {
		echo '<meta name="twitter:image" content="' . esc_url( $img ) . '">' . "\n";
	}
}
add_action( 'wp_head', 'spotino_seo_meta', 5 );

/* -------------------------------------------------------------------------- *
 * Template sections: breadcrumbs, author box, related posts
 * -------------------------------------------------------------------------- */

/**
 * Render a simple breadcrumb trail (Home / Category / Title).
 *
 * @return void
 */
function spotino_breadcrumbs() {
	if ( is_front_page() ) {
		return;
	}
	echo '<nav class="breadcrumbs" aria-label="' . esc_attr__( 'Breadcrumb', 'spotino' ) . '">';
	echo '<a href="' . esc_url( home_url( '/' ) ) . '">' . esc_html__( 'Home', 'spotino' ) . '</a>';
	if ( is_singular( 'post' ) ) {
		$cats = get_the_category();
		if ( ! empty( $cats ) ) {
			echo '<span class="sep">/</span><a href="' . esc_url( get_category_link( $cats[0]->term_id ) ) . '">' . esc_html( $cats[0]->name ) . '</a>';
		}
		echo '<span class="sep">/</span><span>' . esc_html( get_the_title() ) . '</span>';
	} elseif ( is_page() ) {
		echo '<span class="sep">/</span><span>' . esc_html( get_the_title() ) . '</span>';
	} elseif ( is_archive() || is_search() ) {
		echo '<span class="sep">/</span><span>' . esc_html( wp_strip_all_tags( get_the_archive_title() ) ) . '</span>';
	}
	echo '</nav>';
}

/**
 * Render an author E-E-A-T box under a post (avatar + name + bio).
 *
 * @return void
 */
function spotino_author_box() {
	$author_id = (int) get_post_field( 'post_author', get_the_ID() );
	$name      = get_the_author_meta( 'display_name', $author_id );
	if ( '' === (string) $name ) {
		return;
	}
	$bio = get_the_author_meta( 'description', $author_id );
	echo '<aside class="author-box">';
	echo get_avatar( $author_id, 128 ); // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped -- get_avatar returns safe markup.
	echo '<div><p class="a-name">' . esc_html( $name ) . '</p>';
	if ( '' !== (string) $bio ) {
		echo '<p class="a-bio">' . esc_html( $bio ) . '</p>';
	} else {
		echo '<p class="a-bio">' . esc_html( sprintf( /* translators: %s: site name */ __( 'Writing for %s.', 'spotino' ), get_bloginfo( 'name' ) ) ) . '</p>';
	}
	echo '</div></aside>';
}

/**
 * Render up to three related posts (same category) under a single post.
 *
 * @return void
 */
function spotino_related_posts() {
	if ( ! is_singular( 'post' ) ) {
		return;
	}
	$cats = wp_get_post_categories( get_the_ID() );
	$args = array(
		'post_type'           => 'post',
		'posts_per_page'      => 3,
		'post__not_in'        => array( get_the_ID() ),
		'ignore_sticky_posts' => true,
		'orderby'             => 'date',
		'order'               => 'DESC',
	);
	if ( ! empty( $cats ) ) {
		$args['category__in'] = $cats;
	}
	$q = new WP_Query( $args );
	if ( ! $q->have_posts() ) {
		wp_reset_postdata();
		return;
	}
	echo '<section class="related-posts"><div class="wrap"><div class="section-head"><h2>' . esc_html__( 'Related articles', 'spotino' ) . '</h2></div><div class="post-grid">';
	while ( $q->have_posts() ) :
		$q->the_post();
		echo '<article class="post-card">';
		if ( has_post_thumbnail() ) {
			echo '<a class="thumb" href="' . esc_url( get_permalink() ) . '">' . get_the_post_thumbnail( get_the_ID(), 'large' ) . '</a>'; // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped -- core returns safe markup.
		}
		echo '<div class="card-body">';
		$rc = get_the_category();
		if ( ! empty( $rc ) ) {
			echo '<span class="cat">' . esc_html( $rc[0]->name ) . '</span>';
		}
		echo '<h3><a href="' . esc_url( get_permalink() ) . '">' . esc_html( get_the_title() ) . '</a></h3>';
		echo '<div class="meta"><time datetime="' . esc_attr( get_the_date( 'c' ) ) . '">' . esc_html( get_the_date() ) . '</time></div>';
		echo '</div></article>';
	endwhile;
	echo '</div></div></section>';
	wp_reset_postdata();
}
