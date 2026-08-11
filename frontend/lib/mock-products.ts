// frontend/lib/mock-products.ts
//
// Static mock merchandising content for the retail home page. Visual
// credibility only — there is no commerce backend behind these products.

import type { Product } from "@/types/product";

export const mockProducts: Product[] = [
  {
    id: "p1",
    name: "Colorblock Pocket Tee",
    category: "Tops",
    price: 28,
    detail: "Ecru · green and blue trim",
    badge: "New",
    image: "/assets/products/photos/colorblock-pocket-tee.webp",
  },
  {
    id: "p2",
    name: "Striped Popover Top",
    category: "Tops",
    price: 46,
    detail: "Cream · dusty blue stripe",
    image: "/assets/products/photos/striped-popover-top.webp",
  },
  {
    id: "p3",
    name: "Wide Leg Jean",
    category: "Bottoms",
    price: 78,
    detail: "Dark indigo wash",
    badge: "Bestseller",
    image: "/assets/products/photos/wide-leg-jean.webp",
  },
  {
    id: "p4",
    name: "Flare Patch-Pocket Jean",
    category: "Bottoms",
    price: 82,
    detail: "Mid-wash flare",
    image: "/assets/products/photos/flare-patch-pocket-jean.webp",
  },
  {
    id: "p5",
    name: "Straight Fit Jean",
    category: "Bottoms",
    price: 68,
    detail: "Light wash straight leg",
    image: "/assets/products/photos/straight-fit-jean.webp",
  },
  {
    id: "p6",
    name: "Pleated Midi Skirt",
    category: "Bottoms",
    price: 64,
    detail: "Chocolate brown · button front",
    image: "/assets/products/photos/pleated-midi-skirt.webp",
  },
  {
    id: "p7",
    name: "Varsity Zip Cardigan",
    category: "Outerwear",
    price: 72,
    detail: "Navy · red and white trim",
    image: "/assets/products/photos/varsity-zip-cardigan.webp",
  },
  {
    id: "p8",
    name: "Leather Moto Jacket",
    category: "Outerwear",
    price: 248,
    detail: "Black leather",
    image: "/assets/products/photos/leather-moto-jacket.webp",
  },
  {
    id: "p9",
    name: "Floral Midi Dress",
    category: "Dresses",
    price: 88,
    detail: "Blush multi floral",
    image: "/assets/products/photos/floral-midi-dress.webp",
  },
  {
    id: "p10",
    name: "Paisley Shirt Dress",
    category: "Dresses",
    price: 94,
    detail: "Olive and black paisley",
    image: "/assets/products/photos/paisley-shirt-dress.webp",
  },
];
