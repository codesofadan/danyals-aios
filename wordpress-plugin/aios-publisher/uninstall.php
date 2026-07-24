<?php
/**
 * Uninstall handler for AIOS Publisher.
 *
 * Runs ONLY when the plugin is deleted from the WordPress admin. Removes the
 * plugin's own options (the API key + defaults). It deliberately LEAVES the posts
 * it created and their SEO/schema meta in place — deleting a plugin should never
 * destroy published content. The per-post `_aios_*` markers are harmless if left.
 *
 * @package AIOS_Publisher
 */

// Only ever run in the real uninstall context.
if ( ! defined( 'WP_UNINSTALL_PLUGIN' ) ) {
	exit;
}

delete_option( 'aios_publisher_api_key' );
delete_option( 'aios_publisher_options' );

// On a multisite network, clear the options on every site too.
if ( is_multisite() ) {
	$site_ids = get_sites( array( 'fields' => 'ids' ) );
	foreach ( $site_ids as $site_id ) {
		switch_to_blog( (int) $site_id );
		delete_option( 'aios_publisher_api_key' );
		delete_option( 'aios_publisher_options' );
		restore_current_blog();
	}
}
