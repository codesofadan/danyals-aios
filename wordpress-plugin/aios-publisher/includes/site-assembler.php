<?php
/**
 * AIOS Publisher — Site Assembler (whole-site delivery: pages, hierarchy, menu, front page)
 *
 * WHAT THIS EXISTS FOR. Until 1.9.0 the plugin received ONE page per request and
 * nothing on either side created a navigation menu, set a front page, or nested a
 * page under a parent. A fifty-page build therefore arrived as fifty unlinked
 * drafts: each individually correct and individually Elementor-editable, with the
 * client left to assemble the actual website by hand.
 *
 * IT NEVER DELETES ANYTHING. There is no code path here that trashes, removes or
 * unpublishes a post. A page the client wrote is not ours to remove, and an
 * assembler that can delete is one that loses their work on a mistyped slug.
 *
 * IT IS IDEMPOTENT BY SLUG. Re-sending the same plan updates the same pages rather
 * than creating a second set. That is why the platform normalises slugs the way
 * WordPress does before sending: if our key and WordPress's disagree, every
 * republish silently duplicates the whole site.
 *
 * TWO PASSES, deliberately. Every page is created first, THEN parents are resolved -
 * a child can legitimately appear before its parent in the payload, and resolving
 * inline would set post_parent to 0 and silently flatten the site.
 *
 * @package AIOS_Publisher
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

/**
 * Register the /site route.
 *
 * @return void
 */
function aios_publisher_register_site_route() {
	register_rest_route(
		AIOS_PUBLISHER_REST_NAMESPACE,
		'/site',
		array(
			'methods'             => 'POST',
			'callback'            => 'aios_publisher_rest_site',
			'permission_callback' => 'aios_publisher_check_key',
		)
	);
}
add_action( 'rest_api_init', 'aios_publisher_register_site_route' );

/**
 * Read one field off a plan page entry as a string.
 *
 * @param array<string,mixed> $page One entry from the plan's `pages`.
 * @param string              $key  Field name.
 * @return string The value, or ''.
 */
function aios_publisher_page_field( $page, $key ) {
	return isset( $page[ $key ] ) ? (string) $page[ $key ] : '';
}

/**
 * Find the post a plan entry refers to, or null when it is new.
 *
 * THREE LOOKUPS, IN THIS ORDER, and the order is the fix for a real defect.
 *
 *  1. `post_id` — the platform records the WordPress post id when it publishes a
 *     page, so it can name the exact post. Nothing about a slug or a post type can
 *     be wrong about an id.
 *  2. the slug, in the post type the caller NAMED. A long-form article publishes as
 *     a `post`, not a `page`.
 *  3. the slug, in the OTHER type — because a page's type can legitimately have
 *     changed between deliveries, and finding it is better than duplicating it.
 *
 * Only lookup 2 existed, hardcoded to `page`. So re-delivering a blog article found
 * nothing, created an EMPTY `page` at the same slug (which WordPress renamed to
 * `…-2`), and pointed the menu link at the empty duplicate instead of the article.
 *
 * @param array<string,mixed> $page      One entry from the plan's `pages`.
 * @param string              $slug      The sanitized slug.
 * @param string              $post_type The requested post type ('page'|'post').
 * @return WP_Post|null
 */
function aios_publisher_resolve_plan_post( $page, $slug, $post_type ) {
	$post_id = isset( $page['post_id'] ) ? absint( $page['post_id'] ) : 0;
	if ( $post_id > 0 ) {
		$found = get_post( $post_id );
		// A named id that no longer exists (or points at a revision/attachment) falls
		// through to the slug lookups rather than failing the page.
		if ( $found instanceof WP_Post && in_array( $found->post_type, array( 'page', 'post' ), true ) ) {
			return $found;
		}
	}
	$found = get_page_by_path( $slug, OBJECT, $post_type );
	if ( $found instanceof WP_Post ) {
		return $found;
	}
	$other = ( 'page' === $post_type ) ? 'post' : 'page';
	$found = get_page_by_path( $slug, OBJECT, $other );
	return ( $found instanceof WP_Post ) ? $found : null;
}

