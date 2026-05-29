export type OrgType = "PRODUCER" | "RETAILER" | "HYBRID";
export type WarehouseType = "MWH" | "RWH" | "WH" | "SUB_WH";
export type Role = "SA" | "TA" | "NM" | "RM" | "WM" | "LM" | "AU";

export interface DemoWarehouse {
  id: string;
  name: string;
  type: WarehouseType;
  parentId: string | null;
  location?: string;
  manager?: string;
  managerEmail?: string;
  level_number?: number;
}

export interface DemoProduct {
  id: string;
  sku: string;
  name: string;
  category: string;
  unit: string;
  batchTracking: boolean;
  reorderPoint: number;
  stock: Record<string, number>; // warehouseId → quantity
}

export interface DemoUser {
  id: string;
  email: string;
  password: string;
  name: string;
  role: Role;
  warehouseId?: string;
  warehouseName?: string;
}

export interface DemoTenant {
  id: string;
  name: string;
  slug: string;
  orgType: OrgType;
  industry: string;
  color: string;
  bgClass: string;
  logo: string;
  description: string;
  warehouses: DemoWarehouse[];
  products: DemoProduct[];
  users: DemoUser[];
}

// ─── Addis Water ─────────────────────────────────────────────────────────────

const ADDIS_WATER: DemoTenant = {
  id: "tenant-addis-water",
  name: "Addis Water",
  slug: "addis-water",
  orgType: "PRODUCER",
  industry: "Bottled Water",
  color: "#0891B2",
  bgClass: "bg-cyan-600",
  logo: "💧",
  description: "Ethiopia's leading producer of purified and sparkling bottled water, distributed across all regions.",
  warehouses: [
    {
      id: "aw-main",
      name: "Main Production Center",
      type: "MWH",
      parentId: null,
      location: "Addis Ababa Industrial Zone",
      manager: "Selam Bekele",
      managerEmail: "production@addis-water.com",
    },
    {
      id: "aw-north",
      name: "North WH",
      type: "RWH",
      parentId: null,
      location: "Gondar",
      manager: "Hailu Tadesse",
      managerEmail: "north.wm@addis-water.com",
    },
    {
      id: "aw-north-sub",
      name: "North-Subcenter WH",
      type: "SUB_WH",
      parentId: "aw-north",
      location: "Bahir Dar",
      manager: "Tigist Alemu",
      managerEmail: "northsub.wm@addis-water.com",
    },
    {
      id: "aw-south",
      name: "South WH",
      type: "WH",
      parentId: null,
      location: "Hawassa",
      manager: "Dawit Girma",
      managerEmail: "south.wm@addis-water.com",
    },
    {
      id: "aw-east",
      name: "East WH",
      type: "WH",
      parentId: null,
      location: "Dire Dawa",
      manager: "Fatuma Hassan",
      managerEmail: "east.wm@addis-water.com",
    },
    {
      id: "aw-west",
      name: "West WH",
      type: "WH",
      parentId: null,
      location: "Jimma",
      manager: "Abebe Worku",
      managerEmail: "west.wm@addis-water.com",
    },
  ],
  products: [
    {
      id: "aw-p01", sku: "AW-500-P6",  name: "Pure Water 500ml — Pack of 6",
      category: "Still Water", unit: "Pack", batchTracking: true, reorderPoint: 500,
      stock: { "aw-main": 8400, "aw-north": 1200, "aw-north-sub": 350, "aw-south": 980, "aw-east": 760, "aw-west": 540 },
    },
    {
      id: "aw-p02", sku: "AW-500-P12", name: "Pure Water 500ml — Pack of 12",
      category: "Still Water", unit: "Pack", batchTracking: true, reorderPoint: 300,
      stock: { "aw-main": 5200, "aw-north": 840, "aw-north-sub": 210, "aw-south": 620, "aw-east": 490, "aw-west": 380 },
    },
    {
      id: "aw-p03", sku: "AW-500-P24", name: "Pure Water 500ml — Pack of 24",
      category: "Still Water", unit: "Pack", batchTracking: true, reorderPoint: 200,
      stock: { "aw-main": 3100, "aw-north": 520, "aw-north-sub": 140, "aw-south": 410, "aw-east": 320, "aw-west": 280 },
    },
    {
      id: "aw-p04", sku: "AW-1L-P6",   name: "Pure Water 1L — Pack of 6",
      category: "Still Water", unit: "Pack", batchTracking: true, reorderPoint: 400,
      stock: { "aw-main": 6800, "aw-north": 960, "aw-north-sub": 280, "aw-south": 740, "aw-east": 620, "aw-west": 480 },
    },
    {
      id: "aw-p05", sku: "AW-1L-P12",  name: "Pure Water 1L — Pack of 12",
      category: "Still Water", unit: "Pack", batchTracking: true, reorderPoint: 250,
      stock: { "aw-main": 4200, "aw-north": 680, "aw-north-sub": 170, "aw-south": 510, "aw-east": 390, "aw-west": 300 },
    },
    {
      id: "aw-p06", sku: "AW-1L-P24",  name: "Pure Water 1L — Pack of 24",
      category: "Still Water", unit: "Pack", batchTracking: true, reorderPoint: 150,
      stock: { "aw-main": 2600, "aw-north": 420, "aw-north-sub": 110, "aw-south": 340, "aw-east": 270, "aw-west": 210 },
    },
    {
      id: "aw-p07", sku: "AW-1.5L-P6", name: "Pure Water 1.5L — Pack of 6",
      category: "Still Water", unit: "Pack", batchTracking: true, reorderPoint: 300,
      stock: { "aw-main": 4800, "aw-north": 720, "aw-north-sub": 195, "aw-south": 560, "aw-east": 430, "aw-west": 350 },
    },
    {
      id: "aw-p08", sku: "AW-1.5L-P12",name: "Pure Water 1.5L — Pack of 12",
      category: "Still Water", unit: "Pack", batchTracking: true, reorderPoint: 200,
      stock: { "aw-main": 3200, "aw-north": 480, "aw-north-sub": 130, "aw-south": 370, "aw-east": 290, "aw-west": 230 },
    },
    {
      id: "aw-p09", sku: "AW-SP500-P6",name: "Sparkling Water 500ml — Pack of 6",
      category: "Sparkling Water", unit: "Pack", batchTracking: true, reorderPoint: 100,
      stock: { "aw-main": 1800, "aw-north": 240, "aw-north-sub": 60, "aw-south": 190, "aw-east": 150, "aw-west": 110 },
    },
    {
      id: "aw-p10", sku: "AW-SP1L-P6", name: "Sparkling Water 1L — Pack of 6",
      category: "Sparkling Water", unit: "Pack", batchTracking: true, reorderPoint: 80,
      stock: { "aw-main": 1400, "aw-north": 180, "aw-north-sub": 45, "aw-south": 140, "aw-east": 110, "aw-west": 85 },
    },
  ],
  users: [
    { id: "aw-u01", email: "admin@addis-water.com",       password: "AddisWater@2026",  name: "Yohannes Tesfaye",  role: "TA" },
    { id: "aw-u02", email: "production@addis-water.com",  password: "AddisWater@2026",  name: "Selam Bekele",      role: "NM", warehouseId: "aw-main",      warehouseName: "Main Production Center" },
    { id: "aw-u08", email: "regional@addis-water.com",    password: "AddisWater@2026",  name: "Meron Alemu",       role: "RM" },
    { id: "aw-u09", email: "logistics@addis-water.com",   password: "AddisWater@2026",  name: "Abreham Kassa",     role: "LM" },
    { id: "aw-u03", email: "north.wm@addis-water.com",    password: "AddisWater@2026",  name: "Hailu Tadesse",     role: "WM", warehouseId: "aw-north",     warehouseName: "North WH" },
    { id: "aw-u04", email: "northsub.wm@addis-water.com", password: "AddisWater@2026",  name: "Tigist Alemu",      role: "WM", warehouseId: "aw-north-sub", warehouseName: "North-Subcenter WH" },
    { id: "aw-u05", email: "south.wm@addis-water.com",    password: "AddisWater@2026",  name: "Dawit Girma",       role: "WM", warehouseId: "aw-south",     warehouseName: "South WH" },
    { id: "aw-u06", email: "east.wm@addis-water.com",     password: "AddisWater@2026",  name: "Fatuma Hassan",     role: "WM", warehouseId: "aw-east",      warehouseName: "East WH" },
    { id: "aw-u07", email: "west.wm@addis-water.com",     password: "AddisWater@2026",  name: "Abebe Worku",       role: "WM", warehouseId: "aw-west",      warehouseName: "West WH" },
  ],
};

