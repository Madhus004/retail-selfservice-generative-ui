// frontend/lib/item-images.ts
//
// Frontend-only lookup from an order line's itemName (as returned by
// agent/data/mock_orders.py) to a product photo, used to show a small
// thumbnail next to each line item — e.g. in the cancellation wizard's item
// selection step. Purely presentational; the backend order-line contract is
// unchanged.

const ITEM_IMAGES: Record<string, string> = {
  "Lightweight Hoodie": "/assets/products/photos/varsity-zip-cardigan.webp",
  "Everyday Crew Tee": "/assets/products/photos/colorblock-pocket-tee.webp",
  "Everyday Denim": "/assets/products/photos/straight-fit-jean.webp",
};

export function getItemImage(itemName: string): string | undefined {
  return ITEM_IMAGES[itemName];
}
