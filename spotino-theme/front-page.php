<?php
/**
 * Front page: a full-width hero + the latest posts.
 *
 * @package Spotino
 */

get_header();
?>

<main id="main">

	<section class="hero">
		<div class="wrap">
			<span class="eyebrow"><?php bloginfo( 'name' ); ?></span>
			<h1><?php echo esc_html( get_bloginfo( 'description' ) ? get_bloginfo( 'description' ) : get_bloginfo( 'name' ) ); ?></h1>
			<p><?php esc_html_e( 'Insights, guides and updates — written to be read.', 'spotino' ); ?></p>
			<div class="hero-actions">
				<?php
				$posts_page = get_option( 'page_for_posts' );
				$blog_url   = $posts_page ? get_permalink( $posts_page ) : home_url( '/' );
				?>
				<a class="button" href="<?php echo esc_url( $blog_url ); ?>"><?php esc_html_e( 'Read the blog', 'spotino' ); ?></a>
				<a class="button ghost" href="#latest"><?php esc_html_e( 'Latest posts', 'spotino' ); ?></a>
			</div>
		</div>
	</section>

	<?php if ( is_front_page() && ! is_home() ) : ?>
		<?php
		// A static Page is the front page — show its content.
		while ( have_posts() ) :
			the_post();
			?>
			<div class="entry-content" style="padding-block:clamp(40px,6vw,72px)"><?php the_content(); ?></div>
			<?php
		endwhile;
	endif;
	?>

	<div class="wrap list-wrap" id="latest">
		<div class="section-head">
			<h2><?php esc_html_e( 'Latest articles', 'spotino' ); ?></h2>
			<p><?php esc_html_e( 'Fresh from the blog.', 'spotino' ); ?></p>
		</div>

		<?php
		$recent = new WP_Query( array(
			'post_type'           => 'post',
			'posts_per_page'      => 6,
			'ignore_sticky_posts' => true,
		) );
		if ( $recent->have_posts() ) :
			?>
			<div class="post-grid">
				<?php
				while ( $recent->have_posts() ) :
					$recent->the_post();
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
				wp_reset_postdata();
				?>
			</div>
		<?php else : ?>
			<p><?php esc_html_e( 'No posts published yet.', 'spotino' ); ?></p>
		<?php endif; ?>
	</div>

</main>

<?php
get_footer();
