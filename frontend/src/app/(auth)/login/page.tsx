"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { login } from "@/lib/demo-auth";
import { DEMO_TENANTS, SA_USER } from "@/lib/demo-data";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    await new Promise((r) => setTimeout(r, 400)); // simulate network
    const session = login(email, password);
    if (!session) {
      setError("Invalid email or password.");
      setLoading(false);
      return;
    }
    router.push("/dashboard");
  };

  const fillCredentials = (em: string, pw: string) => {
    setEmail(em);
    setPassword(pw);
    setError("");
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-brand-900 to-slate-900 flex">
      {/* ── Left panel: demo accounts ── */}
      <div className="hidden lg:flex lg:w-96 bg-white/5 border-r border-white/10 flex-col p-8">
        <Link href="/" className="flex items-center gap-2 mb-10">
          <div className="w-8 h-8 rounded-md bg-brand-500 flex items-center justify-center">
            <svg viewBox="0 0 24 24" fill="none" className="w-5 h-5 text-white" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M20 7l-8-4-8 4m16 0v10l-8 4m0-14L4 17m8 4V11" />
            </svg>
          </div>
          <span className="text-white font-semibold">SMART Inventory</span>
        </Link>

        <h2 className="text-white font-bold text-lg mb-1">Demo Accounts</h2>
        <p className="text-slate-400 text-sm mb-6">Click any account to auto-fill credentials.</p>

        {/* SA */}
        <div className="mb-6">
          <p className="text-xs text-slate-400 uppercase tracking-wider font-semibold mb-2">
            System Admin (all tenants)
          </p>
          <button
            onClick={() => fillCredentials(SA_USER.email, SA_USER.password)}
            className="w-full text-left p-3 rounded-lg bg-brand-600/30 border border-brand-500/40 hover:bg-brand-600/50 transition-colors group"
          >
            <p className="text-white text-sm font-medium group-hover:text-brand-200">{SA_USER.name}</p>
            <p className="text-slate-400 text-xs font-mono mt-0.5">{SA_USER.email}</p>
            <span className="inline-block mt-1 text-xs bg-brand-500 text-white rounded px-1.5 py-0.5">SA</span>
          </button>
        </div>

        {/* Tenant users */}
        {DEMO_TENANTS.map((tenant) => (
          <div key={tenant.id} className="mb-5">
            <p className="text-xs text-slate-400 uppercase tracking-wider font-semibold mb-2 flex items-center gap-1.5">
              <span>{tenant.logo}</span> {tenant.name}
            </p>
            <div className="space-y-1.5 max-h-48 overflow-y-auto pr-1">
              {tenant.users.map((u) => (
                <button
                  key={u.id}
                  onClick={() => fillCredentials(u.email, u.password)}
                  className="w-full text-left p-2.5 rounded-lg bg-white/5 border border-white/10 hover:bg-white/10 transition-colors group"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="text-white text-xs font-medium truncate">{u.name}</p>
                      <p className="text-slate-400 text-xs font-mono truncate">{u.email}</p>
                    </div>
                    <span className={`flex-shrink-0 text-xs rounded px-1.5 py-0.5 font-medium ${
                      u.role === "TA" ? "bg-purple-500 text-white" :
                      u.role === "NM" ? "bg-blue-500 text-white" :
                      "bg-teal-500 text-white"
                    }`}>{u.role}</span>
                  </div>
                  {u.warehouseName && (
                    <p className="text-slate-500 text-xs mt-0.5 truncate">📍 {u.warehouseName}</p>
                  )}
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>

      {/* ── Right panel: login form ── */}
      <div className="flex-1 flex items-center justify-center p-8">
        <div className="w-full max-w-md">
          {/* Mobile logo */}
          <Link href="/" className="flex items-center justify-center gap-2 mb-8 lg:hidden">
            <div className="w-10 h-10 rounded-lg bg-brand-500 flex items-center justify-center">
              <svg viewBox="0 0 24 24" fill="none" className="w-6 h-6 text-white" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M20 7l-8-4-8 4m16 0v10l-8 4m0-14L4 17m8 4V11" />
              </svg>
            </div>
            <span className="text-white font-bold text-xl">SMART Inventory</span>
          </Link>

          <div className="bg-white rounded-2xl shadow-2xl p-8">
            <div className="mb-7">
              <h1 className="text-2xl font-bold text-gray-900">Sign in</h1>
              <p className="text-gray-500 text-sm mt-1">Access your inventory dashboard</p>
            </div>

            <form onSubmit={handleSubmit} className="space-y-5">
              <div>
                <label htmlFor="email" className="block text-sm font-medium text-gray-700 mb-1.5">
                  Email address
                </label>
                <input
                  id="email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                  autoComplete="email"
                  placeholder="you@company.com"
                  className="w-full rounded-lg border border-gray-300 px-4 py-2.5 text-sm text-gray-900 placeholder-gray-400 focus:border-brand-500 focus:ring-2 focus:ring-brand-200 outline-none transition"
                />
              </div>
              <div>
                <label htmlFor="password" className="block text-sm font-medium text-gray-700 mb-1.5">
                  Password
                </label>
                <input
                  id="password"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  autoComplete="current-password"
                  placeholder="••••••••••"
                  className="w-full rounded-lg border border-gray-300 px-4 py-2.5 text-sm text-gray-900 placeholder-gray-400 focus:border-brand-500 focus:ring-2 focus:ring-brand-200 outline-none transition"
                />
              </div>

              {error && (
                <div className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
                  {error}
                </div>
              )}

              <button
                type="submit"
                disabled={loading}
                className="w-full rounded-lg bg-brand-600 py-3 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-60 transition-colors flex items-center justify-center gap-2"
              >
                {loading ? (
                  <>
                    <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                    Signing in…
                  </>
                ) : "Sign in →"}
              </button>
            </form>

            {/* Mobile credentials hint */}
            <div className="mt-6 p-4 rounded-lg bg-brand-50 border border-brand-100 lg:hidden">
              <p className="text-xs font-semibold text-brand-700 mb-2">SA Demo Account</p>
              <p className="text-xs font-mono text-brand-800">smartadmin@smart-inventory.com</p>
              <p className="text-xs font-mono text-brand-800">SmartAdmin@2026</p>
            </div>
          </div>

          <p className="text-center text-slate-400 text-xs mt-6">
            SMART Inventory Tracker · RBAC + ABAC · 3 languages
          </p>
        </div>
      </div>
    </div>
  );
}
