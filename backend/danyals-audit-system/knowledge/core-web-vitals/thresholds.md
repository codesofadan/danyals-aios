# Core Web Vitals thresholds - 2026

Loaded by: B2 (Performance + CWV).
Source: web.dev/vitals; PageSpeed Insights documentation; CrUX methodology.

## The three metrics that count for ranking signals

| Metric | Good (p75) | Needs improvement | Poor |
|---|---|---|---|
| LCP - Largest Contentful Paint | <= 2.5 s | 2.5 - 4.0 s | > 4.0 s |
| INP - Interaction to Next Paint | <= 200 ms | 200 - 500 ms | > 500 ms |
| CLS - Cumulative Layout Shift | <= 0.1 | 0.1 - 0.25 | > 0.25 |

INP replaced FID as the responsiveness metric in March 2024 and is the 2026 standard.

## Supporting metrics worth monitoring

| Metric | Good | Poor |
|---|---|---|
| FCP - First Contentful Paint | <= 1.8 s | > 3.0 s |
| TTFB - Time to First Byte | <= 800 ms | > 1.8 s |
| TBT - Total Blocking Time (lab) | <= 200 ms | > 600 ms |

## Field vs lab data

- **Field (CrUX)**: real users from the last 28 days, p75 percentile. This is what Google uses for the ranking signal.
- **Lab (Lighthouse)**: synthetic test in a controlled environment. Useful for debugging but does not directly drive ranking.

When field and lab disagree, **trust the field**. Lab POOR but field GOOD = the synthetic environment exaggerates the problem; flag as opportunity not failure. Field POOR but lab GOOD = real users hit something the lab does not see (often INP on real interactions); critical.

## Common LCP causes and fixes

1. **Hero image not preloaded** - add `<link rel="preload" as="image" fetchpriority="high">`
2. **Hero image lazy-loaded** - `loading="lazy"` above-the-fold = LCP regression
3. **Large unoptimized hero** - convert to AVIF/WebP, serve responsive sizes
4. **Render-blocking CSS** - inline critical CSS, defer the rest
5. **Slow TTFB** - hosting / database / CDN bottleneck

## Common CLS causes and fixes

1. **Images without dimensions** - always set width + height attributes
2. **Ads / embeds without reserved space** - reserve via min-height
3. **Web fonts causing FOIT/FOUT** - `font-display: swap` + preload the font
4. **Content injected above existing content** - reserve space or animate

## Common INP causes and fixes

1. **Long JavaScript tasks on input** - break with `await` / scheduler.yield
2. **Synchronous third-party scripts** - load with `defer` or `async`
3. **Heavy event handlers** - debounce, throttle, or move work off the main thread
4. **Hydration on click** - prefetch on hover, prerender critical interactions

## How B2 emits findings using this

B2 cites the actual p75 value AND the rating. "LCP p75 from CrUX is 3.4 s, rated Needs Improvement. Lab LCP is 5.8 s in Lighthouse, with the hero img.banner identified as the LCP element. Preload it and switch to AVIF; expected improvement 1.5-2 s."
