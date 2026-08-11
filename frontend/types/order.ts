// frontend/types/order.ts

import type { ReactNode } from "react";

export type SelectedIntent = "whereIsMyOrder" | null;

export type PromiseTone = "success" | "warning" | "danger" | "neutral";

export type PromiseMilestone = {
  label: string;
  date: string;
  position: number;
  tone: "success" | "neutral" | "warning" | "danger" | "promise";
};

export type PackageLine = {
  itemName: string;
  color: string;
  size: string;
  qty: number;
  price: string;
  imageGradient: string;
};

export type ShipmentPackage = {
  packageNumber: number;
  trackingNumber: string;
  carrier: string;
  status: string;
  promisedDeliveryResult: "Met" | "At risk" | "Missed";
  promisedDelivery: string;
  actualOrEstimatedDelivery: string;
  fullTrackingUrl: string;
  items: PackageLine[];
  milestones: PromiseMilestone[];
  deliveryProof?: {
    deliveredAt: string;
    locationNote: string;
    imageDescription: string;
  };
};

export type ServiceRecovery = {
  title: string;
  description: string;
  badge: string;
  secondaryBadge?: string;
  tone: "coupon" | "refund" | "info";
};

export type OrderScenario = {
  orderNumber: string;
  status: string;
  promise: string;
  date: string;
  items: string;
  customerName: string;
  orderPromiseSummary: string;
  promiseStatusLabel: string;
  promiseStatusTone: PromiseTone;
  customerSummary: string;
  packages: ShipmentPackage[];
  serviceRecovery?: ServiceRecovery;
};

export type WrongDeliveryClaimDraft = {
  orderNumber: string;
  packageNumber?: number;
  issueDescription: string;
  preferredContactMethod: "email" | "phone";
};

export type ClaimSubmissionResult = {
  claimId: string;
  orderNumber: string;
  status: "submitted" | "under_review" | "resolved";
  submittedAt: string;
  slaMessage: string;
};

export type SupportButtonProps = {
  icon: ReactNode;
  label: string;
  active?: boolean;
  disabled?: boolean;
  onClick?: () => void;
};