import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";
import "./globals.css";
import { AiosStoreProvider } from "@/lib/store";
import { AuthProvider } from "@/lib/auth";
import { QueryProvider } from "@/lib/query";
import { LoaderProvider } from "@/components/loader/LoaderProvider";
import DemoSwitcher from "@/components/DemoSwitcher";
import ClickFX from "@/components/ClickFX";

// Self-hosted (bundled) Bricolage Grotesque variable font. Uses next/font/local so
// the font is compiled INTO the build and renders identically in `next dev` and the
// Docker production build - next/font/google fetches at build time, which fails in
// the offline container build and silently falls back to system-ui.
const bricolage = localFont({
  src: "./fonts/BricolageGrotesque.woff2",
  weight: "200 800",
  variable: "--font-bricolage",
  display: "swap",
});

export const metadata: Metadata = {
  title: "AIOS",
  description: "SEO automation platform for the agency — audits, content, clients and Policy Radar.",
};

// WITHOUT this the dashboard rendered at a ~980px desktop width on phones/tablets and
// zoomed out — so none of the responsive @media rules ever fired. `width=device-width`
// makes the layout scale to the real screen so the breakpoints in globals.css take effect
// on mobile + tablet. maximumScale left generous so pinch-zoom still works (accessibility).
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 5,
};

// Root shell holds only the document chrome + ambient glow, plus the public
// free-audit page (this file's own page.tsx). Each portal brings its OWN
// navigation: the admin dashboard's Sidebar lives in admin/layout.tsx; the
// team member portal's shell lives in team/layout.tsx. They are fully
// separate experiences.
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={bricolage.variable}>
      <head>
        {/* Material Symbols Rounded icon font */}
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Material+Symbols+Rounded:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200&display=block"
        />
      </head>
      <body suppressHydrationWarning>
        <div className="glow a" />
        <div className="glow b" />
        {/* Auth owns the bearer token (outermost); Query serves server data;
            the legacy demo store stays nested for screens not yet swapped. */}
        <AuthProvider>
          <QueryProvider>
            <AiosStoreProvider>
              <LoaderProvider>
                {children}
                <DemoSwitcher />
                <ClickFX />
              </LoaderProvider>
            </AiosStoreProvider>
          </QueryProvider>
        </AuthProvider>
      </body>
    </html>
  );
}
