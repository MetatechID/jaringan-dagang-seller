const API_BASE = process.env.NEXT_PUBLIC_BPP_API_URL || "http://localhost:8001";

// AuthProvider stashes a token-getter here at mount time. If unset (e.g.
// Firebase not configured), requests go out unauthed and the backend falls
// back to legacy non-ACL behavior.
type TokenGetter = () => Promise<string | null>;
let _getIdToken: TokenGetter | null = null;
export function setIdTokenGetter(fn: TokenGetter | null): void {
  _getIdToken = fn;
}

async function request<T>(
  path: string,
  options?: RequestInit
): Promise<T> {
  const url = `${API_BASE}/api${path}`;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options?.headers as Record<string, string> | undefined),
  };
  if (_getIdToken) {
    try {
      const tok = await _getIdToken();
      if (tok) headers["Authorization"] = `Bearer ${tok}`;
    } catch {
      // best-effort; let the unauthed call hit the server
    }
  }
  const res = await fetch(url, { headers, ...options });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`API ${res.status}: ${body}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

// -- Store ID resolution ------------------------------------------------

const STORE_ID_KEY = "jd_selected_store_id";

/**
 * Get the selected store ID from localStorage, falling back to the API.
 * Uses a shared promise so concurrent callers don't trigger duplicate requests.
 */
let _storeIdPromise: Promise<string> | null = null;

function getStoreId(): Promise<string> {
  if (!_storeIdPromise) {
    _storeIdPromise = (async () => {
      if (typeof window !== "undefined") {
        const stored = localStorage.getItem(STORE_ID_KEY);
        if (stored) return stored;
      }
      const s = await fetchStore();
      if (typeof window !== "undefined") {
        localStorage.setItem(STORE_ID_KEY, s.id);
      }
      return s.id;
    })();
  }
  return _storeIdPromise;
}

export function getSelectedStoreId(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(STORE_ID_KEY);
}

export function setSelectedStoreId(id: string): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(STORE_ID_KEY, id);
  // Reset the cached promise so next API calls use the new store
  _storeIdPromise = null;
}

// -- Products ---------------------------------------------------------

export interface ProductImage {
  id: string;
  url: string;
  position: number;
  is_primary: boolean;
}

export interface SKU {
  id: string;
  variant_name: string | null;
  variant_value: string | null;
  sku_code: string;
  price: number;
  original_price: number | null;
  stock: number;
  weight_grams: number | null;
}

export interface Product {
  id: string;
  store_id: string;
  name: string;
  description: string | null;
  sku: string | null;
  status: "active" | "draft" | "archived";
  attributes: Record<string, unknown> | null;
  category_id: string | null;
  images: ProductImage[];
  skus: SKU[];
  created_at: string | null;
  updated_at: string | null;
}

export async function fetchProducts(): Promise<Product[]> {
  const storeId = await getStoreId();
  const res = await request<{ data: Product[] }>(`/products?store_id=${storeId}`);
  return res.data;
}

export async function fetchProduct(id: string): Promise<Product> {
  const res = await request<{ data: Product }>(`/products/${id}`);
  return res.data;
}

export async function createProduct(
  body: Record<string, unknown>
): Promise<Product> {
  const storeId = await getStoreId();
  const res = await request<{ data: Product }>(`/products?store_id=${storeId}`, {
    method: "POST",
    body: JSON.stringify(body),
  });
  return res.data;
}

export async function updateProduct(
  id: string,
  body: Record<string, unknown>
): Promise<Product> {
  const res = await request<{ data: Product }>(`/products/${id}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });
  return res.data;
}

export async function deleteProduct(id: string): Promise<void> {
  await request<void>(`/products/${id}`, { method: "DELETE" });
}

// -- Orders -----------------------------------------------------------

export type OrderStatus =
  | "created"
  | "accepted"
  | "in_progress"
  | "completed"
  | "cancelled";

export interface OrderPayment {
  id: string;
  xendit_invoice_id: string | null;
  amount: number;
  method: string | null;
  channel: string | null;
  status: string | null;
  paid_at: string | null;
}

export interface OrderFulfillment {
  id: string;
  type: string | null;
  courier_code: string | null;
  courier_service: string | null;
  awb_number: string | null;
  status: string | null;
  tracking_url: string | null;
  shipping_cost: number | null;
}

export type EscrowStatus = "none" | "held" | "released" | "refunded";

export const BELI_AMAN_BAP_ID = "bap.beli-aman.local";

