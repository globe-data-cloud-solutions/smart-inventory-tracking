"use client";

/** Consistent first-letter color derived from product name so every product
 *  always gets the same color regardless of render order. */
function nameColor(name: string): string {
  let h = 0;
  for (let i = 0; i < name.length; i++) {
    h = (h * 31 + name.charCodeAt(i)) & 0xfffffff;
  }
  const palette = [
    "#1b4332", "#155e75", "#4c1d95", "#881337",
    "#78350f", "#134e4a", "#1e3a5f", "#3b0764",
  ];
  return palette[h % palette.length] ?? "#1b4332";
}

const SIZE_CLS: Record<string, string> = {
  sm: "w-7 h-7 text-[11px]",
  md: "w-10 h-10 text-sm",
  lg: "w-16 h-16 text-xl",
};

interface ProductImageProps {
  image_url?: string | null;
  product_name: string;
  size?: "sm" | "md" | "lg";
  className?: string;
}

export function ProductImage({
  image_url,
  product_name,
  size = "md",
  className = "",
}: ProductImageProps) {
  const sizeCls = SIZE_CLS[size] ?? SIZE_CLS["md"];

  if (image_url) {
    return (
      <img
        src={image_url}
        alt={product_name}
        className={`${sizeCls} rounded object-cover shrink-0 ${className}`}
      />
    );
  }

  const letter = (product_name[0] ?? "?").toUpperCase();
  const bg = nameColor(product_name);

  return (
    <div
      className={`${sizeCls} rounded flex items-center justify-center shrink-0 font-bold text-white ${className}`}
      style={{ backgroundColor: bg }}
      aria-hidden="true"
    >
      {letter}
    </div>
  );
}
