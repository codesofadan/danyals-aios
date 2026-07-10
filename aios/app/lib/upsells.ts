// AIOS · Upsells module mock data — swap for FastAPI/Postgres later.
// Upsell cards deliberately link OUT to the agency's Fiverr gigs (not
// internal services) to keep Xegents' Fiverr-centered public brand front
// and center inside the client portal. Admin curates them here; the active
// ones render as clickable gig cards for every client.
import { SERIES } from "@/lib/data";

export type Upsell = {
  id: string;
  title: string;
  description: string;
  fiverrUrl: string; // real gig URL or "#"
  active: boolean;
  clicks30d: number; // portal clicks in the last 30 days
  price: number; // "starting at" USD on Fiverr
  rating: number; // gig star rating
  reviews: number; // review count
  icon: string; // material symbol
  color: string; // accent for the card badge
};

// Ballpark portal click → Fiverr order rate, used for the est-conversions tile.
export const CONVERSION_RATE = 0.062;

export const upsells: Upsell[] = [
  {
    id: "up-01",
    title: "Premium Backlink Package",
    description: "20 high-authority editorial backlinks from DA70+ niche sites — white-hat, manually placed.",
    fiverrUrl: "https://www.fiverr.com/xegents/build-premium-high-authority-seo-backlinks",
    active: true,
    clicks30d: 412,
    price: 149,
    rating: 4.9,
    reviews: 318,
    icon: "link",
    color: SERIES.c1,
  },
  {
    id: "up-02",
    title: "Google Business Profile Optimization",
    description: "Full GBP setup & optimization — categories, services, geo-tagged posts and review strategy.",
    fiverrUrl: "https://www.fiverr.com/xegents/optimize-your-google-business-profile",
    active: true,
    clicks30d: 356,
    price: 89,
    rating: 5.0,
    reviews: 241,
    icon: "storefront",
    color: SERIES.c2,
  },
  {
    id: "up-03",
    title: "Website Speed Boost",
    description: "Core Web Vitals tune-up — image compression, caching, lazy-load and render-blocking fixes.",
    fiverrUrl: "https://www.fiverr.com/xegents/boost-your-website-speed-and-core-web-vitals",
    active: true,
    clicks30d: 288,
    price: 119,
    rating: 4.8,
    reviews: 176,
    icon: "speed",
    color: SERIES.c4,
  },
  {
    id: "up-04",
    title: "Local Citation Building",
    description: "50 accurate NAP citations across top local directories to strengthen map-pack rankings.",
    fiverrUrl: "https://www.fiverr.com/xegents/build-local-seo-citations-for-your-business",
    active: true,
    clicks30d: 203,
    price: 65,
    rating: 4.9,
    reviews: 402,
    icon: "location_on",
    color: SERIES.c3,
  },
  {
    id: "up-05",
    title: "Monthly SEO Retainer",
    description: "Done-for-you monthly SEO — content, links and reporting managed by a dedicated strategist.",
    fiverrUrl: "https://www.fiverr.com/xegents/manage-your-monthly-seo-campaign",
    active: false,
    clicks30d: 141,
    price: 499,
    rating: 4.9,
    reviews: 98,
    icon: "calendar_month",
    color: SERIES.c5,
  },
  {
    id: "up-06",
    title: "Logo & Brand Refresh",
    description: "Modern logo redesign with a mini brand kit — colors, fonts and social avatars included.",
    fiverrUrl: "https://www.fiverr.com/xegents/design-a-modern-logo-and-brand-kit",
    active: false,
    clicks30d: 97,
    price: 79,
    rating: 4.7,
    reviews: 512,
    icon: "palette",
    color: SERIES.c2,
  },
];