export function isBeliAman(o: Pick<Order, "bap_id">): boolean {
  return o.bap_id === BELI_AMAN_BAP_ID;
}

export interface Order {
  id: string;
  store_id: string;
  beckn_order_id: string | null;
  buyer_name: string | null;
  buyer_phone: string | null;
  buyer_email: string | null;
  buyer_photo_url: string | null;
  billing_address: Record<string, unknown> | null;
  shipping_address: Record<string, unknown> | null;
  status: OrderStatus;
  total: number;
  currency: string;
  items: Record<string, unknown>[] | Record<string, unknown> | null;
  payment?: OrderPayment;
  fulfillment?: OrderFulfillment;
  // Beli Aman fields (added 2026-05-09)
  bap_id: string | null;
  escrow_status: EscrowStatus;
  escrow_amount_idr: number | null;
  created_at: string | null;
  updated_at: string | null;
}

export async function fetchOrders(): Promise<Order[]> {
  const storeId = await getStoreId();
  const res = await request<{ data: Order[] }>(`/orders?store_id=${storeId}`);
  return res.data;
}

export async function fetchOrder(id: string): Promise<Order> {
  const res = await request<{ data: Order }>(`/orders/${id}`);
  return res.data;
}

export async function updateOrderStatus(
  id: string,
  status: OrderStatus
): Promise<Order> {
  const res = await request<{ data: Order }>(`/orders/${id}/status`, {
    method: "PUT",
    body: JSON.stringify({ status }),
  });
  return res.data;
}

// -- Store ------------------------------------------------------------

export interface StoreSettings {
  id: string;
  subscriber_id: string;
  subscriber_url: string;
  name: string;
  description: string | null;
  logo_url: string | null;
  domain: string;
  city: string;
  signing_public_key: string | null;
  status: string;
  created_at: string | null;
  updated_at: string | null;
}

export async function fetchStores(): Promise<StoreSettings[]> {
  const res = await request<{ data: StoreSettings[] }>("/stores");
  return res.data;
}

export async function fetchStore(storeId?: string): Promise<StoreSettings> {
  const id = storeId || getSelectedStoreId();
  const query = id ? `?store_id=${id}` : "";
  const res = await request<{ data: StoreSettings }>(`/store${query}`);
  return res.data;
}

