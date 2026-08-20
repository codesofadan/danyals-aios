<?php
/**
 * Single post — full-width editorial layout.
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
				<?php
				$cats = get_the_category();
				if ( ! empty( $cats ) ) :
					?>
					<a class="cat" href="<?php echo esc_url( get_category_link( $cats[0]->term_id ) ); ?>"><?php echo esc_html( $cats[0]->name ); ?></a>
				<?php endif; ?>

				<?php the_title( '<h1>', '</h1>' ); ?>

				<div class="entry-meta">
					<time datetime="<?php echo esc_attr( get_the_date( 'c' ) ); ?>"><?php echo esc_html( get_the_date() ); ?></time>
					<span>&middot;</span>
					<span><?php echo esc_html( spotino_reading_time() ); ?></span>
					<?php if ( get_the_author() ) : ?>
						<span>&middot;</span>
						<span><?php echo esc_html( get_the_author() ); ?></span>
					<?php endif; ?>
				</div>
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

			<footer class="entry-footer">
				<?php the_tags( '<div class="tag-links">', '', '</div>' ); ?>
			</footer>

			<?php
			spotino_author_box();
			?>

		</article>

		<?php
		if ( comments_open() || get_comments_number() ) :
			echo '<div class="entry-content" style="margin-top:40px">';
			comments_template();
			echo '</div>';
		endif;

		spotino_related_posts();

	endwhile;
	?>
</main>

<?php
get_footer();
