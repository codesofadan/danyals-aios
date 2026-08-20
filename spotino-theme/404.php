<?php
/**
 * 404 template.
 *
 * @package Spotino
 */

get_header();
?>

<main id="main" class="site-main article-top">
	<div class="content">
		<div class="entry-header">
			<span class="cat"><?php esc_html_e( 'Error 404', 'spotino' ); ?></span>
			<h1><?php esc_html_e( 'This page has wandered off', 'spotino' ); ?></h1>
			<div class="entry-meta"><?php esc_html_e( 'The page you were looking for could not be found.', 'spotino' ); ?></div>
		</div>
		<div class="entry-content" style="text-align:center">
			<p><a class="button" href="<?php echo esc_url( home_url( '/' ) ); ?>"><?php esc_html_e( 'Back to home', 'spotino' ); ?></a></p>
			<div style="margin-top:32px"><?php get_search_form(); ?></div>
		</div>
	</div>
</main>

<?php
get_footer();
