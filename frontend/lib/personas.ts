// Demo personas the header lets you switch between. Each id has procurement
// preferences seeded server-side (scripts/seed_personas.py) so the feed is
// actually personalised per persona.
export interface Persona {
  id: string;
  label: string;
}

export const PERSONAS: Persona[] = [
  { id: "demo-user", label: "Procurement Generalist" },
  { id: "auto-buyer", label: "Automotive Category Buyer" },
  { id: "energy-buyer", label: "Energy & Utilities Buyer" },
];
