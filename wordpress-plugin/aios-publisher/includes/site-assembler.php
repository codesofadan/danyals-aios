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
 * Write an Elementor widget tree onto a post.
 *
 * Same writes, same order and same guards as
 * `aios_publisher_store_elementor_data()` in design-reconstruction.php, which takes
 * a WP_REST_Request. That function is on the SHIPPED single-page publish path and is
 * left exactly as it is; this takes raw values for the site path instead.
 *
 * @param int    $post_id Target post.
 * @param string $data    The `_elementor_data` JSON (a top-level array of sections).
 * @return bool Whether a tree was written.
 */
function aios_publisher_apply_elementor_tree( $post_id, $data ) {
	$data = (string) $data;
	if ( '' === trim( $data ) || ! aios_publisher_is_valid_json( $data ) ) {
		return false;
	}
	$decoded = json_decode( $data, true );
	if ( ! is_array( $decoded ) || empty( $decoded ) ) {
		return false;
	}
	update_post_meta( $post_id, '_elementor_edit_mode', 'builder' );
	// wp_slash so the JSON survives the DB write exactly as Elementor stores it.
	update_post_meta( $post_id, '_elementor_data', wp_slash( $data ) );
	$version = defined( 'ELEMENTOR_VERSION' ) ? ELEMENTOR_VERSION : '3.0.0';
	update_post_meta( $post_id, '_elementor_version', $version );
	update_post_meta( $post_id, '_wp_page_template', 'elementor_header_footer' );
	return true;
}

/**
 * Create or update ONE page from the plan. Never deletes.
 *
 * @param array<string,mixed> $page   One entry from the plan's `pages`.
 * @param string              $status Post status for newly created pages.
 * @return array<string,mixed>|null Result row, or null when the entry is unusable.
 */
function aios_publisher_upsert_page( $page, $status ) {
	$slug = sanitize_title( (string) ( isset( $page['slug'] ) ? $page['slug'] : '' ) );
	if ( '' === $slug ) {
		return null;
	}
	$title = sanitize_text_field( (string) ( isset( $page['title'] ) ? $page['title'] : '' ) );
	if ( '' === $title ) {
		$title = $slug;
	}
	$content = aios_publisher_sanitize_content(
		(string) ( isset( $page['content'] ) ? $page['content'] : '' )
	);

	$existing = get_page_by_path( $slug, OBJECT, 'page' );
	$postarr  = array(
		'post_type'    => 'page',
		'post_title'   => $title,
		'post_name'    => $slug,
		'post_content' => $content,
		'menu_order'   => (int) ( isset( $page['menu_order'] ) ? $page['menu_order'] : 0 ),
	);

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
		isset( $page['elementor_data'] ) ? $page['elementor_data'] : ''
	);

	$template = sanitize_text_field( (string) ( isset( $page['template'] ) ? $page['template'] : '' ) );
	if ( '' !== $template && ! $elementor ) {
		// Only when Elementor did not already claim the template - otherwise this
		// would undo the full-width template Elementor needs to render its own layout.
		update_post_meta( $post_id, '_wp_page_template', $template );
	}

	return array(
		'slug'      => $slug,
		'ok'        => true,
		'id'        => $post_id,
		'created'   => $created,
		'elementor' => $elementor,
		'url'       => get_permalink( $post_id ),
	);
}

/**
 * Second pass: set each page's parent now that every page exists.
 *
 * @param array<string,mixed>      $plan     The decoded plan.
 * @param array<string,int>        $ids      slug => post id.
 * @return int How many parents were set.
 */
function aios_publisher_apply_hierarchy( $plan, $ids ) {
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
 * @param array<string,mixed> $plan The decoded plan.
 * @param array<string,int>   $ids  slug => post id.
 * @return array<string,mixed> What happened, for the response.
 */
function aios_publisher_apply_menu( $plan, $ids ) {
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

	// Items already in this menu, keyed by the page they point at, so a re-run
	// updates rather than appending the whole site a second time.
	$seen  = array();
	$items = wp_get_nav_menu_items( $menu_id );
	if ( is_array( $items ) ) {
		foreach ( $items as $item ) {
			if ( 'post_type' === $item->type && 'page' === $item->object ) {
				$seen[ (int) $item->object_id ] = (int) $item->ID;
			}
		}
	}

	$added = 0;
	$pages = isset( $plan['pages'] ) && is_array( $plan['pages'] ) ? $plan['pages'] : array();
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

		$parent_item = 0;
		$parent_slug = sanitize_title( (string) ( isset( $page['parent_slug'] ) ? $page['parent_slug'] : '' ) );
		if ( '' !== $parent_slug && isset( $ids[ $parent_slug ], $seen[ (int) $ids[ $parent_slug ] ] ) ) {
			$parent_item = (int) $seen[ (int) $ids[ $parent_slug ] ];
		}

		$item_id = wp_update_nav_menu_item(
			$menu_id,
			isset( $seen[ $page_id ] ) ? (int) $seen[ $page_id ] : 0,
			array(
				'menu-item-object-id' => $page_id,
				'menu-item-object'    => 'page',
				'menu-item-type'      => 'post_type',
				'menu-item-status'    => 'publish',
				'menu-item-parent-id' => $parent_item,
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
function aios_publisher_apply_front_page( $plan, $ids ) {
	$slug = sanitize_title( (string) ( isset( $plan['front_page_slug'] ) ? $plan['front_page_slug'] : '' ) );
	if ( '' === $slug ) {
		return array( 'changed' => false, 'reason' => 'not requested' );
	}
	if ( ! isset( $ids[ $slug ] ) ) {
		return array( 'changed' => false, 'reason' => 'named page is not in this plan' );
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
		}
	}

	// --- pass 2: parents, menu, front page ----------------------------------
	$parents    = aios_publisher_apply_hierarchy( $plan, $ids );
	$menu       = aios_publisher_apply_menu( $plan, $ids );
	$front_page = aios_publisher_apply_front_page( $plan, $ids );

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