/**
 * Create or update ONE page from the plan. Never deletes.
 *
 * THE BODY IS ONLY WRITTEN WHEN THE PLAN ACTUALLY CARRIES ONE. This used to set
 * `post_content` unconditionally from `$page['content'] ?? ''`, and the platform's
 * navigation rebuild — which knows slugs and hierarchy and nothing about page
 * bodies — sent no `content` key at all. The result was that rebuilding a client's
 * navbar EMPTIED the body of every page in the menu. An absent key now means "leave
 * the body alone"; an explicitly empty string still means "this page has no body",
 * because a caller must be able to say that too.
 *
 * `content_only_if_new` covers the third case: a SEED body, written when creating the
 * page and never over one that exists. The auto-created Services/Locations/Blog hub
 * uses it, so its placeholder line cannot overwrite the real landing copy an operator
 * wrote on it.
 *
 * SEO, schema, design CSS, the full-width flag and the featured image are applied
 * here through the SAME functions `/publish` uses, so a page delivered as part of a
 * site is no longer a second-class page with no meta.
 *
 * @param array<string,mixed> $page   One entry from the plan's `pages`.
 * @param string              $status Post status for newly created pages.
 * @return array<string,mixed>|null Result row, or null when the entry is unusable.
 */
function aios_publisher_upsert_page( $page, $status ) {
	$slug = sanitize_title( aios_publisher_page_field( $page, 'slug' ) );
	if ( '' === $slug ) {
		return null;
	}
	$title = sanitize_text_field( aios_publisher_page_field( $page, 'title' ) );
	if ( '' === $title ) {
		$title = $slug;
	}
	$post_type = sanitize_key( aios_publisher_page_field( $page, 'post_type' ) );
	if ( ! in_array( $post_type, array( 'page', 'post' ), true ) ) {
		$post_type = 'page';
	}

	$existing = aios_publisher_resolve_plan_post( $page, $slug, $post_type );
	// An existing post keeps ITS type. Re-typing a live post would change its
	// permalink and orphan every link to it, which is not a navigation rebuild's
	// business.
	$effective_type = ( $existing instanceof WP_Post ) ? $existing->post_type : $post_type;

	$postarr = array(
		'post_type'  => $effective_type,
		'post_title' => $title,
		'post_name'  => $slug,
		'menu_order' => (int) ( isset( $page['menu_order'] ) ? $page['menu_order'] : 0 ),
	);

	// --- the body, written only when the plan carries one (see the docstring) ---
	$has_content  = array_key_exists( 'content', $page ) && null !== $page['content'];
	$seed_only    = ! empty( $page['content_only_if_new'] );
	$is_new       = ! ( $existing instanceof WP_Post );
	$write_body   = $has_content && ( $is_new || ! $seed_only );
	if ( $write_body ) {
		$postarr['post_content'] = aios_publisher_sanitize_content(
			aios_publisher_page_field( $page, 'content' )
		);
	}

	if ( $existing instanceof WP_Post ) {
		$postarr['ID'] = $existing->ID;
		// The status of a page that already exists is NOT changed. If the client has
		// published it, a re-run must not quietly pull it back to draft.
		$result  = wp_update_post( wp_slash( $postarr ), true );
		$created = false;
	} else {
		$postarr['post_status'] = in_array( $status, array( 'draft', 'pending', 'publish' ), true )
			? $status
			: 'draft';
		$result  = wp_insert_post( wp_slash( $postarr ), true );
		$created = true;
	}

	if ( is_wp_error( $result ) ) {
		return array(
			'slug'  => $slug,
			'ok'    => false,
			'error' => $result->get_error_message(),
		);
	}

	$post_id   = (int) $result;
	$elementor = aios_publisher_apply_elementor_tree(
		$post_id,
		aios_publisher_page_field( $page, 'elementor_data' ),
		'builder',
		aios_publisher_page_field( $page, 'template' )
	);

	$template = sanitize_text_field( aios_publisher_page_field( $page, 'template' ) );
	if ( '' !== $template && ! $elementor ) {
		// Only when Elementor did not already claim the template - otherwise this
		// would undo the full-width template Elementor needs to render its own layout.
		update_post_meta( $post_id, '_wp_page_template', $template );
	}

	// --- the same per-page writes `/publish` performs, via the same functions ---
	aios_publisher_apply_seo_meta(
		$post_id,
		array(
			'meta_title'       => aios_publisher_page_field( $page, 'meta_title' ),
			'meta_description' => aios_publisher_page_field( $page, 'meta_description' ),
			'focus_keyword'    => aios_publisher_page_field( $page, 'focus_keyword' ),
			'og_title'         => aios_publisher_page_field( $page, 'og_title' ),
			'og_description'   => aios_publisher_page_field( $page, 'og_description' ),
			'og_image_url'     => aios_publisher_page_field( $page, 'og_image_url' ),
			'twitter_card'     => aios_publisher_page_field( $page, 'twitter_card' ),
		)
	);
	$schema = aios_publisher_apply_schema_jsonld(
		$post_id,
		aios_publisher_page_field( $page, 'schema_jsonld' )
	);
	aios_publisher_apply_design_css( $post_id, aios_publisher_page_field( $page, 'design_css' ) );
	// Only when the plan states it either way. A structural delivery says nothing
	// about layout, and flipping a landing page back to the narrow article measure
	// because the key was absent would be a visible regression on a live site.
	if ( array_key_exists( 'full_width', $page ) ) {
		aios_publisher_apply_full_width( $post_id, (bool) $page['full_width'] );
	}
	$featured = esc_url_raw( aios_publisher_page_field( $page, 'featured_image_url' ) );
	if ( '' !== $featured && ! has_post_thumbnail( $post_id ) ) {
		// Never re-sideloaded: a second delivery of the same plan would otherwise
		// import a duplicate copy of the image on every run.
		aios_publisher_sideload_featured_image( $post_id, $featured );
	}
	aios_publisher_mark_managed( $post_id );

	return array(
		'slug'       => $slug,
		'ok'         => true,
		'id'         => $post_id,
		'post_type'  => $effective_type,
		'created'    => $created,
		'elementor'  => $elementor,
		'schema'     => $schema,
		'body_written' => $write_body,
		'url'        => get_permalink( $post_id ),
	);
}

