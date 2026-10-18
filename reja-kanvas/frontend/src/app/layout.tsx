import type { Metadata, Viewport } from "next";
import { Bricolage_Grotesque, JetBrains_Mono, Manrope } from "next/font/google";
import { Providers } from "@/components/Providers";
import { THEME_BOOT_SCRIPT } from "@/lib/theme";
import "./globals.css";

const display = Bricolage_Grotesque({ subsets: ["latin", "latin-ext"], weight: ["500", "700", "800"], variable: "--font-display" });
const sans = Manrope({ subsets: ["latin", "latin-ext", "cyrillic"], weight: ["400", "500", "600", "700", "800"], variable: "--font-sans" });
const mono = JetBrains_Mono({ subsets: ["latin", "cyrillic"], weight: ["500"], variable: "--font-mono" });

export const metadata: Metadata = {
  title: "Reja — rejalar kanvasi",
  applicationName: "Reja",
  description: "Rejalarni kanvasga joylang, bajaring va rasman tasdiqlang.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#F4F1EA",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="uz" className={`${display.variable} ${sans.variable} ${mono.variable}`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOT_SCRIPT }} />
        <link rel="manifest" href="/manifest.webmanifest" />
        <link rel="icon" href="/icon.svg" type="image/svg+xml" />
        <link rel="apple-touch-icon" href="/icon.svg" />
      </head>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
