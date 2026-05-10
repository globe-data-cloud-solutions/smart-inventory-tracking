import { NextResponse } from "next/server";
import { readFile } from "fs/promises";
import path from "path";

const SUPPORTED = ["en", "am", "or"] as const;

export async function GET(
  _req: Request,
  context: { params: Promise<{ locale: string }> }
) {
  const { locale } = await context.params;
  if (!SUPPORTED.includes(locale as (typeof SUPPORTED)[number])) {
    return NextResponse.json({ error: "Unknown locale" }, { status: 404 });
  }

  try {
    const filePath = path.join(process.cwd(), "..", "locales", `${locale}.json`);
    const content = await readFile(filePath, "utf-8");
    return new NextResponse(content, {
      headers: { "Content-Type": "application/json" },
    });
  } catch {
    return NextResponse.json({ error: "Locale file not found" }, { status: 404 });
  }
}
