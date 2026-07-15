import type { Metadata } from "next";
import { Bricolage_Grotesque } from "next/font/google";
import "./globals.css";
import { AiosStoreProvider } from "@/lib/store";
import { AuthProvider } from "@/lib/auth";
import { LoaderProvider } from "@/components/loader/LoaderProvider";
import DemoSwitcher from "@/components/DemoSwitcher";
import ClickFX from "@/components/ClickFX";

const bricolage = Bricolage_Grotesque({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700", "800"],
  variable: "--font-bricolage",
  display: "swap",
});

export const metadata: Metadata = {
  title: "AIOS · Xegents",
  description: "SEO automation platform for the agency — audits, content, clients and Policy Radar. Built by Xegents AI.",
};

// Root shell holds only the document chrome + ambient glow. Each portal
// brings its OWN navigation: the admin dashboard's Sidebar lives in
// (admin)/layout.tsx; the team member portal's shell lives in
// portal/layout.tsx. They are fully separate experiences.
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
      <body>
        <div className="glow a" />
        <div className="glow b" />
        <AiosStoreProvider>
          <AuthProvider>
            <LoaderProvider>
              {children}
              <DemoSwitcher />
              <ClickFX />
            </LoaderProvider>
          </AuthProvider>
        </AiosStoreProvider>
      </body>
    </html>
  );
}