/**
 * Second pass: set each page's parent now that every page exists.
 *
 * @param array<string,mixed>      $plan     The decoded plan.
 * @param array<string,int>        $ids      slug => post id.
 * @return int How many parents were set.
 */
function aios_publisher_apply_hierarchy( $plan, $ids, $types = array() ) {
	$set   = 0;
	$pages = isset( $plan['pages'] ) && is_array( $plan['pages'] ) ? $plan['pages'] : array();
	foreach ( $pages as $page ) {
		if ( ! is_array( $page ) ) {
			continue;
		}
		$slug   = sanitize_title( (string) ( isset( $page['slug'] ) ? $page['slug'] : '' ) );
		$parent = sanitize_title( (string) ( isset( $page['parent_slug'] ) ? $page['parent_slug'] : '' ) );
		if ( '' === $slug || '' === $parent ) {
			continue;
		}
		if ( ! isset( $ids[ $slug ], $ids[ $parent ] ) ) {
			continue;
		}
		if ( $ids[ $slug ] === $ids[ $parent ] ) {
			continue; // a page cannot parent itself
		}
		// ONLY a hierarchical type has a parent. `post` is not hierarchical, so
		// setting post_parent on a blog article writes a value WordPress ignores for
		// permalinks and hierarchy alike - the article's nesting comes from the MENU
		// pass below, which nests any object type. Skipping it keeps the reported
		// `parents` count honest rather than inflating it with writes that did nothing.
		$child_type = isset( $types[ $slug ] ) ? (string) $types[ $slug ] : 'page';
		if ( ! is_post_type_hierarchical( $child_type ) ) {
			continue;
		}
		wp_update_post(
			array(
				'ID'          => $ids[ $slug ],
				'post_parent' => $ids[ $parent ],
			)
		);
		++$set;
	}
	return $set;
}

