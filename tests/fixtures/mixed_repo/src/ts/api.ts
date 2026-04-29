import { slugify } from "./utils";

export async function fetchUser(id: number): Promise<{ id: number; name: string }> {
  const res = await fetch(`/api/users/${id}`);
  return res.json();
}

export function buildSlug(name: string): string {
  return slugify(name);
}
