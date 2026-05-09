import Link from "next/link";

export default function HomePage() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-8 p-8">
      <h1 className="text-4xl font-bold text-brand-700">SMART Inventory</h1>
      <p className="text-lg text-gray-600">Multi-tenant inventory management platform</p>
      <div className="flex gap-4">
        <Link
          href="/dashboard/inventory"
          className="rounded-md bg-brand-600 px-6 py-3 text-sm font-medium text-white hover:bg-brand-700"
        >
          Go to Inventory
        </Link>
      </div>
    </main>
  );
}