/**
 * Build the navigation menu and, when asked, assign it to a theme location.
 *
 * THE CLIENT'S EXISTING NAVIGATION IS THEIRS. A location that already holds a menu is
 * left alone unless `replace_existing` is true. Without that rule, delivering a site
 * would silently unhook whatever menu the client had been using.
 *
 * @param array<string,mixed>  $plan  The decoded plan.
 * @param array<string,int>    $ids   slug => post id.
 * @param array<string,string> $types slug => post type ('page'|'post').
 * @return array<string,mixed> What happened, for the response.
 */
function aios_publisher_apply_menu( $plan, $ids, $types = array() ) {
	$menu     = isset( $plan['menu'] ) && is_array( $plan['menu'] ) ? $plan['menu'] : array();
	$name     = sanitize_text_field( (string) ( isset( $menu['name'] ) ? $menu['name'] : '' ) );
	$location = sanitize_key( (string) ( isset( $menu['location'] ) ? $menu['location'] : '' ) );
	$replace  = ! empty( $menu['replace_existing'] );

	if ( '' === $name ) {
		return array( 'built' => false, 'reason' => 'no menu name given' );
	}

	$existing = wp_get_nav_menu_object( $name );
	if ( $existing ) {
		$menu_id = (int) $existing->term_id;
	} else {
		$menu_id = wp_create_nav_menu( $name );
		if ( is_wp_error( $menu_id ) ) {
			return array( 'built' => false, 'reason' => $menu_id->get_error_message() );
		}
		$menu_id = (int) $menu_id;
	}

	// Items already in this menu, keyed by the object they point at, so a re-run
	// updates rather than appending the whole site a second time.
	//
	// BOTH object types, not just 'page'. A menu item pointing at a blog `post` was
	// invisible to this scan, so every rebuild appended a SECOND item for the same
	// article and the dropdown grew a duplicate link on each run.
	$seen  = array();
	$items = wp_get_nav_menu_items( $menu_id );
	if ( is_array( $items ) ) {
		foreach ( $items as $item ) {
			if ( 'post_type' === $item->type && in_array( $item->object, array( 'page', 'post' ), true ) ) {
				$seen[ (int) $item->object_id ] = (int) $item->ID;
			}
		}
	}

	$added = 0;
	$pages = isset( $plan['pages'] ) && is_array( $plan['pages'] ) ? $plan['pages'] : array();
	$pending = $pages;
	$passes  = 0;
	while ( ! empty( $pending ) && $passes <= count( $pages ) ) {
		$next = array();
		$progress = false;
		foreach ( $pending as $page ) {
		if ( ! is_array( $page ) ) {
			continue;
		}
		if ( isset( $page['in_menu'] ) && ! $page['in_menu'] ) {
			continue;
		}
		$slug = sanitize_title( (string) ( isset( $page['slug'] ) ? $page['slug'] : '' ) );
		if ( '' === $slug || ! isset( $ids[ $slug ] ) ) {
			continue;
		}
		$page_id = (int) $ids[ $slug ];

		$parent_item = 0;
		$parent_slug = sanitize_title( (string) ( isset( $page['parent_slug'] ) ? $page['parent_slug'] : '' ) );
		if ( '' !== $parent_slug && isset( $ids[ $parent_slug ] ) ) {
			// The parent page exists in this plan. Defer ONE pass if its menu item is
			// not created yet, so we can attach under it. A parent NOT in $ids (absent
			// or failed to create) is NOT deferred here — the child falls through to top
			// level rather than being dropped, and the post-loop safety net catches any
			// child whose parent is excluded from the menu entirely.
			if ( ! isset( $seen[ (int) $ids[ $parent_slug ] ] ) ) {
				$next[] = $page;
				continue;
			}
			$parent_item = (int) $seen[ (int) $ids[ $parent_slug ] ];
		}

		$item_id = wp_update_nav_menu_item(
			$menu_id,
			isset( $seen[ $page_id ] ) ? (int) $seen[ $page_id ] : 0,
			array(
				'menu-item-object-id' => $page_id,
				// The object's REAL type. Registering a blog `post` as a 'page' made
				// WordPress resolve the item against the wrong post table entry, so
				// the link could 404 or point at an unrelated page of the same id.
				'menu-item-object'    => isset( $types[ $slug ] ) ? (string) $types[ $slug ] : 'page',
				'menu-item-type'      => 'post_type',
				'menu-item-status'    => 'publish',
				'menu-item-parent-id' => $parent_item,
				'menu-item-position'  => (int) ( isset( $page['menu_order'] ) ? $page['menu_order'] : 0 ),
			)
		);
		if ( ! is_wp_error( $item_id ) ) {
			$seen[ $page_id ] = (int) $item_id;
			++$added;
			$progress = true;
		}
	}
		if ( ! $progress ) {
			break;
		}
		$pending = $next;
		++$passes;
	}

	// SAFETY NET: any in-menu page that never received a menu item (its parent was
	// excluded from the menu, failed to create, or formed a cycle) is added at TOP
	// LEVEL rather than silently dropped from the nav. Idempotent — a page already in
	// $seen is skipped.
	foreach ( $pages as $page ) {
		if ( ! is_array( $page ) ) {
			continue;
		}
		if ( isset( $page['in_menu'] ) && ! $page['in_menu'] ) {
			continue;
		}
		$slug = sanitize_title( (string) ( isset( $page['slug'] ) ? $page['slug'] : '' ) );
		if ( '' === $slug || ! isset( $ids[ $slug ] ) ) {
			continue;
		}
		$page_id = (int) $ids[ $slug ];
		if ( isset( $seen[ $page_id ] ) ) {
			continue;
		}
		$item_id = wp_update_nav_menu_item(
			$menu_id,
			0,
			array(
				'menu-item-object-id' => $page_id,
				'menu-item-object'    => isset( $types[ $slug ] ) ? (string) $types[ $slug ] : 'page',
				'menu-item-type'      => 'post_type',
				'menu-item-status'    => 'publish',
				'menu-item-parent-id' => 0,
				'menu-item-position'  => (int) ( isset( $page['menu_order'] ) ? $page['menu_order'] : 0 ),
			)
		);
		if ( ! is_wp_error( $item_id ) ) {
			$seen[ $page_id ] = (int) $item_id;
			++$added;
		}
	}

	$assigned = false;
	$held     = '';
	if ( '' !== $location ) {
		$locations = get_theme_mod( 'nav_menu_locations' );
		$locations = is_array( $locations ) ? $locations : array();
		$occupied  = ! empty( $locations[ $location ] ) && (int) $locations[ $location ] !== $menu_id;
		if ( $occupied && ! $replace ) {
			$held = 'location already holds another menu; not replacing it';
		} else {
			$locations[ $location ] = $menu_id;
			set_theme_mod( 'nav_menu_locations', $locations );
			$assigned = true;
		}
	}

	return array(
		'built'    => true,
		'menu_id'  => $menu_id,
		'items'    => $added,
		'assigned' => $assigned,
		'held'     => $held,
	);
}

