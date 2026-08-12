import type { Metadata } from "next";
import { Space_Grotesk, JetBrains_Mono } from "next/font/google";
import { AppNav } from "@/components/AppNav";
import "./globals.css";

const display = Space_Grotesk({
  subsets: ["latin"],
  weight: ["500", "600", "700"],
  variable: "--font-setup-display",
  display: "swap",
});

const sans = Space_Grotesk({
  subsets: ["latin"],
  weight: ["500", "600", "700"],
  variable: "--font-setup-sans",
  display: "swap",
});

const mono = JetBrains_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-setup-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Data Airlock Suite",
  description: "Pre-transformation data ingestion control plane",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body
        className={`${display.variable} ${sans.variable} ${mono.variable} min-h-screen bg-[#0b1220] font-sans antialiased`}
        style={{
          fontFamily:
            "var(--font-setup-sans), system-ui, -apple-system, sans-serif",
        }}
      >
        <AppNav />
        {children}
      </body>
    </html>
  );
}
