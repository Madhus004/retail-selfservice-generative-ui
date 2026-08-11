// frontend/types/cancellation.ts

export type CancellationLineItem = {
  orderLineId: string;
  itemName: string;
  color: string;
  size: string;
  price: number;
  quantity: number;
  cancellableQuantity: number;
};

export type CancellationEligibleOrder = {
  orderNumber: string;
  orderDate: string;
  orderStatus: string;
  currency: string;
  items: CancellationLineItem[];
};

export type CancellationLineSelection = {
  orderLineId: string;
  quantity: number;
};

export type CancellationResult = {
  cancellationId: string;
  orderNumber: string;
  status: string;
  cancelledItems: {
    itemName: string;
    color: string;
    size: string;
    quantity: number;
  }[];
  reason: string;
  resultingOrderStatus: string;
};
