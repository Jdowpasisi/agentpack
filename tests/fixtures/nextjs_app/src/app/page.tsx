import { verifySession } from '../lib/auth';
import { fetchPosts } from '../lib/api';

interface Post {
  id: number;
  title: string;
}

export default async function HomePage() {
  const session = verifySession('token');
  if (!session) {
    return <div>Not authenticated</div>;
  }

  const posts: Post[] = await fetchPosts();
  return (
    <main>
      <h1>Posts</h1>
      <ul>
        {posts.map((post) => (
          <li key={post.id}>{post.title}</li>
        ))}
      </ul>
    </main>
  );
}
