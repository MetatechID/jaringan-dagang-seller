const API_BASE = process.env.NEXT_PUBLIC_BPP_API_URL || "http://localhost:8001";

async function request<T>(
  path: string,
  options?: RequestInit
): Promise<T> {
  const url = `${API_BASE}/api${path}`;
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
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

export interface Order {
  id: string;
  store_id: string;
  beckn_order_id: string | null;
  buyer_name: string | null;
  buyer_phone: string | null;
  buyer_email: string | null;
  billing_address: Record<string, unknown> | null;
  shipping_address: Record<string, unknown> | null;
  status: OrderStatus;
  total: number;
  currency: string;
  items: Record<string, unknown>[] | null;
  payment?: OrderPayment;
  fulfillment?: OrderFulfillment;
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