/**
 * Set the site's front page, ONLY when the plan explicitly names one.
 *
 * This changes what every visitor to the site sees, so silence means no.
 *
 * @param array<string,mixed> $plan The decoded plan.
 * @param array<string,int>   $ids  slug => post id.
 * @return array<string,mixed>
 */
function aios_publisher_apply_front_page( $plan, $ids, $types = array() ) {
	$slug = sanitize_title( (string) ( isset( $plan['front_page_slug'] ) ? $plan['front_page_slug'] : '' ) );
	if ( '' === $slug ) {
		return array( 'changed' => false, 'reason' => 'not requested' );
	}
	if ( ! isset( $ids[ $slug ] ) ) {
		return array( 'changed' => false, 'reason' => 'named page is not in this plan' );
	}
	// `show_on_front = page` can only point at a PAGE. Pointing it at a blog post
	// leaves WordPress showing visitors nothing, so refuse it with a reason rather
	// than writing an option that breaks the home page.
	$front_type = isset( $types[ $slug ] ) ? (string) $types[ $slug ] : 'page';
	if ( 'page' !== $front_type ) {
		return array(
			'changed' => false,
			'reason'  => "named object is a {$front_type}, and only a page can be the front page",
		);
	}
	$page_id = (int) $ids[ $slug ];
	// A front page has to be publicly visible, so this is the one place a status is
	// forced - a draft front page shows visitors a 404.
	$post = get_post( $page_id );
	if ( $post instanceof WP_Post && 'publish' !== $post->post_status ) {
		wp_update_post(
			array(
				'ID'          => $page_id,
				'post_status' => 'publish',
			)
		);
	}
	update_option( 'show_on_front', 'page' );
	update_option( 'page_on_front', $page_id );
	return array( 'changed' => true, 'page_id' => $page_id );
}

