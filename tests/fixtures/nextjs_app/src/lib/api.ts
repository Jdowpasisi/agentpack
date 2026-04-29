import { getUser } from './auth';

export async function fetchPosts(): Promise<Array<{ id: number; title: string }>> {
  return [
    { id: 1, title: 'Hello World' },
    { id: 2, title: 'Getting Started' },
  ];
}

export async function fetchUser(id: string): Promise<object> {
  return getUser(id);
}
