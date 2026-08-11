"use client";

import { useState } from "react";
import { mockProducts } from "@/lib/mock-products";
import type { Product, ProductCategory } from "@/types/product";

const CATEGORIES: Array<ProductCategory | "All"> = [
  "All",
  "Tops",
  "Bottoms",
  "Outerwear",
  "Dresses",
];

function formatPrice(price: number) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
  }).format(price);
}

function ProductCard({ product }: { product: Product }) {
  return (
    <div className="group rounded-3xl border border-black/10 bg-white p-4 transition hover:-translate-y-0.5 hover:border-black/30 hover:shadow-lg">
      <img
        src={product.image}
        alt={product.name}
        className="mb-4 aspect-[4/5] w-full rounded-2xl object-cover"
      />

      <div className="flex items-start justify-between gap-2">
        <p className="font-black tracking-[-0.03em] text-neutral-950">
          {product.name}
        </p>

        {product.badge && (
          <span className="shrink-0 rounded-full bg-black px-2.5 py-1 text-[10px] font-black uppercase tracking-widest text-white">
            {product.badge}
          </span>
        )}
      </div>

      <p className="mt-1 text-sm text-neutral-500">{product.detail}</p>

      <div className="mt-3 flex items-center justify-between">
        <p className="text-sm font-bold text-neutral-900">
          {formatPrice(product.price)}
        </p>

        <button className="rounded-full border border-black/10 px-3 py-1.5 text-xs font-black text-neutral-700 transition group-hover:border-black/30">
          Add to Bag
        </button>
      </div>
    </div>
  );
}

export function ProductGrid() {
  const [activeCategory, setActiveCategory] =
    useState<(typeof CATEGORIES)[number]>("All");

  const visibleProducts =
    activeCategory === "All"
      ? mockProducts
      : mockProducts.filter((product) => product.category === activeCategory);

  return (
    <div>
      <div className="mb-6 flex flex-wrap gap-2">
        {CATEGORIES.map((category) => (
          <button
            key={category}
            onClick={() => setActiveCategory(category)}
            className={`rounded-full px-4 py-2 text-sm font-bold transition ${
              activeCategory === category
                ? "bg-black text-white"
                : "border border-black/10 bg-white text-neutral-700 hover:border-black/30"
            }`}
          >
            {category}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-4 @3xl:grid-cols-3 @6xl:grid-cols-4">
        {visibleProducts.map((product) => (
          <ProductCard key={product.id} product={product} />
        ))}
      </div>
    </div>
  );
}
