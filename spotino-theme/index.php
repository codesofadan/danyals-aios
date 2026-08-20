<?php
/**
 * Main template — the blog / archive listing.
 *
 * @package Spotino
 */

get_header();
?>

<main id="main" class="site-main">
	<div class="wrap list-wrap">

		<?php if ( is_home() && ! is_front_page() ) : ?>
			<div class="section-head">
				<h1><?php single_post_title(); ?></h1>
			</div>
		<?php elseif ( is_archive() ) : ?>
			<div class="section-head">
				<?php the_archive_title( '<h1>', '</h1>' ); ?>
				<?php the_archive_description( '<p>', '</p>' ); ?>
			</div>
		<?php elseif ( is_search() ) : ?>
			<div class="section-head">
				<h1><?php printf( esc_html__( 'Search results for: %s', 'spotino' ), '<span>' . esc_html( get_search_query() ) . '</span>' ); ?></h1>
			</div>
		<?php endif; ?>

		<?php if ( have_posts() ) : ?>
			<div class="post-grid">
				<?php
				while ( have_posts() ) :
					the_post();
					?>
					<article <?php post_class( 'post-card' ); ?>>
						<?php if ( has_post_thumbnail() ) : ?>
							<a class="thumb" href="<?php the_permalink(); ?>" aria-hidden="true" tabindex="-1">
								<?php the_post_thumbnail( 'large' ); ?>
							</a>
						<?php endif; ?>
						<div class="card-body">
							<?php
							$cats = get_the_category();
							if ( ! empty( $cats ) ) :
								?>
								<span class="cat"><?php echo esc_html( $cats[0]->name ); ?></span>
							<?php endif; ?>
							<h3><a href="<?php the_permalink(); ?>"><?php the_title(); ?></a></h3>
							<p class="excerpt"><?php echo esc_html( wp_trim_words( get_the_excerpt(), 24 ) ); ?></p>
							<div class="meta">
								<time datetime="<?php echo esc_attr( get_the_date( 'c' ) ); ?>"><?php echo esc_html( get_the_date() ); ?></time>
								<span>&middot;</span>
								<span><?php echo esc_html( spotino_reading_time() ); ?></span>
							</div>
						</div>
					</article>
					<?php
				endwhile;
				?>
			</div>

			<div class="pagination">
				<?php
				the_posts_pagination( array(
					'mid_size'  => 1,
					'prev_text' => __( '&larr;', 'spotino' ),
					'next_text' => __( '&rarr;', 'spotino' ),
				) );
				?>
			</div>

		<?php else : ?>
			<div class="section-head">
				<h1><?php esc_html_e( 'Nothing here yet', 'spotino' ); ?></h1>
				<p><?php esc_html_e( 'No posts found. Check back soon.', 'spotino' ); ?></p>
			</div>
		<?php endif; ?>

	</div>
</main>

<?php
get_footer();