// ─── Muger Cement ─────────────────────────────────────────────────────────────

const MUGER_CEMENT: DemoTenant = {
  id: "tenant-muger-cement",
  name: "Muger Cement",
  slug: "muger-cement",
  orgType: "PRODUCER",
  industry: "Cement Manufacturing",
  color: "#D97706",
  bgClass: "bg-amber-600",
  logo: "🏗️",
  description: "One of Ethiopia's largest cement producers, manufacturing OPC, PPC, SRC, and specialty cements from two state-of-the-art plants.",
  warehouses: [
    {
      id: "mc-harar",
      name: "Harar Production Center",
      type: "MWH",
      parentId: null,
      location: "Harar, Harari Region",
      manager: "Biruk Mengistu",
      managerEmail: "harar.pm@muger-cement.com",
    },
    {
      id: "mc-ambo",
      name: "Ambo Production Center",
      type: "MWH",
      parentId: null,
      location: "Ambo, West Shewa",
      manager: "Meseret Tadesse",
      managerEmail: "ambo.pm@muger-cement.com",
    },
    {
      id: "mc-diredawa",
      name: "Dire Dawa Regional WH",
      type: "RWH",
      parentId: "mc-harar",          // Harar MWH → Dire Dawa RWH → Hawassa WH
      location: "Dire Dawa",
      manager: "Abdulaziz Hassen",
      managerEmail: "diredawa.wm@muger-cement.com",
    },
    {
      id: "mc-hawassa",
      name: "Hawassa WH",
      type: "WH",
      parentId: "mc-diredawa",       // under Dire Dawa RWH
      location: "Hawassa, Sidama",
      manager: "Tigabu Tesfay",
      managerEmail: "hawassa.wm@muger-cement.com",
    },
    {
      id: "mc-kombolcha",
      name: "Kombolcha WH",
      type: "WH",
      parentId: "mc-ambo",           // Ambo MWH → Kombolcha WH
      location: "Kombolcha, Amhara",
      manager: "Getnet Assefa",
      managerEmail: "kombolcha.wm@muger-cement.com",
    },
    {
      id: "mc-mekele",
      name: "Mekele WH",
      type: "WH",
      parentId: "mc-ambo",           // Ambo MWH → Mekele WH
      location: "Mekele, Tigray",
      manager: "Hiwot Gebre",
      managerEmail: "mekele.wm@muger-cement.com",
    },
  ],
  products: [
    {
      id: "mc-p01", sku: "MC-OPC42N-25", name: "OPC Grade 42.5N — 25kg Bag",
      category: "Ordinary Portland Cement", unit: "Bag", batchTracking: false, reorderPoint: 2000,
      stock: { "mc-harar": 18500, "mc-ambo": 21000, "mc-kombolcha": 4200, "mc-mekele": 3800, "mc-diredawa": 5100, "mc-hawassa": 4600 },
    },
    {
      id: "mc-p02", sku: "MC-OPC42N-50", name: "OPC Grade 42.5N — 50kg Bag",
      category: "Ordinary Portland Cement", unit: "Bag", batchTracking: false, reorderPoint: 1500,
      stock: { "mc-harar": 12400, "mc-ambo": 15600, "mc-kombolcha": 3100, "mc-mekele": 2800, "mc-diredawa": 3700, "mc-hawassa": 3300 },
    },
    {
      id: "mc-p03", sku: "MC-OPC32R-25", name: "OPC Grade 32.5R — 25kg Bag",
      category: "Ordinary Portland Cement", unit: "Bag", batchTracking: false, reorderPoint: 1500,
      stock: { "mc-harar": 9200, "mc-ambo": 10800, "mc-kombolcha": 2100, "mc-mekele": 1900, "mc-diredawa": 2500, "mc-hawassa": 2200 },
    },
    {
      id: "mc-p04", sku: "MC-OPC32R-50", name: "OPC Grade 32.5R — 50kg Bag",
      category: "Ordinary Portland Cement", unit: "Bag", batchTracking: false, reorderPoint: 1000,
      stock: { "mc-harar": 7400, "mc-ambo": 8200, "mc-kombolcha": 1600, "mc-mekele": 1400, "mc-diredawa": 1900, "mc-hawassa": 1700 },
    },
    {
      id: "mc-p05", sku: "MC-PPC-25",    name: "Portland Pozzolana Cement (PPC) — 25kg Bag",
      category: "Blended Cement", unit: "Bag", batchTracking: false, reorderPoint: 1200,
      stock: { "mc-harar": 8100, "mc-ambo": 9600, "mc-kombolcha": 1800, "mc-mekele": 1600, "mc-diredawa": 2200, "mc-hawassa": 1900 },
    },
    {
      id: "mc-p06", sku: "MC-PPC-50",    name: "Portland Pozzolana Cement (PPC) — 50kg Bag",
      category: "Blended Cement", unit: "Bag", batchTracking: false, reorderPoint: 800,
      stock: { "mc-harar": 5400, "mc-ambo": 6800, "mc-kombolcha": 1200, "mc-mekele": 1100, "mc-diredawa": 1500, "mc-hawassa": 1300 },
    },
    {
      id: "mc-p07", sku: "MC-SRC-25",    name: "Sulphate Resistant Cement (SRC) — 25kg Bag",
      category: "Special Cement", unit: "Bag", batchTracking: false, reorderPoint: 500,
      stock: { "mc-harar": 3200, "mc-ambo": 4100, "mc-kombolcha": 620, "mc-mekele": 540, "mc-diredawa": 810, "mc-hawassa": 690 },
    },
    {
      id: "mc-p08", sku: "MC-SRC-50",    name: "Sulphate Resistant Cement (SRC) — 50kg Bag",
      category: "Special Cement", unit: "Bag", batchTracking: false, reorderPoint: 300,
      stock: { "mc-harar": 2100, "mc-ambo": 2800, "mc-kombolcha": 410, "mc-mekele": 360, "mc-diredawa": 540, "mc-hawassa": 460 },
    },
    {
      id: "mc-p09", sku: "MC-WPC-25",    name: "White Portland Cement (WPC) — 25kg Bag",
      category: "Decorative Cement", unit: "Bag", batchTracking: false, reorderPoint: 200,
      stock: { "mc-harar": 1400, "mc-ambo": 1800, "mc-kombolcha": 280, "mc-mekele": 230, "mc-diredawa": 360, "mc-hawassa": 300 },
    },
    {
      id: "mc-p10", sku: "MC-WPC-50",    name: "White Portland Cement (WPC) — 50kg Bag",
      category: "Decorative Cement", unit: "Bag", batchTracking: false, reorderPoint: 150,
      stock: { "mc-harar": 980,  "mc-ambo": 1200, "mc-kombolcha": 190, "mc-mekele": 160, "mc-diredawa": 240, "mc-hawassa": 205 },
    },
  ],
  users: [
    { id: "mc-u01", email: "admin@muger-cement.com",         password: "MugerCement@2026", name: "Abeba Haile",       role: "TA" },
    { id: "mc-u02", email: "harar.pm@muger-cement.com",      password: "MugerCement@2026", name: "Biruk Mengistu",    role: "NM", warehouseId: "mc-harar",    warehouseName: "Harar Production Center" },
    { id: "mc-u03", email: "ambo.pm@muger-cement.com",       password: "MugerCement@2026", name: "Meseret Tadesse",   role: "NM", warehouseId: "mc-ambo",     warehouseName: "Ambo Production Center" },
    { id: "mc-u08", email: "regional@muger-cement.com",      password: "MugerCement@2026", name: "Chaltu Gemechu",    role: "RM" },
    { id: "mc-u09", email: "logistics@muger-cement.com",     password: "MugerCement@2026", name: "Lemi Belay",        role: "LM" },
    { id: "mc-u04", email: "kombolcha.wm@muger-cement.com",  password: "MugerCement@2026", name: "Getnet Assefa",     role: "WM", warehouseId: "mc-kombolcha",warehouseName: "Kombolcha WH" },
    { id: "mc-u05", email: "mekele.wm@muger-cement.com",     password: "MugerCement@2026", name: "Hiwot Gebre",       role: "WM", warehouseId: "mc-mekele",   warehouseName: "Mekele WH" },
    { id: "mc-u06", email: "diredawa.wm@muger-cement.com",   password: "MugerCement@2026", name: "Abdulaziz Hassen",  role: "WM", warehouseId: "mc-diredawa", warehouseName: "Dire Dawa WH" },
    { id: "mc-u07", email: "hawassa.wm@muger-cement.com",    password: "MugerCement@2026", name: "Tigabu Tesfay",     role: "WM", warehouseId: "mc-hawassa",  warehouseName: "Hawassa WH" },
  ],
};

