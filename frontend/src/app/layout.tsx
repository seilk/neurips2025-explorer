import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import "katex/dist/katex.min.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "NeurIPS 2025 Papers Explorer",
  description: "Fast search and filtering UI for NeurIPS 2025 accepted papers",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className={`${geistSans.variable} ${geistMono.variable}`}>
        <div
          style={{
            position: "fixed",
            top: "16px",
            right: "16px",
            zIndex: 1000,
            background: "rgba(15, 23, 42, 0.85)",
            color: "#f8fafc",
            padding: "6px 12px",
            borderRadius: "999px",
            fontSize: "0.85rem",
            boxShadow: "0 10px 25px rgba(15, 23, 42, 0.2)",
          }}
        >
          <a
            href="https://seilk.github.io/"
            target="_blank"
            rel="noopener noreferrer"
            style={{ color: "inherit", textDecoration: "none" }}
          >
            © Seil Kang
          </a>
        </div>
        {children}
      </body>
    </html>
  );
}