export async function updateStore(
  body: Record<string, unknown>
): Promise<StoreSettings> {
  const id = getSelectedStoreId();
  const query = id ? `?store_id=${id}` : "";
  const res = await request<{ data: StoreSettings }>(`/store${query}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });
  return res.data;
}

// -- Customers / CRM ---------------------------------------------------

export type CustomerSegment =
  | "INACTIVE" | "NEW" | "ONE_TIME" | "REPEAT" | "HIGH_LTV" | "AT_RISK" | "CHAMPION";

export interface CustomerSummary {
  email: string;
  name: string;
  phone: string | null;
  photo_url: string | null;
  order_count: number;
  lifetime_value_idr: number;
  first_order_at: string | null;
  last_order_at: string | null;
  days_since_last_order: number | null;
  beli_aman_pct: number;
  is_beli_aman_buyer: boolean;
  segment: CustomerSegment;
}

export interface CustomerListResponse {
  data: CustomerSummary[];
  summary: {
    total_customers: number;
    beli_aman_customers: number;
    direct_customers: number;
    beli_aman_pct: number;
    total_lifetime_value_idr: number;
    average_lifetime_value_idr: number;
  };
}

export interface CustomerDetail extends CustomerSummary {
  orders: {
    id: string;
    beckn_order_id: string | null;
    status: string;
    total: number;
    currency: string;
    created_at: string;
    bap_id: string | null;
    escrow_status: EscrowStatus;
    items: any;
    shipping_address: any;
  }[];
}

export async function fetchCustomers(source?: "beli_aman" | "direct"): Promise<CustomerListResponse> {
  const storeId = await getStoreId();
  const q = source ? `&source=${source}` : "";
  return request<CustomerListResponse>(`/customers?store_id=${storeId}${q}`);
}

export async function fetchCustomer(email: string): Promise<{ data: CustomerDetail }> {
  const storeId = await getStoreId();
  return request<{ data: CustomerDetail }>(`/customers/${encodeURIComponent(email)}?store_id=${storeId}`);
}

// -- Insights ---------------------------------------------------------

export interface InsightsOverview {
  window_days: number;
  metrics: {
    total_orders: number;
    total_revenue_idr: number;
    unique_buyers: number;
    repeat_buyer_count: number;
    repeat_buyer_pct: number;
    average_order_value_idr: number;
    beli_aman: {
      orders: number;
      buyers: number;
      revenue_idr: number;
      average_order_value_idr: number;
      pct_of_orders: number;
    };
  };
}

export interface SegmentBreakdown {
  segments: { segment: CustomerSegment; buyer_count: number; revenue_idr: number }[];
  total_buyers: number;
}

export interface CrossMerchantInsights {
  available: boolean;
  reason?: string;
  current_buyer_count?: number;
  threshold?: number;
  buyer_cohort_size?: number;
  patterns?: { pattern: string; headline: string; detail: string }[];
  demographic_aggregates?: {
    geography: { label: string; pct: number }[];
    device_mix: { label: string; pct: number }[];
    payment_method_mix: { label: string; pct: number }[];
  };
  data_freshness?: string;
  privacy_note?: string;
}

export async function fetchInsightsOverview(days = 30): Promise<InsightsOverview> {
  const storeId = await getStoreId();
  return request<InsightsOverview>(`/insights/overview?store_id=${storeId}&days=${days}`);
}

export async function fetchSegments(): Promise<SegmentBreakdown> {
  const storeId = await getStoreId();
  return request<SegmentBreakdown>(`/insights/buyer-segments?store_id=${storeId}`);
}

export async function fetchCrossMerchant(): Promise<CrossMerchantInsights> {
  const storeId = await getStoreId();
  return request<CrossMerchantInsights>(`/insights/cross-merchant?store_id=${storeId}`);
}

// -- Catalog imports --------------------------------------------------

export type ImportSourceName = "bigseller" | "shopee" | "tokopedia" | "lazada" | "generic";

export interface ImportSourceInfo {
  name: ImportSourceName;
  display_name: string;
  file_extensions: string[];
  hint: string;
  default_column_mapping: Record<string, string>;
}

export interface ImportItemPreview {
  source_item_id: string;
  source_variant_id: string | null;
  parent_group_key: string;
  name: string;
  sku_code: string;
  price: string;
  stock: number;
  variant_name: string | null;
  variant_value: string | null;
  image_urls: string[];
  weight_grams: number | null;
  category_hint: string | null;
  description: string | null;
  warnings: string[];
  errors: string[];
  row_number: number;
}

export interface ImportJobView {
  id: string;
  store_id: string;
  source: ImportSourceName;
  status: "uploaded" | "previewed" | "confirmed" | "applied" | "failed";
  filename: string;
  column_mapping: Record<string, string> | null;
  summary: {
    new: number;
    update: number;
    warn: number;
    error: number;
    total: number;
    created_products?: number;
    created_skus?: number;
    updated_skus?: number;
    skipped?: number;
    apply_errors?: { row_number: number; sku_code: string; message: string }[];
  } | null;
  preview_rows: ImportItemPreview[] | null;
  detected_headers: string[] | null;
  error_message: string | null;
  confirmed_at: string | null;
  applied_at: string | null;
  created_at: string;
  updated_at: string;
}

export async function fetchImportSources(): Promise<ImportSourceInfo[]> {
  const res = await request<{ data: ImportSourceInfo[] }>(`/imports/sources`);
  return res.data;
}

export async function uploadImport(
  source: ImportSourceName,
  file: File
): Promise<ImportJobView> {
  const storeId = await getStoreId();
  const fd = new FormData();
  fd.append("source", source);
  fd.append("file", file);
  const res = await fetch(`${API_BASE}/api/imports?store_id=${storeId}`, {
    method: "POST",
    body: fd,
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`Upload ${res.status}: ${body}`);
  }
  const json = (await res.json()) as { data: ImportJobView };
  return json.data;
}

export async function fetchImport(jobId: string): Promise<ImportJobView> {
  const res = await request<{ data: ImportJobView }>(`/imports/${jobId}`);
  return res.data;
}

export async function updateImportMapping(
  jobId: string,
  columnMapping: Record<string, string>
): Promise<ImportJobView> {
  const res = await request<{ data: ImportJobView }>(`/imports/${jobId}/mapping`, {
    method: "PATCH",
    body: JSON.stringify({ column_mapping: columnMapping }),
  });
  return res.data;
}

export async function confirmImport(jobId: string): Promise<ImportJobView> {
  const res = await request<{ data: ImportJobView }>(`/imports/${jobId}/confirm`, {
    method: "POST",
  });
  return res.data;
}