// ─── SA (System Admin) ────────────────────────────────────────────────────────

export const SA_USER = {
  id: "sa-001",
  email: "smartadmin@smart-inventory.com",
  password: "SmartAdmin@2026",
  name: "System Administrator",
  role: "SA" as Role,
};

export const DEMO_TENANTS: DemoTenant[] = [ADDIS_WATER, MUGER_CEMENT];

export const ALL_DEMO_USERS = [
  SA_USER,
  ...ADDIS_WATER.users,
  ...MUGER_CEMENT.users,
];

export function getTenantBySlug(slug: string): DemoTenant | undefined {
  return DEMO_TENANTS.find((t) => t.slug === slug);
}

export function getTotalStock(product: DemoProduct): number {
  return Object.values(product.stock).reduce((a, b) => a + b, 0);
}

export function getLowStockProducts(tenant: DemoTenant): DemoProduct[] {
  return tenant.products.filter(
    (p) => getTotalStock(p) < p.reorderPoint * tenant.warehouses.length
  );
}

export function getWarehouseTree(warehouses: DemoWarehouse[]): DemoWarehouse[] {
  return warehouses.filter((w) => w.parentId === null);
}

export function getChildren(warehouses: DemoWarehouse[], parentId: string): DemoWarehouse[] {
  return warehouses.filter((w) => w.parentId === parentId);
}
