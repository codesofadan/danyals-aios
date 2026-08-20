/* Spotino — mobile navigation toggle. */
( function () {
	'use strict';
	var toggle = document.querySelector( '.nav-toggle' );
	var nav = document.querySelector( '.main-nav' );
	if ( ! toggle || ! nav ) {
		return;
	}
	toggle.addEventListener( 'click', function () {
		var open = nav.classList.toggle( 'open' );
		toggle.setAttribute( 'aria-expanded', open ? 'true' : 'false' );
	} );
	// Close the menu when a link is tapped (single-page feel on mobile).
	nav.addEventListener( 'click', function ( e ) {
		if ( e.target.tagName === 'A' ) {
			nav.classList.remove( 'open' );
			toggle.setAttribute( 'aria-expanded', 'false' );
		}
	} );
}() );
