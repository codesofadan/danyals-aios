<?php
/**
 * AIOS Publisher — Core Connector (auth, ping, activation, route registration, connection settings admin UI)
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

// AIOS_PUBLISHER_FILE (defined in the main plugin file) - NOT this include's own
// __FILE__ - is required here: register_activation_hook() must be given the MAIN
// plugin file's path to correctly associate the callback with this plugin.
register_activation_hook( AIOS_PUBLISHER_FILE, 'aios_publisher_activate' );

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
			// --- 1.8.0: what this site can actually do ------------------------
			// Added so the platform stops INFERRING the editor from a settings
			// flag and asks the site instead. Purely additive: every field above
			// is unchanged, so a caller written against 1.7.0 keeps working.
			'capabilities'   => aios_publisher_capabilities(),
		),
		200
	);
}

/**
 * The post meta keys AIOS may write, so the platform can find out which of them
 * this site will actually accept over the WP REST API.
 *
 * WHY THIS LIST IS NARROW: `get_registered_meta_keys()` returns every key every
 * plugin on the site has registered. Returning all of them would leak another
 * plugin's internals to us for no reason and bloat a response that is polled. We
 * only need to know about the keys WE write.
 *
 * @return array<int,string>
 */
function aios_publisher_known_meta_keys() {
	return array(
		'_elementor_data',
		'_elementor_edit_mode',
		'_elementor_version',
		'_wp_page_template',
		'_yoast_wpseo_title',
		'_yoast_wpseo_metadesc',
		'_yoast_wpseo_focuskw',
		'rank_math_title',
		'rank_math_description',
		'rank_math_focus_keyword',
	);
}

/**
 * Which of our known meta keys are registered with `show_in_rest` on this site.
 *
 * THE POINT OF THIS FIELD. WordPress SILENTLY DROPS a REST write to a meta key
 * that is not registered with `show_in_rest`: the response is 200 and carries the
 * OLD value, so a publish reports success and changes nothing. This plugin's own
 * endpoint is unaffected (it calls `update_post_meta()` directly in PHP, which
 * needs no registration) - but the platform also has a native WP-REST transport,
 * and on THAT path an unregistered key is a false success.
 *
 * So the platform can now write only proven-registered keys and report the rest as
 * HELD, instead of discovering the drop by reading the live page later.
 *
 * @param string $post_type Post type to inspect ('post' or 'page').
 * @return array<int,string> The registered subset, in a stable order.
 */
function aios_publisher_registered_meta_keys( $post_type ) {
	if ( ! function_exists( 'get_registered_meta_keys' ) ) {
		return array();
	}
	$registered = get_registered_meta_keys( 'post', $post_type );
	if ( ! is_array( $registered ) ) {
		return array();
	}
	$out = array();
	foreach ( aios_publisher_known_meta_keys() as $key ) {
		if ( ! isset( $registered[ $key ] ) || ! is_array( $registered[ $key ] ) ) {
			continue;
		}
		// `show_in_rest` may be `true` OR an args array; both mean exposed.
		if ( ! empty( $registered[ $key ]['show_in_rest'] ) ) {
			$out[] = $key;
		}
	}
	return $out;
}

/**
 * Describe what this WordPress install can do, for the platform's editor-mode
 * decision.
 *
 * NEVER FATALS. A capability probe that throws would break the connection check
 * itself, which is strictly worse than having no probe: the platform would read a
 * reachable site as unreachable and stop publishing to it. Every lookup below is
 * guarded, and anything unknown is reported as null/false rather than guessed.
 *
 * @return array<string,mixed>
 */
function aios_publisher_capabilities() {
	$theme_name = '';
	$stylesheet = '';
	$template   = '';
	if ( function_exists( 'wp_get_theme' ) ) {
		$theme = wp_get_theme();
		if ( $theme instanceof WP_Theme ) {
			$theme_name = sanitize_text_field( (string) $theme->get( 'Name' ) );
			$stylesheet = sanitize_key( (string) $theme->get_stylesheet() );
			$template   = sanitize_key( (string) $theme->get_template() );
		}
	}

	// Elementor sets ELEMENTOR_VERSION when it loads. Checking the constant is
	// more reliable than is_plugin_active(), which needs wp-admin includes and
	// reports a plugin that is active-but-erroring as available.
	$elementor         = defined( 'ELEMENTOR_VERSION' );
	$elementor_version = $elementor ? sanitize_text_field( (string) ELEMENTOR_VERSION ) : null;

	// Core block editor. `parse_blocks` is the function this plugin's own
	// sanitizer depends on, so probing for it answers the question that matters
	// here rather than a general "is WP 5.0+".
	$gutenberg = function_exists( 'parse_blocks' ) && function_exists( 'serialize_blocks' );

	return array(
		'wp_version'           => sanitize_text_field( (string) get_bloginfo( 'version' ) ),
		'active_theme'         => array(
			'name'       => $theme_name,
			'stylesheet' => $stylesheet,
			'template'   => $template,
		),
		'elementor'            => $elementor,
		'elementor_version'    => $elementor_version,
		'gutenberg'            => $gutenberg,
		'registered_meta_keys' => array(
			'post' => aios_publisher_registered_meta_keys( 'post' ),
			'page' => aios_publisher_registered_meta_keys( 'page' ),
		),
	);
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
