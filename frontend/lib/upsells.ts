// AIOS · Upsells module mock data — swap for FastAPI/Postgres later.
// Upsell cards deliberately link OUT to the agency's Fiverr gigs (not
// internal services) to keep the agency's Fiverr-centered public brand front
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
