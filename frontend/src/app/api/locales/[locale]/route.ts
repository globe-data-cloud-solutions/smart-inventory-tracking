import { NextResponse } from "next/server";
import { readFileSync } from "fs";
import { join } from "path";

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ locale: string }> }
) {
  const { locale } = await params;
  const allowed = ["en", "am", "or"];
  if (!allowed.includes(locale)) {
    return NextResponse.json({ error: "Unknown locale" }, { status: 404 });
  }
  try {
    const filePath = join(process.cwd(), "..", "locales", `${locale}.json`);
    const content = readFileSync(filePath, "utf-8");
    return new NextResponse(content, {
      headers: {
        "Content-Type": "application/json",
        "Cache-Control": "public, max-age=86400",
      },
    });
  } catch {
    return NextResponse.json({ error: "Locale file not found" }, { status: 404 });
  }
}
