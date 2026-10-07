"use client";

import type { ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import type { Components } from "react-markdown";
import remarkGfm from "remark-gfm";

/**
 * GitHub-style heading slug: lowercase, drop anything that isn't a letter,
 * digit, space, underscore or hyphen, then turn each space into a hyphen
 * (no collapsing/trimming — matches the anchors already written into
 * docs/TA_ONBOARDING_GUIDE.md, e.g. "Subscription & Invoices" -> the "&"
 * is dropped but both surrounding spaces survive as "--").
 */
function slugifyHeading(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9 _-]/g, "")
    .replace(/ /g, "-");
}

function flattenText(node: ReactNode): string {
  if (node === null || node === undefined || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(flattenText).join("");
  if (typeof node === "object" && "props" in node) {
    return flattenText((node as { props?: { children?: ReactNode } }).props?.children);
  }
  return "";
}

/** No raw HTML (no rehype-raw) — markdown-authored HTML renders as plain text, never executes. */
function buildMarkdownComponents(): Components {
  const seenSlugs = new Map<string, number>();

  function headingId(children: ReactNode): string {
    const base = slugifyHeading(flattenText(children));
    const count = seenSlugs.get(base) ?? 0;
    seenSlugs.set(base, count + 1);
    return count === 0 ? base : `${base}-${count}`;
  }

  function heading(Tag: "h1" | "h2" | "h3" | "h4" | "h5" | "h6", className: string) {
    return ({ children }: { children?: ReactNode }) => (
      <Tag id={headingId(children)} className={className}>
        {children}
      </Tag>
    );
  }

  return {
    h1: heading("h1", "text-2xl font-bold text-gray-900 mt-8 mb-4 scroll-mt-20"),
    h2: heading("h2", "text-xl font-bold text-gray-900 mt-8 mb-3 pb-2 border-b border-gray-200 scroll-mt-20"),
    h3: heading("h3", "text-lg font-semibold text-gray-800 mt-6 mb-2 scroll-mt-20"),
    h4: heading("h4", "text-base font-semibold text-gray-800 mt-4 mb-2 scroll-mt-20"),
    h5: heading("h5", "text-sm font-semibold text-gray-800 mt-3 mb-1 scroll-mt-20"),
    h6: heading("h6", "text-sm font-semibold text-gray-600 mt-3 mb-1 scroll-mt-20"),
    p: ({ children }) => <p className="text-sm text-gray-700 leading-relaxed mb-3">{children}</p>,
    a: ({ href, children }) => (
      <a href={href} className="text-brand-600 hover:text-brand-700 underline font-medium">
        {children}
      </a>
    ),
    ul: ({ children }) => <ul className="list-disc pl-6 mb-3 text-sm text-gray-700 space-y-1">{children}</ul>,
    ol: ({ children }) => <ol className="list-decimal pl-6 mb-3 text-sm text-gray-700 space-y-1">{children}</ol>,
    li: ({ children }) => <li className="leading-relaxed">{children}</li>,
    blockquote: ({ children }) => (
      <blockquote className="border-l-4 border-brand-200 bg-brand-50 px-4 py-2 mb-3 text-sm text-gray-700 italic">
        {children}
      </blockquote>
    ),
    hr: () => <hr className="my-6 border-gray-200" />,
    strong: ({ children }) => <strong className="font-semibold text-gray-900">{children}</strong>,
    code: ({ children, className }) => {
      const isBlock = typeof className === "string" && className.startsWith("language-");
      if (isBlock) {
        return (
          <code className="block whitespace-pre-wrap font-mono text-xs text-gray-800">{children}</code>
        );
      }
      return (
        <code className="px-1.5 py-0.5 rounded bg-gray-100 text-gray-800 font-mono text-xs">
          {children}
        </code>
      );
    },
    pre: ({ children }) => (
      <pre className="bg-gray-900 text-gray-100 rounded-lg p-4 mb-3 overflow-x-auto text-xs">{children}</pre>
    ),
    table: ({ children }) => (
      <div className="overflow-x-auto mb-3">
        <table className="min-w-full text-sm border border-gray-200 rounded-lg">{children}</table>
      </div>
    ),
    thead: ({ children }) => <thead className="bg-gray-50">{children}</thead>,
    th: ({ children }) => (
      <th className="px-3 py-2 text-left font-semibold text-gray-700 border-b border-gray-200">{children}</th>
    ),
    td: ({ children }) => <td className="px-3 py-2 text-gray-700 border-b border-gray-100 align-top">{children}</td>,
    // Screenshot placeholders render as text, never a broken <img> request.
    img: ({ alt }) => (
      <span className="inline-block text-xs italic text-gray-400 border border-dashed border-gray-300 rounded px-2 py-1">
        [{alt || "image"}]
      </span>
    ),
  };
}

export function DocumentRenderer({ markdown }: { markdown: string }) {
  return (
    <div className="max-w-none">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={buildMarkdownComponents()}>
        {markdown}
      </ReactMarkdown>
    </div>
  );
}
