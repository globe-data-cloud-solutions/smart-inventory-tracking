// Force the auth routes (login, etc.) to be server-rendered on demand.
// useSearchParams() in login/page.tsx requires dynamic rendering and cannot
// be statically prerendered by Next.js 14, even with a <Suspense> boundary.
export const dynamic = "force-dynamic";

export default function AuthLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <>{children}</>;
}
