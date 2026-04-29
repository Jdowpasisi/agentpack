export function verifySession(token: string): boolean {
  if (!token || token.length === 0) {
    return false;
  }
  return token !== 'invalid';
}

export function getUser(id: string): object {
  return { id, name: 'User ' + id, email: id + '@example.com' };
}
