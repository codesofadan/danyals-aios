<?php
/**
 * Static page — full-width.
 *
 * @package Spotino
 */

get_header();
?>

<main id="main" class="site-main article-top">
	<?php
	while ( have_posts() ) :
		the_post();
		?>
		<article <?php post_class(); ?>>

			<?php spotino_breadcrumbs(); ?>

			<header class="entry-header">
				<?php the_title( '<h1>', '</h1>' ); ?>
			</header>

			<?php if ( has_post_thumbnail() ) : ?>
				<figure class="entry-featured">
					<?php the_post_thumbnail( 'full' ); ?>
				</figure>
			<?php endif; ?>

			<div class="entry-content">
				<?php
				the_content();
				wp_link_pages( array(
					'before' => '<div class="page-links">' . esc_html__( 'Pages:', 'spotino' ),
					'after'  => '</div>',
				) );
				?>
			</div>

		</article>

		<?php
		if ( comments_open() || get_comments_number() ) :
			echo '<div class="entry-content" style="margin-top:40px">';
			comments_template();
			echo '</div>';
		endif;

	endwhile;
	?>
</main>

<?php
get_footer();
