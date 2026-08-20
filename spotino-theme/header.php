<?php
/**
 * Header.
 *
 * @package Spotino
 */
?><!DOCTYPE html>
<html <?php language_attributes(); ?>>
<head>
	<meta charset="<?php bloginfo( 'charset' ); ?>">
	<meta name="viewport" content="width=device-width, initial-scale=1">
	<?php wp_head(); ?>
</head>
<body <?php body_class(); ?>>
<?php wp_body_open(); ?>
<a class="skip-link" href="#main"><?php esc_html_e( 'Skip to content', 'spotino' ); ?></a>

<header class="site-header">
	<div class="wrap">
		<div class="site-branding">
			<?php if ( has_custom_logo() ) : ?>
				<?php the_custom_logo(); ?>
			<?php else : ?>
				<div>
					<p class="site-title">
						<a href="<?php echo esc_url( home_url( '/' ) ); ?>" rel="home"><?php bloginfo( 'name' ); ?></a>
					</p>
					<?php $desc = get_bloginfo( 'description', 'display' ); ?>
					<?php if ( $desc ) : ?>
						<p class="site-description"><?php echo esc_html( $desc ); ?></p>
					<?php endif; ?>
				</div>
			<?php endif; ?>
		</div>

		<button class="nav-toggle" aria-expanded="false" aria-controls="primary-menu" aria-label="<?php esc_attr_e( 'Toggle menu', 'spotino' ); ?>">
			&#9776;
		</button>

		<nav class="main-nav" id="primary-menu" aria-label="<?php esc_attr_e( 'Primary', 'spotino' ); ?>">
			<?php
			wp_nav_menu( array(
				'theme_location' => 'primary',
				'container'      => false,
				'fallback_cb'    => 'spotino_fallback_menu',
				'depth'          => 2,
			) );
			?>
		</nav>
	</div>
</header>