/**
 * Assemble a whole site from one plan.
 *
 * @param WP_REST_Request $request The REST request.
 * @return WP_REST_Response|WP_Error
 */
function aios_publisher_rest_site( $request ) {
	$pages = $request->get_param( 'pages' );
	if ( ! is_array( $pages ) || empty( $pages ) ) {
		return new WP_Error(
			'aios_publisher_no_pages',
			__( 'The site plan contains no pages.', 'aios-publisher' ),
			array( 'status' => 400 )
		);
	}

	$settings = aios_publisher_settings();
	$status   = sanitize_key( (string) $request->get_param( 'status' ) );
	if ( ! in_array( $status, array( 'draft', 'pending', 'publish' ), true ) ) {
		$status = isset( $settings['status'] ) ? $settings['status'] : 'draft';
	}

	$plan = array(
		'pages'           => $pages,
		'menu'            => $request->get_param( 'menu' ),
		'front_page_slug' => $request->get_param( 'front_page_slug' ),
	);

	// --- pass 1: every page exists ------------------------------------------
	$results = array();
	$ids     = array();
	$types   = array();
	foreach ( $pages as $page ) {
		if ( ! is_array( $page ) ) {
			continue;
		}
		$row = aios_publisher_upsert_page( $page, $status );
		if ( null === $row ) {
			continue;
		}
		$results[] = $row;
		if ( ! empty( $row['ok'] ) && isset( $row['id'] ) ) {
			$ids[ $row['slug'] ] = (int) $row['id'];
			// The type each object RESOLVED to, not the type the plan asked for - an
			// existing post keeps its own. Passes 2 and 3 need it to nest and to link
			// correctly: `post` is not hierarchical, and a menu item has to name the
			// real object type.
			$types[ $row['slug'] ] = isset( $row['post_type'] ) ? (string) $row['post_type'] : 'page';
		}
	}

	// --- pass 2: parents, menu, front page ----------------------------------
	$parents    = aios_publisher_apply_hierarchy( $plan, $ids, $types );
	$menu       = aios_publisher_apply_menu( $plan, $ids, $types );
	$front_page = aios_publisher_apply_front_page( $plan, $ids, $types );

	return new WP_REST_Response(
		array(
			'ok'         => true,
			'pages'      => $results,
			'parents'    => $parents,
			'menu'       => $menu,
			'front_page' => $front_page,
		),
		200
	);
}
