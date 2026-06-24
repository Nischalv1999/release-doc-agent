import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Release Documentation Agent",
  description: "AI-powered automated release documentation",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen">
        <header className="bg-white border-b border-gray-200 px-6 py-4">
          <div className="max-w-7xl mx-auto flex items-center justify-between">
            <h1 className="text-xl font-semibold text-gray-900">
              Release Documentation Agent
            </h1>
            <span className="text-sm text-gray-500">AI-Powered</span>
          </div>
        </header>
        <main className="max-w-7xl mx-auto px-6 py-8">{children}</main>
      </body>
    </html>
  );
}
