// frontend/types/product.ts

export type ProductCategory = "Tops" | "Bottoms" | "Outerwear" | "Dresses";

export type Product = {
  id: string;
  name: string;
  category: ProductCategory;
  price: number;
  detail: string;
  badge?: string;
  image: string;
};
