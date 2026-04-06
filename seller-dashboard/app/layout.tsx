import type { Metadata } from "next";
import "./globals.css";
import Sidebar from "@/components/Sidebar";
import TopBar from "@/components/TopBar";

export const metadata: Metadata = {
  title: "Seller Dashboard | Jaringan Dagang",
  description: "Manage your store on Jaringan Dagang open commerce network",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <Sidebar />
        <div className="lg:pl-64">
          <TopBar />
          <main className="min-h-[calc(100vh-4rem)]">{children}</main>
        </div>
      </body>
    </html>
  );
}
