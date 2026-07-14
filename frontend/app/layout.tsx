import type { Metadata } from "next";
import { Bricolage_Grotesque } from "next/font/google";
import "./globals.css";

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
          href="https://fonts.googleapis.com/css2?family=Material+Symbols+Rounded:opsz,wght,FILL,GRAD@24,400,0,0&display=swap"
        />
      </head>
      <body>
        <div className="glow a" />
        <div className="glow b" />
        {children}
      </body>
    </html>
  );
}
