<?php
/**
 * Footer.
 *
 * @package Spotino
 */
?>
<footer class="site-footer">
	<div class="wrap">
		<div class="footer-grid">
			<div class="footer-brand">
				<p class="site-title"><a href="<?php echo esc_url( home_url( '/' ) ); ?>"><?php bloginfo( 'name' ); ?></a></p>
				<p><?php echo esc_html( get_bloginfo( 'description' ) ); ?></p>
			</div>

			<div class="footer-menu">
				<h4><?php esc_html_e( 'Explore', 'spotino' ); ?></h4>
				<?php
				if ( has_nav_menu( 'footer' ) ) {
					wp_nav_menu( array( 'theme_location' => 'footer', 'container' => false, 'depth' => 1 ) );
				} else {
					spotino_fallback_menu();
				}
				?>
			</div>

			<div class="footer-widgets">
				<?php if ( is_active_sidebar( 'footer-1' ) ) : ?>
					<?php dynamic_sidebar( 'footer-1' ); ?>
				<?php else : ?>
					<h4><?php esc_html_e( 'Get in touch', 'spotino' ); ?></h4>
					<p><a href="<?php echo esc_url( home_url( '/' ) ); ?>"><?php echo esc_html( home_url() ); ?></a></p>
				<?php endif; ?>
			</div>
		</div>

		<div class="footer-bottom">
			<span>&copy; <?php echo esc_html( date_i18n( 'Y' ) ); ?> <?php bloginfo( 'name' ); ?>. <?php esc_html_e( 'All rights reserved.', 'spotino' ); ?></span>
			<span><?php esc_html_e( 'Built with the Spotino theme.', 'spotino' ); ?></span>
		</div>
	</div>
</footer>

<?php wp_footer(); ?>
</body>
</html>
